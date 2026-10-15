# Accuracy and validation plan (2026-10-14)

Only measured numbers are listed. "Not measured" means exactly that.

| Component | Measured so far | Data and limits | Next validation (free) |
|---|---|---|---|
| Crop health (gemma3:4b) | PlantDoc 108 web photos: macro-F1 0.818, 16/39 healthy false alarms, 0/67 missed. Koppal groundnut 20 field photos: **10/10 healthy called diseased**, macro-F1 0.334 | Web and research photos; small samples; not Karnataka farm evidence (`CROP_HEALTH_EVAL_2026-10-14.md`, `KOPPAL_GROUNDNUT_EVAL_2026-10-14.md`) | Root-cause the healthy-leaf false alarms on a **new** held-out sample (the Koppal 20 are now seen); the uncertainty rule stays OFF |
| Voice understanding (transcript → intent) | Held-out 38 phrasings: old 55.3 % → new 97.4 % (Kannada 56.7 % → 96.7 %); wrong-tool answers 7 → 0 | Text written by the developer in recogniser style; **speech recognition on the phone not measured** | Phone session: 20 spoken Kannada and 10 English questions; log transcript, alternatives, intent, answer; count transcript errors separately from intent errors |
| Voice output (Kannada TTS) | Not measured | Depends on the phone's TTS voice | Phone: does each Kannada answer play fully and intelligibly (native-speaker check) |
| Yield / harvest predictions | Not measured against real harvests | Few recorded actual harvests in the database | Compare predictions with recorded actual harvests once ≥ 20 exist; report MAE against a "crop average" baseline |
| Market prices | None used (never invented) | No price source integrated | Only with an official free source and a dated "as of" label |
| Pooling / allocation | Deterministic; regression and concurrency suites pass | Logic correctness, not field outcomes | Keep the A–E 2,000 kg scenario and concurrency tests in every run |
