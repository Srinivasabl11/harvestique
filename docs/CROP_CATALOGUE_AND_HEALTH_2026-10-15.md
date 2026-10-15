# A–Z crop master catalogue and crop-health coverage (2026-10-15)

**Summary:**
* The catalogue now covers **213 crops in all 18 agricultural groups** (88 existing + 125 added), with scientific
  names and searchable synonyms.
* The photo check handles **every** catalogue crop, with part-specific guidance and a crop-mismatch check.
* **No crop has demonstrated reliable health assessment.** Coverage is not accuracy, and the per-crop status says so.

## 1. Catalogue reconciliation
* **Existing 88 crops:** ids, names, Kannada names, categories and farm links are unchanged. Only EMPTY fields were
  filled: scientific name, aliases, group (`python -m app.cli.seed_crops --reconcile`).
* **Added: 125 crops from the A–Z list** that were not already present under another name. **New crops have no
  Kannada name:** none were invented. They show the English name until an admin adds a verified one.
* **No duplicates.** A new crop whose name or alias already belongs to another crop is skipped, and a test checks
  that no name or alias is used twice.
* **Synonyms resolved to one crop,** for example:
  * ragi / finger millet / nachni;
  * jowar / sorghum;
  * sapota / chikoo / sapodilla;
  * arhar / tur / red gram / pigeon pea;
  * urad / black gram;
  * eggplant / aubergine / brinjal;
  * lady's finger / bhindi / okra;
  * peanut / groundnut;
  * corn / maize;
  * rice / paddy;
  * tapioca / cassava;
  * moringa / drumstick;
  * amla / Indian gooseberry / aonla;
  * cocoyam / tannia / Xanthosoma.
* **Ambiguous names were NOT used as aliases:** "gooseberry", and "orange" (sweet orange vs mandarin).
* **Search** (API and app) now matches English and Kannada names, aliases and scientific names.

**Coverage by group:**

| Group | Crops | Group | Crops |
|---|---|---|---|
| Cereals | 8 | Beverage | 3 |
| Millets | 9 | Fibre | 4 |
| Pulses and legumes | 13 | Sugar and starch | 1 |
| Oilseeds | 10 | Fodder and forage | 7 |
| Vegetables | 40 | Medicinal and aromatic | 13 |
| Fruits | 47 | Ornamental | 11 |
| Spices | 19 | Agroforestry | 5 |
| Roots, tubers, bulbs, rhizomes | 13 | Mushrooms | 1 |
| Plantation | 5 | Other | 4 |

**Not added (an admin can add any of them later):**
* **Legal restrictions:** hemp, opium poppy.
* **Minor or not established as Indian field crops here:** durian, hazelnut, hop, jojoba, Jerusalem artichoke,
  macadamia, olive, oregano, thyme, parsnip, pistachio, quince, rye, rattan, ulluco, viola, hyacinth, white
  mustard.
* **Not a separate crop:**
  * wheatgrass (wheat seedlings);
  * peppermint (covered by Mint);
  * honeydew and European plum (aliases of Muskmelon and Plum);
  * tender coconut (alias of Coconut).

Durations of new crops are **indicative planning defaults**, the same convention as before; perennials use the
365-day record-keeping cycle. No reference yields or prices were added for new crops.

**Database:**
* Migration `0015_crop_catalogue_metadata` adds three nullable columns to `crops`. It is additive: no row was
  changed by the migration itself.
* Backup before it: `harvestique-backups\harvestique_before_0015_20261015.dump` (+ `.sha256`), read back with
  `pg_restore --list` (39 tables).

## 2. Crop-health handling for every crop
* **Crop context.** The photo check now knows the crop:
  * from the crop cycle;
  * or from a new optional `crop_id` on `/crop-health/analyze`;
  * no crop chosen means no crop is assumed.
  It sends the model the crop's name, scientific name and the part it is grown for, with **part-specific
  guidance**:
  * fruit colour change while ripening is not a symptom;
  * soil and skin colour on tubers, roots and rhizomes are normal;
  * dry outer skins on bulbs are normal;
  * flower colour depends on the variety.
* **New signs** for non-leaf parts: rot, cracking, sunken or water-soaked spots.
* **What the model now also reports:**
  * the crop it sees (`crop_seen`, labelled unverified);
  * the plant part (`plant_part`).
  These fields come AFTER the health fields in the answer schema, so the health answer is produced as before.
* **Crop mismatch.** If the model names a different crop than the farmer chose, confidence drops to low and the
  farmer is asked to check (English and Kannada). It never replaces the farmer's crop.
