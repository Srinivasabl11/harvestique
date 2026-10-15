# Free public crop-leaf dataset search and evaluation plan (2026-10-14)

**Update, same day:** you approved the **groundnut dataset only** (20 photos). It was downloaded, checked and
evaluated; see `docs/KOPPAL_GROUNDNUT_EVAL_2026-10-14.md`. The chilli dataset was not downloaded.

**Original status: two suitable datasets were found, both with healthy and diseased classes. The plan below was
waiting for your approval. Nothing had been downloaded and no inference had been run.**

This search follows on from `docs/EXTERNAL_PHOTO_EVAL_2026-10-14.md`, which found only single Wikimedia Commons
photos and 0 reliably labelled healthy ones. That Commons search was not repeated. This time I looked for **published
research datasets** (Mendeley Data, Data in Brief, IEEE DataPort, Hugging Face mirrors, TensorFlow catalogue). The
facts below come from each repository's official API record and, where one exists, the data paper. No dataset
images were opened.

## Label tiers used
* **Independently expert-verified:** a second expert or a lab confirmation, with the protocol documented. **None of
  the datasets reaches this tier.**
* **Institution-labelled with expert involvement, as stated by the authors:** the strongest tier available. These
  are the two suitable datasets below. I did not check their labels independently.
* **Institution-labelled with no labelling method stated:** not suitable for a primary set.
* **Uploader caption only:** excluded.

## Suitable datasets (both CC BY 4.0, healthy and problem classes, field photos from Karnataka)

| | **A. Koppal groundnut** | **B. Krishna-basin chilli** |
|---|---|---|
| Record | "Dataset of groundnut plant leaf images for classification and detection", Mendeley Data v3, DOI 10.17632/22p2vcbxfk.3 (published 2023-04-13); paper in Data in Brief (2023), PMC10293989 | "Image Dataset on Chili Leaf Diseases in the Krishna River Basin of the Deccan Plateau, India", Mendeley Data v3, DOI 10.17632/ymt8k9bjkn.3 (published 2026-02-02) |
| Authors | Aishwarya Manvikar (M P), Padmanabha Reddy; Vijayanagara Sri Krishnadevaraya University, Ballari | Rashmi Laxmikant Malghan, Lingaraj K, Karthik Rao M C, Lalit Garg; Manipal (MAHE/MIT), Visvesvaraya Technological University, RYMEC Ballari, University of Malta |
| Licence | CC BY 4.0 (API `data_licence`). Credit the authors, link the licence and state changes (we resize). | CC BY 4.0 (API `data_licence`). Same conditions. |
| Where collected | Chilwadigi and one other groundnut farm in Koppal district, Karnataka | Ballari and Raichur districts (Karnataka) and Guntur and Prakasam districts (Andhra Pradesh); October 2024 to February 2025 |
| Label evidence | Paper: "Data annotation was done manually and Data acquisition was done with the help of a pathologist." | Record: "All field collection was conducted under the direct supervision of agricultural experts"; "labeled and verified by agricultural experts". No names or protocol given, and no data paper found. |
| Classes (raw images on Mendeley) | healthy leaf **929**; early leaf spot **885**; late leaf spot **689**; rust **226**; nutrition deficiency **329** (3,058 raw images). The paper's 10,361 total includes augmented copies, which we would not use. | 1,856 original images in 6 classes: Healthy, Bacterial Spot, Curl Virus, Cercospora Leaf Spot, White Spot, Nutrition Deficiency. **Per-class counts are not yet known** (they are inside the zip). 12,000 augmented images, not used. |
| Format | JPG, 1200×800 (paper), files 135–806 KB, Canon camera, some cropped to the leaf | High-resolution JPG, digital camera; inside "Chili Leaf Disease Original Dataset.zip" (525,828,851 bytes) |
| Minimum download | Each image can be downloaded separately and has a SHA-256 from the API, so only the sampled files are needed (about 20 × 0.4 MB ≈ 8 MB) | The server supports byte-range requests (checked: `206 Partial Content`), so only the zip directory and the sampled members are needed (about 20–30 MB), not 526 MB |
| Overlap with PlantDoc | Unlikely: PlantDoc (2019) has no groundnut or chilli class, and this dataset dates from 2023. Must still be checked with SHA-256 and dHash. | Unlikely for the same reasons, and the photos date from 2024–25. Must be checked. |
| Training-data contamination | Possible: public since 2023, and gemma3 was released in 2025. Unknown either way. | Less likely (collected 2024–25, v3 published 2026). |

**Limitations to state with any result:**
* These are research photos, mostly single leaves with careful framing, not farmer phone snapshots.
* The labels are the authors' own; we cannot check the expert's role independently.
* Only 2 crops are covered.
* About 40 photos gives wide uncertainty (roughly ±15 percentage points at 95 %).
* Koppal, Ballari and Raichur are Karnataka districts, but a good score here **still does not prove accuracy on your
  farms**. It is an external check on published field photos.

