# Karnataka crop-health validation: status (2026-10-14)

**Status 2: preparation complete; genuine, independently labelled photos are not available. No inference was run.**

## What was checked
* `harvestique-eval-data\karnataka\` contains only the README (and now `labels_by.TEMPLATE.txt`): **0 photos**.
* Project folders, backups and evaluation data: no labelled crop photos usable for this. The 8 Wikimedia photos used
  in earlier sessions to tune the prompt and thresholds are excluded (tuning leakage; not from Karnataka). Personal
  folders (Pictures, Downloads, phone gallery) were **not** searched: private, and they carry no independent labels.
  Harvestique itself stores only a hash of each uploaded photo, never the photo.
* Public sources (Wikimedia Commons API, metadata only, nothing downloaded; one 429 rate-limit, then 4 s between
  requests). A photo qualified only if it is a real leaf photo, freely licensed, and its **own caption or category from
  the uploader names the condition** (no labels from appearance, never from the AI):

| Searched | Usable candidates | Notes |
|---|---|---|
| Rice: brown spot, blast, bacterial blight | 2 | Bugwood.org brown spot (W. M. Brown Jr., CC BY 3.0 US); rice blast "necrotic area" (Associacio de Defensa Vegetal Arros de Pals, CC BY-SA 3.0); the rest microscopy, field or panicle shots |
| Groundnut: early leaf spot, rust | 3 | Peanut rust, LandCare Research NZ (CC BY-SA 3.0), 3 photos from one source, probably near-duplicates; leaf spot only as journal figure panels |
| Maize: common rust, northern leaf blight | 0 | |
| Tomato: Septoria, yellow leaf curl, late blight; chilli bacterial spot | 0 | categories empty or no leaf photos (Alternaria photos are the excluded tuning photos) |
| Ragi (finger millet) blast | 0 | |
| "Healthy" rice / tomato / chilli / groundnut leaves | 1 weak | "Healthy tomato leaves" by a home gardener ("Wish they all looked like this"), not an independent label; all other hits were food photos |

* Result: about **5 problem photos, at most 1 weakly labelled healthy photo**, none taken in Karnataka, some possibly
  also inside PlantDoc (itself scraped from the web). That does not meet the target (20-30 photos, about 1/3 healthy,
  3-5 crops, independent labels) and would only repeat the PlantDoc-style internet-photo test on a tiny scale, so it
  was **not** assembled or run.

## Ready (verified today)
* Folder rules and collection guidance: `harvestique-eval-data\karnataka\README.md`; labelling record template:
  `labels_by.TEMPLATE.txt` (copy to `labels_by.txt` with true information only).
* Dry run (no model): run name `karnataka_gemma3_4b`, separate checkpoint/report/lock (none exist), gemma3:4b
  installed, no evaluation running, memory 60 % committed / 6.8 GB available, backend ready; photo check:
  **No images found** (the only blocker). Explicit healthy rule, app-equivalent resizing and PlantDoc duplicate check
  are part of the command and were tested on the 236 PlantDoc photos in the previous session.
* Run command (pre-authorised by you once real labelled photos pass the dry run):
  `scripts\eval-plantdoc.ps1 -ImagesSubdir karnataka -PerClass 0 -Name karnataka_gemma3_4b -HealthyPattern '^[A-Za-z_ ]+ healthy$' -AppResize -ReferenceSubdir plantdoc_test`

## What is missing (only you can provide it)
20-30 real photos of crops you grow (ragi, paddy, tomato, chilli, brinjal, groundnut, beans...), about one third
healthy, in the folder layout of the README, with labels decided by you or, better, confirmed by an agriculture
officer / Raitha Samparka Kendra, and `labels_by.txt` filled in truthfully. Then use Prompt 2 in
`docs/NEXT_STAGE_PROMPT.md`.

## Changes in this session
* New: `harvestique-eval-data\karnataka\labels_by.TEMPLATE.txt`, this report.
* No code changed (so no tests were needed or run); no model loaded; no download; production, database, server,
  Windows/WSL settings, Granite and all existing results untouched.
