# gemma3:4b on Koppal groundnut leaves: preliminary external check (2026-10-14)

**Result: the model called all 20 leaves diseased, including all 10 labelled healthy.** Problem recall was 10/10 and
healthy recall 0/10. This confirms, on independent field photos, the false-alarm weakness already seen on PlantDoc,
and here it is worse. This is a small external test on published research photos, **not** proof of accuracy on any
farm.

## Dataset (approved: groundnut only)
* **Source:** "Dataset of groundnut plant leaf images for classification and detection".
  * Authors: Aishwarya Manvikar (M P) and Padmanabha Reddy, Vijayanagara Sri Krishnadevaraya University, Ballari.
  * Mendeley Data v3, DOI [10.17632/22p2vcbxfk.3](https://data.mendeley.com/datasets/22p2vcbxfk/3); paper in Data in
    Brief (2023), PMC10293989.
  * Licence **CC BY 4.0**. Credit the authors; changes: folders renamed and images resized in memory by the evaluator.
* **Where and how:** field photos from groundnut farms in Koppal district, Karnataka, taken with a Canon camera at
  1200×800 px.
* **Labels:** the paper states "Data annotation was done manually and Data acquisition was done with the help of a
  pathologist." These are institution labels made with expert involvement, **not independently re-verified**.
* **Sample:**
  * 20 raw (not augmented) images: healthy 10; early leaf spot 4, late leaf spot 3, rust 3.
  * They were chosen from the API file list **before download**: per folder, ordered by SHA-256("42:"+filename),
    first N taken.
  * "Nutrition deficiency" was excluded as not a disease.
  * 12 spares were downloaded and none were needed.
  * Each file was verified against the repository's SHA-256 and re-verified afterwards (0 mismatches).
  * Attribution record: `harvestique-eval-data\public_datasets_ATTRIBUTION.json`.
* **Leakage and duplicate checks** (app-style resize on):
  * 0 unusable photos.
  * 0 exact or near-duplicates within the set (dHash, Hamming distance ≤ 6).
  * 0 matches against the 236 PlantDoc photos and the 8 tuning photos.
* **Not ruled out:** the dataset has been public since 2023, so gemma3 may have seen it in training.

## Results (measured)

| Metric | As answered (production behaviour) | Candidate rule (re-score only, not enabled) |
|---|---|---|
| Coverage | 20/20 (100 %) | 9/20 (45 %) |
| Healthy: told healthy / told disease / unknown | **0 / 10 / 0** | 0 / 1 / 9 |
| Problem: told disease / unknown | 10 / 0 | 8 / 2 (both early leaf spot) |
| Healthy precision / recall | 0.00 / 0.00 | 0.00 / 0.00 (1 answered) |
| Problem precision / recall | 0.50 / 1.00 | 0.89 / 1.00 (on answered) |
| Accuracy on answered | 0.50 | 0.89 |
| Macro-F1 on answered | **0.334** | 0.470 |

* **Uncertainty:** with 10 photos per class, the 95 % Wilson intervals are wide. The false-alarm rate on healthy
  leaves is 10/10, which means anywhere from 72 % to 100 %; problem recall is 10/10, also 72–100 %. Even so, the
  false-alarm problem is clear.
* **What the model said about healthy leaves:** mostly "vibrant green … some small, light-coloured spots" (generic
  `spots`, confidence low). Diseased leaves drew more specific signs (brown or dark spots, yellowing) at medium or high
  confidence.
* **Candidate rule:** it turns most false alarms into "unknown" (the retake tip), but **never produces a correct
  "healthy"**. It also hid 2 of the 4 early leaf spot cases.
* **Errors, timeouts and resources:**
  * 0 errors, 0 timeouts, 0 colour fallbacks; 1 `poor_photo` soft flag.
  * Latency: mean 69.2 s, p90 75.4 s per photo on the CPU; wall time about 23 minutes in 2 batches (15 + 5), with
    the model unloaded after each batch.
* **Memory (one deviation):**
  * Committed memory went from 63 % before the run to a **peak of 84 % with 952 MB available** late in batch 1.
  * That is above the plan's limits (75 % committed, 1,500 MB available). The runner only checks them *between*
    batches, and it measured 62 % at each check.
  * Nothing failed or froze. After the model was unloaded, memory returned to about 62 %.
  * Other containers (Nextcloud, trademind-db) were running at the time.
  * For future runs, use batches of 10 or stop those containers first.

## What this means
* **Comparison with PlantDoc** (web photos, 108): healthy recall was 0.59 and macro-F1 0.818. On these field photos
  of a crop it hadn't been tuned on, the healthy-leaf false alarm is much stronger, and macro-F1 is 0.334.
* **A diseased leaf is almost never missed,** but a **"possible disease" answer from the current model carries little
  information on groundnut**. The app's wording ("possible", low confidence and the retake tip) matters, and the
  result should not be presented to farmers as a diagnosis.
* **The candidate rule is not a fix.** It would convert false alarms into "unknown" at the cost of 45 % coverage and
  some missed early disease. Enabling it is still your decision. It was **not** enabled.
* Possible next work: improving healthy-leaf recognition, for example with prompt or threshold changes evaluated on a
  *separate* held-out sample. This 20-photo set has now been seen and should not be used for tuning.

## Commands (all free; no production changes)
```
python -I scratchpad\karnataka_src\fetch_koppal.py C:\Users\Srinivasa\Documents\harvestique-eval-data
scripts\eval-plantdoc.ps1 -ImagesSubdir public_datasets -PerClass 0 -Name koppal_groundnut_gemma3_4b -HealthyPattern '^[A-Za-z_ ]+ healthy$' -AppResize -ReferenceSubdir plantdoc_test -DryRun
(tuning-photo check: eval_crop_health --check-only --reference-dir <8 tuning photos>, in hq-test-runner)
scripts\eval-plantdoc.ps1 ... (same, without -DryRun)
scripts\eval-plantdoc.ps1 ... -RescoreOnly
```
The download script lives in the session scratchpad, not the project. It uses curl, because the Mendeley server
sometimes returned a 395-byte JSON or 502 response; every such response failed the hash check and was retried.

## Files
* New data: `harvestique-eval-data\public_datasets\` (20 photos), `public_datasets_spares\` (12),
  `public_datasets_ATTRIBUTION.json`.
* New results: `results\koppal_groundnut_gemma3_4b.json`, `.partial.jsonl`, `_rescore.json`,
  `koppal_groundnut_run.log`, `koppal_groundnut_memory.log`.
* New docs: this file; `docs/PUBLIC_DATASET_SEARCH_2026-10-14.md` (inventory and plan; status line updated).
* No code changed, so no tests were needed. Unchanged: production settings (`CROP_HEALTH_GENERIC_SPOTS_UNCERTAIN`
  off), the server, the database, Windows/WSL settings, Granite, PlantDoc, Karnataka and external_public data, all
  earlier results and reports. No money was spent.
