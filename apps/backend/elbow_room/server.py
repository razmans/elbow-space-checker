"""Dependency-free local demo server. Run from the repository root."""

import argparse
from contextlib import closing, contextmanager
import json
import math
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[3]


@contextmanager
def database_connection(path):
    with closing(sqlite3.connect(path)) as connection:
        with connection:
            yield connection


def read_config(path, interval=None, video=None, speed=None):
    config = json.loads(Path(path).read_text())
    # Accept the original one-coach configuration as well as the train layout.
    if "coaches" not in config:
        config = {"train_name": "Demo train", "platform_name": "Demo platform", "direction": "right", "coaches": [config]}
    if not isinstance(config["coaches"], list) or not config["coaches"]:
        raise ValueError("coaches must be a nonempty list")
    for key in ("train_name", "platform_name"):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError(f"{key} must be a nonempty string")
    if config.get("direction") not in ("left", "right"):
        raise ValueError("direction must be left or right")
    if video is not None:
        config["coaches"][0].update(source="recorded_video", video_path=str(Path(video).resolve()))
    ids, positions = set(), set()
    for index, coach in enumerate(config["coaches"], start=1):
        coach.setdefault("position", index)
        coach.setdefault("platform_zone", f"Zone {index}")
        coach.setdefault("source", "simulation")
        if interval is not None:
            coach["interval_seconds"] = interval
        for key in ("coach_id", "coach_name", "platform_zone"):
            if not isinstance(coach.get(key), str) or not coach[key].strip():
                raise ValueError(f"{key} must be a nonempty string")
        if coach["coach_id"] in ids:
            raise ValueError("coach_id values must be unique")
        ids.add(coach["coach_id"])
        position = coach["position"]
        if type(position) is not int or position <= 0 or position in positions:
            raise ValueError("position values must be unique positive integers")
        positions.add(position)
        if coach["source"] not in ("simulation", "recorded_video", "rtsp"):
            raise ValueError("source must be simulation, recorded_video or rtsp")
        if type(coach.get("capacity")) is not int or coach["capacity"] <= 0:
            raise ValueError("capacity must be a positive integer")
        seconds = coach.get("interval_seconds")
        if type(seconds) not in (float, int) or not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("interval_seconds must be finite and positive")
        if coach["source"] == "simulation":
            counts = coach.get("counts")
            if not isinstance(counts, list) or not counts or any(n is not None and (type(n) is not int or n < 0) for n in counts):
                raise ValueError("counts must be a nonempty list of nonnegative integers or null (missed update)")
            coach["playback_speed"] = 1
        else:
            coach.setdefault("playback_speed", 1)
            if speed is not None and coach["source"] == "recorded_video":
                coach["playback_speed"] = speed
            if coach["source"] == "rtsp":
                coach["playback_speed"] = 1
                name = coach.get("rtsp_url_env")
                if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                    raise ValueError("RTSP sources require rtsp_url_env (environment-variable name, not a URL)")
                for key, default in {"open_timeout_seconds": 5, "read_timeout_seconds": 3, "reconnect_seconds": 2, "max_frame_age_seconds": 1, "reconnect_warmup_seconds": 0.5}.items():
                    coach.setdefault(key, default)
                    value = coach[key]
                    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 60:
                        raise ValueError(f"{key} must be between 0 and 60 seconds")
            coach.setdefault("window_seconds", min(2, seconds))
            coach.setdefault("sample_count", 3)
            coach.setdefault("confidence_threshold", 0.5)
            coach.setdefault("model_dir", str(ROOT / "data/models/mobilenet-ssd"))
            for key in (("video_path", "model_dir") if coach["source"] == "recorded_video" else ("model_dir",)):
                value = coach.get(key)
                if not isinstance(value, str) or not value or "://" in value:
                    raise ValueError(f"{key} must be a local filesystem path")
                target = Path(value).expanduser()
                coach[key] = str((Path(path).resolve().parent / target).resolve())
            for key in ("playback_speed", "window_seconds", "confidence_threshold"):
                value = coach[key]
                if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                    raise ValueError(f"{key} must be finite and positive")
            if coach["playback_speed"] > 100:
                raise ValueError("playback_speed must not exceed 100")
            if coach["window_seconds"] > seconds:
                raise ValueError("window_seconds must not exceed interval_seconds")
            if coach["confidence_threshold"] > 1:
                raise ValueError("confidence_threshold must be at most 1")
            if type(coach["sample_count"]) is not int or not 3 <= coach["sample_count"] <= 15:
                raise ValueError("sample_count must be an integer from 3 to 15")
        verification = coach.setdefault("verification", {})
        if not isinstance(verification, dict):
            raise ValueError("verification must be an object")
        verification.setdefault("enabled", coach["source"] != "simulation")
        verification.setdefault("interval_seconds", 1800)
        verification.setdefault("endpoint", "http://127.0.0.1:8081/v1/chat/completions")
        verification.setdefault("model", "elbow-verifier")
        verification.setdefault("timeout_seconds", 120)
        if type(verification["enabled"]) is not bool:
            raise ValueError("verification.enabled must be boolean")
        if coach["source"] == "simulation" and verification["enabled"]:
            raise ValueError("Simulated counts have no images to verify")
        from .verification import validate_endpoint
        validate_endpoint(verification["endpoint"])
        if not isinstance(verification["model"], str) or not verification["model"].strip():
            raise ValueError("verification.model must be a nonempty string")
        for key in ("interval_seconds", "timeout_seconds"):
            value = verification[key]
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"verification.{key} must be finite and positive")
        if verification["timeout_seconds"] > 300:
            raise ValueError("verification.timeout_seconds must not exceed 300")
    config["coaches"].sort(key=lambda coach: coach["position"])
    return config


