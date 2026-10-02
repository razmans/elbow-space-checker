"""Generate local test footage; optional user-supplied image for a positive smoke test."""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--image", type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
output = root / "data/video-e2e"
output.mkdir(parents=True, exist_ok=True)
image = cv2.imread(str(args.image)) if args.image else None
if args.image and image is None:
    raise SystemExit("Cannot read smoke-test image")
frame = cv2.resize(image, (500, 376)) if image is not None else np.zeros((376, 500, 3), dtype=np.uint8)
writer = cv2.VideoWriter(str(output / "sample.avi"), cv2.VideoWriter_fourcc(*"MJPG"), 10, (500, 376))
if not writer.isOpened():
    raise SystemExit("MJPG video encoder unavailable")
for _ in range(240):
    writer.write(frame)
writer.release()
config = json.loads((root / "config/demo.json").read_text())
config["train_name"] = "Recorded Video Test"
config["coaches"][0].update(source="recorded_video", video_path=str(output / "sample.avi"),
                            capacity=10, interval_seconds=3, window_seconds=1,
                            playback_speed=2, sample_count=3, verification={"enabled": False})
for coach in config["coaches"][1:]:
    coach["interval_seconds"] = 1
(output / "config.json").write_text(json.dumps(config, indent=2) + "\n")
print(f"Generated {output / 'sample.avi'} and config.json")
