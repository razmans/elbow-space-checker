"""User category labels stay separate from actual image-model predictions."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from apps.backend.elbow_room.server import Observations, read_config

ROOT = Path(__file__).resolve().parents[3]


def script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(importlib.util.find_spec('cv2'), 'Install optional video runtime')
class ImageDemoTest(unittest.TestCase):
    def test_inputs_replay_at_same_capacity_without_expected_labels_forcing_predictions(self):
        import cv2
        import numpy as np
        from apps.backend.elbow_room.video import RecordedVideo
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = []
            for index, value in enumerate((0, 80, 160)):
                path = root / f'{index}.png'
                self.assertTrue(cv2.imwrite(str(path), np.full((31, 33, 3), value, dtype=np.uint8)))
                inputs.append(path)
            output = root / 'prepared'
            script('prepare-image-demo').prepare(inputs, output, capacity=100, duration=3)
            config = read_config(output / 'config.json')
            labels = json.loads((output / 'image-labels.json').read_text())
            self.assertEqual([s['expected_colour'] for s in labels['samples']], ['green', 'yellow', 'red'])
            self.assertTrue(all(s['manual_passenger_count'] is None for s in labels['samples']))
            for index, coach in enumerate(config['coaches']):
                self.assertEqual(coach['capacity'], 100)
                self.assertEqual((output / labels['samples'][index]['image']).read_bytes(), inputs[index].read_bytes())
                video = RecordedVideo(coach['video_path'])
                try:
                    frames, _, _ = video.sample(0, 2, 3)
                    self.assertEqual(len(frames), 3)
                    self.assertEqual(frames[0].shape[:2], (32, 34))
                finally:
                    video.close()
            database = root / 'history.sqlite3'
            store = Observations(database, config)
            full = config['coaches'][2]
            checked = store.publish(full, 5)
            store.finish_verification(checked['id'], count=8, model='controlled', sample_counts=[8, 8, 8])
            store.publish(full, 6)
            result = script('report-image-demo').report(output / 'image-labels.json', database)
            row = result['samples'][2]
            self.assertEqual(row['observation']['id'], checked['id'])
            self.assertEqual(row['observation']['status'], 'green')
            self.assertFalse(row['effective_matches_user_category'])
            self.assertIsNone(result['count_mae'])
            self.assertIsNone(result['samples'][0]['observation'])

    def test_bad_image_never_creates_a_false_empty_dataset(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'bad.jpg'
            path.write_text('not an image')
            with self.assertRaises(ValueError):
                script('prepare-image-demo').prepare([path] * 3, root / 'output')
            self.assertFalse((root / 'output').exists())
