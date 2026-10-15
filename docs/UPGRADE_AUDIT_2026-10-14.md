# Upgrade audit: five external repositories vs. the existing Harvestique (2026-10-14)

Phase One only: nothing was installed, downloaded (beyond reading repository metadata and text files through the
GitHub API), migrated or sent while producing this audit.

## 0. Current state (verified today)
* Workspace `C:\Users\Srinivasa\Documents\harvestique` is **not a Git repository** (no history, no `git status`).
  Safety therefore rests on database backups and on not overwriting files outside the planned changes.
* Live DB at migration `0013_plantation_category`; 14 users, 88 crops. Latest verified backup:
  `C:\Users\Srinivasa\Documents\harvestique-backups\harvestique_before_0013_20261013_2257.dump` (+ `.sha256`).
* Last verified test baseline (2026-10-14, same code): backend **1480 passed** (ruff, format, mypy clean); Flutter
  **143 passed**, `flutter analyze` clean; debug APK installed on the phone and exercised (see
  `PHONE_TEST_REPORT_2026-10-13.md`).
* Hardware: Intel i7-7700 (Windows reports 3 logical processors), 15.9 GB RAM (1.2 GB free at audit time, with
  Ollama `llama3.2:3b`, WSL/Docker, Gradle and browsers running), Intel HD 630 only (no CUDA GPU), 279 GB free disk.
  Any model runs on the CPU.
* Installed models: Ollama `gemma3:4b` (3.4 GB, crop health), `llama3.2:3b` (2.0 GB, assistant), `llama3.1:8b`
  (4.9 GB, unused).

## 1. Existing feature inventory relevant to this request
| Area | Existing implementation (files) | Verified status |
|---|---|---|
| Crop-health photo analysis | `backend/app/providers/vision/ollama.py` (gemma3:4b, schema-constrained JSON, symptom cross-check, unclear handling, retake tips, capped probabilities), `providers/vision/base.py` (`CropHealthClassifier` protocol + colour measurements fallback), `services/media.py` (upload validation: size, magic bytes, decompression-bomb guard, single frame, dimensions), `api/v1/assistant.py` (`POST /crop-health/analyze`, `GET /crop-health/analyses`), Flutter `features/crop_health/crop_health_screen.dart` | Working; phone-tested 2026-10-14 on 3 public photos; real accuracy **not measured** (8 public photos only) |
| Model abstraction | `CropHealthClassifier` protocol + `crop_health_classifier` setting (`colour_heuristic` / `ollama_vision`) + registry | Exists: a new model is one more implementation, not a new pipeline |
| AI assistant | `services/assistant.py` (controlled tools, general/mixed answers, grounding and personal-claim filters), Ollama `llama3.2:3b`, Kannada voice on the phone | Working (phone: mixed answer) |
| Reminders / notifications | `services/engagement.py`, `models/engagement.py`, in-app `NotificationChannel` (`providers/notifications`), dedup keys, unread counts, Flutter bell + notifications screen | Working in-app (phone-tested); **no SMS or push delivery for notifications** |
| SMS | `providers/sms/providers.py`: `dev_console`, **`android_gateway`** (your own Android phone + SIM via the open-source capcom6 "SMS Gateway for Android", LAN only, Basic auth), `disabled`, `RecordingSms` test double; used for **OTP only**; production refuses `dev_console` | Exists; never configured with a real phone |
| Harvest pooling | `services/pooling.py`, domain allocation, shortage detection, reallocation, ledger | Working, 1480-test baseline; untouched by this plan |
| Testing tools | `scripts/validate.ps1` / `validate.sh` | **Broken on this PC**: expects `backend\.venv` (absent) and DB port 5433 (this PC uses 5434). The Docker test runner used in all sessions lives only in Claude's temporary folder, not in the project |

