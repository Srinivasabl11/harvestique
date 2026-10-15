"""Per-crop validation status of the crop-health check: what has actually been MEASURED for each catalogue crop.

Coverage is not accuracy: every catalogue crop can be photographed and assessed, but a crop counts as reliably
assessed only with enough labelled, representative photos (MIN_PER_CLASS healthy and problem photos from the field)
and both recalls at least MIN_RECALL. No crop meets that today. Numbers below come from the evaluation result files
(harvestique-eval-data/results) and the reports in docs/; nothing here is estimated.
"""

from __future__ import annotations

from dataclasses import dataclass

MIN_PER_CLASS = 30
MIN_RECALL = 0.8


@dataclass(frozen=True, slots=True)
class HealthEvidence:
    dataset: str
    field_photos: bool  # photos from farms (True) or web/lab collections (False)
    healthy_n: int
    healthy_correct: int
    problem_n: int
    problem_flagged: int
    report: str


@dataclass(frozen=True, slots=True)
class IdentificationEvidence:
    dataset: str
    n: int
    crop_correct: int
    part_correct: int
    report: str


PLANTDOC = "PlantDoc test split, 108-photo stratified sample (web photos, CC BY 4.0)"
PLANTDOC_REPORT = "docs/CROP_HEALTH_EVAL_2026-10-14.md"
KOPPAL = "Koppal groundnut field photos, Mendeley 10.17632/22p2vcbxfk.3 (pathologist-assisted labels)"
KOPPAL_REPORT = "docs/KOPPAL_GROUNDNUT_EVAL_2026-10-14.md"

# healthy vs problem evaluations already run with gemma3:4b (catalogue crop name -> evidence)
HEALTH: dict[str, tuple[HealthEvidence, ...]] = {
    "Apple": (HealthEvidence(PLANTDOC, False, 4, 3, 8, 8, PLANTDOC_REPORT),),
    "Capsicum": (HealthEvidence(PLANTDOC, False, 4, 1, 4, 4, PLANTDOC_REPORT),),  # PlantDoc "Bell_pepper"
    "Blueberry": (HealthEvidence(PLANTDOC, False, 4, 2, 0, 0, PLANTDOC_REPORT),),
    "Cherry": (HealthEvidence(PLANTDOC, False, 4, 3, 0, 0, PLANTDOC_REPORT),),
    "Maize": (HealthEvidence(PLANTDOC, False, 0, 0, 12, 12, PLANTDOC_REPORT),),  # PlantDoc "Corn"
    "Peach": (HealthEvidence(PLANTDOC, False, 4, 3, 0, 0, PLANTDOC_REPORT),),
    "Potato": (HealthEvidence(PLANTDOC, False, 0, 0, 8, 8, PLANTDOC_REPORT),),
    "Raspberry": (HealthEvidence(PLANTDOC, False, 4, 2, 0, 0, PLANTDOC_REPORT),),
    "Soybean": (HealthEvidence(PLANTDOC, False, 4, 2, 0, 0, PLANTDOC_REPORT),),
    "Strawberry": (HealthEvidence(PLANTDOC, False, 4, 3, 0, 0, PLANTDOC_REPORT),),
    "Tomato": (HealthEvidence(PLANTDOC, False, 4, 1, 28, 27, PLANTDOC_REPORT),),
    "Grapes": (HealthEvidence(PLANTDOC, False, 4, 3, 4, 4, PLANTDOC_REPORT),),
    "Groundnut": (HealthEvidence(KOPPAL, True, 10, 0, 10, 10, KOPPAL_REPORT),),
}
# crop identification and plant-part tests, blind (the model was not told the crop), gemma3:4b, 2026-10-15:
# results/crop_id_gemma3_4b.partial.jsonl scored by matching the model's guess to the catalogue name, aliases and
# genus. Every test photo showed LEAVES, so plant-part identification is tested for leaves only.
CROP_ID = "Blind identification: 39 PlantDoc + 20 Koppal leaf photos (already labelled)"
CROP_ID_REPORT = "docs/CROP_CATALOGUE_AND_HEALTH_2026-10-15.md"
IDENTIFICATION: dict[str, tuple[IdentificationEvidence, ...]] = {
    "Apple": (IdentificationEvidence(CROP_ID, 3, 0, 3, CROP_ID_REPORT),),
    "Blueberry": (IdentificationEvidence(CROP_ID, 3, 0, 3, CROP_ID_REPORT),),
    "Capsicum": (IdentificationEvidence(CROP_ID, 3, 0, 3, CROP_ID_REPORT),),
    "Cherry": (IdentificationEvidence(CROP_ID, 3, 0, 3, CROP_ID_REPORT),),
    "Grapes": (IdentificationEvidence(CROP_ID, 3, 1, 3, CROP_ID_REPORT),),
    "Groundnut": (IdentificationEvidence(CROP_ID, 20, 6, 20, CROP_ID_REPORT),),
    "Maize": (IdentificationEvidence(CROP_ID, 3, 2, 3, CROP_ID_REPORT),),
    "Peach": (IdentificationEvidence(CROP_ID, 3, 0, 3, CROP_ID_REPORT),),
    "Potato": (IdentificationEvidence(CROP_ID, 3, 0, 3, CROP_ID_REPORT),),
    "Raspberry": (IdentificationEvidence(CROP_ID, 3, 0, 3, CROP_ID_REPORT),),
    "Soybean": (IdentificationEvidence(CROP_ID, 3, 0, 3, CROP_ID_REPORT),),
    "Strawberry": (IdentificationEvidence(CROP_ID, 3, 3, 3, CROP_ID_REPORT),),
    "Tomato": (IdentificationEvidence(CROP_ID, 3, 3, 3, CROP_ID_REPORT),),
}


def validation_for(crop_name: str) -> dict[str, object]:
    """The validation status of one crop, for the API and the app (no evidence = 'insufficient evidence')."""
    health = HEALTH.get(crop_name, ())
    ident = IDENTIFICATION.get(crop_name, ())
    healthy_n = sum(e.healthy_n for e in health)
    problem_n = sum(e.problem_n for e in health)
    healthy_recall = sum(e.healthy_correct for e in health) / healthy_n if healthy_n else None
    problem_recall = sum(e.problem_flagged for e in health) / problem_n if problem_n else None
    field_n = (
        min(sum(e.healthy_n for e in health if e.field_photos), sum(e.problem_n for e in health if e.field_photos))
        if health
        else 0
    )
    if (
        field_n >= MIN_PER_CLASS
        and healthy_recall is not None
        and problem_recall is not None
        and min(healthy_recall, problem_recall) >= MIN_RECALL
    ):
        verdict = "reliable"
    elif healthy_n >= 10 and healthy_recall is not None and healthy_recall < 0.5:
        verdict = "not_reliable"  # e.g. healthy leaves mostly called diseased
    else:
        verdict = "insufficient_evidence"
    return {
        "catalogue_entry": True,
        "crop_identification_tested": any(e.n for e in ident),
        "plant_part_identification_tested": any(e.n for e in ident),
        "health_dataset_available": bool(health),
        "health_evaluation_completed": bool(health),
        "verdict": verdict,
        "healthy_photos": healthy_n,
        "problem_photos": problem_n,
        "healthy_recall": round(healthy_recall, 2) if healthy_recall is not None else None,
        "problem_recall": round(problem_recall, 2) if problem_recall is not None else None,
        "identification": [
            {"dataset": e.dataset, "photos": e.n, "crop_correct": e.crop_correct, "part_correct": e.part_correct}
            for e in ident
        ],
        "sources": sorted({e.report for e in health} | {e.report for e in ident}),
    }
