"""Compare model readings with user-supplied image categories, without inventing counts."""
import argparse
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from apps.backend.elbow_room.evaluation import colour


def report(labels_path, database):
    labels = json.loads(labels_path.read_text())
    results = []
    with closing(sqlite3.connect(f'{database.resolve().as_uri()}?mode=ro', uri=True)) as connection:
        for sample in labels['samples']:
            saved = [json.loads(row[0]) for row in connection.execute(
                "SELECT payload FROM observations WHERE json_extract(payload, '$.coach_id')=? ORDER BY id DESC",
                (sample['coach_id'],))]
            # Inspect the checked observation, even after newer regular samples arrive.
            observation = next((row for row in saved if row.get('verification', {}).get('status') in ('verified', 'unavailable', 'pending')), saved[0] if saved else None)
            result = {**sample, 'observation': observation}
            if observation:
                regular = observation.get('regular_passenger_count', observation['passenger_count'])
                result.update(regular_colour=colour(regular, observation['capacity']),
                    effective_matches_user_category=observation['status'] == sample['expected_colour'])
            results.append(result)
    return {'scope': labels['scope'], 'capacity': labels['capacity'], 'capacity_basis': labels['capacity_basis'],
        'count_mae': None, 'count_mae_reason': 'No manually annotated passenger counts were supplied',
        'note': 'Three user-labelled still images are preliminary category checks, not a representative video accuracy benchmark. Expected labels never override model predictions.',
        'samples': results}


def markdown(data):
    lines = ['# User image comparison', '', f"Capacity: {data['capacity']} per coach, provisionally configured.", '', data['note'], '',
             '| Image | Expected | Regular count / colour | AI count | Effective percent / colour | Verification |', '| --- | --- | --- | --- | --- | --- |']
    for sample in data['samples']:
        row = sample['observation']
        if row is None:
            lines.append(f"| {sample['original_filename']} | {sample['expected_colour']} | No observation | — | — | — |")
            continue
        check = row.get('verification', {})
        lines.append(f"| {sample['original_filename']} | {sample['expected_colour']} | {row.get('regular_passenger_count', row['passenger_count'])} / {sample['regular_colour']} | {check.get('passenger_count', '—')} | {row['occupancy_percent']}% / {row['status']} | {check.get('status', 'not_recorded')} |")
    lines += ['', 'The low/empty reference contains visible passengers; it is not labelled zero people. Count MAE is unmeasured because exact manual counts are absent. Camera coverage and real capacity remain unverified. Repeating each image in a video does not add independent evaluation samples.', '']
    return '\n'.join(lines)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--labels', type=Path, required=True)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New directory for the comparison')
    args = parser.parse_args()
    try:
        result = report(args.labels, args.database)
        args.output.mkdir(parents=True, exist_ok=False)
        (args.output / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
        (args.output / 'report.md').write_text(markdown(result))
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.error(str(error))
    print(args.output / 'report.md')
