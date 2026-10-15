# Crop health result and produce quality grade (2026-10-15)

Two separate features. **Crop health** looks at a growing plant's leaves. **Produce grade** rates harvested produce
for sale. A healthy crop can give grade C produce (picked late, bruised) and the reverse, so neither feeds the other.

## Crop health: one clear result

The vision model still answers in its internal categories (healthy, possible disease, stress, possible deficiency,
unknown). They are stored for evaluations and **never shown**. Farmers see one of four results
(`app/domain/crop_health_decision.py`, English and Kannada):

| Result | When | What it says |
|---|---|---|
| **Healthy** | usable photo, AI confidence medium or high, no sign of damage named | "No spots, yellowing, holes, drying or other damage is visible", the confidence, keep checking |
| **Needs attention** | the AI named at least one visible sign (any confidence) | the signs and how widespread, the confidence (low: "look at the plant yourself before acting"), practical checks for those signs |
| **Clearer photo needed** | dark, blurred, too far, not a plant, possibly another crop, only fruit colour, AI unsure, or "healthy" at low confidence | no health claim; how to take a better photo |
| **Photo check unavailable** | AI not configured, unreachable, too slow, busy, or its answer failed validation | no health claim; try later; check the plant yourself |

Rules that keep it honest:

* Low confidence is never enough for **Healthy** ("no damage seen" from a doubtful answer becomes "clearer photo").
* Next steps are field checks (count affected plants, check soil moisture at root depth, look under leaves, remove
  badly affected leaves, soil test). They never name a disease, product, chemical or dose. Any spray or fertiliser
  goes through an agriculture officer, Raitha Samparka Kendra or KVK.
* The model's answer is checked against a JSON schema. Malformed answers, timeouts (`VISION_TIMEOUT_SECONDS`),
  refused keys, rate limits and an unreachable server are each logged by cause and reported as "unavailable".
* Old stored results are re-explained with the same rules when the history is loaded. The stored result itself
  does not change.

Accuracy: `gemma3:4b` over-reports problems on healthy leaves (PlantDoc and Koppal evaluations,
`docs/CROP_HEALTH_EVAL_2026-10-14.md`, `docs/KOPPAL_GROUNDNUT_EVAL_2026-10-14.md`). That is why "Needs attention" at
low confidence asks the farmer to look first, and the report keeps the "this AI often reported problems on healthy
leaves" limit. The hosted `gemma4:31b` has not been evaluated.

**Measured on the reserved held-out set** (74 never-seen PlantDoc + groundnut photos, `gemma3:4b`, prompt v1,
2026-10-15, `harvestique-eval-data/results/heldout_v1_gemma3_4b.json`): macro F1 0.779. Mapped to the farmer-facing
result: of 33 healthy leaves, 19 were shown **Healthy** and 14 **Needs attention** (false alarms). Of 41 problem
leaves, 40 were shown **Needs attention** and 1 **Healthy**. When this model says Healthy it was right 19 times out of
20 here, but a "Needs attention" on a healthy-looking plant is common, which is why the result asks the farmer to look
before acting. Candidate prompt v2 has not been run on this set yet; it stays off.

## Produce quality grade: A / B / C

Stored per recorded harvest in `produce_gradings` (migration 0018). The rules are in
`app/domain/produce_grading.py`, configured in one place:

* **Profiles by crop group.** *Fresh produce* (vegetables, fruits, roots and tubers, flowers...): size and
  uniformity, ripeness and colour, damage, freshness. *Grain, seed or dried produce* (cereals, millets, pulses,
  oilseeds, spices, plantation, fibre...): grain size, colour and lustre, broken, insect-damaged or sprouted grains,
  cleanliness, dryness.
* Each check has 3 levels with indicative thresholds shown to the farmer, for example damage: "under about 2 in 100",
  "up to about 10 in 100", "more than about 10 in 100, or any rot".
* **Grade = the worst level.** All best = A, any middle = B, any worst = C.
* **No grade without every check.** The API refuses to confirm with checks missing (`checks_missing`).
* **The farmer decides.** A photo of the produce can get an AI suggestion (same Ollama vision model). Only what is
  visible is rated, and dryness never is. Low confidence gives no ratings. A poor photo, non-produce or another crop
  asks for a retake. The suggestion is never final: the farmer reviews every check, corrects what is wrong, and
  confirms. The stored record keeps both the suggestion and the confirmed ratings, and marks corrections
  (`photo_corrected`).
* The farmer may give a **lower** grade than the ratings support, with a reason. They may never give a higher one
  (also a database check).
* **Without AI** (server without a model, PC off in development, allowance used up), grading works fully with the
  checklist.
* The confirmed grade becomes the lot's grade for buyers. Pooling matches it against buyers' minimum grade. Buyers
  see "graded by the farmer after harvest" or "farmer's expectation (not graded yet)". The lot's grade cannot be
  edited to differ from a confirmed grading.
* Once produce from the harvest reaches a collection hub, the grade is locked, and the hub's measured quality check
  decides acceptance.
* These are Harvestique's indicative grades, **not** official AGMARK or BIS grades, and every screen says so.

API: `GET/PUT /crop-cycles/{id}/grading`, `POST /crop-cycles/{id}/grading/photo` (farmer only, own harvests). AI photo
calls (crop health + grading) are limited per person per hour (`AI_PHOTO_CHECKS_PER_HOUR`).
