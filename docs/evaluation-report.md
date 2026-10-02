# Ticket 8 — demonstration and evaluation status

## Update: user-provided train stills

The user subsequently supplied `emptyCoach.jpg`, `midTrain.jpeg`, and `fullTrain.jpeg` as low/green, mid/yellow, and full/red references, and approved capacity **100 provisionally** for all three. These now run as three static image replays through the real detector, local verifier, history and dashboard. They are not synthetic empty scenes. The earlier synthetic results below remain a separate historical smoke run.

| Reference | Regular count | AI count | Effective colour for checked observation | Expected |
| --- | --- | --- | --- | --- |
| Low / empty | 0 | 12 | Green (12%) | Green |
| Mid | 6 | 12 | Green (12%) | Yellow |
| Full | 6 | Unavailable: could not assess every frame | Green (6%, regular retained) | Red |

**The present models fail the mid and full category checks.** Both produce falsely reassuring green relative to the user labels at the agreed provisional capacity. Even the low category match does not validate the count: the picture visibly contains passengers, while the regular detector returns zero and the verifier estimates twelve. No exact manual counts were supplied, so count MAE remains unmeasured. Do not tune individual image capacities to conceal these failures.

These are preliminary outcomes on three related stills. Unknown camera coverage, occlusion, model limitations, and the provisional capacity prevent claims of whole-coach accuracy. Repeated frames add no independent samples. The first checked observations retain their AI results; subsequent regular observations remain current under the agreed policy. The full image's unavailable check correctly retains the baseline estimate, but that failure policy does not make the baseline accurate.

See [aggregate evidence](evidence/user-train-image-comparison.json) and [reproduction instructions](user-image-demo.md). The images and generated clips remain in ignored local storage. Representative moving-video evaluation and independently reviewed counts remain outstanding.

## Earlier synthetic evaluation

**2026-10-02: demonstration and evaluation tooling implemented; representative train accuracy evaluation pending.** The user confirmed that no train footage is available. No passenger-labelled train dataset, actual coach capacity, or camera coverage evidence was supplied. Ticket 8 cannot be marked fully complete on synthetic inputs alone.

## Demonstrated locally

A three-coach run exercised a known-empty synthetic file through FFmpeg → loopback MediaMTX RTSP → real MobileNet-SSD → SQLite/API/SSE → React dashboard, with a separate real SmolVLM check on the same samples. Two other coaches remained clearly labelled simulations. The RTSP source was explicitly labelled a replay. A valid completed verification and subsequent independent regular observations were visible in coach history.

The optional browser test passed with desktop and mobile layouts. A separate bounded launcher run shut down automatically and retained its history. All API, web, and verifier ports opened by those runs were confirmed closed afterward. Existing backend tests also exercised RTSP disconnect/recovery, delayed AI results, stale readings, and persisted history.

Validation in this implementation run: **29 backend tests passed, full-demo browser test passed, production build passed.** Controlled metric tests include undercounting, colour mismatches, false green, verifier failure/fallback, invalid label alignment, decoding failure, and empty denominators. Controlled tests establish software behaviour, not model accuracy.

## Measured synthetic smoke run

The [aggregate JSON evidence](evidence/ticket8-synthetic-smoke.json) records a real evaluation run on three windows of the same solid-grey, known-empty clip. There are no people, no coach interior, and no independent scenes. Labels are zero by construction, not manual passenger annotations. Configured capacity 100 is arbitrary for this fixture.

Machine: AMD Ryzen 3 3200G, four CPU cores, Linux x86-64, Python 3.14.7. OpenCV 4.13.0.92 and NumPy 2.5.3. Regular detector: pinned CPU MobileNet-SSD at confidence 0.5. Verifier: pinned SmolVLM-500M Q8 through llama.cpp, two CPU threads. The detector/verifier provenance and hashes are documented in [video detector](video-detector.md) and [RTSP/verification](rtsp-verification.md).

| Measurement | Observed value | Interpretation |
| --- | --- | --- |
| Attempted / decoded windows | 3 / 3 | Pipeline smoke coverage only |
| Available AI checks | 3 / 3 | Structured local inference completed |
| Regular / AI / effective count MAE | 0 / 0 / 0 | Only on known-empty synthetic frames |
| Colour errors | 0 across three windows | All truth windows are green |
| False-green rate | **Not measurable** | Zero non-green ground-truth windows; rate is null |
| Detector initialization | 0.128 s | One initialization |
| Window decode median / P95 | 0.005 / 0.005 s | Three sampled frames per window |
| Detector median / P95 | 0.117 / 0.169 s | Three inference calls per window |
| Verifier median / P95 | 2.186 / 2.207 s | Three image requests per window, warm local server |

These timings were recorded while the three-coach demo was active. The repeated identical image and warm verifier cache favour fast responses. In the separate browser demonstration, the first verification took roughly 16 seconds from observation time to completion; that includes waiting and runtime load and is not directly comparable to warm offline inference timing. These measurements do not establish latency on crowded images, three simultaneous video sources, other hardware, or a real camera. P95 from only three windows is the largest of three measurements, not a stable tail-latency estimate.

## Required evidence still missing

| Required evaluation | Status |
| --- | --- |
| Representative train footage with known processing rights | Not available |
| Independently reviewed passenger counts on exact sampled frames | Not available |
| Actual coach capacity and whole-coach camera coverage | Unverified |
| Count MAE/bias across crowded and uncrowded coach scenes | Unmeasured |
| Coach colour errors and falsely reassuring green readings | Unmeasured |
| Lighting, occlusion, seated/distant-passenger performance | Unmeasured |
| Camera capture latency and sustained multi-camera inference timing | Unmeasured |
| Agreed numerical acceptance targets | Not set; no passing target invented |

The existing upstream example image is also nonrepresentative and is not included as passenger-labelled train evidence. There is no accuracy or boarding-suitability claim. Once suitable footage is available, use the [annotation and evaluation guide](evaluation.md), report excluded/unassessable scenes and coverage limits, and review the resulting failure cases before setting an acceptance policy.
