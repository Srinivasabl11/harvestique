"""The farmer-facing crop-health result (pure, no model call): one clear status instead of five model categories.

The classifier still produces its internal category (healthy / possible disease / stress / possible deficiency /
unknown), which is stored and used by the evaluations. Farmers only see this decision, built from that category, the
signs the AI named, its confidence and the photo checks:

* healthy          the AI judged the photo with medium or high confidence, the photo was usable, and no spots,
                   yellowing, holes, drying or other damage was named. Low confidence is NOT enough for "healthy".
* needs_attention  the AI named at least one visible sign of a possible problem (any confidence; the confidence is
                   shown, and low confidence asks the farmer to check the plant before acting).
* retake_photo     the photo could not be judged (dark, blurred, too far, not a plant, possibly another crop, only a
                   colour change on fruit, or the AI was unsure): no health claim, ask for a clearer photo.
* unavailable      the AI photo check could not run (service offline, too slow, invalid answer) or does not apply
                   to this crop: no health claim, say so plainly.

Next steps are general field practice for the signs seen. They never name a disease, product, chemical or dose; any
spray or fertiliser decision is referred to an agriculture officer.
"""

from __future__ import annotations

from typing import Any, Literal

from app.core.enums import CropHealthClass
from app.domain.crop_health_report import EXTENT_FACTOR, EXTENT_NAME, SIGN_NAME, SIGN_WEIGHT

Status = Literal["healthy", "needs_attention", "retake_photo", "unavailable"]
STATUSES: tuple[Status, ...] = ("healthy", "needs_attention", "retake_photo", "unavailable")
PROBLEMS = (CropHealthClass.POSSIBLE_DISEASE, CropHealthClass.STRESS, CropHealthClass.POSSIBLE_DEFICIENCY)
CONFIDENCES = ("low", "medium", "high")
# photo problems in the order they are reported (the first one present is the reason)
PHOTO_REASONS = (
    "not_a_plant",
    "too_dark",
    "blurry",
    "too_bright",
    "little_plant_visible",
    "not_close_up",
    "poor_photo",
)
AI_ERRORS = ("timeout", "unavailable", "busy", "invalid_response")

# sign families -> the practical checks that fit them
FAMILIES: dict[str, frozenset[str]] = {
    "lesions": frozenset({"spots", "brown_spots", "dark_spots", "sunken_spots", "white_powder", "mould", "rot"}),
    "water": frozenset({"wilting", "dry_edges", "browning", "curling", "cracking"}),
    "yellowing": frozenset({"yellowing"}),
    "pests": frozenset({"holes", "insects_visible"}),
}

