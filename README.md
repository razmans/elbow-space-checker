# Elbow Room

Elbow Room is an **MIT-licensed, local train-coach occupancy demo**. It estimates visible passenger counts from recorded video or an RTSP camera and shows each coach's occupancy, colour, freshness, and configured platform position in a React dashboard.

The monorepo contains a Python backend and a TypeScript / React / Vite frontend. SQLite stores aggregate observations, and Server-Sent Events (SSE) update the dashboard without reloading. A separate local vision model periodically checks the detector's estimate.

**No OpenAI account, OpenAI API key, Firestore, or hosted AI service is required.** Detection and verification run on your machine. Setup downloads public dependencies and model files; inference can run offline afterward.

> This is an experimental demo, not boarding guidance. The current models misclassify the supplied mid/full reference images as green at the provisional capacity of 100. Camera coverage and representative train-video accuracy remain unvalidated. See the [evaluation report](docs/evaluation-report.md).

## What it does

- Compare three independently configured coaches, with explicit simulation, recording, or RTSP source labels.
- Sample a short video window every 60 seconds by default and use the median per-frame passenger count.
- Calculate occupancy as `estimated count / configured capacity × 100`.
- Show **green below 30%**, **yellow from 30% through 80%**, and **red above 80%**.
- Mark readings unknown after two missed intervals; distinguish missing data from a valid zero.
- Verify the same sampled images initially and every 30 minutes with a separate local model.
- Preserve original and AI counts, disagreements, and separate observation/completion timestamps in browsable history.
- Reconnect to RTSP streams automatically and support accelerated recorded-video playback.

A valid verifier count overrides only the observation it checked. Failed verification retains the regular estimate. Delayed results cannot replace newer live readings or refresh an old timestamp. AI verification is another estimate, not established ground truth.

## Requirements

| Mode | Requirements |
| --- | --- |
| Simulation | Python 3.11+, Node.js 22.12+ and npm; Node 24 is pinned in `.mise.toml` |
| Video detection | Python 3.12+, the optional video dependencies, and downloaded detector weights |
| Local AI verification | The bundled setup targets Linux x86-64 and runs on CPU; other platforms need a compatible local llama.cpp server |
| Local RTSP replay test | Optional MediaMTX download and FFmpeg with the `libx264` encoder on PATH |

Commands below use a Unix shell and run from the repository root. The default servers bind to loopback only.

## Quick start: no camera or model required

After cloning this repository:

```sh
cd elbow-room
npm ci
npm run dev
```

Open **http://127.0.0.1:5173**. The Python API runs at **http://127.0.0.1:8000**. Three clearly labelled simulated coaches update every minute. Press Ctrl+C to stop both services.

For faster updates, run these in separate terminals:

```sh
python3 -m apps.backend.elbow_room.server --interval 3
```

```sh
npm run dev:web
```

Do not run a second API on the same port alongside `npm run dev`.

## Install the optional video and AI runtime

Use Python 3.12 or newer for the virtual environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r apps/backend/requirements-video.txt
npm run model:download
npm run verifier:setup
```

The regular detector is CPU **MobileNet-SSD** through OpenCV (about 23 MB of model downloads). The separate verifier is **SmolVLM-500M Q8** through **llama.cpp** (about 563 MB of downloads including runtime and vision projector). Downloaded assets are pinned and SHA-256 checked, stored under ignored `data/`, and never automatically downloaded during inference.

Project code uses MIT; dependencies and model weights retain their own licences. See [detector provenance](docs/video-detector.md) and [verifier provenance](docs/rtsp-verification.md).

## Run a recording

After optional setup:

```sh
npm run demo -- --video /absolute/path/to/coach.mp4 --interval 60 --speed 10
```

The launcher starts the API, dashboard, and local verifier together. Coach 01 uses the recording; the other two remain labelled simulations. At 10× playback, a 60-second media interval takes six wall-clock seconds. For short clips, use `--interval 3 --speed 1`.

The recording ends at EOF, making its current reading unknown while preserving history. Add `--without-verifier` for detector-only operation; then the verifier download is optional.

Every launcher run saves its configuration, SQLite database, and logs in a new `data/demo-runs/` directory. Ctrl+C stops only the services that launcher started. It refuses occupied ports; alternatives include `--port 8070 --web-port 5177 --verifier-port 8083`.

## Run an RTSP camera

With optional video/AI setup complete:

```sh
export COACH_01_RTSP_URL='rtsp://camera-address/stream'
npm run demo -- --rtsp --interval 60
```

Replace the example with your camera's URL. If authentication is required, keep the actual URL in your local environment rather than committing it. The API does not expose camera URLs. RTSP disconnections expire old readings and trigger automatic retries; fresh observations restore the display.

For per-coach settings, copy and edit `config/rtsp.example.json`. Start a prepared configuration with:

```sh
npm run demo -- --config /absolute/path/to/local-config.json
```

Prepared configurations retain their own intervals, capacities and playback speeds. The launcher supplies its local verifier endpoint. See [capture and verification behaviour](docs/rtsp-verification.md), including the limitation that RTSP timestamps represent frame reception rather than camera capture time.

## Demo without real footage

After creating the optional Python environment, `npm run demo` runs a faster three-coach simulation that demonstrates missed observations, unknown status, recovery, and a valid zero.

To exercise the actual RTSP transport and local models using known-empty synthetic video:

```sh
python3 scripts/setup-local-services.py --rtsp-test-server
npm run evaluation:smoke:prepare
npm run demo -- --rtsp-video data/evaluation-smoke/empty.avi
```

This also needs FFmpeg, detector weights, and the local verifier setup. Synthetic footage establishes software integration only, not passenger-counting accuracy. Follow the [complete demo runbook](docs/demo-runbook.md).

### Use your own reference images

Reference photos and generated clips are **not included in a public clone**. Prepare your own local low, mid, and full images:

```sh
.venv/bin/python scripts/prepare-image-demo.py \
  --empty /path/to/emptyCoach.jpg \
  --mid /path/to/midTrain.jpeg \
  --full /path/to/fullTrain.jpeg \
  --capacity 100 --output data/user-train-images
