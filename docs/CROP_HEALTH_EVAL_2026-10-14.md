# Crop-health evaluation on PlantDoc (2026-10-14)

Evaluation of the **existing production pipeline** (upload validation `decode_image` -> fast photo-quality pre-check ->
Ollama `gemma3:4b` with the schema-constrained prompt and server-side checks), unchanged. Nothing about the model, the
prompt, the thresholds or the database was changed for or during this evaluation.

## Data
* **Source:** PlantDoc test split, Singh et al., "PlantDoc: A Dataset for Visual Plant Disease Detection",
  CoDS-COMAD 2020 (Hyderabad), https://github.com/pratikkayal/PlantDoc-Dataset, licence **CC BY 4.0**.
  The authors annotated **internet-scraped** photos: each photo's original copyright stays with its creator, so the
  photos are used here only for private evaluation and are **not** copied into the project or redistributed.
* **Downloaded:** all 236 test-split photos (73.5 MB, 27 class folders) to
  `C:\Users\Srinivasa\Documents\harvestique-eval-data\plantdoc_test\`; every file verified against its Git blob SHA-1
  from the repository listing (236/236 matched). Windows-invalid characters (`?`) in 5 file names were replaced by `_`; `harvestique-eval-data\plantdoc_test_manifest.json` maps every original path to its local name and hash.
* **Ground truth:** folder names. "Healthy" = the 10 folders named `<crop> leaf` with no disease word (Apple, Bell
  pepper, Blueberry, Cherry, Peach, Raspberry, Soyabean, Strawberry, Tomato, grape); "problem" = the 17 disease folders.
* **Duplicate / leakage checks** (whole test split, before sampling): exact duplicates by SHA-256 of the bytes: **0**;
  near duplicates by 64-bit difference hash (Hamming distance <= 6): **0**; matches with the 8 Wikimedia photos used to
  tune the prompt and the pre-check thresholds: **0**; the same photo under two different labels: **0**.
  Harvestique did not train or fine-tune the model, so there is no train/test split to leak. Whether some of these
  internet photos were part of Gemma 3's own web training data **cannot be checked** and is a limitation.
* **Sample:** reproducible stratified sample, 4 photos per class (`--per-class 4 --sample-seed harvestique-eval-1`,
  files ordered by SHA-256 of seed + name): **108 photos, 40 healthy, 68 problem**.

## Method
```powershell
# from the project folder; uses the same settings as the server (.env: CROP_HEALTH_CLASSIFIER=ollama_vision,
# OLLAMA_VISION_MODEL=gemma3:4b, VISION_TIMEOUT_SECONDS=150)
docker run -d --name hq-eval -v "${PWD}\backend:/src/backend:ro" -v "C:\Users\Srinivasa\Documents\harvestique-eval-data:/data" `
  -e CROP_HEALTH_CLASSIFIER=ollama_vision -e OLLAMA_BASE_URL=http://host.docker.internal:11434 `
  -e OLLAMA_VISION_MODEL=gemma3:4b -e VISION_TIMEOUT_SECONDS=150 --entrypoint sh hq-test-runner `
  -c "cd /src/backend && PYTHONPATH=/src/backend python -m app.cli.eval_crop_health /data/plantdoc_test --per-class 4 --sample-seed harvestique-eval-1 --drop-duplicates --out /data/results/plantdoc_gemma3_4b_108.json"
```
* Scoring: the classifier gives categories, not disease names. "Possible disease", "stress" and "possible deficiency"
  count as **problem**; "healthy" as **healthy**; "unknown" is a **refusal** (reported as coverage / unclear rate, not
  as right or wrong). Precision/recall/F1 are computed on answered photos only, so the unclear rate must be read
  together with them.
* Disease-level top-3 accuracy is **not applicable**: the pipeline deliberately does not name diseases.
* Latency: wall-clock per photo on this PC (Intel i7-7700, CPU only, Windows reports 3 logical processors), with
  normal desktop use and Docker running.

## Results: COMPLETE (108 of 108 photos, all 27 classes)
Files (outside the project): `harvestique-eval-data/results/plantdoc_gemma3_4b_108.json` (final report, per photo),
`plantdoc_gemma3_4b_108.partial.jsonl` (checkpoint, 108 rows, 0 duplicates), `plantdoc_gemma3_4b_108_rescore.json`
(candidate-rule scoring), `batch_run.log`.

### Run history and exclusions
* 2026-10-14 02:26-04:14: 28 photos, then the PC ran out of memory (Docker froze; ~1 photo in 6.5 h).
* One photo processed during that collapse got the colour **fallback** (model unreachable). It was removed and re-run;
  the harness now records any fallback as an error (`model_unavailable_fallback`) and retries errors on resume.
