"""Local-file replay and CPU inference; optional dependencies load on demand."""

import math
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


class VideoError(Exception):
    """An actionable video/model failure suitable for the local dashboard."""


class PersonDetector:
    """MobileNet-SSD VOC person detections, using the OpenCV CPU backend."""

    name = "mobilenet-ssd-voc"

    def __init__(self, model_dir, confidence=0.5):
        try:
            import cv2
        except ImportError as error:
            raise VideoError("Video runtime missing. Install the backend video requirements in .venv.") from error
        from .model import verify_model
        verify_model(model_dir)
        self.cv2 = cv2
        self.confidence = confidence
        # Bound CPU usage, including when several video coaches are configured.
        cv2.setNumThreads(2)
        try:
            self.net = cv2.dnn.readNetFromCaffe(
                str(Path(model_dir) / "deploy.prototxt"),
                str(Path(model_dir) / "mobilenet_iter_73000.caffemodel"),
            )
            self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        except cv2.error as error:
            raise VideoError("Cannot load the local detector. Run the model download command again.") from error

    def count(self, frame):
        # The upstream model uses BGR, 300x300, (pixel - 127.5) / 127.5.
        blob = self.cv2.dnn.blobFromImage(frame, 1 / 127.5, (300, 300), (127.5, 127.5, 127.5), swapRB=False, crop=False)
        self.net.setInput(blob)
        detections = self.net.forward().reshape(-1, 7)
        # VOC class 15 is person; the network already performs SSD suppression.
        return sum(1 for row in detections if int(row[1]) == 15 and row[2] >= self.confidence)


class RecordedVideo:
    def __init__(self, path):
        try:
            import cv2
        except ImportError as error:
            raise VideoError("Video runtime missing. Install the backend video requirements in .venv.") from error
        self.cv2 = cv2
        self.capture = cv2.VideoCapture(str(path))
        if not self.capture.isOpened():
            self.capture.release()
            raise VideoError("Cannot open recorded video. Check the local file and codec.")
        self.fps = self.capture.get(cv2.CAP_PROP_FPS)
        frames = self.capture.get(cv2.CAP_PROP_FRAME_COUNT)
        if not math.isfinite(self.fps) or self.fps <= 0 or not math.isfinite(frames) or frames < 1:
            self.close()
            raise VideoError("Recorded video must provide a valid frame rate and frame count.")
        self.frames = int(frames)
        self.duration = self.frames / self.fps

    def sample(self, start, window, sample_count):
        end_frame = min(self.frames - 1, round((start + window) * self.fps))
        start_frame = min(self.frames - 1, round(start * self.fps))
        positions = sorted({round(start_frame + (end_frame - start_frame) * i / (sample_count - 1)) for i in range(sample_count)})
        images = []
        for position in positions:
            if not self.capture.set(self.cv2.CAP_PROP_POS_FRAMES, position):
                raise VideoError("Recorded video does not support frame seeking.")
            ok, frame = self.capture.read()
            if not ok or frame is None:
                raise VideoError("Recorded video decode failed before its reported end; no count was published.")
            images.append(frame)
        return images, positions[0] / self.fps, positions[-1] / self.fps

    def close(self):
        self.capture.release()


def run_recorded(coach, observations, stopped, detector_factory=PersonDetector):
    """Publish sampled windows on a media clock; never turn decode errors into zero."""
    video = None
    try:
        video = RecordedVideo(coach["video_path"])
        detector = detector_factory(coach["model_dir"], coach["confidence_threshold"])
        speed = coach["playback_speed"]
        origin = time.monotonic()
        origin_utc = datetime.now(timezone.utc)
        observations.set_source_state(coach, "playing", duration=video.duration)
        start = 0.0
        while start < video.duration and not stopped.is_set():
            # Do not decode a later window until replay reaches its start.
            if stopped.wait(max(0, origin + start / speed - time.monotonic())):
                return
            images, media_start, media_end = video.sample(start, coach["window_seconds"], coach["sample_count"])
            counts = [detector.count(frame) for frame in images]
            count = math.floor(statistics.median(counts) + 0.5)
            if stopped.wait(max(0, origin + media_end / speed - time.monotonic())):
                return
            observed_at = origin_utc + timedelta(seconds=media_end / speed)
            observation = observations.publish(coach, count, observed_at=observed_at, metadata={
                "media_position_seconds": media_end,
                "media_window_start_seconds": media_start,
                "sample_counts": counts,
                "detector": detector.name,
                "playback_speed": speed,
            })
            if observations.verifier:
                observations.verifier.submit(coach, observation, images, clock=media_end)
            del images  # Only a bounded verifier job retains copies, in memory.
            start += coach["interval_seconds"]
            # Slow inference skips obsolete windows, rather than replaying a backlog
            # and stamping old frames as fresh. Observation time stays media-derived.
            elapsed_media = (time.monotonic() - origin) * speed
            if start + coach["window_seconds"] < elapsed_media:
                start = math.ceil(elapsed_media / coach["interval_seconds"]) * coach["interval_seconds"]
        if not stopped.wait(max(0, origin + video.duration / speed - time.monotonic())):
            observations.set_source_state(coach, "ended")
    except Exception as error:
        message = str(error) if isinstance(error, VideoError) else "Recorded-video analysis failed; no fresh count is available."
        observations.set_source_state(coach, "error", message=message)
    finally:
        if video is not None:
            video.close()
