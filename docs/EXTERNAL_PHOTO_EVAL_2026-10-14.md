# External public crop-photo validation (Option 2): status (2026-10-14)

**Status: stopped before download and inference. The labels needed for a balanced, scorable set are not available:
there are 0 independently labelled healthy photos.** No images were downloaded, no model was loaded and no accuracy
was measured. Nothing in this file is evidence about Karnataka fields or about local agricultural accuracy.

## Files inspected first
`docs/KARNATAKA_VALIDATION_STATUS_2026-10-14.md`, `docs/NEXT_STAGE_PROMPT.md`, `docs/CROP_HEALTH_EVAL_2026-10-14.md`,
`harvestique-eval-data\karnataka\README.md` (0 photos). The earlier Karnataka status already found about 5 problem
photos and at most 1 weak healthy photo on Commons. This pass searched more widely to see whether that changes.

## How the search was done
* Source: Wikimedia Commons API, **metadata only**, about 5 s between requests (one 429 rate-limit response earlier
  in the session). Many Commons files in plant pathology are mirrored from Bugwood.org (University of Georgia), LSU
  AgCenter, Virginia Tech, Clemson–USDA, USDA ARS and LandCare Research, so the search covers those university and
  government collections where their photos are openly licensed. Their own websites were not scraped.
* Queries: about 20 disease searches for rice, ragi, groundnut, maize, tomato and chilli (by disease name, pathogen
  name, Bugwood and USDA), plus about 15 "healthy leaf" searches. 117 + 160 files were screened, and full provenance
  was then fetched for the plausible ones (`by_title.py`).
* Label tiers (as the user required: a caption alone is not proof of an expert diagnosis):
  * **A: independently verified** (for example a second expert, a lab test or a curated dataset with a stated
    protocol). **None found.**
  * **B: institution- or expert-attributed source label.** The photo comes from a plant pathologist or extension
    collection, with the pathogen named. This is credible, but I did not re-verify it independently.
  * **C: caption only, from a non-expert uploader.** Excluded from any primary scored set.
* The full record (source page, direct URL, licence and licence URL, attribution requirement, author and credit,
  categories, format, resolution, size and SHA-1) is in
  `harvestique-eval-data\external_public\SOURCE_INVENTORY.json`. That file is metadata only; the folder holds no images.

## Inventory (21 candidates)

| # | Crop | Condition as stated | Tier | Author / institution | Licence | Size (px) | Notes |
|---|---|---|---|---|---|---|---|
| 1 | Rice | stackburn | B | Donald Groth, LSU AgCenter | CC BY 3.0 US | 515×767 | |
| 2 | Rice | brown spot (*Cochliobolus miyabeanus*) | B | Donald Groth, LSU AgCenter | CC BY 3.0 US | 3072×1605 | |
| 3 | Rice | brown spot (*Helminthosporium oryzae*) | B | W. M. Brown Jr., Bugwood.org | CC BY 3.0 US | 2022×3071 | |
| 4–5 | Rice | leaf smut (*Entyloma oryzae*) 01, 02 | B | W. M. Brown Jr., Bugwood.org | CC BY 3.0 US | ~3071×2050 | same series; possible near-duplicates |
| 6 | Rice | leaf smut (*Entyloma oryzae*) 03 | B | Donald Groth, LSU AgCenter | CC BY 3.0 US | 3072×2098 | |
| 7 | Tomato | cucumber mosaic virus | B | Elizabeth Bush, Virginia Tech | CC BY 3.0 | 1152×1536 | |
| 8 | Tomato | leaf mould | B | Elizabeth Bush, Virginia Tech | CC BY 3.0 | 384×288 | very low resolution |
| 9 | Chilli/Capsicum | powdery mildew (*Leveillula taurica*) | B | Dr. P. Seethapathy, Amrita School of Agricultural Sciences | CC BY 3.0 | 1536×864 | crop known only from the category "Diseases and disorders of Capsicum" |
| 10 | Chilli/Capsicum | tomato chlorotic spot virus | B | USDA ARS (USDAgov) | Public domain | 8256×4640 | the original file is too large (decoder limit is 25 MP), so the 1600 px thumbnail would be needed |
| 11 | Maize | bacterial leaf streak | B | Vinicius Garnica, Bugwood.org | CC BY 3.0 | 720×600 | |
| 12 | Maize | southern corn leaf blight | B | David B. Langston, UGA | CC BY 3.0 US | 1536×827 | |
| 13 | Sorghum | *Ascochyta* leaf spot | B | Clemson University – USDA Cooperative Extension | Public domain | 3072×2048 | sorghum is not a target crop |
| 14–16 | Groundnut | rust (*Puccinia arachidis*) | B | LandCare Research, New Zealand | CC BY-SA 3.0 | ~432×300 | 3 photos from one source, probably near-duplicates; low resolution |
| 17 | Maize | soft rot (*Erwinia*) | X | Howard F. Schwartz, Colorado State University | CC BY 3.0 US | 2045×3072 | **excluded:** stalk or sheath, not a leaf |
| 18 | Tomato | "healthy tomato leaves" | C | Dwight Sipler (home gardener, Flickr) | CC BY 2.0 | 3872×2592 | caption only |
| 19 | Rice | "young paddy in promise" | C | Aerospectra (Wiki Science Competition) | CC BY 4.0 | 3000×4000 | caption only; field scene, not a leaf |
| 20–21 | Chilli (*C. chinense*) | "a healthy young plant", 01 and 02 | C | AjayDas | CC BY-SA 4.0 | ~3024×3900 | caption only; whole plant; same plant series |

