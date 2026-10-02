"""Video -> detector -> HTTP/SSE/history checks, with real decoding.

The deterministic detector replaces only ML inference, not transport or media time.
A separate opt-in model smoke test runs the actual pinned detector.
"""
import importlib.util
import json
import tempfile
import threading
import time
import unittest
from datetime import datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

from apps.backend.elbow_room.server import Observations, make_handler, read_config
from apps.backend.elbow_room.video import PersonDetector, run_recorded
from apps.backend.elbow_room.model import DEFAULT_MODEL_DIR, FILES

HAS_VIDEO = importlib.util.find_spec("cv2") is not None


class EncodedCountDetector:
    name = "controlled-test-detector"

    def __init__(self, *_):
        pass

    def count(self, frame):
        # Generated gray frames encode counts. No production path uses this detector.
        return round(float(frame.mean()) / 30)


@unittest.skipUnless(HAS_VIDEO, "Install requirements-video.txt and run npm run test:video")
class VideoPipelineTest(unittest.TestCase):
    def setUp(self):
        import cv2
        import numpy as np
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.video = self.root / "controlled.avi"
        writer = cv2.VideoWriter(str(self.video), cv2.VideoWriter_fourcc(*"MJPG"), 10, (64, 64))
        self.assertTrue(writer.isOpened())
        for index in range(30):
            # Window 0 includes counts [1, 2, 3], which must aggregate to 2.
            value = (1 + (index % 10) // 3) * 30
            writer.write(np.full((64, 64, 3), value, dtype=np.uint8))
        writer.release()

    def start(self, speed=2, detector=EncodedCountDetector, video_path=None, **overrides):
        config_path = self.root / "config.json"
        coach = {"coach_id": "video", "coach_name": "Video coach", "position": 1,
                 "platform_zone": "Zone A", "capacity": 10, "interval_seconds": 1,
                 "source": "recorded_video", "video_path": str(video_path or self.video),
                 "playback_speed": speed, "window_seconds": 0.6, "sample_count": 3,
                 **overrides}
        config_path.write_text(json.dumps({"train_name": "Video test", "platform_name": "Test platform",
                                           "direction": "right", "coaches": [coach]}))
        config = read_config(config_path)
        store = Observations(self.root / "history.sqlite3", config)
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(store))
        serving = threading.Thread(target=server.serve_forever, daemon=True)
        serving.start()
        stopped = threading.Event()
        worker = threading.Thread(target=run_recorded, args=(config["coaches"][0], store, stopped, detector), daemon=True)
        worker.start()

        def cleanup():
            stopped.set()
            worker.join(timeout=5)
            server.shutdown()
            server.server_close()
            serving.join(timeout=5)
        self.addCleanup(cleanup)
        self.base = f"http://127.0.0.1:{server.server_port}"
        return store

    def get(self, path):
        with urlopen(self.base + path, timeout=5) as response:
            return json.load(response)

    def until(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.get("/api/state")
            if predicate(state["coaches"][0]):
                return state
            time.sleep(0.05)
        self.fail(f"Timed out, last state: {state}")

    def test_window_median_media_clock_persistence_and_eof(self):
        self.start()
        state = self.until(lambda coach: coach["last_observation"] is not None)
        coach = state["coaches"][0]
        first = coach["last_observation"]
        self.assertEqual(first["passenger_count"], 2)
        self.assertEqual(first["sample_counts"], [1, 2, 3])
        self.assertEqual(first["occupancy_percent"], 20)
        self.assertEqual(first["source"], "recorded_video")
        self.assertAlmostEqual(first["media_position_seconds"], 0.6)
        self.assertAlmostEqual((datetime.fromisoformat(coach["stale_at"]) - datetime.fromisoformat(first["observed_at"])).total_seconds(), 1)
        final = self.until(lambda coach: coach["source_status"] == "ended")["coaches"][0]
        self.assertEqual(final["status"], "unknown")
        self.assertIsNone(final["occupancy_percent"])
        history = list(reversed(self.get("/api/observations")))
        self.assertEqual(len(history), 3)
        self.assertEqual([o["media_position_seconds"] for o in history], [0.6, 1.6, 2.6])
        for before, after in zip(history, history[1:]):
            difference = (datetime.fromisoformat(after["observed_at"]) - datetime.fromisoformat(before["observed_at"])).total_seconds()
            self.assertAlmostEqual(difference, 0.5)
        self.assertEqual(final["last_observation"], history[-1])

    def test_real_time_replay_uses_unscaled_expiry(self):
        self.start(speed=1)
        coach = self.until(lambda coach: coach["last_observation"] is not None)["coaches"][0]
        delta = datetime.fromisoformat(coach["stale_at"]) - datetime.fromisoformat(coach["last_observation"]["observed_at"])
        self.assertEqual(delta.total_seconds(), 2)

    def test_sse_delivers_video_source_and_eof_without_reload(self):
        self.start()
        saw_reading = False
        with urlopen(self.base + "/api/events", timeout=5) as response:
            while True:
                line = response.readline().decode()
                if not line.startswith("data: "):
                    continue
                coach = json.loads(line[6:])["coaches"][0]
                if coach["availability"] == "fresh":
                    saw_reading = True
                    self.assertEqual(coach["source"], "recorded_video")
                if coach["source_status"] == "ended":
                    self.assertEqual(coach["status"], "unknown")
                    break
        self.assertTrue(saw_reading)

    def test_missing_or_undecodable_file_is_unknown_not_zero(self):
        corrupt = self.root / "corrupt.avi"
        corrupt.write_text("not a video")
        self.start(video_path=corrupt)
        coach = self.until(lambda coach: coach["source_status"] == "error")["coaches"][0]
        self.assertEqual(coach["status"], "unknown")
        self.assertIsNone(coach["last_observation"])
        self.assertIn("Cannot open recorded video", coach["source_message"])
        self.assertEqual(self.get("/api/observations"), [])

    def test_detector_failure_does_not_publish_zero(self):
        class BrokenDetector(EncodedCountDetector):
            def count(self, frame):
                raise RuntimeError("intentional inference failure")
        self.start(detector=BrokenDetector)
        coach = self.until(lambda coach: coach["source_status"] == "error")["coaches"][0]
        self.assertEqual(coach["status"], "unknown")
        self.assertEqual(self.get("/api/observations"), [])

    def test_slow_inference_does_not_retimestamp_old_frames_as_fresh(self):
        class SlowDetector(EncodedCountDetector):
            def count(self, frame):
                time.sleep(0.35)
                return super().count(frame)
        self.start(speed=1, detector=SlowDetector, interval_seconds=0.2, window_seconds=0.1)
        state = self.until(lambda coach: coach["last_observation"] is not None)
        coach = state["coaches"][0]
        self.assertEqual(coach["status"], "unknown")
        self.assertEqual(coach["availability"], "stale")
        self.assertLess(datetime.fromisoformat(coach["stale_at"]), datetime.fromisoformat(state["server_time"]))

    def test_missing_model_is_an_actionable_source_error(self):
        self.start(detector=PersonDetector, model_dir=str(self.root / "missing-model"))
        coach = self.until(lambda coach: coach["source_status"] == "error")["coaches"][0]
        self.assertIn("verified weights", coach["source_message"])
        self.assertEqual(self.get("/api/observations"), [])


@unittest.skipUnless(HAS_VIDEO and all((DEFAULT_MODEL_DIR / name).exists() for name in FILES), "Download the pinned model to run the real CPU detector smoke test")
class RealDetectorSmokeTest(unittest.TestCase):
    def test_blank_frame_has_no_people_and_model_runs_on_cpu(self):
        import numpy as np
        detector = PersonDetector(DEFAULT_MODEL_DIR)
        self.assertEqual(detector.count(np.zeros((300, 300, 3), dtype=np.uint8)), 0)


if __name__ == "__main__":
    unittest.main()
