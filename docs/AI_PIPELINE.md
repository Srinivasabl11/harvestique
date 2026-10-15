# Agricultural Intelligence Pipeline (Phases 4 and 6, assistant completed 2026-10-09)

No LLM is involved in predictions. The prediction "intelligence" is a deterministic hybrid-rule model behind a replaceable provider interface,
plus risk scoring, a virtual inventory and calibration. Formulas: `docs/ALGORITHMS.md`.

```
farm (lat/lon) -> WeatherService -> Open-Meteo forecast + archive -> weather_daily cache
                     refresh fails -> cached rows served as STALE; no data -> UNAVAILABLE
crop cycle, plot, catalog crop, owner's recorded harvests, observations, calibration profile, commitments
                     |
         PredictionService (gathers inputs; no reasoning here)
                     |  PredictionInput (pure dataclasses)
         PredictionProvider  -- today: RuleBasedPredictor "hybrid-rules" 1.0.0
                     |  p10/p50/p90, harvest window, CV, factors, widenings, sources, confidence, warnings
         Farm Risk Engine (9 categories; unassessed when data is missing)
                     |
yield_predictions: new version row, never updated  ->  inventory lot re-derived (p10 committable)
measured harvest -> prediction_feedback (one row per version) -> calibration_profiles (new versions)
next prediction uses a profile only when it has >= 5 outcomes
POST /crop-plans/{id}/items/from-prediction -> Phase 3 planner takes p10/p50/p90 per acre as its yield range
```

## Data provenance

| Label | Used for |
|---|---|
| measured | Open-Meteo archive (ERA5 reanalysis: model-based observation, not an on-farm gauge), farmer-recorded observations, recorded harvests |
| estimate | Open-Meteo forecast, the farmer's yield estimate, every prediction output |
| assumption | catalog reference yield, CV and water need, typical duration (seeded values are indicative and unverified) |
| simulated | synthetic data in the evaluation study only (`docs/EVALUATION.md`) |

## Missing, stale and failing data (each case is tested)

| Situation | Behaviour |
|---|---|
| farm has no coordinates | weather UNAVAILABLE; prediction continues with CV +0.10, window +3 days and a warning |
| Open-Meteo HTTP error, timeout, invalid or malformed payload | `ProviderUnavailableError`; cache served as STALE (CV +0.05) or UNAVAILABLE |
| cached forecast younger than 12 h | no network call |
| missing days in a series | skipped, never interpolated; lower coverage |
| no yield evidence | `insufficient_data`: no quantity, timing only |
| observations older than 30 days | ignored, with a warning |
| fewer than 5 recorded outcomes | profile stored but not applied; confidence labelled heuristic |
| a risk input not supplied | category not assessed and excluded from the overall score |

## Extending with a trained model
Implement `PredictionProvider` (`app/providers/prediction/base.py`: `name`, `version`,
`predict(PredictionInput) -> PredictionResult`) without database access, register it in `providers/registry.py` and
select it with `PREDICTION_PROVIDER`. Rows store `model_name` and `model_version`, so outputs of different models go
through the same feedback and calibration path.

## Endpoints
`GET /farms/{id}/weather`, `POST|GET /crop-cycles/{id}/predictions`, `GET /predictions/{id}`, `GET /farms/{id}/risk`,
`POST /crop-cycles/{id}/harvest-actual`, `GET /crop-cycles/{id}/feedback`, `GET /calibration`,
`POST /admin/calibration/recompute`, `GET /inventory/lots`, `GET /inventory/lots/{id}`,
`POST /inventory/lots/{id}/reservations`, `POST /inventory/reservations/{id}/release`,
`POST /inventory/reservations/{id}/fulfil`, `POST /crop-plans/{id}/items/from-prediction`.
Farmer-only except calibration (read: any signed-in user, aggregate statistics only; recompute: admin).


## Phase 6: AI Farm Assistant, voice and crop-health vision

All three are **advisory**. None of them can decide or change allocation quantities, orders, reservations or
inventory, and none of them invents weather, market, prediction or availability figures.

