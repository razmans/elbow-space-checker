"""Offline evaluation of explicitly labelled video windows; no accuracy pass threshold."""
import argparse
import hashlib
import json
import math
import platform
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from .server import ROOT
from .verification import LocalVisionVerifier
from .video import PersonDetector, RecordedVideo, VideoError


def median_count(counts):
    return math.floor(statistics.median(counts) + 0.5)


def colour(count, capacity):
    percent = count / capacity * 100
    return 'green' if percent < 30 else 'yellow' if percent <= 80 else 'red'


def metrics(rows, field):
    valid = [row for row in rows if row.get(field) is not None and row.get('truth') is not None]
    matrix = {actual: {predicted: 0 for predicted in ('green', 'yellow', 'red')} for actual in ('green', 'yellow', 'red')}
    errors, colour_errors, false_green, non_green = [], 0, 0, 0
    for row in valid:
        errors.append(row[field] - row['truth'])
        actual, predicted = colour(row['truth'], row['capacity']), colour(row[field], row['capacity'])
        matrix[actual][predicted] += 1
        colour_errors += actual != predicted
        non_green += actual != 'green'
        false_green += actual != 'green' and predicted == 'green'
    return {
        'evaluated_windows': len(valid),
        'mean_absolute_count_error': statistics.mean(map(abs, errors)) if errors else None,
        'mean_count_bias': statistics.mean(errors) if errors else None,
        'colour_errors': colour_errors,
        'colour_error_rate': colour_errors / len(valid) if valid else None,
        'false_green_windows': false_green, 'non_green_truth_windows': non_green,
        'false_green_rate': false_green / non_green if non_green else None,
        'confusion_matrix': matrix,
    }


def timings(values):
    ordered = sorted(values)
    return {'n': len(values), 'median_seconds': statistics.median(values) if values else None,
            'p95_seconds': ordered[math.ceil(len(ordered) * .95) - 1] if values else None}


def load_manifest(path):
    manifest = json.loads(path.read_text())
    if not isinstance(manifest, dict):
        raise ValueError('The manifest must be a JSON object')
    if manifest.get('schema_version') != 1 or manifest.get('scope') not in ('representative_coach', 'nonrepresentative_smoke'):
        raise ValueError('Use schema_version 1 and an explicit dataset scope')
    for key in ('dataset_name', 'provenance', 'annotator', 'labelled_at'):
        if not isinstance(manifest.get(key), str) or not manifest[key].strip():
            raise ValueError(f'{key} is required; do not invent manual labels')
    if not isinstance(manifest.get('samples'), list) or not manifest['samples']:
        raise ValueError('Provide at least one manually labelled sample')
    seen = set()
    for sample in manifest['samples']:
        if not isinstance(sample, dict):
            raise ValueError('Each sample must be a JSON object')
        if not isinstance(sample.get('id'), str) or not sample['id'] or sample['id'] in seen:
            raise ValueError('Sample IDs must be unique nonempty strings')
        seen.add(sample['id'])
        if type(sample.get('capacity')) is not int or sample['capacity'] <= 0:
            raise ValueError('Each sample requires a positive capacity')
        if sample.get('coverage') not in ('whole_coach', 'partial', 'unknown'):
            raise ValueError('Declare whole_coach, partial or unknown camera coverage')
        for key in ('start_seconds', 'window_seconds'):
            value = sample.get(key)
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (key == 'window_seconds' and value == 0):
                raise ValueError(f'Invalid {key}')
        count = sample.get('sample_count', 3)
        indices, labels = sample.get('frame_indices'), sample.get('manual_counts')
        if type(count) is not int or not 3 <= count <= 15:
            raise ValueError('sample_count must be 3–15')
        if not isinstance(indices, list) or not indices or any(type(n) is not int or n < 0 for n in indices) or indices != sorted(set(indices)):
            raise ValueError('frame_indices must be increasing unique nonnegative integers')
        if not isinstance(labels, list) or len(labels) != len(indices) or any(type(n) is not int or n < 0 for n in labels):
            raise ValueError('manual_counts must label each exact sampled frame')
        video = sample.get('video')
        if not isinstance(video, str) or not video or '://' in video:
            raise ValueError('video must be a local file')
        sample['video'] = str((path.parent / video).resolve())
    return manifest