TEXT: dict[str, dict[str, str]] = {
    "en": {
        "title_healthy": "Healthy",
        "title_needs_attention": "Needs attention",
        "title_retake_photo": "Clearer photo needed",
        "title_unavailable": "Photo check unavailable",
        "sum_healthy": "No spots, yellowing, holes, drying or other damage is visible in this photo.",
        "sum_needs_attention": "Visible signs that may point to a problem: {signs}.",
        "sum_not_a_plant": "The photo does not seem to show a crop plant, so no health result is given.",
        "sum_too_dark": "The photo is too dark to judge, so no health result is given.",
        "sum_blurry": "The photo is too blurred to judge, so no health result is given.",
        "sum_too_bright": "The photo is over-exposed, so no health result is given.",
        "sum_little_plant_visible": "Too little of the plant is visible to judge, so no health result is given.",
        "sum_not_close_up": "The plant is too far away to see leaf detail, so no health result is given.",
        "sum_poor_photo": "The photo quality (light, focus or angle) is too poor to judge, so no health result is "
        "given.",
        "sum_crop_mismatch": "The photo may not show the crop you chose, so no health result is given.",
        "sum_produce_colour": "Only a colour change on the {part} was seen. That is often normal ripening, which one "
        "photo cannot tell apart from a problem.",
        "sum_low_confidence": "The AI saw no damage but was not sure enough to call the crop healthy.",
        "sum_unclear": "The AI could not judge this photo clearly, so no health result is given.",
        "sum_no_ai": "The AI photo check was not available, so no health result is given. Nothing was decided from "
        "this photo.",
        "sum_timeout": "The AI photo check took too long to answer, so no health result is given.",
        "sum_unavailable": "The AI photo check service could not be reached, so no health result is given.",
        "sum_busy": "The AI photo check is busy right now, so no health result is given.",
        "sum_invalid_response": "The AI gave an answer that could not be checked safely, so it was not used.",
        "sum_specialist": "{crop} is a cultivated fungus, not a green plant; this photo check does not apply to it.",
        "conf": "Confidence: {level}. This is the AI's own rating, lowered by our checks. It is not a measured "
        "accuracy, and the AI can be wrong.",
        "conf_low_problem": "Confidence: low. The AI may be wrong; look at the plant yourself before acting.",
        "low": "low",
        "medium": "medium",
        "high": "high",
        "step_healthy_watch": "Keep checking every few days, and photograph any leaf that changes colour or gets "
        "spots.",
        "step_healthy_more": "One photo shows one plant: check a few plants in different parts of the field too.",
        "step_lesions": "Count how many plants show these signs and whether new leaves are affected. Remove badly "
        "affected leaves or fruit and take them out of the field. If you can, avoid wetting the leaves when watering.",
        "step_water": "Check the soil at root depth (about a finger's length down): water if it is dry, and drain the "
        "field if it is waterlogged. Look at the stem base and roots for rot or damage.",
        "step_yellowing": "Note whether the yellowing is on old (lower) or new (top) leaves, and whether it is even or "
        "patchy. A soil test shows which nutrient, if any, is really short.",
        "step_pests": "Look under the leaves and at the growing tips, early in the morning, for insects, eggs or "
        "caterpillars, and note how many plants have them.",
        "step_officer": "Before buying or spraying any product or extra fertiliser, show the plant or a sample to an "
        "agriculture officer, the Raitha Samparka Kendra or the Krishi Vigyan Kendra. They can confirm the cause and "
        "the right product and dose.",
        "step_follow_up": "Take another photo of the same plant in 3 to 5 days to see whether the signs spread.",
        "step_photo": "Take a sharp close-up of one or two leaves in daylight, so that they fill the photo. Hold the "
        "phone steady and tap the leaf to focus.",
        "step_affected": "If some leaves look unusual, photograph those; otherwise photograph a typical leaf.",
        "step_crop": "Check that the crop you chose is the one in the photo.",
        "step_leaves": "For plant health, photograph the leaves rather than the {part}.",
        "step_retry_later": "Try again in a few minutes. Your photo was not stored.",
        "step_self_check": "Meanwhile, check the plant yourself for spots, yellowing, holes, drying or insects, and "
        "ask an agriculture officer if you see signs spreading.",
        "sum_several_items": "The photo shows several kinds of crop or produce, so no health result is given.",
        "sum_unidentified": "The item in the photo could not be identified with confidence, so no health result is "
        "given.",
        "step_one_item": "Photograph one kind of crop or produce at a time, close up, in daylight.",
        "step_from_crop": "Or start the check from your crop in My Farm, so the crop is already known.",
        "score_meaning": "Health score: how healthy it looks in this photo (100 % = no visible damage). It is not the "
        "AI's confidence and not a diagnosis.",
        "step_specialist": "For contamination, odd colours or smells in the beds, ask your Krishi Vigyan Kendra or a "
        "mushroom-growing specialist.",
    },
    "kn": {
        "title_healthy": "ಆರೋಗ್ಯಕರ",
        "title_needs_attention": "ಗಮನ ಬೇಕು",
        "title_retake_photo": "ಇನ್ನಷ್ಟು ಸ್ಪಷ್ಟ ಫೋಟೋ ಬೇಕು",
        "title_unavailable": "ಫೋಟೋ ಪರಿಶೀಲನೆ ಲಭ್ಯವಿಲ್ಲ",
        "sum_healthy": "ಈ ಫೋಟೋದಲ್ಲಿ ಕಲೆ, ಹಳದಿ, ರಂಧ್ರ, ಒಣಗುವಿಕೆ ಅಥವಾ ಇತರ ಹಾನಿ ಕಾಣುತ್ತಿಲ್ಲ.",
        "sum_needs_attention": "ಸಮಸ್ಯೆಯನ್ನು ಸೂಚಿಸಬಹುದಾದ ಲಕ್ಷಣಗಳು ಕಾಣುತ್ತಿವೆ: {signs}.",
        "sum_not_a_plant": "ಫೋಟೋದಲ್ಲಿ ಬೆಳೆ ಗಿಡ ಕಾಣುತ್ತಿಲ್ಲ; ಆದ್ದರಿಂದ ಆರೋಗ್ಯ ಫಲಿತಾಂಶ ನೀಡಿಲ್ಲ.",
        "sum_too_dark": "ಫೋಟೋ ತುಂಬಾ ಕತ್ತಲಾಗಿದೆ; ಆದ್ದರಿಂದ ಆರೋಗ್ಯ ಫಲಿತಾಂಶ ನೀಡಿಲ್ಲ.",
        "sum_blurry": "ಫೋಟೋ ತುಂಬಾ ಮಸುಕಾಗಿದೆ; ಆದ್ದರಿಂದ ಆರೋಗ್ಯ ಫಲಿತಾಂಶ ನೀಡಿಲ್ಲ.",
        "sum_too_bright": "ಫೋಟೋದಲ್ಲಿ ಬೆಳಕು ಅತಿಯಾಗಿದೆ; ಆದ್ದರಿಂದ ಆರೋಗ್ಯ ಫಲಿತಾಂಶ ನೀಡಿಲ್ಲ.",
        "sum_little_plant_visible": "ಗಿಡದ ಭಾಗ ತುಂಬಾ ಕಡಿಮೆ ಕಾಣುತ್ತಿದೆ; ಆದ್ದರಿಂದ ಆರೋಗ್ಯ ಫಲಿತಾಂಶ ನೀಡಿಲ್ಲ.",
        "sum_not_close_up": "ಗಿಡ ತುಂಬಾ ದೂರದಲ್ಲಿದೆ, ಎಲೆಯ ವಿವರ ಕಾಣುವುದಿಲ್ಲ; ಆದ್ದರಿಂದ ಆರೋಗ್ಯ ಫಲಿತಾಂಶ ನೀಡಿಲ್ಲ.",
        "sum_poor_photo": "ಫೋಟೋದ ಗುಣಮಟ್ಟ (ಬೆಳಕು, ಫೋಕಸ್ ಅಥವಾ ಕೋನ) ಕಡಿಮೆ; ಆದ್ದರಿಂದ ಆರೋಗ್ಯ ಫಲಿತಾಂಶ ನೀಡಿಲ್ಲ.",
        "sum_crop_mismatch": "ಫೋಟೋದಲ್ಲಿ ನೀವು ಆಯ್ಕೆ ಮಾಡಿದ ಬೆಳೆ ಇಲ್ಲದಿರಬಹುದು; ಆದ್ದರಿಂದ ಆರೋಗ್ಯ ಫಲಿತಾಂಶ ನೀಡಿಲ್ಲ.",
        "sum_produce_colour": "{part} ಮೇಲೆ ಬಣ್ಣ ಬದಲಾವಣೆ ಮಾತ್ರ ಕಂಡಿದೆ. ಇದು ಹೆಚ್ಚಾಗಿ ಸಹಜವಾಗಿ ಹಣ್ಣಾಗುವಿಕೆ; ಒಂದು ಫೋಟೋದಿಂದ "
        "ಅದನ್ನು ಸಮಸ್ಯೆಯಿಂದ ಬೇರ್ಪಡಿಸಲು ಆಗುವುದಿಲ್ಲ.",
        "sum_low_confidence": "AI ಗೆ ಹಾನಿ ಕಾಣಲಿಲ್ಲ, ಆದರೆ ಬೆಳೆ ಆರೋಗ್ಯಕರ ಎಂದು ಹೇಳುವಷ್ಟು ಖಚಿತತೆ ಇರಲಿಲ್ಲ.",
        "sum_unclear": "AI ಗೆ ಈ ಫೋಟೋವನ್ನು ಸ್ಪಷ್ಟವಾಗಿ ನಿರ್ಣಯಿಸಲು ಆಗಲಿಲ್ಲ; ಆದ್ದರಿಂದ ಆರೋಗ್ಯ ಫಲಿತಾಂಶ ನೀಡಿಲ್ಲ.",
        "sum_no_ai": "AI ಫೋಟೋ ಪರಿಶೀಲನೆ ಲಭ್ಯವಿರಲಿಲ್ಲ; ಆದ್ದರಿಂದ ಆರೋಗ್ಯ ಫಲಿತಾಂಶ ನೀಡಿಲ್ಲ. ಈ ಫೋಟೋದಿಂದ ಏನನ್ನೂ ನಿರ್ಧರಿಸಿಲ್ಲ.",
        "sum_timeout": "AI ಫೋಟೋ ಪರಿಶೀಲನೆ ಉತ್ತರಿಸಲು ತುಂಬಾ ಸಮಯ ತೆಗೆದುಕೊಂಡಿತು; ಆದ್ದರಿಂದ ಆರೋಗ್ಯ ಫಲಿತಾಂಶ ನೀಡಿಲ್ಲ.",
        "sum_unavailable": "AI ಫೋಟೋ ಪರಿಶೀಲನೆ ಸೇವೆಯನ್ನು ತಲುಪಲು ಆಗಲಿಲ್ಲ; ಆದ್ದರಿಂದ ಆರೋಗ್ಯ ಫಲಿತಾಂಶ ನೀಡಿಲ್ಲ.",
        "sum_busy": "AI ಫೋಟೋ ಪರಿಶೀಲನೆ ಈಗ ಕಾರ್ಯನಿರತವಾಗಿದೆ; ಆದ್ದರಿಂದ ಆರೋಗ್ಯ ಫಲಿತಾಂಶ ನೀಡಿಲ್ಲ.",
        "sum_invalid_response": "AI ನೀಡಿದ ಉತ್ತರವನ್ನು ಸುರಕ್ಷಿತವಾಗಿ ಪರಿಶೀಲಿಸಲು ಆಗಲಿಲ್ಲ; ಆದ್ದರಿಂದ ಅದನ್ನು ಬಳಸಿಲ್ಲ.",
        "sum_specialist": "{crop} ಬೆಳೆಸಿದ ಶಿಲೀಂಧ್ರ, ಹಸಿರು ಗಿಡವಲ್ಲ; ಈ ಫೋಟೋ ಪರಿಶೀಲನೆ ಇದಕ್ಕೆ ಅನ್ವಯಿಸುವುದಿಲ್ಲ.",
        "conf": "ಖಚಿತತೆ: {level}. ಇದು AI ಯ ಸ್ವಂತ ಅಂದಾಜು, ನಮ್ಮ ಪರಿಶೀಲನೆಗಳು ಇದನ್ನು ಕಡಿಮೆ ಮಾಡುತ್ತವೆ. ಇದು ಅಳೆದ ನಿಖರತೆ ಅಲ್ಲ; AI ತಪ್ಪಾಗಬಹುದು.",
        "conf_low_problem": "ಖಚಿತತೆ: ಕಡಿಮೆ. AI ತಪ್ಪಾಗಿರಬಹುದು; ಕ್ರಮ ಕೈಗೊಳ್ಳುವ ಮೊದಲು ಗಿಡವನ್ನು ನೀವೇ ನೋಡಿ.",
        "low": "ಕಡಿಮೆ",
        "medium": "ಮಧ್ಯಮ",
        "high": "ಹೆಚ್ಚು",
        "step_healthy_watch": "ಕೆಲವು ದಿನಗಳಿಗೊಮ್ಮೆ ಪರಿಶೀಲಿಸುತ್ತಿರಿ; ಬಣ್ಣ ಬದಲಾದ ಅಥವಾ ಕಲೆ ಬಂದ ಎಲೆಯ ಫೋಟೋ ತೆಗೆಯಿರಿ.",
        "step_healthy_more": "ಒಂದು ಫೋಟೋ ಒಂದು ಗಿಡವನ್ನು ಮಾತ್ರ ತೋರಿಸುತ್ತದೆ: ಹೊಲದ ಬೇರೆ ಬೇರೆ ಭಾಗಗಳ ಕೆಲವು ಗಿಡಗಳನ್ನೂ ಪರಿಶೀಲಿಸಿ.",
        "step_lesions": "ಎಷ್ಟು ಗಿಡಗಳಲ್ಲಿ ಈ ಲಕ್ಷಣಗಳಿವೆ ಮತ್ತು ಹೊಸ ಎಲೆಗಳಿಗೂ ಹರಡಿದೆಯೇ ಎಂದು ನೋಡಿ. ತೀವ್ರವಾಗಿ ಬಾಧಿತ ಎಲೆ ಅಥವಾ "
        "ಹಣ್ಣುಗಳನ್ನು ತೆಗೆದು ಹೊಲದಿಂದ ಹೊರಗೆ ಹಾಕಿ. ಸಾಧ್ಯವಾದರೆ ನೀರು ಹಾಯಿಸುವಾಗ ಎಲೆಗಳನ್ನು ಒದ್ದೆ ಮಾಡಬೇಡಿ.",
        "step_water": "ಬೇರಿನ ಆಳದಲ್ಲಿ (ಸುಮಾರು ಒಂದು ಬೆರಳಿನಷ್ಟು ಕೆಳಗೆ) ಮಣ್ಣನ್ನು ಪರಿಶೀಲಿಸಿ: ಒಣಗಿದ್ದರೆ ನೀರು ಕೊಡಿ, ನೀರು "
        "ನಿಂತಿದ್ದರೆ ಬಸಿದು ಹೋಗುವಂತೆ ಮಾಡಿ. ಕಾಂಡದ ಬುಡ ಮತ್ತು ಬೇರುಗಳಲ್ಲಿ ಕೊಳೆತ ಅಥವಾ ಹಾನಿ ಇದೆಯೇ ನೋಡಿ.",
        "step_yellowing": "ಹಳದಿಯಾಗುವಿಕೆ ಹಳೆಯ (ಕೆಳಗಿನ) ಎಲೆಗಳಲ್ಲಿದೆಯೇ ಅಥವಾ ಹೊಸ (ಮೇಲಿನ) ಎಲೆಗಳಲ್ಲಿದೆಯೇ, ಸಮವಾಗಿದೆಯೇ ಅಥವಾ "
        "ಮಚ್ಚೆಯಾಗಿದೆಯೇ ಎಂದು ಗಮನಿಸಿ. ಯಾವ ಪೋಷಕಾಂಶ ನಿಜವಾಗಿ ಕಡಿಮೆ ಇದೆ ಎಂದು ಮಣ್ಣು ಪರೀಕ್ಷೆ ತೋರಿಸುತ್ತದೆ.",
        "step_pests": "ಬೆಳಗಿನ ಹೊತ್ತು ಎಲೆಗಳ ಕೆಳಭಾಗ ಮತ್ತು ಬೆಳೆಯುವ ತುದಿಗಳಲ್ಲಿ ಕೀಟಗಳು, ಮೊಟ್ಟೆಗಳು ಅಥವಾ ಹುಳುಗಳಿವೆಯೇ ಎಂದು "
        "ನೋಡಿ; ಎಷ್ಟು ಗಿಡಗಳಲ್ಲಿವೆ ಎಂದು ಗಮನಿಸಿ.",
        "step_officer": "ಯಾವುದೇ ಔಷಧ ಅಥವಾ ಹೆಚ್ಚುವರಿ ಗೊಬ್ಬರ ಖರೀದಿಸುವ ಅಥವಾ ಸಿಂಪಡಿಸುವ ಮೊದಲು ಗಿಡ ಅಥವಾ ಮಾದರಿಯನ್ನು ಕೃಷಿ "
        "ಅಧಿಕಾರಿ, ರೈತ ಸಂಪರ್ಕ ಕೇಂದ್ರ ಅಥವಾ ಕೃಷಿ ವಿಜ್ಞಾನ ಕೇಂದ್ರಕ್ಕೆ ತೋರಿಸಿ. ಅವರು ಕಾರಣ ಮತ್ತು ಸರಿಯಾದ ಔಷಧ, ಪ್ರಮಾಣವನ್ನು "
        "ಖಚಿತಪಡಿಸಬಹುದು.",
        "step_follow_up": "ಲಕ್ಷಣಗಳು ಹರಡುತ್ತಿವೆಯೇ ಎಂದು ನೋಡಲು 3 ರಿಂದ 5 ದಿನಗಳಲ್ಲಿ ಅದೇ ಗಿಡದ ಇನ್ನೊಂದು ಫೋಟೋ ತೆಗೆಯಿರಿ.",
        "step_photo": "ಹಗಲು ಬೆಳಕಿನಲ್ಲಿ ಒಂದು ಅಥವಾ ಎರಡು ಎಲೆಗಳು ಫೋಟೋವನ್ನು ತುಂಬುವಂತೆ ಸ್ಪಷ್ಟ ಹತ್ತಿರದ ಫೋಟೋ ತೆಗೆಯಿರಿ. "
        "ಫೋನ್ ಅಲುಗಾಡದಂತೆ ಹಿಡಿದು, ಎಲೆಯ ಮೇಲೆ ಟ್ಯಾಪ್ ಮಾಡಿ ಫೋಕಸ್ ಮಾಡಿ.",
        "step_affected": "ಕೆಲವು ಎಲೆಗಳು ವಿಚಿತ್ರವಾಗಿ ಕಂಡರೆ ಅವುಗಳ ಫೋಟೋ ತೆಗೆಯಿರಿ; ಇಲ್ಲದಿದ್ದರೆ ಸಾಮಾನ್ಯ ಎಲೆಯ ಫೋಟೋ ತೆಗೆಯಿರಿ.",
        "step_crop": "ನೀವು ಆಯ್ಕೆ ಮಾಡಿದ ಬೆಳೆಯೇ ಫೋಟೋದಲ್ಲಿದೆಯೇ ಎಂದು ಪರಿಶೀಲಿಸಿ.",
        "step_leaves": "ಗಿಡದ ಆರೋಗ್ಯಕ್ಕಾಗಿ {part} ಬದಲು ಎಲೆಗಳ ಫೋಟೋ ತೆಗೆಯಿರಿ.",
        "step_retry_later": "ಕೆಲವು ನಿಮಿಷಗಳ ನಂತರ ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ. ನಿಮ್ಮ ಫೋಟೋವನ್ನು ಉಳಿಸಿಲ್ಲ.",
        "step_self_check": "ಅಲ್ಲಿಯವರೆಗೆ ಗಿಡದಲ್ಲಿ ಕಲೆ, ಹಳದಿ, ರಂಧ್ರ, ಒಣಗುವಿಕೆ ಅಥವಾ ಕೀಟಗಳಿವೆಯೇ ಎಂದು ನೀವೇ ನೋಡಿ; ಲಕ್ಷಣಗಳು "
        "ಹರಡುತ್ತಿದ್ದರೆ ಕೃಷಿ ಅಧಿಕಾರಿಯನ್ನು ಕೇಳಿ.",
        "sum_several_items": "ಫೋಟೋದಲ್ಲಿ ಹಲವು ಬಗೆಯ ಬೆಳೆ ಅಥವಾ ಉತ್ಪನ್ನಗಳಿವೆ; ಆದ್ದರಿಂದ ಆರೋಗ್ಯ ಫಲಿತಾಂಶ ನೀಡಿಲ್ಲ.",
        "sum_unidentified": "ಫೋಟೋದಲ್ಲಿರುವ ಬೆಳೆಯನ್ನು ಖಚಿತವಾಗಿ ಗುರುತಿಸಲು ಆಗಲಿಲ್ಲ; ಆದ್ದರಿಂದ ಆರೋಗ್ಯ ಫಲಿತಾಂಶ ನೀಡಿಲ್ಲ.",
        "step_one_item": "ಒಂದು ಬಾರಿಗೆ ಒಂದೇ ಬಗೆಯ ಬೆಳೆ ಅಥವಾ ಉತ್ಪನ್ನದ ಹತ್ತಿರದ ಫೋಟೋವನ್ನು ಹಗಲು ಬೆಳಕಿನಲ್ಲಿ ತೆಗೆಯಿರಿ.",
        "step_from_crop": "ಅಥವಾ 'ನನ್ನ ಹೊಲ'ದಲ್ಲಿರುವ ನಿಮ್ಮ ಬೆಳೆಯಿಂದ ಪರಿಶೀಲನೆ ಆರಂಭಿಸಿ; ಆಗ ಬೆಳೆ ಮೊದಲೇ ತಿಳಿದಿರುತ್ತದೆ.",
        "score_meaning": "ಆರೋಗ್ಯ ಅಂಕ: ಈ ಫೋಟೋದಲ್ಲಿ ಎಷ್ಟು ಆರೋಗ್ಯಕರವಾಗಿ ಕಾಣುತ್ತದೆ (100 % = ಕಾಣುವ ಹಾನಿ ಇಲ್ಲ). ಇದು AI ಯ ಖಚಿತತೆ "
        "ಅಲ್ಲ, ರೋಗನಿರ್ಣಯವೂ ಅಲ್ಲ.",
        "step_specialist": "ಹಾಸಿಗೆಯಲ್ಲಿ ಕಲುಷಿತತೆ, ವಿಚಿತ್ರ ಬಣ್ಣ ಅಥವಾ ವಾಸನೆ ಕಂಡರೆ ಕೃಷಿ ವಿಜ್ಞಾನ ಕೇಂದ್ರ ಅಥವಾ ಅಣಬೆ ಬೆಳೆ ತಜ್ಞರನ್ನು ಸಂಪರ್ಕಿಸಿ.",
    },
}


