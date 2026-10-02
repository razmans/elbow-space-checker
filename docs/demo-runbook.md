# Repeatable three-coach demo

Complete the README's Node/Python video setup and download the pinned detector. For the full camera-path smoke demo, also run:

```sh
npm run verifier:setup
python3 scripts/setup-local-services.py --rtsp-test-server
```

The RTSP replay option needs `ffmpeg` with the `libx264` encoder on PATH. The bundled optional services target Linux x86-64. No external camera or hosted AI service is needed for the synthetic smoke demonstration.

## Start with simulation

```sh
npm run demo
```

Open `http://127.0.0.1:5173`. Every launch creates a new directory in `data/demo-runs/` containing its configuration, logs, and SQLite history. Existing runs are preserved. The API is on port 8000. The launcher refuses occupied ports; it never takes over an existing service.

This profile updates every three seconds. Coach 01 starts green, misses three updates and becomes unknown, recovers red, and then shows a valid zero. Coaches 02 and 03 continue independently. The six-step sequence repeats. All three are visibly labelled simulated.

## Exercise the complete RTSP path without footage

```sh
npm run evaluation:smoke:prepare
npm run demo -- --rtsp-video data/evaluation-smoke/empty.avi
```

The input is **synthetic solid-grey video with no people or train interior**, repeated continuously. This demonstrates transport and software integration only. The train title and Coach 01 name explicitly identify RTSP replay; its source badge identifies the live RTSP transport. The other coaches remain simulations.

The launcher starts a loopback-only MediaMTX server on an available port, an FFmpeg publisher, the real CPU detector, a separate local SmolVLM verifier, Python API/SQLite/SSE, and Vite. The first valid observation is verified; later checks retain the normal 30-minute interval. A valid AI count applies only to its checked observation. Subsequent regular samples remain current.

Walk through these checks:

1. Compare all three coach percentages and the configured platform positions. Confirm the source labels.
2. Wait for Coach 01's first valid sample and completed AI check. Check the original and verifier counts in Observation history.
3. Observe subsequent samples. A previous AI check becomes historical without replacing the newer live reading.
4. Select Coach 01 in history. Inspect observation and verification completion times separately.
5. Toggle browser network offline long enough for the readings to expire, then reconnect. Current state should recover without reloading.
6. Stop with Ctrl+C. The launcher stops only its own services and keeps the run's aggregate history. Reopen that database with `--database` on the backend to inspect persisted records; live producers start a new cycle.

RTSP loss/recovery is tested automatically by `npm run test:rtsp`, which stops and restarts a real publisher with different content. Recorded EOF and malformed/delayed verification have separate integration tests. These are distinct from real-model accuracy evaluation.

## Use the supplied static images

Run `npm run demo:images` to use the prepared low, mid and full references together. See [image setup and interpretation](user-image-demo.md). This runs actual inference with capacity 100 for all three cases, and does not force the expected colours.

## Use real inputs when available

```sh
npm run demo -- --video /absolute/path/to/coach.mp4 --interval 60 --speed 10
```

Recorded intervals and verification scheduling use media time. Simulation and RTSP intervals use wall time. Each video sample uses up to a two-second window. EOF ends the recorded source and makes its current reading unknown; history remains available.

For an actual camera, set the URL in the environment:

```sh
export COACH_01_RTSP_URL='rtsp://camera-address/stream'
npm run demo -- --rtsp --interval 60
```

Camera URLs are not written into generated configurations. `--without-verifier` runs detector-only. To avoid port conflicts, use `--port`, `--web-port`, and `--verifier-port`. `--duration 30` stops the demo after 30 seconds of readiness; `--no-web` starts only the backend and required video services. API readiness means the server is listening, not that the camera has yielded a valid sample.

## Automated demonstration

```sh
PLAYWRIGHT_CHROMIUM_EXECUTABLE=/usr/bin/chromium npm run test:e2e:demo
```

The optional full-demo browser test prepares the synthetic input, runs the launcher with isolated ports, and checks RTSP, the real models, three coach cards, stored verification results, and desktop/mobile layouts. It accepts a valid verification or an explicitly unavailable assessment: image assessability is model-dependent. The test does not claim train accuracy. Screenshots are written to `test-results/`. Process groups created by the launcher are terminated on normal stop or test shutdown.
