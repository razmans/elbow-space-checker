# Recorded-video detector

## Implementation and provenance

The initial detector is MobileNet-SSD, executed by OpenCV DNN on the CPU. Only the PASCAL VOC `person` class (15) is counted. Confidence defaults to 0.5 and is configurable. It is a baseline visible-person detector, not a validated whole-coach or crowd-density model.

The network definition and pretrained weights come from [chuanqi305/MobileNet-SSD](https://github.com/chuanqi305/MobileNet-SSD), pinned to commit `bb17b6c3eef36d80be441ae8e5339be66e8e3b7a`. The upstream repository distributes these artifacts under its MIT licence; a copy is retained in `third-party/MobileNet-SSD-LICENSE.txt` and downloaded beside the weights. The upstream author reports COCO pretraining followed by VOC0712 fine-tuning. Elbow Room does not redistribute either training dataset or claim an independently audited training-data licence chain.

| Asset | SHA-256 |
| --- | --- |
| deploy.prototxt | `2d180f723b3109e21f8287f6b3c691390d07b60eed998327cd3259ffa0e50608` |
| mobilenet_iter_73000.caffemodel | `52eed8be80522c152a17fb56740de705b79881bde1a167e0e747310523685fc7` |
| LICENSE | `5de433821cfe672af2fca73c3005f48af16121c95f6a11e1031b07807ea59905` |

The explicit model-download command verifies hashes before installing files atomically. Each detector instance checks hashes before loading. Runtime inference does not download assets or send frames over the network.

OpenCV's current code is [Apache-2.0 licensed](https://github.com/opencv/opencv/blob/4.x/LICENSE). NumPy and the binary wheels contain their own licence notices, including bundled dependencies. Installed wheel notices must be preserved when redistributing that runtime. Elbow Room's own code remains MIT; using an Apache-licensed dependency does not change that project choice.

## Sampling and counting

For each configured interval of media time, sample a short window (default two seconds, three evenly spaced frames). Resize to 300×300 BGR and normalize using the upstream preprocessing. Run the same detector on each frame, count person detections above the confidence threshold, and publish the median count. A half-integer median rounds up. Counts are never summed across frames; no cross-frame passenger identities are created. Duplicate frame positions in very short windows are removed.

Images are decoded locally and held temporarily in memory. Only counts, source metadata, timestamps, model identity, and media positions are stored or broadcast. There is no image API, frame archive, or overlay feed.

The model uses one CPU network instance per recorded coach and two OpenCV execution threads. Timing and accuracy must still be measured on the target machine and representative train footage.

## Replay clock

Playback starts when the local file and detector are ready. `interval_seconds` and `window_seconds` are measured in media time; `playback_speed` maps them into wall time. At 10×, a 60-second media interval takes six wall-clock seconds.

The observation carries the sampled window's ending frame position, window start, per-frame counts, detector ID, and playback speed. Its UTC `observed_at` is replay origin plus media position divided by speed, rather than the moment inference finishes. This is a replay timestamp, not the video's original capture date. Expiry is two media intervals after that observation, divided by replay speed. The browser uses the server's expiry and server clock offset as before.

No observation is published ahead of its playback position. If inference is too slow, skip obsolete windows instead of broadcasting a backlog as fresh. A late observation can therefore be immediately stale, which is intentional.

The last sampling window is clipped to valid frame positions. At the end of the file, stop replay, mark the source `ended`, clear live occupancy to unknown, and retain history. Restarting the backend starts a new replay; looping and seeking controls are not implemented. Decode/model errors mark only the affected coach `error` and unknown; they never publish a false zero.

## Validation and limitations

Deterministic tests generate short local videos and replace only the inference function, exercising actual decoding, sampling, persistence, HTTP/SSE, timing, and failure handling. Separate smoke tests run the real pinned model. The optional browser video suite runs the actual detector on locally generated footage and verifies dashboard updates and EOF.

An upstream example image was used locally for a positive detection smoke test and a short repeated-image recording. That is not representative train footage, and those ignored local test assets are not distributed with the repository. No camera-coverage or counting-accuracy target is claimed. Occlusion, distant people, seated passengers, lighting, and partial views require evaluation before a coach-capacity percentage can be trusted. The separate 30-minute AI verifier and RTSP source are described in [RTSP and verification](rtsp-verification.md).