def _lang(language: str) -> str:
    return language if language in TEXT else "en"


def status_and_reason(label: CropHealthClass, features: dict[str, Any], flags: list[str]) -> tuple[Status, str]:
    """The decision rules from the module docstring, in order. Also works for results stored before this module."""
    f, fl = features, set(flags)
    if "specialist_needed" in fl or f.get("assessment") == "specialist_needed":
        return "unavailable", "specialist"
    if f.get("mode") == "measurements_only" or f.get("ai_unavailable"):
        error = f.get("ai_error")
        return "unavailable", error if error in AI_ERRORS else "no_ai"
    if "several_items" in fl:  # which item would the result be about?
        return "retake_photo", "several_items"
    if f.get("identification") == "none":  # no crop chosen and the photo's item is not one we can name
        return "retake_photo", "unidentified"
    signs = [s for s in f.get("symptoms") or [] if s in SIGN_WEIGHT]
    if label in PROBLEMS and signs:
        return "needs_attention", "visible_signs"
    photo = next((r for r in PHOTO_REASONS if r in fl), None)
    if photo is not None or "precheck" in f:
        return "retake_photo", photo or str(f.get("precheck"))
    if "crop_mismatch" in fl:
        return "retake_photo", "crop_mismatch"
    if f.get("produce_colour_only"):
        return "retake_photo", "produce_colour"
    if label in PROBLEMS:  # a problem category with no sign named: nothing to show the farmer, so no claim
        return "retake_photo", "unclear"
    if label is CropHealthClass.HEALTHY and not signs:
        if f.get("ai_confidence") in ("medium", "high"):
            return "healthy", "no_visible_signs"
        return "retake_photo", "low_confidence"
    return "retake_photo", "unclear"