def evaluate(manifest_path, *, model_dir=None, confidence=.5, verifier=None, detector_factory=PersonDetector):
    manifest_path = Path(manifest_path).resolve()
    manifest = load_manifest(manifest_path)
    started = time.perf_counter()
    detector = detector_factory(model_dir or ROOT / 'data/models/mobilenet-ssd', confidence)
    initialization = time.perf_counter() - started
    rows, hashes = [], {}
    for sample in manifest['samples']:
        row = {'id': sample['id'], 'capacity': sample['capacity'], 'coverage': sample['coverage'],
               'frame_indices': sample['frame_indices'], 'manual_counts': sample['manual_counts'],
               'truth': median_count(sample['manual_counts'])}
        video = None
        try:
            path = Path(sample['video'])
            if str(path) not in hashes:
                with path.open('rb') as source:
                    hashes[str(path)] = hashlib.file_digest(source, 'sha256').hexdigest()
            row['video_sha256'] = hashes[str(path)]
            started = time.perf_counter()
            video = RecordedVideo(path)
            if sample['start_seconds'] >= video.duration:
                raise ValueError('Sample begins after EOF')
            frames, start, end = video.sample(sample['start_seconds'], sample['window_seconds'], sample.get('sample_count', 3))
            first, last = round(start * video.fps), round(end * video.fps)
            actual_indices = sorted({round(first + (last - first) * i / (sample.get('sample_count', 3) - 1)) for i in range(sample.get('sample_count', 3))})
            if actual_indices != sample['frame_indices']:
                raise ValueError('Labels do not match the decoded frame indices')
            row['decode_seconds'] = time.perf_counter() - started
            started = time.perf_counter()
            counts = [detector.count(frame) for frame in frames]
            row.update(regular=median_count(counts), regular_frame_counts=counts,
                       detector_seconds=time.perf_counter() - started)
            row['effective'] = row['regular']
            row['verification_status'] = 'disabled'
            if verifier:
                started = time.perf_counter()
                try:
                    row['ai'], row['ai_frame_counts'] = verifier.verify(frames)
                    row['effective'] = row['ai']
                    row['verification_status'] = 'verified'
                    row['disagreement'] = row['regular'] != row['ai']
                except Exception as error:
                    row.update(verification_status='unavailable', verification_error=str(error))
                row['verifier_seconds'] = time.perf_counter() - started
        except Exception as error:
            row['error'] = str(error)
        finally:
            if video:
                video.close()
        rows.append(row)
    return {
        'schema_version': 1, 'generated_at': datetime.now(timezone.utc).isoformat(),
        'dataset_name': manifest['dataset_name'], 'scope': manifest['scope'],
        'provenance': manifest['provenance'], 'annotator': manifest['annotator'], 'labelled_at': manifest['labelled_at'],
        'manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        'runtime': {'platform': platform.platform(), 'python': platform.python_version(),
                    'detector': detector.name, 'confidence': confidence, 'initialization_seconds': initialization,
                    'verifier_model': verifier.settings['model'] if verifier and hasattr(verifier, 'settings') else None},
        'attempted_windows': len(rows), 'failed_windows': sum('error' in row for row in rows),
        'verification_unavailable_windows': sum(row.get('verification_status') == 'unavailable' for row in rows),
        'metrics': {field: metrics(rows, field) for field in ('regular', 'ai', 'effective')},
        'timing': {field: timings([row[field] for row in rows if field in row]) for field in ('decode_seconds', 'detector_seconds', 'verifier_seconds')},
        'samples': rows,
        'limitations': [
            'No accuracy pass target is defined. These results do not establish boarding suitability.',
            'AI-only metrics exclude unavailable checks; effective metrics retain the regular estimate on failure.',
            'False-green rate = predicted green with non-green truth / all evaluated non-green truth windows; null means no denominator.',
            'Partial or unknown camera coverage cannot establish whole-coach occupancy.',
            'Offline checks verify every labelled window; this is not the live 30-minute scheduler or a concurrent-load benchmark.',
            'Small or overlapping samples are correlated; no statistical confidence or generalization claim is made.',
        ],
    }


def markdown(report):
    lines = [f"# Evaluation: {report['dataset_name']}", '', f"Scope: **{report['scope']}**. Generated {report['generated_at']}.",
             f"Attempted windows: {report['attempted_windows']}; failed: {report['failed_windows']}; unavailable verification: {report['verification_unavailable_windows']}.", '',
             '| Estimate | Windows | Count MAE | Count bias | Colour errors | False green / non-green truth |', '| --- | --- | --- | --- | --- | --- |']
    for name, result in report['metrics'].items():
        lines.append(f"| {name} | {result['evaluated_windows']} | {result['mean_absolute_count_error']} | {result['mean_count_bias']} | {result['colour_errors']} | {result['false_green_windows']} / {result['non_green_truth_windows']} |")
    lines += ['', '## Local timing', '', f"Model initialization: {report['runtime']['initialization_seconds']:.3f}s.", '', '| Stage | Windows | Median seconds | P95 seconds |', '| --- | --- | --- | --- |']
    for name, result in report['timing'].items():
        lines.append(f"| {name} | {result['n']} | {result['median_seconds']} | {result['p95_seconds']} |")
    lines += ['', '## Limits', ''] + ['- ' + note for note in report['limitations']]
    if report['scope'] == 'nonrepresentative_smoke':
        lines += ['', '**This is a smoke test, not a train-coach accuracy evaluation.**']
    lines += ['', 'See the adjacent JSON report for per-window errors, counts, exact frame indices, confusion matrices and provenance.', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--output', type=Path, required=True, help='New output directory; existing reports are never overwritten')
    parser.add_argument('--verify', action='store_true', help='Use the running local verifier for each labelled window')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output directory already exists; choose a new run directory')
    verifier = LocalVisionVerifier({'endpoint': 'http://127.0.0.1:8081/v1/chat/completions', 'model': 'elbow-verifier', 'timeout_seconds': 120}) if args.verify else None
    try:
        report = evaluate(args.manifest, verifier=verifier)
        args.output.mkdir(parents=True, exist_ok=False)
        (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        (args.output / 'report.md').write_text(markdown(report))
    except (ValueError, OSError, VideoError) as error:
        parser.error(str(error))
    print(f"Report: {args.output / 'report.md'}")
    if report['failed_windows'] or report['verification_unavailable_windows']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
