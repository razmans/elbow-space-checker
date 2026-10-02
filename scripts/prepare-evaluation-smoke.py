"""Generate known-empty synthetic footage; never a representative accuracy dataset."""
import json
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

root = Path(__file__).resolve().parents[1]
output = root / 'data/evaluation-smoke'
output.mkdir(parents=True, exist_ok=True)
path = output / 'empty.avi'
writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), 10, (320, 240))
if not writer.isOpened():
    raise SystemExit('MJPG encoder unavailable')
for _ in range(120):
    writer.write(np.full((240, 320, 3), 180, dtype=np.uint8))
writer.release()
manifest = {
    'schema_version': 1, 'dataset_name': 'Known-empty synthetic pipeline smoke',
    'scope': 'nonrepresentative_smoke', 'provenance': 'Locally generated solid grey frames. No real people, train footage, or independent scenes.',
    'annotator': 'Synthetic fixture: count zero by construction; not human-labelled passenger footage',
    'labelled_at': datetime.now(timezone.utc).isoformat(),
    'samples': [dict(id=f'empty-{start}', video='empty.avi', capacity=100, coverage='unknown',
        start_seconds=start, window_seconds=2, sample_count=3, frame_indices=[start * 10, start * 10 + 10, start * 10 + 20], manual_counts=[0, 0, 0]) for start in (0, 3, 6)],
}
(output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(output / 'manifest.json')
