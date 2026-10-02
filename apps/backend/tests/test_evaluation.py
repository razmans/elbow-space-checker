"""Controlled inference with real decoded windows and persisted evaluation reports."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from apps.backend.elbow_room.evaluation import evaluate, load_manifest, markdown


class Detector:
    name = 'controlled-colour-detector'

    def __init__(self, *_):
        pass

    def count(self, frame):
        return round(float(frame.mean()) / 10) * 10  # Ignore MJPG rounding in the controlled input.


class Verifier:
    settings = {'model': 'controlled-test-verifier'}

    def verify(self, frames):
        count = round(float(frames[0].mean()) / 10) * 10
        if count == 0:
            return 30, [30] * len(frames)
        raise ValueError('Controlled unassessable sample')


@unittest.skipUnless(importlib.util.find_spec('cv2'), 'Install optional video dependencies')
class EvaluationTest(unittest.TestCase):
    def setUp(self):
        import cv2
        import numpy as np
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = self.root / 'manifest.json'
        samples = []
        for index, (value, truth) in enumerate(((0, 30), (80, 81), (30, 30))):
            name = f'{index}.avi'
            writer = cv2.VideoWriter(str(self.root / name), cv2.VideoWriter_fourcc(*'MJPG'), 10, (32, 32))
            self.assertTrue(writer.isOpened())
            for _ in range(30):
                writer.write(np.full((32, 32, 3), value, dtype=np.uint8))
            writer.release()
            samples.append(dict(id=name, video=name, capacity=100, coverage='unknown', start_seconds=0,
                window_seconds=2, sample_count=3, frame_indices=[0, 10, 20], manual_counts=[truth] * 3))
        self.data = dict(schema_version=1, dataset_name='Controlled test', scope='nonrepresentative_smoke',
            provenance='Synthetic test fixture', annotator='Test fixture', labelled_at='2026-10-02', samples=samples)
        self.save()

    def save(self):
        self.manifest.write_text(json.dumps(self.data))

    def test_count_colour_false_green_and_fallback_metrics(self):
        report = evaluate(self.manifest, detector_factory=Detector, verifier=Verifier())
        self.assertEqual(report['failed_windows'], 0)
        regular, effective, ai = (report['metrics'][key] for key in ('regular', 'effective', 'ai'))
        self.assertEqual(regular['mean_absolute_count_error'], 31 / 3)
        self.assertEqual(regular['mean_count_bias'], -31 / 3)
        self.assertEqual(regular['colour_errors'], 2)
        self.assertEqual(regular['false_green_rate'], 1 / 3)
        self.assertEqual(regular['confusion_matrix']['red']['yellow'], 1)
        self.assertEqual(effective['false_green_windows'], 0)
        self.assertEqual(effective['colour_errors'], 1)
        self.assertEqual(ai['evaluated_windows'], 1)
        self.assertEqual(report['verification_unavailable_windows'], 2)
        self.assertEqual(report['timing']['detector_seconds']['n'], 3)
        self.assertTrue(all(len(row['video_sha256']) == 64 for row in report['samples']))
        output = self.root / 'report.json'
        output.write_text(json.dumps(report))
        self.assertEqual(json.loads(output.read_text())['metrics'], report['metrics'])
        self.assertIn('not a train-coach accuracy evaluation', markdown(report))

    def test_mismatched_labels_and_decode_failure_never_become_zero_error(self):
        self.data['samples'][0]['frame_indices'] = [1, 10, 20]
        self.data['samples'][1]['video'] = 'missing.avi'
        self.data['samples'][2]['start_seconds'] = 100
        self.save()
        report = evaluate(self.manifest, detector_factory=Detector)
        self.assertEqual(report['failed_windows'], 3)
        self.assertEqual(report['metrics']['regular']['evaluated_windows'], 0)
        self.assertIsNone(report['metrics']['regular']['mean_absolute_count_error'])
        self.assertIsNone(report['metrics']['regular']['false_green_rate'])

    def test_missing_annotations_rejected_and_zero_denominator_is_null(self):
        self.data['samples'] = self.data['samples'][:1]
        self.data['samples'][0]['manual_counts'] = [0, 0, 0]
        self.save()
        report = evaluate(self.manifest, detector_factory=Detector)
        self.assertIsNone(report['metrics']['regular']['false_green_rate'])
        self.assertEqual(report['metrics']['regular']['mean_absolute_count_error'], 0)
        self.data['annotator'] = ''
        self.save()
        with self.assertRaises(ValueError):
            load_manifest(self.manifest)