## 2. Repository evaluation (source inspected, not README claims)
| Repo | License | What is actually there | Usable weights? | Verdict |
|---|---|---|---|---|
| A Jenpoer/plant-disease-detection | MIT | 164 training configs, PlantVillage -> PlantDoc domain-shift study, FastAPI ViT-B/16 inference (top-3 + low-confidence warning) | **No.** 576 MB checkpoint "must be obtained separately"; no download link | **Reuse the method, not the model.** Its own result: best real-field macro-F1 **0.45** (0.08-0.45 across runs) while lab F1 is ~0.97+. Classes: 26, mostly temperate crops (apple, cherry, peach, raspberry...); of Karnataka crops only tomato, potato, corn, grape |
| B shatini/crop-disease-detection-ai | MIT | Clean ResNet18 training/eval/inference scripts, 38 PlantVillage classes | **No.** Must train from PlantVillage yourself | **Reject as a model.** 98.8% is lab-split accuracy; A shows such models drop to ~0.3-0.45 F1 in the field. Training on this CPU is hours to days and still would not cover ragi, paddy, brinjal, chilli, beans... |
| C yesh00008/crop-diseases-detection | MIT | React/TS web app + Keras training scripts | **No** ("link to be added") | **Reject.** Advertised 72% (lab), duplicate/garbled class labels, `ensemblePredictor.ts` *simulates* detection with `Math.random()`, and a **hard-coded third-party Gemini API key** in `geminiService.ts` (cloud, not free to rely on, and not yours to use) |
| D garrytan/gstack | MIT | Markdown slash-command prompts for Claude Code; needs Bun, Git, Node; downloads Chromium | n/a | **Do not install now.** Overlaps the review/security tools this Claude Code already has (`/code-review`, `/security-review`); assumes Git/PR workflow (project has no Git); stops working without Claude Code; its installer asks the agent to rewrite CLAUDE.md and change tool rules. Optional later, on your decision |
| E NdoleStudio/httpsms | **AGPL-3.0** | Go API + web + Android app; hosted service on Google Cloud, or self-host with Firebase (FCM), Cloudflare Turnstile and a rebuilt Android app | n/a | **Reject: duplicates the existing `android_gateway` provider** with more moving parts (cloud account or Firebase project, phone needs internet). Hosted pricing could not be verified (page is JavaScript-only) |

