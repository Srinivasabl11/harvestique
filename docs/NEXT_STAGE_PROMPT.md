# Next stage: prompt to continue (prepared 2026-10-14)

Copy the block below into a new session. It reuses the existing scripts and reports; nothing in it repeats finished work.

## Status at the time of writing
| Item | State |
|---|---|
| gemma3:4b PlantDoc evaluation (108 photos) | **done**: `docs/CROP_HEALTH_EVAL_2026-10-14.md` |
| Candidate rule `CROP_HEALTH_GENERIC_SPOTS_UNCERTAIN` | implemented, tested, **off** in production; your decision |
| Granite Vision 2B | pilot done (`docs/GRANITE_PILOT_2026-10-14.md`): 40 % timeouts, slower; **full run not recommended** |
| Karnataka photo validation | **ready in software**; blocked only on labelled photos |
| Tools | `scripts\eval-plantdoc.ps1` (`-Model`, `-ImagesSubdir`, `-PerClass 0`, `-Name`, `-Batch`, `-MaxBatches`, `-DryRun`, `-RescoreOnly`), memory checks, locks, resumable checkpoints |

| Needs your approval | Can be done without new downloads |
|---|---|
| Running the full 98 remaining Granite photos (not recommended) | Karnataka evaluation with gemma3:4b once photos exist |
| Removing Granite (`ollama rm granite3.2-vision:2b`, frees 2.44 GB) | Re-scoring any saved run (`-RescoreOnly`) |
| Enabling `CROP_HEALTH_GENERIC_SPOTS_UNCERTAIN` (production behaviour) | Comparing baseline vs rule on Karnataka photos |
| Rebuilding/deploying the server | Updating documentation and tests |

## Prompt 2
```
Continue in my existing Harvestique repository on Windows 11. Read docs/CROP_HEALTH_EVAL_2026-10-14.md,
docs/GRANITE_PILOT_2026-10-14.md and docs/NEXT_STAGE_PROMPT.md first; do not repeat finished work.

Karnataka crop-photo validation with the existing gemma3:4b pipeline:
1. I have placed labelled photos in C:\Users\Srinivasa\Documents\harvestique-eval-data\karnataka\, one folder per
   class, following harvestique-eval-data\karnataka\README.md (folders ending in " healthy" = healthy, e.g.
   "Ragi healthy"; every other folder = problem, e.g. "Ragi blast", "Tomato leaf curl").
   Labels were given by: <me / agriculture officer / RSK>. Check folder names, counts, file types and duplicates
   (also against the PlantDoc photos) before running; report problems instead of guessing labels.
2. Run the dry run (photo check, no model):
   scripts\eval-plantdoc.ps1 -ImagesSubdir karnataka -PerClass 0 -Name karnataka_gemma3_4b -HealthyPattern '^[A-Za-z_ ]+ healthy$' -AppResize -ReferenceSubdir plantdoc_test -DryRun
   then the same command without -DryRun (batches of 15, memory checks, model unloaded after each batch).
   Do not run if memory is too tight; report it instead.
3. Report per-class precision/recall/F1, macro F1, false alarms, missed diseases, unclear rate, latency, and the
   baseline vs CROP_HEALTH_GENERIC_SPOTS_UNCERTAIN comparison from -RescoreOnly. Compare with the PlantDoc results.
   With 20-30 photos, give intervals and do not overstate accuracy.
4. Keep CROP_HEALTH_GENERIC_SPOTS_UNCERTAIN off in production; no server rebuild/deploy, database change,
   Windows/WSL change, download, paid service or SMS. Granite: do not run more photos.
5. Update docs/CROP_HEALTH_EVAL_2026-10-14.md (new Karnataka section) and report results, tests and the single best
   next step.
```

## How to prepare the Karnataka photos (you)
* 20-30 photos taken with a phone in daylight, one leaf or a few leaves filling the frame, of crops grown locally
  (ragi, paddy, tomato, chilli, brinjal, beans...). Include healthy leaves too (about a third).
* Ask an agriculture officer or Raitha Samparka Kendra to confirm each label if possible; write who labelled them.
* Put each photo in a folder named after its class under `harvestique-eval-data\karnataka\`. Photos stay on this PC.
