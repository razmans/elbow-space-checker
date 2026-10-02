"""Pinned, integrity-checked MobileNet-SSD assets. No downloads during inference."""

import argparse
import hashlib
import os
from pathlib import Path
from urllib.request import urlopen

REVISION = "bb17b6c3eef36d80be441ae8e5339be66e8e3b7a"
BASE_URL = f"https://raw.githubusercontent.com/chuanqi305/MobileNet-SSD/{REVISION}"
DEFAULT_MODEL_DIR = Path(__file__).resolve().parents[3] / "data/models/mobilenet-ssd"
FILES = {
    "deploy.prototxt": "2d180f723b3109e21f8287f6b3c691390d07b60eed998327cd3259ffa0e50608",
    "mobilenet_iter_73000.caffemodel": "52eed8be80522c152a17fb56740de705b79881bde1a167e0e747310523685fc7",
    "LICENSE": "5de433821cfe672af2fca73c3005f48af16121c95f6a11e1031b07807ea59905",
}


def valid_asset(path, expected):
    return path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == expected


def verify_model(directory):
    from .video import VideoError
    for name, expected in FILES.items():
        if not valid_asset(Path(directory) / name, expected):
            raise VideoError("Detector files are missing or changed. Run python -m apps.backend.elbow_room.model to download verified weights.")


def download(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for name, expected in FILES.items():
        target = directory / name
        if valid_asset(target, expected):
            print(f"Verified {name}")
            continue
        temporary = target.with_suffix(target.suffix + ".download")
        try:
            with urlopen(f"{BASE_URL}/{name}", timeout=60) as response, temporary.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
            if not valid_asset(temporary, expected):
                raise ValueError(f"Integrity check failed for {name}")
            os.replace(temporary, target)
            print(f"Downloaded and verified {name}")
        finally:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=DEFAULT_MODEL_DIR)
    args = parser.parse_args()
    download(args.directory)