## 3. Feature-mapping table
| Requirement | Existing | Verified gap | Proposed action | Duplication risk | Files | Acceptance test |
|---|---|---|---|---|---|---|
| Better crop-disease accuracy | gemma3 vision provider | Accuracy never measured on a labelled field set | **Evaluation suite** (A's method: held-out field images, per-class P/R/F1, macro F1, confusion matrix, unclear rate, latency) for the existing provider; adopt a new model only if it measurably wins | None (evaluates existing provider through its interface) | new `backend/app/cli/eval_crop_health.py`, tests | Runs on a small fixture; produces metrics; never fabricates |
| Top-3 candidate diagnoses | Category + capped probabilities; no disease names by design | Only true with a validated disease classifier | **Not now**: no usable classifier exists for your crops; naming diseases from gemma3 would be guessing | High (would add a second answer source) | — | — |
| Blur / dark / unsupported handling | Model self-reports `poor_photo` / `not_close_up` / `not_a_plant`; colour code measures blur and darkness but only in the fallback | Obviously blurred or black photos still cost ~60-90 s of model time | **Fast quality pre-check** reusing the existing measurements before calling the model; clearly bad photos get an instant retake message | Low (reuses existing code) | `providers/vision/ollama.py`, `domain/vision.py`, tests | Blurred/dark test images rejected in <1 s without a model call; good photos unchanged |
| Model failure isolation | Fallback to colour measurements; timeouts; worker thread | — | Keep; add regression test for the pre-check path | — | tests | Existing tests pass |
| Engineering workflows (gstack) | Claude Code review tools; `scripts/validate.*` | Local validation broken; no in-project test runner | **Project-local test scripts** (Docker-based, no venv needed, port from `.env`); a written manual QA checklist. gstack not installed | Low | `scripts/`, `backend/Dockerfile.test`, `docs/` | `scripts\test-backend.ps1` runs the suite from a fresh PowerShell |
| SMS (Airtel SIM) | `android_gateway` SMS provider (OTP) | Notifications/reminders are in-app only | **Proposal only (needs your approval):** optional SMS copy of selected notifications through the *existing* SmsSender, off by default, per-user opt-in (one additive column), daily cap, dedup by notification id | Medium if done as a new subsystem; low via existing provider | `services/engagement.py`, `providers/notifications`, migration 0014 | Mock-provider tests; no real SMS without approval |
| Pooling | Existing | None found | Untouched | — | — | Pooling suites still pass |

## 4. Costs and limits
* Recurring money: **₹0** for everything proposed. Optional SMS: each message is a normal SMS from your SIM; your
  Airtel plan's SMS allowance and daily limits apply (commonly ~100 SMS/day on prepaid; check your plan), and charges
  apply beyond it. Indian rules (TRAI) restrict promotional messages from personal numbers; transactional notices to
  users who opted in are the only intended use.
* One-time: optional evaluation data: PlantDoc (CC BY 4.0, 933 MB in total, 27 test-split class folders); a
  stratified sample of ~100 test photos is a few tens of MB, fetched file by file - **needs your approval**. Running
  gemma3:4b over 100 field images takes roughly 1.5-2.5 hours of CPU time on this PC.
* Nothing proposed depends on Claude Pro at runtime.

## 5. Implementation sequence (low-risk first) and rollback
1. Project-local test runner + fixed validate scripts (files only; rollback = delete the new files).
2. Crop-health fast quality pre-check (code + tests; rollback = previous file contents, kept in the stage log).
3. Evaluation harness (code + tests on a tiny fixture; no download).
4. **Needs approval:** download PlantDoc subset and run the baseline evaluation (~2 h CPU).
5. **Needs approval:** optional SMS notification copies (migration 0014 after a verified backup; disabled by default;
   no real SMS until you approve a test to your own number).

## 6. Stages carried out (2026-10-14)
| Stage | Change | Files | Evidence |
|---|---|---|---|
| 1 | Project-local test runner; `validate.ps1` / `validate.sh` read the DB port from `.env` and fall back to Docker when there is no `backend\.venv` | `backend/Dockerfile.test`, `scripts/test-backend.ps1`, `scripts/validate.ps1`, `scripts/validate.sh` | `test-backend.ps1` run from PowerShell: lint, format, mypy, tests |
| 2 | Fast photo-quality pre-check inside the existing vision provider (no new pipeline); shared measurement function | `backend/app/providers/vision/ollama.py`, `backend/app/domain/vision.py`, `tests/unit/test_vision_ollama.py` | 8 real photos: 0 originals refused; near-black copies 8/8 refused, heavy blur 6/8, light blur and dim copies 0 refused; unit tests prove no model call on refusal |
| 3 | Evaluation harness for the existing classifier (A's held-out field-set method) | `backend/app/cli/eval_crop_health.py`, `tests/unit/test_eval_crop_health.py` | Unit tests check the arithmetic; **no field-set result yet** (needs the approved data run) |
| docs | Pre-check and evaluation documented; manual QA checklist for use without AI tools | `docs/AI_PIPELINE.md`, `docs/MANUAL_QA_CHECKLIST.md` | — |

No database change, migration, download of models or datasets, SMS, or authentication change was made.
Rollback for stage 2: pre-change copies are in
`C:\Users\Srinivasa\Documents\harvestique-backups\code_before_precheck_20261014\` (`ollama.py` goes back to
`backend/app/providers/vision/`, `vision.py` to `backend/app/domain/`), then rebuild the backend container. Stages 1
and 3 roll back by deleting the new files (and restoring the port line of each validate script).
