# Elbow Room — AI project handoff

This file preserves project context for coding assistants. Read [README.md](README.md) for setup and [docs/evaluation-report.md](docs/evaluation-report.md) for actual model results. Treat this as a handoff snapshot, not proof that the current checkout or local services match a previous run.

## Purpose and agreed scope

Elbow Room is an MIT-licensed Python + TypeScript monorepo demonstrating train-coach occupancy estimates. It supports simulation, recorded video, and RTSP. A React/Vite dashboard compares three coaches and their configured platform positions, with percentages, colours, freshness, source labels and observation history.

The user chose local, open-source operation: SQLite and SSE, not Firestore; local inference, not hosted AI. No OpenAI account or API credentials are used. Keep dependency/model licensing separate from the project's MIT licence.

Arrival prediction, automatic best-coach recommendations, exact-door guidance, live train tracking, production deployment, custom training, and guaranteed whole-coach accuracy are outside the implemented scope.

## Behaviour to preserve

- Regular sampling defaults to one short window every 60 seconds. The default window is two seconds with three frames. Count people per frame, then take the median rounded half up; never sum recurring passengers across frames.
- Occupancy is count divided by configured positive capacity times 100. Classify the unrounded value: green below 30%, yellow from 30% through 80%, red above 80%. Keep percentages above 100%; only the visual bar is capped.
- A valid zero is distinct from a failed observation. Missing samples must not create zero readings or refresh timestamps. Two missed intervals make current occupancy unknown.
- Each coach has independent configuration and freshness. Always identify simulated inputs and recorded/static replays honestly.
- Recorded sources use media time for scheduling, expiry, and accelerated playback. EOF makes the source unavailable while retaining history. Skip obsolete sampling windows after slow inference.
- RTSP continuously drains into one latest-frame slot. Disconnect clears that slot; generation changes prevent results from an old connection repopulating current state. Timestamps are frame-reception times, not independently verified camera-capture times.
- A separate local vision model checks the same sampled images on the first valid observation and every 1,800 seconds thereafter. Verification is asynchronous, bounded, and must not block regular capture.
- A valid AI count overrides only its associated observation. Preserve the original count, AI count, disagreement, original observation time and verification completion time. The next regular observation becomes current. A late check may update history but cannot replace a newer live reading or make old data fresh.
- Failed, malformed, timed-out or unassessable verification retains the regular estimate and records verification unavailable. This fallback preserves functionality; it does not establish the regular estimate's accuracy.
- Historical colours describe saved estimates, not current availability. History survives restart; interrupted pending jobs become unavailable.
- Runtime images remain local/in memory. Publish aggregate readings only. Do not introduce passenger identification, external image uploads or persistent runtime frame archives.

## Implementation map

| Area | Location and approach |
| --- | --- |
| API, configuration, SQLite, SSE | `apps/backend/elbow_room/server.py`; standard-library `ThreadingHTTPServer` |
| Recorded replay and regular detector | `apps/backend/elbow_room/video.py`; OpenCV CPU MobileNet-SSD VOC person class |
| Detector downloads/checksums | `apps/backend/elbow_room/model.py` |
| RTSP capture/recovery | `apps/backend/elbow_room/rtsp.py` |
| Local vision requests and job queue | `apps/backend/elbow_room/verification.py` |
| Labelled-window evaluation | `apps/backend/elbow_room/evaluation.py` |
| Dashboard and history view | `apps/web/src/main.tsx`, `apps/web/src/History.tsx`, `apps/web/src/style.css` |
| Response contracts | `contracts/observation.ts`; keep Python responses and TypeScript consumers aligned |
| Example configurations | `config/demo.json`, `config/video.example.json`, `config/rtsp.example.json` |
| Local service setup/launch | `scripts/setup-local-services.py`, `scripts/run-verifier.py`, `scripts/run-demo.py` |
| Static reference-image preparation/reporting | `scripts/prepare-image-demo.py`, `scripts/report-image-demo.py` |
| Tests | `apps/backend/tests/`, `tests/`, `playwright*.config.ts` |

The verifier is SmolVLM-500M Q8 through llama.cpp, CPU-only with two threads and one inference slot. The supplied optional binary setup targets Linux x86-64. Model and runtime assets are pinned and SHA-256 checked. See the provenance documents before changing models or downloaded binaries.

The loopback verifier uses `/v1/chat/completions` with structured JSON containing `assessable` and `passenger_count`. This is a local compatibility endpoint, not an OpenAI-hosted service. Redirects and proxies are disabled. Preserve loopback validation and keep raw request/image data out of public responses and logs.

SQLite stores JSON observation payloads. `/api/state` and named `state` SSE events provide complete snapshots. `/api/observations` provides the newest 100 records; `/api/history` provides coach filtering and exclusive-ID cursor pagination with `{items, next_before}`. See the README for the full API contract.

## Implementation status

The original numbered work was:

1. One simulated coach through SQLite/SSE/dashboard — implemented.
2. Stale readings and reconnection — implemented.
3. Three-coach comparison and configured platform diagram — implemented.
4. Recorded-video detection and accelerated replay — implemented.
5. RTSP capture/recovery — implemented.
6. Separate local AI verification and disagreement handling — implemented.
7. Occupancy and verification history — implemented.
8. Complete demo and real-footage evaluation — demo and evaluation tooling implemented; representative video accuracy evaluation remains incomplete.

Do not mark ticket 8 fully complete based on synthetic videos, repeated stills, or passing integration tests. No numerical accuracy target has been agreed.

## Supplied image cases and known failures

The user provided three images and approved **capacity 100 provisionally for every case**:

| File | User reference category | Expected colour |
| --- | --- | --- |
| `emptyCoach.jpg` | Low / empty | Green |
| `midTrain.jpeg` | Mid | Yellow |
| `fullTrain.jpeg` | Full | Red |

The low reference visibly contains passengers; it is not a zero-person annotation. Exact manual passenger counts, confirmed coach capacity, and whole-coach camera coverage have not been supplied. The user initially had no footage and later supplied these still images; moving footage is still unavailable.

In the recorded run, regular counts were **0, 6, 6**. The AI returned **12 for low, 12 for mid, and unavailable for full**. All checked effective colours were green at capacity 100. Both mid/full therefore failed their expected category checks. The low colour match does not validate either count. Preserve these failures honestly; do not hard-code expected colours, fabricate manual counts, or tune a different capacity per image to make the results pass.

Prepared originals, five-minute static replays, config, reports and screenshots live under ignored `data/user-train-images/` on the original development machine. They are not part of a public clone. Recreate them from user-provided files using [docs/user-image-demo.md](docs/user-image-demo.md). Only aggregate evidence is included under `docs/evidence/`; do not copy photos into tracked files or assume the project's MIT licence covers them.

Model quality is the main unresolved issue. Any future model change should be evaluated against the supplied reference categories and, when available, reviewed exact counts and representative footage. Keep count-based occupancy separate from any proposed direct visual-crowding classification; changing that policy needs an explicit product decision.

## Commands and local operation

Run from the repository root. Simulation needs Python 3.11+ and Node 22.12+; Node 24 is pinned. Optional video dependencies require Python 3.12+.

```sh
npm ci
npm run dev                       # simulation, no model downloads needed

python3 -m venv .venv
.venv/bin/python -m pip install -r apps/backend/requirements-video.txt
npm run model:download
npm run verifier:setup
npm run demo                      # faster simulation with missed updates/recovery
npm run demo:images               # requires locally prepared image cases
npm run demo -- --video /path/to/coach.mp4 --interval 60 --speed 10
```

Default ports: API 8000, Vite 5173, verifier 8081. `run-demo.py` manages its own services, refuses occupied ports, and saves each run in a new `data/demo-runs/` directory. Ctrl+C or a bounded `--duration` stops its processes and preserves history. Do not kill unrelated services to free ports. Prepared `--config` sources retain their own intervals/capacities/speeds.

For RTSP, set `COACH_01_RTSP_URL` locally and run `npm run demo -- --rtsp --interval 60`. A local replay uses `--rtsp-video PATH` and needs the optional MediaMTX runtime and FFmpeg/libx264. See [docs/demo-runbook.md](docs/demo-runbook.md).

## Validation approach

The user approved testing through the running system, from controlled source/detector/verifier inputs through persistence/API and the dashboard. Use deterministic inference substitutes for behavioural tests; evaluate real-model accuracy separately against labelled footage. Real RTSP publisher tests and real-model smoke tests complement these boundaries.

```sh
npm test                          # optional cases may skip without dependencies
npm run build
npm run test:backend               # optional Python environment, full backend suite
npm run test:e2e
npm run test:e2e:video
npm run test:e2e:verification
npm run test:rtsp                  # optional MediaMTX + FFmpeg required
npm run test:e2e:demo              # actual RTSP + local models + browser
```

Use `PLAYWRIGHT_CHROMIUM_EXECUTABLE=/usr/bin/chromium` when available, or install Playwright Chromium. Browser tests start actual local services; ensure their ports are free. Check desktop and mobile when changing the UI.

At this handoff, the latest full backend run passed **31 tests**. The full RTSP demo browser regression and an actual three-image browser check also passed. The production build previously passed. These are historical results, not claims about future edits or accuracy. Documentation-only changes since then were checked for valid README links, existing npm commands, ignored private paths and credential patterns.

## Public-repository hygiene

The user plans to publish this repository on GitHub. A project-file audit found no OpenAI credentials or hosted OpenAI usage. Credential-like URLs found in dependency templates and negative tests were placeholders, not real secrets.

Keep environment files, credentials, private keys, recordings, model weights, logs, SQLite databases and local image assets ignored. Sanitized `.env.example` files are permitted by `.gitignore`; never put real keys in them. The app reads shell environment variables and does not automatically load `.env` files. Do not force-add ignored artifacts or copy machine/account authentication into the project.

Do not assume local weights, input images, virtual environments or model services exist in a fresh checkout. Use documented explicit setup steps. Keep local paths portable in tracked documents, and update the README and evaluation evidence when behaviour or findings change.
