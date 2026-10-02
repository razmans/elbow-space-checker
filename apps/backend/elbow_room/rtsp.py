"""Continuously drain RTSP into a single latest-frame slot; sample without backlog."""
import math
import os
import statistics
import threading
import time
from datetime import datetime, timezone

from .video import PersonDetector, VideoError


class RtspReader:
    def __init__(self, coach, observations, stopped, capture_factory=None):
        self.coach = coach
        self.observations = observations
        self.stopped = stopped
        self.closed = threading.Event()
        self.condition = threading.Condition()
        self.latest = None
        self.sequence = 0
        self.generation = 0
        self.capture_factory = capture_factory or self.open_capture
        self.worker = threading.Thread(target=self.run, daemon=True)
        self.worker.start()

    def open_capture(self):
        # Silence native FFmpeg diagnostics, which can include credential-bearing URLs.
        os.environ['OPENCV_FFMPEG_LOGLEVEL'] = '-8'
        os.environ['OPENCV_LOG_LEVEL'] = 'SILENT'
        import cv2
        # Some OpenCV wheels omit the Python logging API.
        if hasattr(cv2, 'setLogLevel'):
            cv2.setLogLevel(0)
        url = os.environ.get(self.coach['rtsp_url_env'])
        if not url:
            raise VideoError('RTSP URL environment variable is not set')
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.scheme not in ('rtsp', 'rtsps') or not parsed.hostname:
            raise VideoError('RTSP URL environment variable must contain a valid rtsp:// or rtsps:// URL')
        return cv2.VideoCapture(url, cv2.CAP_FFMPEG, [
            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, int(self.coach['open_timeout_seconds'] * 1000),
            cv2.CAP_PROP_READ_TIMEOUT_MSEC, int(self.coach['read_timeout_seconds'] * 1000),
        ])

    def clear(self):
        with self.condition:
            self.latest = None
            self.condition.notify_all()

    def run(self):
        while not self.stopped.is_set() and not self.closed.is_set():
            capture = None
            self.clear()
            self.observations.set_source_state(self.coach, 'connecting' if self.generation == 0 else 'reconnecting')
            try:
                capture = self.capture_factory()
                if not capture.isOpened():
                    raise VideoError('RTSP stream unavailable; retrying')
                self.generation += 1
                warm_until = time.monotonic() + self.coach['reconnect_warmup_seconds']
                announced = False
                while not self.stopped.is_set() and not self.closed.is_set():
                    ok, frame = capture.read()
                    received = time.monotonic()
                    if not ok or frame is None:
                        raise VideoError('RTSP connection lost; retrying')
                    if received < warm_until:
                        continue
                    if not announced:
                        self.observations.set_source_state(self.coach, 'live')
                        announced = True
                    with self.condition:
                        self.sequence += 1
                        self.latest = (self.sequence, self.generation, datetime.now(timezone.utc), received, frame)
                        self.condition.notify_all()
            except Exception:
                self.clear()
                self.observations.set_source_state(self.coach, 'reconnecting', message='RTSP unavailable; reconnecting automatically')
            finally:
                if capture is not None:
                    capture.release()
            self.closed.wait(self.coach['reconnect_seconds'])
        self.clear()

    def frame_after(self, sequence, timeout):
        deadline = time.monotonic() + timeout
        with self.condition:
            while not self.stopped.is_set() and not self.closed.is_set():
                item = self.latest
                if item and item[0] > sequence and time.monotonic() - item[3] <= self.coach['max_frame_age_seconds']:
                    return item
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self.condition.wait(min(remaining, 0.2))
        return None

    def is_current(self, generation):
        with self.condition:
            return self.latest is not None and self.latest[1] == generation

    def close(self):
        self.closed.set()
        with self.condition:
            self.condition.notify_all()
        self.worker.join(timeout=self.coach['read_timeout_seconds'] + self.coach['open_timeout_seconds'] + 1)


def run_rtsp(coach, observations, stopped, detector_factory=PersonDetector, reader_factory=RtspReader):
    reader = None
    try:
        detector = detector_factory(coach['model_dir'], coach['confidence_threshold'])
        reader = reader_factory(coach, observations, stopped)
        next_window = time.monotonic()
        while not stopped.is_set():
            if stopped.wait(max(0, next_window - time.monotonic())):
                break
            first = reader.frame_after(-1, coach['read_timeout_seconds'])
            if first is None:
                continue
            frames = [first[4]]
            item = first
            valid = True
            spacing = coach['window_seconds'] / (coach['sample_count'] - 1)
            for index in range(1, coach['sample_count']):
                if stopped.wait(max(0, first[3] + spacing * index - time.monotonic())):
                    return
                item = reader.frame_after(item[0], coach['read_timeout_seconds'])
                if item is None or item[1] != first[1]:
                    valid = False
                    break
                frames.append(item[4])
            if not valid or not reader.is_current(first[1]):
                continue
            counts = [detector.count(frame) for frame in frames]
            if not reader.is_current(first[1]):
                continue  # A disconnected generation can never repopulate live state.
            count = math.floor(statistics.median(counts) + 0.5)
            observation = observations.publish(coach, count, observed_at=item[2], metadata={
                'sample_counts': counts, 'detector': detector.name,
                'capture_generation': item[1], 'timestamp_basis': 'frame_received_at',
            })
            if observations.verifier:
                observations.verifier.submit(coach, observation, frames, clock=item[3])
            next_window = max(next_window + coach['interval_seconds'], time.monotonic())
    except Exception as error:
        message = str(error) if isinstance(error, VideoError) else 'RTSP analysis failed'
        observations.set_source_state(coach, 'error', message=message)
    finally:
        if reader is not None:
            reader.close()