## Considered and not used

| Dataset | Why not |
|---|---|
| West Bengal groundnut (Sasmal et al., Mendeley 10.17632/x6x5jkk873.2, CC BY 4.0, 1,720 images, healthy class) | The record says nothing about who labelled the photos. Kept as a backup only. |
| "chilli dataset" (Aishwarya M P and Reddy, Mendeley 10.17632/tf9dtfz9m6.2, CC BY 4.0) | The record has a one-line description, no classes and no labelling method. |
| Indian Rice Disease Dataset (IEEE DataPort) | Expert-verified, but only sample images are released, and IEEE DataPort needs an account. |
| Rice datasets with a healthy class (Mendeley jw7hp6r5gj, g7tcwvshff, hx6f852hw4, vwv3nry3wr, zfwkkdj6dk) | Mostly from Bangladesh, with no labelling method stated. zfwkkdj6dk reads like auto-generated text. |
| Sambalpur rice (fwcj7stb8r), Mendeley z4hx2v3ywc | No healthy class. |
| PlantVillage (Hughes and Salathé 2015) | Lab photos on plain backgrounds, not from India. Sources disagree on the licence (CC0 vs CC BY-SA 3.0). Very likely in model training data, and PlantDoc uses its class names. |
| Ragi (finger millet) | No image dataset with documented labels found. |

## Proposed evaluation plan (waiting for approval)

1. **Sample before downloading.** List the files with the Mendeley API. For the chilli zip, read only the zip
   directory with a range request. Using seed 42, pick:
   * Groundnut: healthy 10; early leaf spot 4, late leaf spot 3, rust 3 (problem total 10).
   * Chilli: healthy 10; bacterial spot 3, curl virus 3, Cercospora 2, white spot 2 (problem total 10).
   * Plus about 2 spares per folder, in case the duplicate check removes photos (burst shots are likely).
   * "Nutrition deficiency" is **excluded** from the primary binary score, because it is not a disease and its label
     is ambiguous for a healthy/problem split.

   That makes **40 primary photos, 20 healthy and 20 problem**, so the false-alarm weakness (healthy leaves called
   diseased) is measured directly.
2. **Download** into a new folder `harvestique-eval-data\public_datasets\` with folders `Groundnut healthy`,
   `Groundnut early leaf spot`, `Groundnut late leaf spot`, `Groundnut rust`, `Chilli healthy`, `Chilli bacterial spot`,
   `Chilli curl virus`, `Chilli cercospora leaf spot`, `Chilli white spot`.
   * Use free HTTPS only. Groundnut files are checked against their SHA-256; chilli members against the zip CRC.
   * Write `ATTRIBUTION.json` with the DOI, authors, licence, original path and hash for every file.
   * Use a scratchpad download script that is not production code. Downloaded files are treated as untrusted data,
     and Python runs with `-I`.
   * Total about 30–40 MB, and no existing folder is touched.
3. **Dry run (no model):**
   ```
   scripts\eval-plantdoc.ps1 -ImagesSubdir public_datasets -PerClass 0 -Name public_datasets_gemma3_4b -HealthyPattern '^[A-Za-z_ ]+ healthy$' -AppResize -ReferenceSubdir plantdoc_test -DryRun
   ```
   * This checks decodability, size limits, the app-style resize, and SHA-256/dHash duplicates against PlantDoc and
     within the set.
   * A separate check-only pass is run against the 8 tuning photos.
   * Near-duplicates within the set are removed by swapping in spares; the replacement rule is fixed before any model
     output is seen.
   * It also confirms that the checkpoint, report and lock names are new.
4. **Run:** the same command without `-DryRun`.
   * Batches of 15 (3 batches), with `ollama stop` after each batch and the commit guard (stop above 75 % committed or
     below 1,500 MB available).
   * Expected time: about 40 × 71 s ≈ 50 minutes on the CPU.
   * Production settings stay unchanged: `CROP_HEALTH_GENERIC_SPOTS_UNCERTAIN` stays off. The candidate rule is
     reported by re-scoring only.
5. **Report:**
   * Healthy and problem precision and recall, macro-F1, coverage (unknown answers), errors and timeouts, latency, and
     memory.
   * Results per crop as well as combined.
   * The confusion counts, with confidence intervals.
   * The limitations listed above.

No production code changes are expected. The existing harness already supports this folder layout.

## Changes in this session
* New: this file. No downloads, no model runs and no code changes.
* `docs/EXTERNAL_PHOTO_EVAL_2026-10-14.md` and `SOURCE_INVENTORY.json` are preserved unchanged.
