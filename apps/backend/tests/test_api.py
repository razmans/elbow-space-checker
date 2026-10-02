"""Black-box checks against the actual HTTP server, SSE stream and SQLite history."""
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[3]


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name) / "config.json"
        self.database = Path(self.temp.name) / "history.sqlite3"
        self.config.write_text(json.dumps({"coach_id": "test-01", "coach_name": "Test Coach", "capacity": 100, "interval_seconds": 0.05, "counts": [0, 29, 30, 70, 80, 81, 110]}))

    def start_server(self):
        process = subprocess.Popen([sys.executable, "-m", "apps.backend.elbow_room.server", "--port", "0", "--config", str(self.config), "--database", str(self.database)], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.addCleanup(self.stop_server, process)
        line = process.stdout.readline()
        self.assertTrue(line.startswith("Elbow Room API:"), line)
        return process, line.split()[3]

    @staticmethod
    def stop_server(process):
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        process.stdout.close()

    @staticmethod
    def get(base, path):
        with urlopen(base + path, timeout=3) as response:
            return json.load(response)

    def test_thresholds_and_persisted_history_survive_restart(self):
        process, base = self.start_server()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            history = self.get(base, "/api/observations")
            if len(history) >= 7:
                break
            time.sleep(0.03)
        expected = {0: "green", 29: "green", 30: "yellow", 70: "yellow", 80: "yellow", 81: "red", 110: "red"}
        self.assertTrue(set(expected) <= {row["passenger_count"] for row in history})
        for row in history:
            self.assertEqual(row["status"], expected[row["passenger_count"]])
            self.assertEqual(row["occupancy_percent"], row["passenger_count"])
            self.assertEqual(row["source"], "simulation")
            self.assertEqual(row["coach_id"], "test-01")
            self.assertTrue(row["observed_at"].endswith("+00:00"))
        retained = history[-1]
        self.stop_server(process)
        _, base = self.start_server()
        self.assertIn(retained, self.get(base, "/api/observations"))

    def test_sse_sends_initial_observation_and_updates_on_same_connection(self):
        _, base = self.start_server()
        events = []
        with urlopen(base + "/api/events", timeout=3) as response:
            self.assertEqual(response.headers.get_content_type(), "text/event-stream")
            while len(events) < 3:
                line = response.readline().decode()
                if line.startswith("data: "):
                    events.append(json.loads(line[6:])["coaches"][0]["last_observation"])
        self.assertEqual(len({event["id"] for event in events}), 3)
        self.assertEqual(sorted(event["id"] for event in events), [event["id"] for event in events])
        history = self.get(base, "/api/observations")
        for event in events:
            self.assertIn(event, history)

    def test_invalid_configuration_fails_before_serving(self):
        config = json.loads(self.config.read_text())
        for capacity in (0, -1, True):
            config["capacity"] = capacity
            self.config.write_text(json.dumps(config))
            result = subprocess.run([sys.executable, "-m", "apps.backend.elbow_room.server", "--config", str(self.config)], cwd=ROOT, capture_output=True, text=True, timeout=3)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("capacity must be a positive integer", result.stderr)


    def write_train(self, coaches):
        self.config.write_text(json.dumps({"train_name": "Test train", "platform_name": "Platform 2", "direction": "left", "coaches": coaches}))

    def coach(self, coach_id, position, counts, capacity=100, interval=0.2):
        return {"coach_id": coach_id, "coach_name": coach_id, "position": position,
                "platform_zone": f"Zone {position}", "source": "simulation",
                "capacity": capacity, "interval_seconds": interval, "counts": counts}

    def test_stale_transition_is_broadcast_without_a_new_observation_and_recovers(self):
        self.write_train([self.coach("empty-then-missing", 1, [0, None, None, None, None, 20])])
        _, base = self.start_server()
        states = []
        with urlopen(base + "/api/events", timeout=4) as response:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                line = response.readline().decode()
                if not line.startswith("data: "):
                    continue
                coach = json.loads(line[6:])["coaches"][0]
                states.append(coach)
                if coach["passenger_count"] == 20:
                    break
        self.assertEqual([s["availability"] for s in states], ["fresh", "stale", "fresh"])
        self.assertEqual(states[0]["passenger_count"], 0)
        self.assertEqual(states[0]["status"], "green")
        self.assertEqual(states[1]["status"], "unknown")
        self.assertIsNone(states[1]["passenger_count"])
        self.assertIsNone(states[1]["occupancy_percent"])
        self.assertEqual(states[1]["last_observation"], states[0]["last_observation"])
        self.assertEqual(states[2]["status"], "green")
        self.assertEqual(len(self.get(base, "/api/observations")), 2)

    def test_independent_coaches_order_capacity_and_reconnect_snapshot(self):
        self.write_train([
            self.coach("missing", 3, [None], capacity=80),
            self.coach("busy", 2, [90], capacity=100, interval=0.1),
            self.coach("empty", 1, [0, None, None, None, None, None, None], capacity=120),
        ])
        _, base = self.start_server()
        initial = self.get(base, "/api/state")
        self.assertEqual(initial["direction"], "left")
        self.assertEqual([c["coach_id"] for c in initial["coaches"]], ["empty", "busy", "missing"])
        self.assertEqual([c["status"] for c in initial["coaches"]], ["green", "red", "unknown"])
        self.assertEqual([c["capacity"] for c in initial["coaches"]], [120, 100, 80])
        self.assertEqual(initial["coaches"][2]["availability"], "unavailable")
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            state = self.get(base, "/api/state")
            if state["coaches"][0]["availability"] == "stale":
                break
            time.sleep(0.03)
        self.assertEqual(state["coaches"][0]["status"], "unknown")
        self.assertEqual(state["coaches"][1]["status"], "red")
        # Every new stream receives all coaches, including unavailable ones.
        with urlopen(base + "/api/events", timeout=3) as response:
            while True:
                line = response.readline().decode()
                if line.startswith("data: "):
                    reconnected = json.loads(line[6:])
                    break
        self.assertEqual(len(reconnected["coaches"]), 3)
        self.assertEqual(reconnected["coaches"][0]["availability"], "stale")
        self.assertGreater(reconnected["coaches"][1]["last_observation"]["id"], initial["coaches"][1]["last_observation"]["id"])
        self.assertIsNone(reconnected["coaches"][2]["last_observation"])

    def test_duplicate_ids_and_positions_are_rejected(self):
        for coaches, message in [
            ([self.coach("same", 1, [1]), self.coach("same", 2, [2])], "coach_id values must be unique"),
            ([self.coach("one", 1, [1]), self.coach("two", 1, [2])], "position values must be unique"),
        ]:
            self.write_train(coaches)
            result = subprocess.run([sys.executable, "-m", "apps.backend.elbow_room.server", "--config", str(self.config)], cwd=ROOT, capture_output=True, text=True, timeout=3)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(message, result.stderr)


if __name__ == "__main__":
    unittest.main()