### AI Farm Assistant (`domain/assistant/`, `services/assistant.py`)
```
question (typed or an on-device transcript; English or Kannada) + up to 8 earlier turns sent back by the app
  1. keyword rules (pure, deterministic)                               -> intent       understood_by = rules
  2. else a follow-up of the previous turn ("and tomorrow?", "what about ragi?")  understood_by = context
  3. else, if Ollama is available, the local model picks ONE read-only tool from the caller's allowed list,
     or "general"; anything else it says is ignored                                 understood_by = local_model
  -> ONE whitelisted tool (allowed roles, validated arguments) -> existing service called with the CALLER's id
  -> template answer in the reply language, numbers copied from the tool result        answer_kind = records
  writes (reminder, expense) are only PROPOSED; they run via POST /assistant/tools/{name} with confirm=true
  "general": a short local-model answer, rejected if it contains numbers, labelled     answer_kind = general_ai
```
* **Intents** (English and Kannada keywords): weather, harvest prediction, farm risk, reminders (list / create),
  **expenses (questions; recording a spoken expense)**, inventory, buyer opportunities, supply requests, orders,
  market supply, income plans, crop-health help, help. Allocation requests are recognised and **refused**.
* **Tools** (`GET /assistant/tools`): `weather_summary`, `harvest_prediction`, `farm_risk`, `list_reminders`,
  `inventory_summary`, `buyer_opportunities`, `my_supply_requests`, **`expense_summary`** (all pages, by category
  and period), **`income_plans`** (the latest plan with crops, evaluated by the planning engine) (farmers);
  `my_orders`, `market_supply` (buyers). Write tools: `create_reminder` and **`record_expense`**. They run only
  with `confirm=true`, through the same services and ownership checks as the screens.
* **Crop and farm names** in a question ("ragi", "ರಾಗಿ", "Green Acres") are matched against the caller's own
  records only.
* **Validation:** unknown tools 404, wrong role 403, extra or invalid arguments 422, write without confirmation 409,
  another user's farm 404, future-dated expense 422. History: at most 8 turns, roles `user`/`assistant` only.
* **Never invented:** amounts, dates and categories of a spoken expense come from the words. A missing amount or
  category makes the assistant ask, not guess. Every answer about the farmer's data is a template filled from a
  tool result, with sources labelled measured / estimate / assumption.

### Local model (Ollama) - what it may do, and measured speed
| Use | Default | Safeguard |
|---|---|---|
| Pick a tool for a question the rules do not understand (`ASSISTANT_LLM_INTENTS`) | on | must be a read-only tool allowed for the caller's role; otherwise ignored |
| Short general farming answer in English (`ASSISTANT_LLM_GENERAL_ANSWERS`) | on | rejected if it contains any number (doses, prices, dates); labelled "AI (general, not your data)" with an "it can be wrong" disclaimer |
| General answer in Kannada (`ASSISTANT_LLM_GENERAL_ANSWERS_KANNADA`) | **off** | small local models wrote garbled Kannada in testing (below); the farmer is told to ask the Raitha Samparka Kendra instead |
| Reword tool answers (`ASSISTANT_LLM_REWORDING`) | off | kept only if every number appears in the tool facts; off because it is slow on CPU |

Availability is re-checked every 30 s and requires the configured model to be installed, so starting Ollama
later works without a restart. When it is down, the rules still answer, and only free-form questions get
"did not understand".

Measured on the development PC: Intel i7-7700 (4 cores / 8 threads), 16 GB RAM, Intel HD 630 graphics, so the
model runs on the **CPU only**. Ollama, warm model, the assistant's real prompts, 2026-10-09:

| Model | Tool routing (6 EN/KN questions) | General answer, English | General answer, Kannada |
|---|---|---|---|
| `llama3.2:3b` (2.0 GB) | 6/6 correct, 4.5 s mean | 12 s, sensible | 23 s, **largely meaningless** |
| `llama3.1:8b` (4.9 GB) | 6/6 correct, 6.5 s mean | 12 s, sensible | 41 s, **repetitive, cut off** |