* 09:43 restart; resumed at 10:20 from the checkpoint. Root cause found at 69 photos: the Ollama process serving
  gemma3:4b **grows with every photo** (4.0 GB at start -> 9.1 GB after ~35 photos; Ollama itself reports 2.9 GB).
  Unloading the model (`ollama stop gemma3:4b`) took committed memory from 90 % to 57 %.
* The remaining 39 photos ran with `scripts/eval-plantdoc.ps1` in batches of 15, unloading the model after each batch:
  committed memory stayed at 57-78 %, nothing froze. Finished 12:02.
* Final: **108 photos, 0 errors, 0 fallbacks, 0 duplicates**; checkpoint order equals the seeded sample order.

### Metrics (dataset labels as given)
| Truth \ answer | possible disease | possible deficiency | healthy | unknown |
|---|---|---|---|---|
| problem (68) | 64 | 3 | **0** | 1 |
| healthy (40) | 14 | 2 | 23 | 1 |

| Class | Precision (95 % Wilson) | Recall (95 % Wilson) | F1 | answered |
|---|---|---|---|---|
| healthy | 1.00 (0.86-1.00) | **0.59** (0.43-0.73) | 0.74 | 39 |
| problem | 0.81 (0.71-0.88) | **1.00** (0.95-1.00) | 0.89 | 67 |