* **Mushrooms** get a fixed specialist answer with no model call: this is a green-plant check.
* **Unchanged:** the existing poor-photo handling (pre-check, retake tips, "unclear"), capped probabilities and the
  "not a diagnosis" disclaimer. The uncertainty rule stays OFF and the model stays `gemma3:4b`.

## 3. Evaluation (measured, 2026-10-15, gemma3:4b, CPU)
**Blind crop and plant-part identification** (the model was not told the crop):
* **Photos:** 59 labelled leaf photos already on disk, nothing downloaded:
  * 39 PlantDoc photos (3 per crop, from the 108 used before);
  * 20 Koppal groundnut field photos.
* **Results:** `harvestique-eval-data\results\crop_id_gemma3_4b*.json`, `crop_id_scores_20261015.json`.

| Crop | Photos | Crop named correctly | "unknown" | Wrong crop named |
|---|---|---|---|---|
| Tomato | 3 | 3 | 0 | 0 |
| Strawberry | 3 | 3 | 0 | 0 |
| Maize (Corn) | 3 | 2 | 1 | 0 |
| Grapes | 3 | 1 | 0 | 2 ("vine") |
| Groundnut (field) | 20 | 6 ("peanut") | 11 | 3 ("pea", "legume") |
| Capsicum (Bell pepper) | 3 | 0 | 1 | 2 ("basil", "tomato") |
| Apple, Blueberry, Cherry, Peach, Potato, Raspberry, Soybean | 3 each | 0 | 3 each | 0 |
| Squash (no single catalogue crop) | 3 | not scored | | |
| **Total (scored)** | **56** | **15 (27 %)** | **34** | **7** |

**Plant part:** "leaf" for 59 of 59, which is correct. But **every test photo was a leaf**, so recognising fruit,
tubers, bulbs, rhizomes or flowers is **untested**.

**Health on the same photos with the new prompt:**
* healthy recall 0.44 (14/32); problem recall 1.00 (27/27); macro-F1 0.679; 0 errors; 72 s per photo.
* Compared with the earlier runs on the same 59 photos, 54 labels were unchanged. Of the 5 that changed, 3 became
  correct (healthy called healthy), 2 moved between problem categories, and none got worse.
* This is too small to call an improvement; it shows no measured harm. The known weakness remains: healthy leaves
  are often called diseased (all 10 Koppal healthy groundnut leaves again).

## 4. Per-crop validation status (`GET /crop-health/validation`; also in each analysis's `features.validation`)
* **Reliable:** needs ≥ 30 labelled **field** photos per class (healthy and problem) and both recalls ≥ 80 %.
* **Results:**

| Status | Crops |
|---|---|
| Catalogue entry, photo check available | 213 (all) |
| Crop identification tested (leaf photos) | 13: Apple, Blueberry, Capsicum, Cherry, Grapes, Groundnut, Maize, Peach, Potato, Raspberry, Soybean, Strawberry, Tomato |
| Health evaluation completed (small samples) | the same 13 |
| Health assessment **not reliable** (measured) | Groundnut: 0/10 healthy field leaves recognised |
| **Insufficient evidence** | every other crop, including Tomato (4 healthy web photos) and Maize (no healthy photos) |
| **Demonstrated reliable** | **none** |

## 5. Tests
* **New:**
  * `tests/unit/test_crop_catalog.py`
  * `tests/integration/test_crop_master_catalogue.py`
  * 4 new crop- and part-aware tests in `tests/unit/test_vision_ollama.py`
  * the alias-search case in the app's `crop_catalog_test.dart`
* **Updated:** the plantation list (Oil Palm, Cocoa); the startup-seed test now pages through 213 crops.
* **Results:** backend full suite **1665 passed** (ruff, format and mypy clean); Flutter 148 passed, analyze clean.

## 5a. Live deployment (2026-10-15)
* Server rebuilt; migration 0015 applied.
* `seed_crops --reconcile`: 247 empty metadata fields filled, 125 crops added.
* **Existing 88 crops:** the id, name, Kannada name and category fingerprint is identical before and after
  (`55a414b1…`).
* **Live database:** 213 crops, all with scientific names and groups (18 groups); 14 users and 13 crop cycles,
  unchanged.
* **Live validation summary:** 213 catalogue crops; 13 evaluated; 0 reliable; 1 not reliable (Groundnut); 212
  insufficient evidence.
* **New debug APK** (crop search by alias and scientific name): SHA-256 starts `02a6550474b302b9`. Not installed.

## 6. Limits
* Crop identification is weak (27 %), and plant-part identification is only shown for leaves.
* Health assessment is not validated for any crop. Results remain advisory "possible" findings.
* The new crops' Kannada names, scientific names and durations should be reviewed by an agronomist or native
  speaker. Scientific names were written from standard references and may need checking for regional cultivars.
* Mushrooms are not assessed from photos.
