# User-provided low, mid and full images

The supplied files are mapped by filename:

| Input | User category | Expected colour |
| --- | --- | --- |
| `emptyCoach.jpg` | Low / empty reference | Green |
| `midTrain.jpeg` | Mid reference | Yellow |
| `fullTrain.jpeg` | Full reference | Red |

The low reference contains visible passengers. Its label does not imply a passenger count of zero. No exact manual passenger counts were provided. Capacity is **100 for every case**, provisionally approved by the user; it has not been measured for this camera view. Expected categories remain separate from model outputs and never override them.

## Run the prepared cases

```sh
npm run demo -- --config data/user-train-images/config.json
```

This starts three recorded-video sources, one per image, with the real detector, separate local verifier, SQLite/SSE and dashboard. Each still is held for five minutes at 1 FPS; it is explicitly labelled a static image replay. Each source samples three frames initially and every 60 seconds. Verification assesses the first sample and follows the normal 30-minute schedule. After five minutes, EOF marks current occupancy unknown and history remains inspectable. Restart the command to replay again.

Prepared configurations preserve their own capacities, intervals and speeds. The launcher supplies the local verifier endpoint and can disable it with `--without-verifier`; the configuration's expected reference category is never used to generate a count.

The three original images are copied byte-for-byte into ignored `data/user-train-images/`. Original files in Downloads are unchanged. Video generation repeats the complete image; MJPG encoding adds at most one replicated edge pixel for even dimensions and introduces compression. Repeated frames are not independent footage and do not evaluate motion, camera timing, or changing occupancy. The dashboard receives aggregate readings, not the images.

## Recreate on another machine

Use the supplied images at your own local paths and choose a new output directory:

```sh
.venv/bin/python scripts/prepare-image-demo.py \
  --empty /path/to/emptyCoach.jpg \
  --mid /path/to/midTrain.jpeg \
  --full /path/to/fullTrain.jpeg \
  --capacity 100 --output data/my-image-cases
npm run demo -- --config data/my-image-cases/config.json
```

Only tooling and aggregate evidence belong in the repository. The input images and generated videos remain local; their presence does not grant redistribution rights under the project's MIT licence.

## Compare predictions with the references

Wait for all three initial checks to complete. Each launch prints its run directory. To compare the checked observations even after newer samples arrive:

```sh
.venv/bin/python scripts/report-image-demo.py \
  --labels data/user-train-images/image-labels.json \
  --database data/demo-runs/YOUR-RUN/history.sqlite3 \
  --output data/image-comparisons/YOUR-RUN
```

The report preserves original counts, verifier counts, effective percentages/colours, and disagreements with the reference categories. Exact count MAE remains unavailable without manual counts. These three related stills are preliminary checks, not a representative train-video benchmark. A mismatch can reflect undercounting, model limitations, or the unvalidated relationship between visible passengers and configured coach capacity; do not tune a separate capacity for each image just to obtain the desired colours.
