"""Make three explicitly labelled still-image replays for the existing video pipeline."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]


def prepare(paths, output, capacity=100, duration=300):
    if type(capacity) is not int or capacity <= 0 or type(duration) is not int or duration < 3:
        raise ValueError('Use a positive capacity and an integer duration of at least three seconds')
    # Decode every input before creating the dataset. Never substitute a failed decode with zero.
    frames = []
    for path in paths:
        frame = cv2.imread(str(path))
        if frame is None:
            raise ValueError(f'Cannot decode image: {path}')
        frames.append(frame)
    output.mkdir(parents=True, exist_ok=False)
    config = json.loads((ROOT / 'config/demo.json').read_text())
    config['train_name'] = 'User images · static replay comparison'
    manifest = {'scope': 'three_user_labelled_stills', 'capacity': capacity,
                'capacity_basis': 'Unvalidated demo assumption; not a measured coach capacity',
                'note': 'Category labels are user expectations, not model outputs or exact passenger-count annotations. Repeated frames are one image, not independent footage.',
                'samples': []}
    for index, (path, frame, category, expected) in enumerate(zip(paths, frames, ('low', 'mid', 'full'), ('green', 'yellow', 'red'))):
        original = output / f'{category}{path.suffix.lower()}'
        shutil.copyfile(path, original)
        height, width = frame.shape[:2]
        # MJPG needs even dimensions; pad at most one edge pixel, preserving the whole image.
        encoded_frame = cv2.copyMakeBorder(frame, 0, height % 2, 0, width % 2, cv2.BORDER_REPLICATE)
        video = output / f'{category}.avi'
        writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'MJPG'), 1, (encoded_frame.shape[1], encoded_frame.shape[0]))
        if not writer.isOpened():
            raise ValueError('MJPG encoder unavailable')
        try:
            for _ in range(duration):
                writer.write(encoded_frame)
        finally:
            writer.release()
        coach = config['coaches'][index]
        coach.pop('counts', None)
        coach.update(coach_name=f'Coach {index + 1:02d} · {category} image', source='recorded_video',
                     video_path=str(video.resolve()), capacity=capacity, interval_seconds=60,
                     window_seconds=2, sample_count=3, playback_speed=1,
                     verification={'enabled': True, 'interval_seconds': 1800})
        manifest['samples'].append({'coach_id': coach['coach_id'], 'user_category': category,
            'expected_colour': expected, 'original_filename': path.name, 'image': original.name,
            'image_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'video': video.name,
            'manual_passenger_count': None, 'coverage': 'unknown'})
    (output / 'config.json').write_text(json.dumps(config, indent=2) + '\n')
    (output / 'image-labels.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return config, manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for label in ('empty', 'mid', 'full'):
        parser.add_argument('--' + label, type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New directory under ignored data/')
    parser.add_argument('--capacity', type=int, default=100)
    parser.add_argument('--duration', type=int, default=300)
    args = parser.parse_args()
    try:
        prepare([args.empty, args.mid, args.full], args.output, args.capacity, args.duration)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(f'Prepared {args.output / "config.json"}')