* Macro F1 **0.82**; accuracy on answered photos 0.85 (90/106).
* Unclear rate **1.9 %** (2/108: 1 diseased with `poor_photo`, 1 healthy); coverage 98 %.
* **False negatives (diseased called healthy): 0.** False positives (healthy called a problem): **16** (14 "possible
  disease", 2 "possible deficiency").
* CPU time per photo: mean **71.1 s**, p90 **75.5 s** (i7-7700, no GPU), plus ~20 s for each model reload.
* Disease-level top-3 accuracy: not applicable (categories, not disease names).
* Per class: every disease class was flagged as a problem in 4/4 photos except Corn gray leaf spot, Tomato mosaic
  virus and Tomato yellow virus (3 "possible disease" + 1 "possible deficiency" each, still a problem) and Tomato late
  blight (3/4, 1 unknown). Healthy classes: Cherry, Peach, Strawberry, Apple 3/4 healthy; grape 3/4 (+1 unknown);
  Blueberry, Raspberry, Soyabean 2/4; Bell pepper and Tomato leaf only 1/4.

### Failure cases
All 16 errors are healthy-labelled leaves reported as a problem. **10 of the 16** have the same signature: the only
sign in the model's own description is generic "spots" / "markings" (not brown or dark spots) **and** the model's
confidence is low. The other 6 describe dark spots or yellowing with medium confidence. At least 4 of the 16
"healthy" photos are probably **mislabelled** in PlantDoc: `iron-deficiency-raspberry-leaf...`,
`GREEN BELL PLANT YELLOW LEAF`, `why-are-my-pepper-plants-yellow...`, and `Peach leaf/rose_tree_...` (a rose, not a
peach); they were scored as labelled, so the real healthy-leaf error is somewhat lower than shown.

### Pre-registered candidate rule (evaluation only)
Fixed on 2026-10-14 after the first 33 photos and before the other 75 were evaluated: a problem answer whose only sign
is generic "spots" with low confidence is reported as **unknown**. Scored from the saved answers (no new model calls):

| Set | Answered | Macro F1 | Healthy recall | Problem precision | Problem recall | Unclear: healthy / problem |
|---|---|---|---|---|---|---|
| Held-out 75, as answered | 73 | 0.84 | 0.61 (0.41-0.78) | 0.85 (0.73-0.92) | 1.00 | 4 % / 2 % |
| Held-out 75, with rule | 64 | **0.94** | **0.82** (0.59-0.94) | **0.94** (0.84-0.98) | 1.00 | 29 % / 8 % |
| All 108, as answered | 106 | 0.82 | 0.59 | 0.81 | 1.00 | 2.5 % / 1.5 % |
| All 108, with rule | 93 | 0.92 | 0.79 | 0.91 | 1.00 | 28 % / 6 % |

The rule held up on photos it was not chosen from. Its cost: about 1 in 13 diseased leaves (3 of 50 held-out) gets
"unknown" instead of "possible disease" (still never "healthy"), and coverage falls from 97 % to 85 %.
**Production is unchanged.** The rule is implemented behind `CROP_HEALTH_GENERIC_SPOTS_UNCERTAIN` (default
`false`); a unit test checks that it uses exactly the evaluated definition.

### What this does and does not show
* On PlantDoc (internet photos, mostly temperate crops) the pipeline missed no diseased leaf but called about 4 in 10
  healthy leaves a problem; it errs on the side of "check this plant".
* It does **not** measure accuracy on Karnataka farms or crops (ragi, paddy, brinjal, chilli...), on phone photos
  taken by farmers, or under field lighting. Gemma 3 may have seen some of these web photos in training (not checkable).
* 108 photos give wide intervals (healthy recall 0.43-0.73).

### Reproducing / re-running
```powershell
powershell -ExecutionPolicy Bypass -File scripts\eval-plantdoc.ps1               # continues or finishes a run, 15 per batch
powershell -ExecutionPolicy Bypass -File scripts\eval-plantdoc.ps1 -RescoreOnly  # metrics from saved answers, no model
```
The script refuses to start if an evaluation is already running or if memory is too tight (commit > 75 % or
< 1.5 GB available), and unloads the model after every batch.

## Baseline vs candidate rule on identical photos (re-scored 2026-10-14, no new model calls)
Re-scored from the saved 108 answers with `scripts\eval-plantdoc.ps1 -RescoreOnly`; the output
(`plantdoc_gemma3_4b_108_rescore.json`) is identical to the earlier re-score, and Ollama stayed unloaded.
Healthy / problem cells are precision / recall / F1.

| Set | Photos | Answered | Coverage | Unknown | Healthy P/R/F1 | Problem P/R/F1 | Macro F1 | False alarms | Missed diseases |
|---|---|---|---|---|---|---|---|---|---|
| Full 108, baseline | 108 | 106 | 98.1 % | 2 (1.9 %) | 1.00 / 0.59 / 0.74 | 0.81 / 1.00 / 0.89 | 0.818 | 16 | 0 |
| Full 108, rule | 108 | 93 | 86.1 % | 15 (13.9 %) | 1.00 / 0.79 / 0.89 | 0.91 / 1.00 / 0.95 | 0.920 | 6 | 0 |
| Held-out 75, baseline | 75 | 73 | 97.3 % | 2 (2.7 %) | 1.00 / 0.61 / 0.76 | 0.85 / 1.00 / 0.92 | 0.837 | 9 | 0 |
| Held-out 75, rule | 75 | 64 | 85.3 % | 11 (14.7 %) | 1.00 / 0.82 / 0.90 | 0.94 / 1.00 / 0.97 | 0.936 | 3 | 0 |

* The rule changes **13** photos: 10 healthy false alarms become "unknown" (Apple, Bell pepper, Blueberry, Cherry,
  Peach, Raspberry, Soyabean, Strawberry, 2 x Tomato leaf), and 3 correctly flagged diseased leaves also become
  "unknown" (Corn leaf blight, Tomato mosaic virus, Grape black rot). No answer becomes "healthy".
* The **full-set** rows include the 33 photos the rule was chosen from, so they flatter the rule; the **held-out 75**
  rows are the fair estimate.
* Production: off. `.env` does not set `CROP_HEALTH_GENERIC_SPOTS_UNCERTAIN`, the code default is `false`, and the
  running server was not rebuilt (its code does not contain the rule at all). Tests: 8 rule-specific tests pass,
  including one proving the production rule equals the evaluated definition.

## Feasibility (nothing downloaded)
### 20-30 labelled Karnataka crop photos
* **Ready on the software side** (updated, see "Karnataka preparation" below): folders ending in ` healthy` are
  healthy, all others are problems; `harvestique-eval-data\karnataka\README.md` has the rules. (The earlier example
  `Ragi blast leaf` would have been scored *healthy* by the PlantDoc naming rule, because "blast" is not in its
  disease-word list; the explicit ` healthy` convention removes that risk.)
* **Blocker:** no labelled Karnataka photos exist on this PC (crop-health uploads keep only a hash, never the photo),
  and no Karnataka field dataset has been checked for licence. Photos must come from you or the farmers, ideally
  labelled by an agriculture officer / Raitha Samparka Kendra; labels guessed by us would make the test meaningless.
* **Cost:** ₹0; about 25 photos x ~71 s = ~30 minutes, two batches. Photos stay on this PC.

### A smaller local vision model (sizes and licences read from the Ollama registry, not downloaded)
| Model | Download | Licence (Ollama listing) | Notes |
|---|---|---|---|
| gemma3:4b (current) | 3.35 GB | Gemma terms | baseline above |
| moondream (1.8B) | 1.74 GB | Apache-2.0 | smallest and fastest; weak at following a JSON schema |
| granite3.2-vision:2b | 2.44 GB | Apache-2.0 | IBM; tuned for documents and charts, plant photos untested |
| qwen2.5vl:3b | 3.20 GB | Apache-2.0 in the listing | barely smaller than gemma3:4b; check the upstream licence before commercial use |
| llava-phi3 | 2.93 GB | no licence layer in the listing | not recommended without a clear licence |
* Any of them runs through the same pipeline and the same 108 photos with `-Model <name>` (the script refuses
  models that are not installed, so nothing downloads by accident). Each run keeps its own checkpoint and report.
* Expected effort: one ~1.7-2.4 GB download (needs your approval) and ~1-1.5 h of CPU time for 108 photos.
* Likely benefit: lower memory and faster answers; accuracy is **unknown** and smaller models usually describe
  fine leaf detail less well, so a model would only replace gemma3:4b if it beats the table above on the same photos.

## Granite Vision 2B comparison: pre-download checks (2026-10-14, NOT downloaded, awaiting approval)
| Check | Result |
|---|---|
| Model | `granite3.2-vision:2b` (IBM Granite Vision 3.2, 2.5B parameters, GGUF Q4_K_M, families granite + clip) |
| Licence | **Apache-2.0** (licence file in the Ollama manifest, and upstream `ibm-granite/granite-vision-3.2-2b` on Hugging Face) |
| Exact download | **2,437,851,819 bytes (2.44 GB / 2.27 GiB)**: weights 1,545,294,400 + vision projector 892,544,608 + 4 small files |
| Ollama | installed 0.40.3; GGUF + CLIP projector format is supported; the template uses our pipeline's own system message |
| Disk | 282 GB free |
| RAM now | 59 % of commit limit used, 6.6 GB available (script needs <= 75 % and >= 1.5 GB to start) |
| Memory risk | default context is **16 384** tokens (gemma3:4b: 4 096) and the pipeline does not override it, so RAM use may be higher than the file size suggests; batches of 15 with an unload after each, plus the memory checks, cover this |
| Expected runtime | **not measured.** Smaller language model than gemma, but Granite's image encoder splits images into tiles, so per-photo CPU time could be similar; plan on 1-3.5 h for 108 photos and measure with a 10-photo pilot first |
| Accuracy | unknown until run; only a better result on the same 108 photos would justify a change |

Separation and duplicate protection (verified with `-DryRun`): run name `plantdoc_granite3_2-vision_2b_108`, its own
checkpoint, report and lock files in `harvestique-eval-data\results\` (none exist yet; gemma files untouched); the
script refuses if any `hq-eval*` container is running, and the harness refuses a checkpoint whose lock is fresh. A run
with a model that is not installed is refused (verified: nothing is downloaded automatically). The report now records
the full model name (the stored version is cut to 16 characters).

### Steps after approval (nothing changes in production)
```powershell
ollama pull granite3.2-vision:2b                                                                     # 2.44 GB, one time
powershell -ExecutionPolicy Bypass -File scripts\eval-plantdoc.ps1 -Model granite3.2-vision:2b -Batch 10 -MaxBatches 1   # pilot: 10 photos, then stops
powershell -ExecutionPolicy Bypass -File scripts\eval-plantdoc.ps1 -Model granite3.2-vision:2b             # continue to 108
powershell -ExecutionPolicy Bypass -File scripts\eval-plantdoc.ps1 -Model granite3.2-vision:2b -RescoreOnly
```
To remove it afterwards: `ollama rm granite3.2-vision:2b` (frees the 2.44 GB).

### Granite pilot result (10 photos, done 2026-10-14)
4 of 10 photos timed out at 150 s; answered photos took 100 s on average (gemma3:4b: 78 s on the same photos, no
timeouts); memory peaked at 86 % committed. The full Granite run was **not** started; gemma3:4b stays.
Details: `docs/GRANITE_PILOT_2026-10-14.md`.

## Karnataka preparation (2026-10-14, no inference)
* `harvestique-eval-data\karnataka\` created with a README (folder naming, formats, collection and labelling rules).
* Evaluator additions (evaluation only, production unchanged): explicit healthy convention
  (`--healthy-pattern '^[A-Za-z_ ]+ healthy$'`); `--app-resize` prepares photos exactly like the phone app before
  upload (longest side 1,600 px, JPEG 85; raw 50 MP phone photos exceed the server's 5 MB / 25 MP / 8,000 px limits);
  `--check-only` validates every photo, label and duplicate (also against the nested PlantDoc folders) without a model;
  unreadable files no longer stop the duplicate check. Script: `-HealthyPattern`, `-AppResize`, `-ReferenceSubdir`;
  `-DryRun` now includes the photo check.
* Dry run, Karnataka: run name `karnataka_gemma3_4b`, separate checkpoint/report/lock (none exist), memory OK,
  no evaluation running; photo check: **No images found** (the only blocker). Photo-check smoke test on PlantDoc with
  `-AppResize`: 236 photos, 90 healthy / 146 problem, 0 unusable, 0 duplicates; no model loaded.
* Exact run command (after you approve, once photos are in place):
  `scripts\eval-plantdoc.ps1 -ImagesSubdir karnataka -PerClass 0 -Name karnataka_gemma3_4b -HealthyPattern '^[A-Za-z_ ]+ healthy$' -AppResize -ReferenceSubdir plantdoc_test`