Dropped during screening:
* The rice blast photo listed in the earlier status, "PCC-747-Arròs amb piriculariosi.jpg", no longer resolves
  on Commons (reported missing).
* Every ragi (finger millet) search returned no leaf photo.
* Most "healthy" results were food, people or unrelated plants.

## Counts against the target (20–30 photos, healthy and problem, several crops)
* **Problem, tier B:** 16 photos across rice (6), groundnut (3), chilli (2), tomato (2), maize (2) and sorghum (1).
  After allowing for near-duplicate series and the unusable leaf-mould thumbnail, about **11–13 effectively distinct**
  photos remain.
* **Healthy, tier A or B:** **0.**
* **Healthy, tier C:** 4, all excluded under the label rule. Two of the four are whole-plant or field scenes rather
  than leaf photos anyway.

## Why it stopped (your stop conditions)
1. **The labels for the healthy class are not reliable enough.** No photo labelled "healthy" is backed by an expert or
   institution. Scoring the caption-only photos would break your rule against using uncertain labels.
2. **Without healthy photos, the main metrics cannot be computed.** With 0 healthy photos, healthy precision and recall
   and macro-F1 are undefined, and "accuracy" becomes the same number as problem recall.
3. **A problem-only check would add almost no information.** On PlantDoc, gemma3:4b had 0 false negatives and
   16 false positives: it rarely misses a disease, and its known weakness is calling healthy leaves diseased. Problem
   recall on about 12 photos cannot reveal that weakness and would almost certainly come out near 100 %. Reporting
   that figure would overstate the evidence.
4. **The photos may overlap with PlantDoc.** PlantDoc was scraped from the web, and Bugwood and Commons photos are
   typical sources. Overlap could only be measured after downloading (SHA-256 and dHash against `plantdoc_test` and the
   8 tuning photos). Because the run was not justified, I did not download anything to check, so **overlap is
   unmeasured**.

The licensing is not the problem: every tier-B photo is CC BY 3.0 (US), CC BY-SA 3.0 or public domain, with the
author recorded. Memory was not the problem either: at the last check about 60 % was committed, 6.8 GB was available,
no evaluation was running and no locks were present.

## If you want to go further later (free options)
* **Recommended:** genuine local photos labelled by you or a Raitha Samparka Kendra officer (Prompt 2 in
  `docs/NEXT_STAGE_PROMPT.md`). Only this can say anything about Karnataka accuracy.
* An openly licensed, expert-curated dataset whose labelling protocol is documented and which includes healthy leaves
  from these crops. Its licence, its labelling method and its overlap with PlantDoc would have to be checked first,
  and it would remain internet or lab evidence, not field evidence.
* If you explicitly accept a problem-recall-only check (point 3 explains why it adds little), the 16 tier-B photos
  could be used. You would need to tell me so; I have not run it.

The tooling is ready and needs no code change. A dataset that qualifies would go in
`harvestique-eval-data\external_public\<Crop condition>\` and `<Crop> healthy\`, with an attribution manifest. The dry
run comes first, then the run:
```
scripts\eval-plantdoc.ps1 -ImagesSubdir external_public -PerClass 0 -Name external_public_gemma3_4b -HealthyPattern '^[A-Za-z_ ]+ healthy$' -AppResize -ReferenceSubdir plantdoc_test -DryRun
```

## Changes in this session
* New: this report and `harvestique-eval-data\external_public\SOURCE_INVENTORY.json` (metadata only).
* Scratchpad only (not in the project): `inventory.py`, `by_title.py` and the search JSON files.
* No code changed, so no tests were needed or run. No images were downloaded; no model was loaded or run.
* Untouched: Granite, the PlantDoc and Karnataka data, earlier results, production settings,
  `CROP_HEALTH_GENERIC_SPOTS_UNCERTAIN` (still off), the server, the database and Windows/WSL settings. No money was
  spent.
