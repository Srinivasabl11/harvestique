# Granite Vision 2B pilot (2026-10-14)

Approved: download `granite3.2-vision:2b` (2,437,851,819 bytes, Apache-2.0) and run exactly one 10-photo batch of the
PlantDoc sample. Done with `scripts\eval-plantdoc.ps1 -Model granite3.2-vision:2b -Batch 10 -MaxBatches 1`, the same
pipeline, prompt, 150 s timeout and seeded sample as the gemma3:4b run. Production was not changed.

## Measured
* Run: 12:39-12:59, wall time **1,211 s** for 10 photos (includes the first model load), exit 0, stopped after one
  batch as asked. Lock released; model unloaded afterwards (commit back to 62 %, 6.6 GB available).
* **4 of 10 photos timed out** at the 150 s limit (151 s each); the pipeline fell back to the colour check and the
  harness recorded them as errors (`model_unavailable_fallback`), not as answers. 0 other errors.
* Answered photos: mean **100.4 s**, max 149.2 s (gemma3:4b on the same 10 photos: mean 77.9 s, 0 timeouts).
* Memory (sampled every 10 s to ~4 min; the sampler slowed under load, so peaks may be slightly higher):
  Granite process **4.1 GB -> 6.3 GB** over 10 photos (same steady growth as gemma3:4b); peak committed memory
  **86 %** of the limit; lowest available RAM **472 MB**. Granite loads with a 16 384-token context (gemma: 4 096).

## Same 10 photos, same scoring
| Photo (PlantDoc folder) | Truth | Granite | gemma3:4b |
|---|---|---|---|
| Apple Scab Leaf x4 | problem | possible disease x4 | possible disease x4 |
| Apple leaf (20180511...) | healthy | **healthy** | possible disease |
| Apple leaf x3 | healthy | timeout x3 | healthy x3 |
| Apple rust leaf (99e886...) | problem | possible disease | possible disease |
| Apple rust leaf (4-apple-rust2...) | problem | timeout | possible disease |

Granite: 6 answered, 6 correct, 4 timeouts. gemma3:4b: 10 answered, 9 correct. **10 photos (6 answers) say nothing
reliable about accuracy**; only 3 classes of 27 were reached.

## Decision
**Do not run the remaining 98 photos.** Measured blockers:
1. 40 % timeouts at the production timeout: in the app those farmers would get only the colour check.
2. Slower than gemma3:4b on the photos it did answer (100 s vs 78 s): the smaller language model does not offset its
   image tiling and longer context on this CPU.
3. Memory came within 4 points of the 90 % guard after only 10 photos; a full run would need batches of ~5.

A full run would take 4+ hours and still be mostly about timeouts. Making Granite fit (longer timeout, smaller context
via a new `num_ctx` option) would change production-relevant settings and still leave it slower than the current model.
**Keep gemma3:4b.** The 2.44 GB model can be removed with `ollama rm granite3.2-vision:2b` (not done: deleting needs
your decision).

## Files
`harvestique-eval-data\results\`: `plantdoc_granite3_2-vision_2b_108.partial.jsonl` (10 rows),
`plantdoc_granite3_2-vision_2b_108_rescore.json`, `granite_pilot_run.log`, `granite_pilot_memory.log`.
gemma3:4b checkpoint and report unchanged (SHA-256 prefixes `a37c53eabfeefe4a`, `127639fbd8c46a39` before and after).