Through the live API with `llama3.2:3b`, an unclear question took 3.5 s and an English general answer took 7.9 s.
The first question after a restart adds the model load time (about 20 s for the 8B model).
**Recommendation:** `llama3.2:3b` on CPU-only machines with 8 GB or more RAM. A GPU, or a model trained on Indian
languages, is needed before Kannada general answers can be enabled. The app waits up to 120 s for assistant answers.

### Voice (English `en-IN`, Kannada `kn-IN`)
* **Speech-to-text and text-to-speech run on the phone** (Android's recogniser and TTS engine through
  `speech_to_text` and `flutter_tts`). They are free and only the text reaches the server. Offline use needs the
  phone's offline speech pack for the language; otherwise Android's recogniser uses Google's service over the
  network, still free for the user. The app has an "offline speech recognition only" switch.
* `POST /voice/intent` runs the **same** assistant as chat, with the same confirmations. Spoken writes are proposed
  and need "yes"/"ಹೌದು" or a Confirm tap.
* The app (`features/assistant/`):
  * one large microphone button: tap to speak, tap to stop, tap to cancel while thinking, tap to interrupt the
    spoken answer;
  * conversation mode: after each answer it listens again, while the screen is open and the app is in the
    foreground. It stops on "stop"/"ಸಾಕು", after two silences, on errors or when the app is backgrounded. There
    is **no background wake word**: Android does not allow an app to keep the microphone open in the background
    for that;
  * clear messages for a refused microphone permission, silence, unrecognised speech, a missing offline pack or
    network, and a missing Kannada TTS voice;
  * typing always works.
* **Server speech (not used):** the `SpeechToTextProvider` / `TextToSpeechProvider` interfaces remain
  (`providers/speech/`) and the default `device` provider answers 503. Free local server options were considered
  and not adopted:
  * Whisper has weak Kannada at sizes a CPU can run in real time;
  * Vosk has no Kannada model;
  * Piper has no Kannada voice;
  * AI4Bharat IndicTTS needs a GPU-class machine.

  Audio uploads are still validated before any provider sees them.

### Crop-health image analysis (`providers/vision/ollama.py`, `providers/vision/base.py`, `services/media.py`)
* Output: a category among **Healthy / Possible disease / Stress / Possible deficiency / Unknown**, capped
  probabilities, photo-quality flags, the signs seen, an explanation and advice (English or Kannada; the AI's own
  description is English and labelled "may be wrong"), labelled `estimate`.
* `CROP_HEALTH_CLASSIFIER=ollama_vision` (stage 3): a general local vision model (`gemma3:4b` through Ollama; free,
  Gemma licence, about 3.3 GB disk and 6 GB RAM, 10-75 s per photo on the i7-7700 CPU). It returns schema-constrained
  JSON: a plain description written first, then whether a plant is shown, whether it is a close-up, photo quality,
  symptoms from a fixed list, a category and its confidence. It is told not to name diseases, pests, nutrients or
  chemicals. The server then:
  * adds signs named in the description (the model often leaves the list empty), ignoring negated mentions;
  * turns "healthy" with any described sign into Unknown, and a problem category with no sign into low confidence;
  * returns Unknown for not-a-plant photos, and for not-a-close-up or poor photos when no sign is visible (visible
    signs are kept at low confidence with a retake tip);
  * drops sentences about spraying, chemicals or doses;
  * caps the top probability at 0.70 (high 0.65, medium 0.55, low 0.42), as whole percentages that add up to exactly
    100. These are a fixed mapping of the model's confidence word, **not measured probabilities**, and the app says so.
  It is **not a validated plant-disease classifier**.
* Structured report (2026-10-15, `domain/crop_health_report.py`, stored as `features.analysis`): photo check, crop
  and part (the AI's unverified guess), visible observations, possible cause families (never a named disease or a
  treatment), a **visual condition score out of 10** (or the reason it is withheld), limitations and the next step,
  in English or Kannada. The score is a documented rubric over the visible signs, separate from the AI's confidence.
  It is not validated against expert severity ratings. Fruit, tuber and other non-leaf photos are judged only for
  that part, and colour change alone on them is not called a problem. Optional candidate prompt
  `CROP_HEALTH_PROMPT_VERSION=v2` (default v1). Details and evaluation status:
  `docs/CROP_PHOTO_ANALYSIS_2026-10-15.md`.