class Observations:
    def __init__(self, database, config):
        self.database = database
        self.config = config
        self.changed = threading.Condition()
        self.latest = {}
        self.last_verification = {}
        self.verifier = None
        self.source_states = {c["coach_id"]: {"source_status": "loading" if c["source"] != "simulation" else "running", "source_message": None, "duration_seconds": None} for c in config["coaches"]}
        Path(database).parent.mkdir(parents=True, exist_ok=True)
        with database_connection(database) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS observations (id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL)")
            connection.execute("CREATE INDEX IF NOT EXISTS observations_coach_id ON observations(json_extract(payload, '$.coach_id'), id)")
            # A crashed process cannot complete the old in-memory verification job.
            for row_id, payload in connection.execute("SELECT id, payload FROM observations WHERE json_extract(payload, '$.verification.status') = 'pending'").fetchall():
                row = json.loads(payload)
                row["verification"].update(status="unavailable", reason="Verification interrupted by restart")
                connection.execute("UPDATE observations SET payload=? WHERE id=?", (json.dumps(row), row_id))

    def set_source_state(self, coach, status, message=None, duration=None):
        with self.changed:
            state = self.source_states[coach["coach_id"]]
            state.update(source_status=status, source_message=message)
            if duration is not None:
                state["duration_seconds"] = duration
            self.changed.notify_all()

    def publish(self, coach, count, observed_at=None, metadata=None):
        if count is None:
            return  # A failed sample is not an empty coach or a fresh observation.
        percentage = count / coach["capacity"] * 100
        observation = {
            "coach_id": coach["coach_id"],
            "coach_name": coach["coach_name"],
            "source": coach["source"],
            "observed_at": (observed_at or datetime.now(timezone.utc)).isoformat(),
            "passenger_count": count,
            "regular_passenger_count": count,
            "verification": {"status": "not_due" if coach["verification"]["enabled"] else "disabled"},
            "capacity": coach["capacity"],
            "occupancy_percent": round(percentage, 2),
            "status": "green" if percentage < 30 else "yellow" if percentage <= 80 else "red",
            "interval_seconds": coach["interval_seconds"],
        }
        if metadata:
            observation.update(metadata)
        with self.changed:
            with database_connection(self.database) as connection:
                cursor = connection.execute("INSERT INTO observations(payload) VALUES (?)", (json.dumps(observation),))
                observation["id"] = cursor.lastrowid
                connection.execute("UPDATE observations SET payload = ? WHERE id = ?", (json.dumps(observation), observation["id"]))
            self.latest[coach["coach_id"]] = observation
            self.changed.notify_all()
        return observation

    def _update_verification(self, observation_id, verification, count=None):
        with self.changed:
            with database_connection(self.database) as connection:
                saved = connection.execute("SELECT payload FROM observations WHERE id=?", (observation_id,)).fetchone()
                if saved is None:
                    return
                row = json.loads(saved[0])
                row["verification"] = verification
                if count is not None:
                    row["regular_passenger_count"] = row.get("regular_passenger_count", row["passenger_count"])
                    row["passenger_count"] = count
                    percentage = count / row["capacity"] * 100
                    row["occupancy_percent"] = round(percentage, 2)
                    row["status"] = "green" if percentage < 30 else "yellow" if percentage <= 80 else "red"
                    verification["disagreement"] = count != row["regular_passenger_count"]
                connection.execute("UPDATE observations SET payload=? WHERE id=?", (json.dumps(row), observation_id))
            coach_id = row["coach_id"]
            current = self.latest.get(coach_id)
            if current and current["id"] == observation_id:
                self.latest[coach_id] = row
            self.last_verification[coach_id] = {"observation_id": observation_id, "observed_at": row["observed_at"], "regular_passenger_count": row.get("regular_passenger_count", row["passenger_count"]), **verification}
            self.changed.notify_all()

    def mark_verification_pending(self, observation_id, model):
        self._update_verification(observation_id, {"status": "pending", "model": model})

    def finish_verification(self, observation_id, count=None, sample_counts=None, error=None, model=None):
        verification = {"status": "unavailable" if error else "verified", "model": model,
                        "completed_at": datetime.now(timezone.utc).isoformat()}
        if error:
            verification["reason"] = error
        else:
            verification.update(passenger_count=count, sample_counts=sample_counts)
        self._update_verification(observation_id, verification, count=None if error else count)

    def snapshot(self):
        now = datetime.now(timezone.utc)
        coaches = []
        with self.changed:
            for coach in self.config["coaches"]:
                observation = self.latest.get(coach["coach_id"])
                deadline = (datetime.fromisoformat(observation["observed_at"]) + timedelta(seconds=2 * coach["interval_seconds"] / coach["playback_speed"])) if observation else None
                source_state = self.source_states[coach["coach_id"]]
                fresh = deadline is not None and now < deadline and source_state["source_status"] not in ("ended", "error")
                coaches.append({
                    **source_state,
                    "playback_speed": coach["playback_speed"],
                    **{key: coach[key] for key in ("coach_id", "coach_name", "source", "capacity", "interval_seconds", "position", "platform_zone")},
                    "availability": "fresh" if fresh else "unavailable" if source_state["source_status"] in ("ended", "error") or not observation else "stale",
                    "status": observation["status"] if fresh else "unknown",
                    "passenger_count": observation["passenger_count"] if fresh else None,
                    "occupancy_percent": observation["occupancy_percent"] if fresh else None,
                    "stale_at": deadline.isoformat() if deadline else None,
                    "last_observation": observation,
                    "last_verification": self.last_verification.get(coach["coach_id"]),
                })
        return {
            "server_time": now.isoformat(),
            "train_name": self.config["train_name"],
            "platform_name": self.config["platform_name"],
            "direction": self.config["direction"],
            "coaches": coaches,
        }

    def history(self):
        with database_connection(self.database) as connection:
            return [json.loads(row[0]) for row in connection.execute("SELECT payload FROM observations ORDER BY id DESC LIMIT 100")]

    def history_page(self, coach_id=None, before=None, limit=20):
        clauses, parameters = [], []
        if coach_id:
            clauses.append("json_extract(payload, '$.coach_id') = ?")
            parameters.append(coach_id)
        if before is not None:
            clauses.append("id < ?")
            parameters.append(before)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with database_connection(self.database) as connection:
            rows = [json.loads(row[0]) for row in connection.execute(
                "SELECT payload FROM observations" + where + " ORDER BY id DESC LIMIT ?", (*parameters, limit + 1))]
        items = rows[:limit]
        for row in items:
            # Pre-verifier records stored only the original/effective count.
            row.setdefault("regular_passenger_count", row["passenger_count"])
            row.setdefault("verification", {"status": "not_recorded"})
        return {"items": items, "next_before": items[-1]["id"] if len(rows) > limit else None}


