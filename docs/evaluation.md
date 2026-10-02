# Evaluate manually labelled footage

Ticket 8's representative-video evaluation is pending. The user has now provided three coach stills labelled low, mid and full; these support preliminary category checks but have no exact manual passenger counts. See [the image cases](user-image-demo.md) and [the evaluation report](evaluation-report.md). Synthetic clips and the upstream detector example remain smoke inputs only.

## Prepare labels

Use local recordings that you are entitled to process. Keep recordings, labels, and generated reports under ignored `data/`; do not commit passenger imagery. Record source/licence or permission, camera location and coverage, lighting, crowded/uncrowded conditions, and annotation date. Evaluate distinct clips and time periods rather than treating adjacent or repeated frames as independent evidence.

Manually count each visible person once in every sampled frame, including partially visible people when a person can be identified consistently. Document uncertain or uncountable windows separately; do not silently label them zero or remove difficult scenes without accounting for them. Independently review ambiguous labels before using them as ground truth. Coverage of a doorway or part of the coach cannot validate whole-coach occupancy.

Create a JSON manifest. This example is a **template**, not an annotated dataset; replace every placeholder and supply your own counts:

```json
{
  "schema_version": 1,
  "dataset_name": "REPLACE with dataset name",
  "scope": "representative_coach",
  "provenance": "REPLACE with source, rights, camera view, conditions and label-review method",
  "annotator": "REPLACE with reviewer identity",
  "labelled_at": "REPLACE with annotation date",
  "samples": [
    {
      "id": "coach-a-window-01",
      "video": "coach-a.mp4",
      "capacity": 100,
      "coverage": "unknown",
      "start_seconds": 0,
      "window_seconds": 2,
      "sample_count": 3,
      "frame_indices": [0, 30, 60],
      "manual_counts": [null, null, null]
    }
  ]
}
```

Video paths resolve relative to the manifest. Null counts intentionally make this template invalid until annotation is complete. `frame_indices` are zero-based decoded frame positions. The example positions assume 30 FPS; check the actual file. Sampling follows the production recorded-video adapter: round the start/end frame positions, clip to EOF, then sample evenly spaced unique positions. The runner rejects labels if the exact decoded positions do not match. Use seekable constant-frame-rate footage; variable-frame-rate material needs separate timestamp validation before evaluation.

Allowed coverage values are `whole_coach`, `partial`, and `unknown`. `scope` is either `representative_coach` or `nonrepresentative_smoke`; it is the dataset author's declaration, not an automated certification. Inspect coverage and provenance alongside every metric. Whole-coach accuracy requires actual whole-coach ground truth and camera coverage, not merely setting this field.

## Run

With the optional video dependencies and pinned detector installed:

```sh
npm run evaluate -- data/labels/manifest.json --output data/evaluation-runs/run-01
```

For comparison with the separate local model, start `npm run verifier:start` in another terminal and add `--verify`. Evaluation uses the production verifier's structured-response validation and loopback-only transport. It evaluates every labelled window, independent of the live 30-minute schedule. Stop the verifier after the evaluation.

The output directory must be new; earlier reports are not overwritten. `report.json` contains per-window labels, video SHA-256, manifest SHA-256, predicted counts, errors, source coverage, runtime metadata and confusion matrices. `report.md` summarizes the result. Frames remain in memory; the runner does not export images or upload them. Decoder/model failures are recorded and excluded from evaluated-count denominators, not treated as zero. Verifier failures preserve the regular count in effective metrics. A run with failed windows or unavailable verifications exits nonzero while preserving its report for inspection.

## Metric definitions

- Ground-truth window count: the median of manually labelled per-frame counts, with half-integers rounded up, matching the production aggregation policy.
- Count MAE: mean absolute difference between predicted and ground-truth window count.
- Count bias: mean predicted minus ground-truth count; a negative value means undercounting.
- Colour error rate: mismatched predicted/truth classifications divided by evaluated windows. Thresholds are green below 30%, yellow from 30% through 80%, and red above 80%, using configured capacity.
- False-green rate: green predictions on non-green ground truth divided by evaluated non-green ground-truth windows. A null rate means no eligible denominator, not 0% risk.
- Separate metrics are emitted for the regular detector, valid AI results, and effective counts after fallback. AI-only results cover only assessable checks; compare denominators before interpreting improvements.
- Timing: initialization plus per-window decoding, detector inference, and verifier HTTP/inference latency. The median and nearest-rank P95 include the first measured window. They exclude file hashing. Model-server startup and end-to-end camera latency are not included. Record concurrent machine load and warm caches when comparing runs.

Do not establish a passing accuracy threshold from the observed score. First inspect representative footage, agree on an acceptable count/colour error policy, and report falsely reassuring green outcomes separately. Empty synthetic scenes contain no crowd-detection evidence; repeated images give no independent statistical confidence.

## Synthetic runner smoke test

```sh
npm run evaluation:smoke:prepare
npm run evaluate -- data/evaluation-smoke/manifest.json --output data/evaluation-runs/smoke-01
```

This generates three windows of the same uniformly grey, known-empty clip. Counts are zero by construction, not manual annotations of train passengers. Its manifest and report are explicitly marked `nonrepresentative_smoke`. The automated metric tests additionally use controlled inference to exercise false-green errors, count bias, malformed labels, decoding failure and verifier fallback; those tests do not measure model accuracy.
