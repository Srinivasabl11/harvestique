# Evidence-based crop-photo analysis: structured report, condition score, prompt v2 (2026-10-15)

## Pre-registration (written 2026-10-15 BEFORE any held-out inference)

**Held-out set.** `harvestique-eval-data\heldout_20261015\` (manifest `heldout_20261015_MANIFEST.json`):
* 74 photos, never sent to any model before:
  * PlantDoc test split: 30 healthy (3 per healthy folder) and 32 problem (2 per problem folder, fewer where fewer
    unseen photos remained);
  * the 12 unused Koppal groundnut spares (3 healthy, 9 problem).
* Selection: seeded SHA-256 order (`heldout-20261015`). Photos were excluded by file name if they appeared in any
  earlier checkpoint (PlantDoc 108, crop-id 59, Granite pilot, Koppal 20).
* Prompt v2 was written from failure descriptions in those *earlier* answers only. None of these 74 photos was
  looked at.

**Runs.** The same 74 photos, paired:
* `heldout_v1_gemma3_4b` (production prompt);
* `heldout_v2_gemma3_4b` (`CROP_HEALTH_PROMPT_VERSION=v2`).

Both runs use gemma3:4b, app-style resize, batches of 10, and an unload after each batch.

**Decision rule.** v2 becomes the default only if ALL of these hold:
1. On healthy photos, false alarms (healthy called a problem) fall by **at least 5 of 33** compared with v1.
2. False-healthy answers (a problem photo called healthy) rise by **at most 1 of 41**.
3. Problem photos turned "unknown" rise by at most 3 of 41.
4. Errors or fallbacks: at most 1 per run.
5. Mean latency per photo is at most 25 % higher than v1.

Otherwise v1 stays the default and v2 stays available but off. With 33 and 41 photos, any difference is reported with
its counts. This sample cannot establish validated accuracy for any crop.

**Status (end of 2026-10-15 session): NOT RUN.**
* Neither held-out run has started, so prompt v2 is **unevaluated** and stays off (`CROP_HEALTH_PROMPT_VERSION=v1`).
* **Blocker: memory.** Committed memory stayed at 80–81 % of the limit, while the runner needs ≤ 75 %. This held even
  with Nextcloud, nextcloud-db and trademind-db stopped for about 2 hours (restarted afterwards).
* gemma3:4b adds about 4 GB on load and grows with every photo. The last run, started at 63 %, peaked at 84 %. From
  80 % it would reach the range where Docker froze on 2026-10-14.
* The remaining load was WSL/Docker (about 7 GB committed), Android Studio's Java, browsers and VS Code. Closing
  those is the user's decision.
* Commands for when memory allows. `-DryRun` has already checked the photos, labels and duplicates: 74 photos,
  0 unusable, 0 duplicates, 0 matches with the 20 seen Koppal photos. Each run takes about 74 × 70–90 s, roughly
  1.5–2 h.
  ```
  scripts\eval-plantdoc.ps1 -ImagesSubdir heldout_20261015 -PerClass 0 -Name heldout_v1_gemma3_4b -HealthyPattern '^[A-Za-z_ ]+ healthy$' -AppResize -ReferenceSubdir public_datasets -Batch 10 -PromptVersion v1
  scripts\eval-plantdoc.ps1 -ImagesSubdir heldout_20261015 -PerClass 0 -Name heldout_v2_gemma3_4b -HealthyPattern '^[A-Za-z_ ]+ healthy$' -AppResize -ReferenceSubdir public_datasets -Batch 10 -PromptVersion v2
  ```

## 1. Root causes (from the code and 187 saved answers; no new model calls)
Saved gemma3:4b v1 answers: PlantDoc 108, Koppal 20, crop-id 59.

| Symptom | Origin | Evidence / status |
|---|---|---|
| Healthy leaves called "possible disease" | **Description parsing plus the rule "healthy only if no spots or markings".** Healthy leaves are described as having "small, light-coloured spots/markings" (veins, glare, dust). The regex maps that to generic `spots`, and generic `spots` maps to possible disease. | 10 of 16 PlantDoc and 9 of 10 Koppal false alarms have generic `spots` only, at low confidence. Diseased leaves mostly get brown or dark spots, yellowing, or several signs. Prompt v2 targets this at the model; unevaluated. |
| "Yellowing" on a green leaf | Parsing: "The veins … appear yellow" matches `yellow\w*`. | 1 PlantDoc false alarm. The parser was not changed, because that would be tuning on seen data. |
| Model errors could not be told apart from server overrides | Saved `ai_overall` / `ai_confidence` are post-check values. | **Fixed:** `ai_raw_overall` and `ai_raw_confidence` are now stored. |
| Category percentages adding to 101 % | Each share was rounded on its own (3 decimals on the server, per bar in the app). "High" answers showed 65 + 21 + 5 + 5 + 5 and "low" answers 42 + 35 + 8 + 8 + 8. | **Fixed:** largest-remainder whole percentages on the server and in the app; always 100. |
| Percentages read as probabilities | They are a fixed mapping of the confidence word (65/55/42 %), capped at 70 %. | **Fixed (wording):** "AI estimate, not a measured probability"; the report explains the mapping. |
| Weak crop identification | Model ability: 15 of 56 correct, blind (`docs/CROP_CATALOGUE_AND_HEALTH_2026-10-15.md`). | Shown as an unverified guess together with the measured rate. |
| Fruit photos in the leaf check | Leaf rules were applied to any part; ripening colour could be called deficiency. | **Fixed:** see §2. Untested live: no labelled fruit photos on this PC. |

Image suitability and Flutter rendering were not sources of the measured healthy/problem errors. The photo checks
refused only 1 PlantDoc photo.

## 2. What changed
**Backend**
* `app/domain/crop_health_report.py` (new): the structured report, in English and Kannada, with these parts:
  * photo check;
  * crop and plant part (the AI's guess, shown with the measured 1-in-4 rate);
  * observations, with colour and extent when the model gives them;
  * possible cause families;
  * condition score, or the reason it is withheld;
  * limitations and next step.

  It never names a disease, product or dose (a test checks this).
* **Visual condition score (0–10).** The full rubric is in the module docstring:
  * It starts at 10. Each sign subtracts its weight × an extent factor.
    * Weights: generic spots 1, yellowing 1.5, other spots and damage 2, powder, sunken spots or wilting 3, mould
      or rot 4.
    * Extent factors: ×1, ×1.5, ×2.
  * It is capped at 6 when only "some" tissue looks normal and at 3 when "little" does. The minimum is 1.
  * Bands: 10 none visible, 8–9 minor, 5–7 moderate, 1–4 severe.
  * It is **withheld** for:
    * not-a-plant, dark, blurred, poor or far-away photos;
    * no clear answer from the AI;
    * a crop mismatch;
    * no AI model used (colour check or fallback);
    * mushrooms;
    * colour change only, on fruit, tubers, grain and similar parts.
  * It is **separate from the AI's confidence**: the same signs give the same score at any confidence. It is **not
    a disease probability**, and the weights are **not validated** against expert severity ratings.
* `app/domain/vision.py`: `percent_shares`; `_cap` now returns whole percentages that sum to 100.
* `app/providers/vision/ollama.py`:
  * stores the model's raw verdict;
  * `part_not_leaves` flag and tip (English and Kannada) for non-leaf photos sent to the leaf check;
  * colour change only on such parts gives "unknown";
  * parses v2 observations;
  * candidate prompt v2 behind `CROP_HEALTH_PROMPT_VERSION` (default v1; 360 answer tokens instead of 240).
* `app/domain/crop_profiles.py`: `is_crop_guess`.
* `app/services/media.py`: stores the report as `features.analysis`. `features` is JSON, so no migration was
  needed.
* `app/core/config.py`, `app/providers/registry.py`, `.env.example`: the prompt setting.

**Scripts:** `scripts/eval-plantdoc.ps1` gets a per-run `-PromptVersion`.

**Flutter:** `lib/features/crop_health/crop_health_screen.dart`:
* whole-percentage bars that sum to 100, also for older stored results;
* the "not a measured probability" label;
* the condition score or the reason it is withheld;
* the report sections in the server's language.

Older results without a report keep the original layout.

**Not changed:**
* model (gemma3:4b), the v1 prompt and its rules;
* generic-spots rule (still off);
* thresholds, database, migrations, API shape (new keys only inside `features`);
* existing English and Kannada texts.

**Deliberately not added:**
* a second model pass, which would double CPU time (about 70 s → 140 s per photo) with no measured benefit;
* image preprocessing (no evidence that it causes errors);
* a new model (Granite Vision 2B timed out on 4 of 10 photos; only about 2 GB of RAM is free).

## 3. Condition score on the 187 saved answers (consistency check, NOT validation)
v1 answers carry no extent, so the extent factor is ×1 throughout.

| Set | Healthy: n / mean / median | Problem: n / mean / median | Withheld |
|---|---|---|---|
| PlantDoc 108 | 38 / 9.42 / 10 | 62 / 6.47 / 7 | 8 (7 photo flags, 1 unclear) |
| Koppal 20 | 10 / 8.90 / 9 | 9 / 7.22 / 7 | 1 |
| Crop-id 59 | 32 / 9.09 / 9 | 26 / 6.69 / 7 | 1 |

* On average the score is lower for problem photos, but the overlap is large:
  * 2 PlantDoc problem photos score 10;
  * every healthy Koppal leaf scores 8–9 ("minor visible signs").
* The score inherits the model's false alarms; it cannot correct them.
* These photos were seen before, and they are labelled healthy/problem, not by severity. The check shows the score
  is consistent with the categories, not that it is accurate.

## 4. Baseline measurements (from earlier reports; no post-change model run exists)

| Set | Healthy recall | Problem recall | Macro-F1 | Unclear | Mean latency |
|---|---|---|---|---|---|
| PlantDoc 108 (web) | 0.59 | 1.00 | 0.818 | 1.9 % | 71 s |
| Koppal groundnut 20 (field) | 0.00 (0/10) | 1.00 | 0.334 | 0 % | 69 s |

* False-healthy: 0/68 and 0/10.
* False-disease on healthy photos: 16/39 and 10/10.
* Crop identification: 15/56.
* gemma3:4b memory: about 4 GB at load, growing to 9 GB over about 35 photos.
* The deterministic changes cannot alter labels on leaf photos. The only label-changing rule applies to non-leaf
  parts, and all 59 photos with a recorded part were leaves.
* The report itself is pure Python, with no measurable cost next to about 70 s of model time.

## 5. Tests (run 2026-10-15)
* **New:** `tests/unit/test_crop_health_report.py` covers:
  * percentages that sum to 100;
  * the score rubric;
  * healthy, disease, deficiency, stress and pest cases;
  * every case where the score is withheld;
  * unrelated objects;
  * dark and blurred photos;
  * malformed answers and Ollama failures (HTTP 500, broken JSON, a list, missing fields, a missing key, connection
    refused);
  * mushrooms;
  * fruit in the leaf check, colour on fruit, and tomato fruit for tomato;
  * the crop guess and validation lines;
  * forbidden wording, and unsafe model text never copied;
  * the raw verdict;
  * the v1 default and the v2 request;
  * v2 parsing, including junk entries;
  * the registry setting, the colour check, and older stored results;
  * Kannada in every section.
* **Extended:**
  * the crop-health API tests (report stored, Kannada, percentages sum to 100, crop validation line);
  * the Flutter crop-health widget tests (score, withheld score, sections, Kannada, whole percentages).
* **Results:**
  * vision unit tests: 149 passed;
  * 1748 passed, 0 failed (22 min). Run on a private test database `harvestique_test_crophealth`, because concurrent sessions sharing `harvestique_test` reset each other's data;
  * ruff lint and format: clean;
  * mypy: full `mypy app` clean (173 files) after the pooling session fixed `schemas/pooling.py`. Re-checked
    together with ruff (257 files formatted);
  * Flutter: `flutter analyze` clean; 156 passed.

## 6. Remaining failures and limits
* Healthy leaves are still often called a problem (v1). On Koppal groundnut every healthy leaf was. Treat a
  "possible problem" as "look closer", not as a diagnosis.
* Prompt v2 is unevaluated (memory blocker); do not switch it on before the held-out comparison.
* Plant-part recognition is only shown for leaves. The fruit, tuber and grain handling is tested with scripted model
  answers, not with real photos.
* The condition-score weights are a rubric and have not been validated against agronomist severity ratings.
* The new Kannada strings were written without a native-speaker review and should be checked.
* There are no Karnataka field photos labelled for severity, and no labelled fruit, unrelated-object or dark/blurred
  photo sets. Those cases are covered by unit tests and the existing pre-check thresholds only.
