# RTSP and separate local verification

## Capture and recovery

`config/rtsp.example.json` configures a live coach using an environment-variable name (`rtsp_url_env`). The value must be an RTSP or RTSPS URL. Missing or inaccessible streams are retried automatically. URL values and credentials are excluded from configuration snapshots, history, and source error messages. Native FFmpeg diagnostics are suppressed to avoid printing credential-bearing URLs.

An OpenCV/FFmpeg reader continuously drains the stream into one latest-frame slot. Every interval, the analysis worker samples a short window, counts people in each image using MobileNet-SSD, and publishes the rounded median. Capture continues during inference. Old windows are skipped rather than queued for later replay. Different coaches run independently.

| Per-coach setting | Default | Meaning |
| --- | --- | --- |
| `interval_seconds` | required; example 60 | Time between analysis windows |
| `window_seconds` | 2, capped at interval | Sampling window duration |
| `sample_count` | 3 | Images per window, allowed 3–15 |
| `open_timeout_seconds` | 5 | Bound on opening the stream |
| `read_timeout_seconds` | 3 | Bound on waiting for a decoded frame |
| `reconnect_seconds` | 2 | Delay before reopening a lost stream |
| `max_frame_age_seconds` | 1 | Maximum age of a frame in the latest slot |
| `reconnect_warmup_seconds` | 0.5 | Discard decoded frames immediately after connection |

The latest slot is cleared on disconnection. Reopening increments a generation counter; windows spanning connections and results from disconnected generations are discarded. When no new valid sample arrives, the existing reading expires after two observation intervals. Connecting/reconnecting is visible in the dashboard. Failures never publish zero passengers.

RTSP `observed_at` is the UTC time the last sampled image was **received by this process**, not when inference completed. `timestamp_basis: frame_received_at` and `capture_generation` record this explicitly. Camera capture timestamps are not available through this adapter: it prevents application backlog replay but cannot detect a camera or upstream relay replaying old video as a live feed. Camera-side buffering, codec negotiation, latency and credentials must be tested against the actual camera. The included integration test uses a local MediaMTX publisher.

## Verification semantics

Every video source defaults to verification enabled. Simulation has no images and cannot be verified. Settings live in each coach's `verification` object:

| Setting | Default |
| --- | --- |
| `enabled` | true for video, false for simulation |
| `interval_seconds` | 1800 |
| `endpoint` | `http://127.0.0.1:8081/v1/chat/completions` |
| `model` | `elbow-verifier` |
| `timeout_seconds` | 120, maximum 300 |

The first successful observation is eligible immediately. Subsequent checks are at least 30 minutes apart by default. Live sources use monotonic elapsed time; recordings use media time, so accelerated replay also accelerates the verification schedule. Restart begins a new schedule. A failed attempt is retried at the next due observation, rather than on every frame.

A single separate worker handles at most one outstanding job per coach. Regular capture, inference, persistence and SSE do not wait for AI. Due jobs copy the same sampled images in memory; they are resized to at most 768 pixels on their longest side and JPEG encoded for local inference. The verifier counts each image independently. All responses must be assessable and valid; the effective AI count is their rounded median, never their sum.

The HTTP adapter disables proxies and redirects and accepts only loopback endpoints. Frames are not written to disk, stored in SQLite, or sent to the browser. Model setup requires explicit downloads; inference runs offline after setup. Use a trusted local verifier process.

Responses must finish normally and contain exactly `assessable` (boolean) and `passenger_count` (nonnegative integer, or null when unassessable). Unavailable, timed-out, incomplete, malformed or unassessable responses preserve the regular estimate and record an unavailable verification. An assessable count of zero remains a valid empty scene.

A valid AI result takes precedence for its observation, as requested. SQLite retains `regular_passenger_count`, the effective `passenger_count`, detector `sample_counts`, and a `verification` object containing status, AI per-image counts, model alias, completion time and disagreement flag. Observation ID and original `observed_at` never change. Thus historical rows can acquire a verification result; they are not immutable. A late check cannot replace a newer current observation or make an expired observation fresh. SSE broadcasts verification changes; the dashboard distinguishes current overrides from historical checks. Interrupted pending jobs become unavailable on restart.

## Model and runtime provenance

The regular detector remains [MobileNet-SSD](video-detector.md). The distinct verifier is [SmolVLM-500M-Instruct](https://huggingface.co/HuggingFaceTB/SmolVLM-500M-Instruct), distributed under Apache-2.0, running locally through the MIT-licensed [llama.cpp](https://github.com/ggml-org/llama.cpp). This does not change Elbow Room's MIT licence. Dependency notices must be retained when redistributing runtimes or model files.

`scripts/setup-local-services.py` pins and SHA-256-verifies every download. It installs into ignored `data/local-services/`, not the operating system. The provided binary setup targets Linux x86-64. Other platforms need an equivalent local llama.cpp server with multimodal support and the configured API schema.

| Artifact | Version/revision | SHA-256 |
| --- | --- | --- |
| llama.cpp Ubuntu x64 archive | b11146 | `c150306eb16b5ab696f76a8bdf810c35fd98a24e82158742e6fa28f420ff8410` |
| SmolVLM Q8 model | GGUF revision `72e986006ef53e37cdd3f6d4241c90b0f01df376` | `9d4612de6a42214499e301494a3ecc2be0abdd9de44e663bda63f1152fad1bf4` |
| SmolVLM Q8 vision projector | same revision | `d1eb8b6b23979205fdf63703ed10f788131a3f812c7b1f72e0119d5d81295150` |
| MediaMTX Linux amd64 test server | v1.21.1, MIT | `653abc672a3e693f8d3b2717752492fdcfb8072291ec108d03d3dd857411b0ee` |

The GGUF conversion is from [ggml-org's pinned model repository](https://huggingface.co/ggml-org/SmolVLM-500M-Instruct-GGUF/tree/72e986006ef53e37cdd3f6d4241c90b0f01df376). The runtime uses CPU only, two threads and one inference slot. Exact release URLs are in the setup script. llama.cpp and MediaMTX licences ship in their downloaded archives. FFmpeg is an optional test publisher installed separately; its licence depends on the build, and it is not redistributed here.

## Validation boundary and limits

Backend integration tests run actual video decoding, local verifier HTTP, SQLite, and the application's HTTP API. Controlled inputs cover same-image delivery, disagreements, delayed responses, original timestamps, timeout/unassessable/malformed results, the 30-minute schedule and interrupted-job recovery. A real RTSP publisher is disconnected and restarted with different content to prove unknown-state expiry and recovery without reusing the prior generation. The browser verification suite runs a real recording and detector with controlled verifier replies, then checks the live override and the next regular observation through SSE.

The real CPU verifier was also smoke-tested on three copies of an upstream example image. It produced a valid median count of 2 while the regular detector counted 1. This demonstrates a functioning independent model and disagreement path, **not that the AI estimate is correct**. No representative labelled train footage has been evaluated. Small vision models can miscount or confidently assess unsuitable frames. Occlusion, camera coverage and crowd density remain unresolved accuracy limits; these demo estimates are not boarding guidance.