* Evaluation (8 public Wikimedia Commons photos, final prompt): healthy tomato -> Healthy; Alternaria spots and
  aphid curling -> Possible disease; Septoria and Cercospora spots -> Unknown (spots described); potassium-deficient
  soybean -> Possible disease (yellowing described; the category is wrong); healthy brinjal -> Unknown (poor photo);
  tractor in a field -> Unknown (not a close-up). No diseased leaf was called healthy. Eight photos are far too few
  to give an accuracy figure.
* `colour_heuristic` (and the fallback when the model is missing, times out or answers nonsense): colour
  measurements only (green / yellow / brown shares, brightness with exposure normalisation, sharpness) and **no
  health label**, because on the same 8 photos its labels were wrong 7 times (e.g. the tractor came out as "stress").
* The disclaimer names the method used and says it is not a diagnosis; confirm with an agriculture officer.
* File safety:
  * 5 MB limit, enforced before decoding;
  * JPEG, PNG or WebP only, judged by magic bytes and confirmed by the decoder;
  * a 25 MP pixel limit (decompression-bomb guard), `verify()`, single frame only, 64–8,000 px sides;
  * re-decoded to RGB and downscaled to 768 px (the colour check downsizes again to 384 px).
* Fast photo-quality pre-check (2026-10-14): before the vision model is called, photos that are almost black
  (brightness < 0.04) or very blurred (sharpness < 0.15 when brightness >= 0.15) get an immediate "Unclear" answer
  with a retake tip, without spending model time. Thresholds come from the 8 public test photos (originals: sharpness
  >= 2.18, brightness >= 0.39); none of them, and none of their lightly blurred or dim copies, is refused.
* Evaluation harness: `python -m app.cli.eval_crop_health <folders-of-labelled-photos> --out report.json` measures the
  configured classifier (healthy vs problem precision/recall/F1, macro F1, coverage / unclear rate, confusion matrix,
  latency) on photos it was never trained on, e.g. the PlantDoc test split (CC BY 4.0). It checks exact and
  near-duplicate photos and overlap with tuning photos, and treats a colour fallback as an error, not an answer.
* PlantDoc result (complete: 108 photos, all 27 classes, 0 errors): no diseased leaf missed (problem recall 67/67)
  but 16 of 39 answered healthy leaves called a problem (healthy recall 0.59, 95% interval 0.43-0.73); problem
  precision 0.81; macro F1 0.82; 1.9% unclear; 71 s per photo on this CPU. Internet photos of mostly temperate crops:
  **not** a measure of accuracy on Karnataka farms. Details: `docs/CROP_HEALTH_EVAL_2026-10-14.md`.
* Optional rule `CROP_HEALTH_GENERIC_SPOTS_UNCERTAIN` (default **off**): a problem answer whose only sign is generic
  "spots" at low confidence becomes "unknown". Pre-registered and checked on 75 held-out PlantDoc photos: macro F1
  0.84 -> 0.94, healthy recall 0.61 -> 0.82, but 3 of 50 diseased leaves became "unknown" and coverage fell 97% -> 85%.
* Memory: the Ollama process serving gemma3:4b grows with every photo (4 GB -> 9 GB over ~35 photos). Long batch jobs
  must unload the model regularly (`ollama stop gemma3:4b`); `scripts/eval-plantdoc.ps1` does this every 15 photos.
* The analysis runs in a worker thread so a slow model does not block other requests.
* Only the SHA-256 hash and the result are stored, never the photo.

### Demo mode
`python -m app.cli.demo --reset` (database name must contain "demo") runs the whole product flow through the real
API. It uses the `demo_scripted` prediction provider, which echoes the farmer's estimate exactly and labels every
output **simulated**; configuration validation refuses it when `APP_ENV=production`.