def make_handler(observations):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/api/events":
                self.stream()
                return
            if path == "/api/health":
                payload, status = {"status": "ok"}, 200
            elif path in ("/api/state", "/api/observations/latest"):
                payload, status = observations.snapshot(), 200
            elif path == "/api/observations":
                payload, status = observations.history(), 200
            elif path == "/api/history":
                try:
                    query = parse_qs(parsed.query, keep_blank_values=True)
                    if any(key not in ("coach_id", "before", "limit") or len(values) != 1 for key, values in query.items()):
                        raise ValueError("Unknown or repeated history parameter")
                    limit = int(query.get("limit", ["20"])[0])
                    before = int(query["before"][0]) if "before" in query else None
                    if not 1 <= limit <= 100 or (before is not None and not 1 <= before <= 9223372036854775807):
                        raise ValueError("limit must be 1–100 and before must be a positive SQLite ID")
                    payload, status = observations.history_page(query.get("coach_id", [None])[0], before, limit), 200
                except ValueError as error:
                    payload, status = {"error": str(error)}, 400
            else:
                payload, status = {"error": "Not found"}, 404
            body = json.dumps(payload).encode()
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True  # A browser can cancel a previous history filter.

        def stream(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            previous = None
            heartbeat_at = time.monotonic()
            # Recheck time even when every producer has stopped sending updates.
            tick = min(0.5, min(c["interval_seconds"] / c["playback_speed"] for c in observations.config["coaches"]) / 2)
            try:
                while True:
                    snapshot = observations.snapshot()
                    fingerprint = json.dumps(snapshot["coaches"])
                    if fingerprint != previous:
                        message = f"retry: 1000\nevent: state\ndata: {json.dumps(snapshot)}\n\n"
                        previous = fingerprint
                    elif time.monotonic() - heartbeat_at >= 15:
                        message = ": heartbeat\n\n"
                    else:
                        message = None
                    if message:
                        self.wfile.write(message.encode())
                        self.wfile.flush()
                        heartbeat_at = time.monotonic()
                    with observations.changed:
                        observations.changed.wait(timeout=tick)
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config/demo.json")
    parser.add_argument("--database", type=Path, default=ROOT / "data/elbow-room.sqlite3")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--interval", type=float, help="Override intervals (media seconds for recorded video)")
    parser.add_argument("--video", type=Path, help="Use this local recording for the first coach")
    parser.add_argument("--speed", type=float, help="Override recorded-video playback speed (1–100, fractional speeds allowed)")
    args = parser.parse_args()
    try:
        config = read_config(args.config, args.interval, args.video, args.speed)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    observations = Observations(args.database, config)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(observations))
    stopped = threading.Event()
    from .verification import VerificationManager
    observations.verifier = VerificationManager(observations, config["coaches"])
    workers = []

    def simulate(coach):
        index = 1
        while not stopped.wait(coach["interval_seconds"]):
            observations.publish(coach, coach["counts"][index % len(coach["counts"])])
            index += 1

    for coach in config["coaches"]:
        if coach["source"] == "recorded_video":
            from .video import run_recorded
            worker = threading.Thread(target=run_recorded, args=(coach, observations, stopped), daemon=True)
        elif coach["source"] == "rtsp":
            from .rtsp import run_rtsp
            worker = threading.Thread(target=run_rtsp, args=(coach, observations, stopped), daemon=True)
        else:
            observations.publish(coach, coach["counts"][0])
            worker = threading.Thread(target=simulate, args=(coach,), daemon=True)
        worker.start()
        workers.append(worker)
    print(f"Elbow Room API: http://127.0.0.1:{server.server_port} (local demo)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stopped.set()
        observations.verifier.close()
        for worker in workers:
            worker.join(timeout=5)
        server.server_close()


if __name__ == "__main__":
    main()