npm run demo:images
```

The script creates three five-minute static replays in a new output directory. It preserves the originals and keeps expected category labels separate from actual predictions. Capacity 100 is an unvalidated demo assumption. See [image-case instructions and results](docs/user-image-demo.md).

## Configuration and history

`config/demo.json` defines train/platform names, travel direction, and an ordered coach list. Each coach has an ID, name, positive capacity, source, interval, position, and platform zone. Simulations use a repeating `counts` list; `null` represents a missed update. Configured positions are illustrative, not live train tracking or exact-door guidance.

`config/video.example.json` and `config/rtsp.example.json` show video settings. Relative video/model paths resolve against the configuration file. Video verification defaults to enabled, with a 1,800-second interval; set `verification.enabled` to `false` to disable it. Recorded-source scheduling uses media time; live scheduling uses elapsed wall time.

The dashboard's **Observation history** section filters by coach and paginates saved records. It shows original and verifier counts, effective occupancy, disagreements, and both timestamps in your local timezone. History refreshes every five seconds and survives restart. Historical colours describe the saved observation, not current freshness.

Default backend history is `data/elbow-room.sqlite3`; launcher runs have separate databases. To reopen a saved run, start the backend with `--config PATH --database PATH`, then `npm run dev:web`. This preserves history while starting new live producer cycles. Start `npm run verifier:start` separately if that configuration enables verification.

## API

| Endpoint | Response |
| --- | --- |
| `GET /api/health` | Server readiness, not camera/model health |
| `GET /api/state` | Current train snapshot with per-coach freshness |
| `GET /api/observations/latest` | Alias of `/api/state` |
| `GET /api/observations` | Latest 100 saved observations, newest ID first |
| `GET /api/history` | `{items, next_before}`; optional `coach_id`, `limit` (1–100, default 20), and exclusive `before` ID cursor |
| `GET /api/events` | Named `state` SSE events containing complete snapshots |

The shared TypeScript contract is `contracts/observation.ts`. SSE sends current state rather than guaranteeing delivery of every historical event. Set `ELBOW_API_URL` for Vite if the API runs on a different port.

## Repository layout

```text
apps/backend/   Python capture, detection, verification, API and tests
apps/web/       React / TypeScript / Vite dashboard
config/         Example coach and source configurations
contracts/      Shared TypeScript response types
scripts/        Local model setup, demo launchers and dataset preparation
tests/          Browser integration tests
docs/           Runbooks, model licences and evaluation evidence
data/           Ignored local inputs, model weights, logs and databases
```

## Tests and evaluation

Basic simulation checks need no model downloads:

```sh
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

With video/model dependencies installed:

```sh
npm run test:backend
npm run test:e2e:video
npm run test:e2e:verification
npm run test:rtsp       # also needs MediaMTX and FFmpeg
npm run test:e2e:demo   # complete RTSP + real local models + browser
```

You can use an installed Chromium with `PLAYWRIGHT_CHROMIUM_EXECUTABLE=/usr/bin/chromium`. Optional backend cases skip when their dependencies are absent. Behavioural tests use controlled inputs where needed; passing tests do not establish real-model accuracy.

The [evaluation guide](docs/evaluation.md) explains manually labelled frame windows and reports count error, colour error, false-green rates, and timings. Run it with:

```sh
npm run evaluate -- data/labels/manifest.json --output data/evaluation-runs/run-01
```

Add `--verify` while `npm run verifier:start` is running to compare both models. Output directories must be new. See the [evaluation report](docs/evaluation-report.md) for observed limitations and the failed mid/full image checks.

## Credentials and public repository contents

**This project does not use OpenAI credentials or call OpenAI's hosted API.** Its verifier endpoint is a local llama.cpp server on `127.0.0.1:8081`; the backend accepts only loopback verifier endpoints and disables proxies and redirects for image requests.

`.gitignore` excludes local data, recordings, model weights, databases, logs, environment files (including `.env.local` and `.env.production`), common credential files, and private keys. Sanitized `.env.example` templates may be committed if added later. The application reads environment variables from the shell; it does not automatically load `.env` files.

Keep private RTSP settings in your local environment and local media under `data/`. Images and model files are not part of the project's MIT grant. Do not force-add ignored local files. The dashboard receives aggregate data; sampled passenger images stay local and are not archived by the capture/verification service.

## Scope and licence

This is a local development demo. Python's standard-library HTTP server and the Vite development server are not a production deployment. Arrival predictions, automatic boarding recommendations, live train tracking, and fleet-scale operation are outside the current scope.

[MIT](LICENSE) applies to project-authored code. Third-party software, model weights, and user-supplied media retain their respective licences and rights.