def _signs_text(features: dict[str, Any], lang: str) -> list[str]:
    detail = {o.get("sign"): o for o in features.get("observations") or [] if isinstance(o, dict)}
    out = []
    for s in features.get("symptoms") or []:
        if s not in SIGN_WEIGHT:
            continue
        extent = (detail.get(s) or {}).get("extent")
        name = SIGN_NAME[lang][s]
        out.append(f"{name} ({EXTENT_NAME[lang][extent]})" if extent in EXTENT_FACTOR else name)
    return out


def decide(
    label: CropHealthClass,
    features: dict[str, Any],
    flags: list[str],
    language: str,
    *,
    part_name: str = "",
    crop_name: str = "",
) -> dict[str, Any]:
    """The farmer-facing decision: status, title, one-sentence summary, confidence, visible signs and next steps."""
    lang = _lang(language)
    t = TEXT[lang]
    status, reason = status_and_reason(label, features, flags)
    signs = _signs_text(features, lang) if status == "needs_attention" else []
    confidence = features.get("ai_confidence") if status in ("healthy", "needs_attention") else None
    if confidence not in CONFIDENCES:
        confidence = None if status not in ("healthy", "needs_attention") else "low"

    if status == "healthy":
        summary = t["sum_healthy"]
    elif status == "needs_attention":
        summary = t["sum_needs_attention"].format(signs=", ".join(signs))
    else:
        summary = t[f"sum_{reason}"].format(part=part_name or "fruit", crop=crop_name or "This crop")

    if confidence is None:
        confidence_text = None
    elif status == "needs_attention" and confidence == "low":
        confidence_text = t["conf_low_problem"]
    else:
        confidence_text = t["conf"].format(level=t[confidence])

    steps: list[str] = []
    if status == "healthy":
        steps = [t["step_healthy_watch"], t["step_healthy_more"]]
    elif status == "needs_attention":
        seen = set(features.get("symptoms") or [])
        steps = [t[f"step_{family}"] for family, members in FAMILIES.items() if members & seen]
        steps += [t["step_officer"], t["step_follow_up"]]
    elif status == "retake_photo":
        if reason == "crop_mismatch":
            steps.append(t["step_crop"])
        if reason == "produce_colour":
            steps.append(t["step_leaves"].format(part=part_name or "fruit"))
        if reason in ("several_items", "unidentified"):
            steps += [t["step_one_item"], t["step_from_crop"]]
        else:
            steps += [t["step_photo"], t["step_affected"]]
    elif reason == "specialist":
        steps = [t["step_specialist"]]
    else:
        steps = [t["step_retry_later"], t["step_self_check"]]

    # health score and A/B/C category: only when the photo gave a health result (never for a retake or no AI)
    from app.domain.agri_taxonomy import CATEGORY_TEXT, health_category
    from app.domain.crop_health_report import health_percent

    score = health_percent(features) if status in ("healthy", "needs_attention") else None
    category = health_category(score)
    return {
        "status": status,
        "reason": reason,
        "title": t[f"title_{status}"],
        "summary": summary,
        "item": item_of(features, lang, crop_name),
        "health_score": score,
        "health_category": category,
        "category_text": CATEGORY_TEXT[lang][category],
        "score_meaning": t["score_meaning"],
        "confidence": confidence,
        "confidence_label": t[confidence] if confidence else None,  # one word, in the request's language
        "confidence_text": confidence_text,
        "signs": signs,
        "next_steps": steps,
        "is_diagnosis": False,
    }


def item_of(features: dict[str, Any], lang: str, crop_name: str = "") -> dict[str, Any] | None:
    """The identified item with its parent category (stored by the service as features["identified"]), else the
    farmer's chosen crop for results stored before identification existed. None when nothing is known."""
    from app.domain.agri_taxonomy import parent_name, parent_of

    found = features.get("identified")
    if isinstance(found, dict) and found.get("name"):
        parent = parent_of(found.get("group"))
        local = found.get("local_name") or None
        return {
            "name": found["name"],
            "local_name": local,
            "display_name": local if lang == "kn" and local else found["name"],
            "parent": parent,
            "parent_name": parent_name(parent, lang),
            "source": found.get("source"),  # your_crop (chosen by the farmer) or photo (the AI's guess, matched)
        }
    name = crop_name or features.get("expected_crop")
    if name:
        return {
            "name": name,
            "local_name": None,
            "display_name": name,
            "parent": None,
            "parent_name": None,
            "source": "your_crop",
        }
    return None
