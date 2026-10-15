"""Structured, evidence-based crop-photo report built from a classifier result (pure, no model call).

Order of reasoning, each step only from what the previous ones allow:
1. photo suitability and subject;  2. crop and plant part (the AI's guess, unverified);  3. visible observations;
4. possible explanations of those observations (cause families, never a named disease or a treatment);
5. visual condition score;  6. limitations and the next thing to look at.

VISUAL CONDITION SCORE (0-10, only with enough evidence). Starts at 10; each visible sign subtracts its weight (how
much damage the sign itself represents) times an extent factor (one or a few x1, several x1.5, many x2; x1 when the
model did not say). When the model said little of the tissue looks normal the score is capped (some: 6, little: 3).
Minimum 1. Bands: 10 no visible damage, 8-9 minor, 5-7 moderate, 1-4 severe. It rates what is VISIBLE in this photo.
It is not the probability of a disease and not the AI's confidence (reported separately as low / medium / high). The
weights are a documented rubric, not fitted to data, and have not been validated against expert severity ratings.
It is withheld (None, with the reason) when the photo is unusable or doubtful, shows no plant, the AI gave no clear
answer, the photo may not show the chosen crop, no AI model was used, or the crop is not assessed from photos.
"""

from __future__ import annotations

from typing import Any

from app.core.enums import CropHealthClass
from app.domain.crop_profiles import is_crop_guess
from app.domain.vision import HealthAssessment

REPORT_VERSION = 2  # 2: farmer-facing decision (domain.crop_health_decision); no category-bar text
SIGN_WEIGHT: dict[str, float] = {
    "spots": 1.0,  # unspecified spots or markings: the weakest sign (often veins, glare or dust on healthy leaves)
    "yellowing": 1.5,
    "brown_spots": 2.0,
    "dark_spots": 2.0,
    "browning": 2.0,
    "dry_edges": 2.0,
    "curling": 2.0,
    "holes": 2.0,
    "insects_visible": 2.0,
    "cracking": 2.0,
    "sunken_spots": 3.0,
    "white_powder": 3.0,
    "wilting": 3.0,
    "mould": 4.0,
    "rot": 4.0,
}
EXTENT_FACTOR = {"one_or_few": 1.0, "several": 1.5, "many": 2.0}
TISSUE_CAP = {"some": 6, "little": 3}
COLOURS = ("light_or_white", "yellow", "brown", "dark_or_black")
PRODUCE_PARTS = frozenset({"fruit", "tuber", "root", "bulb", "rhizome", "corm", "grain", "pod", "seed", "flower"})
PHOTO_FLAGS = ("not_a_plant", "too_dark", "blurry", "poor_photo", "not_close_up")
PROBLEMS = (CropHealthClass.POSSIBLE_DISEASE, CropHealthClass.STRESS, CropHealthClass.POSSIBLE_DEFICIENCY)
# measured blind crop naming on leaf photos, 2026-10-15 (docs/CROP_CATALOGUE_AND_HEALTH_2026-10-15.md): 15 of 56
CROP_ID_MEASURED = {"en": "about 1 in 4", "kn": "ಸುಮಾರು 4 ರಲ್ಲಿ 1"}

PART_NAME = {
    "en": {
        "leaf": "leaves",
        "fruit": "fruit",
        "grain": "grain or ear",
        "pod": "pods",
        "seed": "seeds",
        "root": "root",
        "tuber": "tuber",
        "bulb": "bulb",
        "rhizome": "rhizome",
        "corm": "corm",
        "flower": "flowers",
        "stem": "stem",
        "whole_plant": "whole plant",
        "unknown": "not clear",
    },
    "kn": {
        "leaf": "ಎಲೆಗಳು",
        "fruit": "ಹಣ್ಣು/ಕಾಯಿ",
        "grain": "ಕಾಳು ಅಥವಾ ತೆನೆ",
        "pod": "ಕಾಯಿಗಳು",
        "seed": "ಬೀಜಗಳು",
        "root": "ಬೇರು",
        "tuber": "ಗೆಡ್ಡೆ",
        "bulb": "ಗಡ್ಡೆ (ಈರುಳ್ಳಿಯಂತೆ)",
        "rhizome": "ಗೆಡ್ಡೆಕಾಂಡ (ಶುಂಠಿ/ಅರಿಶಿನದಂತೆ)",
        "corm": "ಗೆಡ್ಡೆ",
        "flower": "ಹೂವುಗಳು",
        "stem": "ಕಾಂಡ",
        "whole_plant": "ಇಡೀ ಗಿಡ",
        "unknown": "ಸ್ಪಷ್ಟವಿಲ್ಲ",
    },
}
SIGN_NAME = {
    "en": {
        "spots": "Spots or markings",
        "yellowing": "Yellowing",
        "brown_spots": "Brown spots",
        "dark_spots": "Dark spots",
        "browning": "Browning",
        "dry_edges": "Dry edges",
        "curling": "Curling or distortion",
        "holes": "Holes",
        "insects_visible": "Insects visible",
        "cracking": "Cracking",
        "sunken_spots": "Sunken or water-soaked spots",
        "white_powder": "White powdery coating",
        "wilting": "Wilting",
        "mould": "Mould or fuzzy growth",
        "rot": "Rot",
    },
    "kn": {
        "spots": "ಕಲೆಗಳು ಅಥವಾ ಗುರುತುಗಳು",
        "yellowing": "ಹಳದಿಯಾಗುವಿಕೆ",
        "brown_spots": "ಕಂದು ಕಲೆಗಳು",
        "dark_spots": "ಕಪ್ಪು ಕಲೆಗಳು",
        "browning": "ಕಂದುಬಣ್ಣಕ್ಕೆ ತಿರುಗುವಿಕೆ",
        "dry_edges": "ಒಣಗಿದ ಅಂಚುಗಳು",
        "curling": "ಸುರುಳಿ ಅಥವಾ ವಿಕಾರ",
        "holes": "ರಂಧ್ರಗಳು",
        "insects_visible": "ಕೀಟಗಳು ಕಾಣುತ್ತಿವೆ",
        "cracking": "ಬಿರುಕು",
        "sunken_spots": "ಕುಸಿದ ಅಥವಾ ನೀರು ತುಂಬಿದಂತಹ ಕಲೆಗಳು",
        "white_powder": "ಬಿಳಿ ಪುಡಿಯಂತಹ ಲೇಪನ",
        "wilting": "ಬಾಡುವಿಕೆ",
        "mould": "ಬೂಸ್ಟ್ (ಹತ್ತಿಯಂತಹ ಬೆಳವಣಿಗೆ)",
        "rot": "ಕೊಳೆತ",
    },
}
COLOUR_NAME = {
    "en": {"light_or_white": "light or white", "yellow": "yellow", "brown": "brown", "dark_or_black": "dark or black"},
    "kn": {"light_or_white": "ತಿಳಿ ಅಥವಾ ಬಿಳಿ", "yellow": "ಹಳದಿ", "brown": "ಕಂದು", "dark_or_black": "ಕಪ್ಪು"},
}
EXTENT_NAME = {
    "en": {"one_or_few": "one or a few", "several": "several", "many": "many or widespread"},
    "kn": {"one_or_few": "ಒಂದೆರಡು", "several": "ಹಲವು", "many": "ಬಹಳಷ್ಟು (ವ್ಯಾಪಕ)"},
}
CONFIDENCE_NAME = {
    "en": {"low": "low", "medium": "medium", "high": "high"},
    "kn": {"low": "ಕಡಿಮೆ", "medium": "ಮಧ್ಯಮ", "high": "ಹೆಚ್ಚು"},
}
# cause FAMILIES that can produce a sign: general agronomy, no disease names, no products or doses
EXPLAIN: dict[str, tuple[frozenset[str], str, str]] = {
    "lesions": (
        frozenset({"spots", "brown_spots", "dark_spots", "sunken_spots"}),
        "Spots or lesions are often caused by a fungal or bacterial infection; insect feeding, sun scorch or spray "
        "injury can look similar.",
        "ಕಲೆಗಳು ಹೆಚ್ಚಾಗಿ ಶಿಲೀಂಧ್ರ ಅಥವಾ ಬ್ಯಾಕ್ಟೀರಿಯಾ ಸೋಂಕಿನಿಂದ ಬರುತ್ತವೆ; ಕೀಟಗಳ ಹಾನಿ, ಬಿಸಿಲಿನ ಸುಡುವಿಕೆ ಅಥವಾ ಸಿಂಪಡಣೆಯ ಹಾನಿಯೂ ಹೀಗೆಯೇ ಕಾಣಬಹುದು.",
    ),
    "powder": (
        frozenset({"white_powder"}),
        "A white powdery coating is often a fungal growth; dust or spray residue can look similar.",
        "ಬಿಳಿ ಪುಡಿಯಂತಹ ಲೇಪನ ಹೆಚ್ಚಾಗಿ ಶಿಲೀಂಧ್ರದ ಬೆಳವಣಿಗೆ; ಧೂಳು ಅಥವಾ ಸಿಂಪಡಣೆಯ ಉಳಿಕೆಯೂ ಹೀಗೆಯೇ ಕಾಣಬಹುದು.",
    ),
    "rot": (
        frozenset({"mould", "rot"}),
        "Mould or rot usually means a fungal or bacterial infection, often helped by damp conditions or a wound.",
        "ಬೂಸ್ಟ್ ಅಥವಾ ಕೊಳೆತ ಸಾಮಾನ್ಯವಾಗಿ ಶಿಲೀಂಧ್ರ ಅಥವಾ ಬ್ಯಾಕ್ಟೀರಿಯಾ ಸೋಂಕನ್ನು ಸೂಚಿಸುತ್ತದೆ; ತೇವಾಂಶ ಅಥವಾ ಗಾಯ ಇದಕ್ಕೆ ನೆರವಾಗಬಹುದು.",
    ),
    "yellowing": (
        frozenset({"yellowing"}),
        "Yellowing can come from a nutrient shortage, too much or too little water, natural ageing of older leaves, "
        "or a virus (often as a mottled pattern).",
        "ಹಳದಿಯಾಗುವಿಕೆ ಪೋಷಕಾಂಶ ಕೊರತೆ, ಹೆಚ್ಚು ಅಥವಾ ಕಡಿಮೆ ನೀರು, ಹಳೆಯ ಎಲೆಗಳ ಸಹಜ ಮುಪ್ಪು, ಅಥವಾ ವೈರಸ್‌ನಿಂದ (ಹೆಚ್ಚಾಗಿ ಮಚ್ಚೆ ಮಚ್ಚೆಯಾಗಿ) ಬರಬಹುದು.",
    ),
    "wilting": (
        frozenset({"wilting"}),
        "Wilting can come from lack of water, heat, root damage or a wilt infection.",
        "ಬಾಡುವಿಕೆ ನೀರಿನ ಕೊರತೆ, ಬಿಸಿಲು, ಬೇರಿನ ಹಾನಿ ಅಥವಾ ಸೊರಗು ರೋಗದಿಂದ ಬರಬಹುದು.",
    ),
    "drying": (
        frozenset({"dry_edges", "browning"}),
        "Dry or brown edges often come from heat or water stress, wind, or salt or fertiliser burn.",
        "ಒಣಗಿದ ಅಥವಾ ಕಂದು ಅಂಚುಗಳು ಹೆಚ್ಚಾಗಿ ಬಿಸಿಲು ಅಥವಾ ನೀರಿನ ಒತ್ತಡ, ಗಾಳಿ, ಅಥವಾ ಉಪ್ಪು/ಗೊಬ್ಬರದ ಸುಡುವಿಕೆಯಿಂದ ಬರುತ್ತವೆ.",
    ),
    "curling": (
        frozenset({"curling"}),
        "Curling or distortion can come from heat or water stress, sap-sucking insects or a virus.",
        "ಸುರುಳಿ ಅಥವಾ ವಿಕಾರ ಬಿಸಿಲು/ನೀರಿನ ಒತ್ತಡ, ರಸ ಹೀರುವ ಕೀಟಗಳು ಅಥವಾ ವೈರಸ್‌ನಿಂದ ಬರಬಹುದು.",
    ),
    "holes": (
        frozenset({"holes"}),
        "Holes usually come from insects, caterpillars, snails or other pests feeding.",
        "ರಂಧ್ರಗಳು ಸಾಮಾನ್ಯವಾಗಿ ಕೀಟಗಳು, ಹುಳುಗಳು, ಬಸವನಹುಳು ಅಥವಾ ಇತರ ಪೀಡೆಗಳು ತಿನ್ನುವುದರಿಂದ ಆಗುತ್ತವೆ.",
    ),
    "insects": (
        frozenset({"insects_visible"}),
        "Insects are visible. Many insects are harmless, so check whether they are feeding on the plant.",
        "ಕೀಟಗಳು ಕಾಣುತ್ತಿವೆ. ಎಲ್ಲಾ ಕೀಟಗಳೂ ಹಾನಿಕಾರಕವಲ್ಲ; ಅವು ಗಿಡವನ್ನು ತಿನ್ನುತ್ತಿವೆಯೇ ಎಂದು ಪರಿಶೀಲಿಸಿ.",
    ),
    "cracking": (
        frozenset({"cracking"}),
        "Cracking often follows uneven watering or fast growth after rain, and can let rot in.",
        "ಬಿರುಕು ಹೆಚ್ಚಾಗಿ ಅಸಮ ನೀರಾವರಿ ಅಥವಾ ಮಳೆಯ ನಂತರದ ವೇಗದ ಬೆಳವಣಿಗೆಯಿಂದ ಆಗುತ್ತದೆ; ಇದರಿಂದ ಕೊಳೆತ ಬರಬಹುದು.",
    ),
}

T: dict[str, dict[str, str]] = {
    "en": {
        "photo": "Photo check",
        "identity": "Crop and plant part (AI guess, not verified)",
        "observations": "What is visible",
        "explanations": "Possible explanations (not a diagnosis)",
        "limitations": "Limits of this check",
        "next": "What to do next",
        "usable": "The photo shows a plant close up and is clear enough to look at.",
        "not_a_plant": "The photo does not seem to show a crop plant.",
        "too_dark": "The photo is too dark to judge.",
        "blurry": "The photo is too blurred to judge.",
        "poor_photo": "The AI found the photo quality poor (light, focus or angle).",
        "not_close_up": "The plant is too far away to see leaf detail.",
        "part_not_leaves": "The photo mainly shows the {part}, not the leaves; only the {part} was judged.",
        "no_ai": "No AI model was used for this photo: only colours were measured.",
        "specialist": "This crop is not judged from photos.",
        "chosen": "Your crop: {crop}.",
        "seen": "The AI thinks this may be: {seen}. This is a guess (in our tests it named the crop correctly in "
        "{rate} leaf photos).",
        "not_seen": "The AI could not tell which crop this is.",
        "match": "That fits the crop you chose.",
        "mismatch": "That does not match the crop you chose: check the crop or the photo.",
        "part": "Plant part in the photo: {part}.",
        "none_seen": "No spots, yellowing, holes, drying or other damage was reported in this photo.",
        "nothing_read": "No clear sign could be read from this photo.",
        "no_explanation": "No sign that needs explaining was seen.",
        "produce_colour": "Colour change on {part} is often normal ripening or the variety's own colour, which one "
        "photo cannot tell apart from a problem.",
        "limit_photo": "Only what is visible in this one photo was checked, not the underside of the leaves, the "
        "roots, the stems or the rest of the field.",
        "limit_healthy": "No visible sign does not prove the plant is healthy: early infections, root problems and "
        "some pests do not show yet.",
        "limit_problem": "In our tests this AI often reported problems on healthy leaves, so look at the plant "
        "in the field before acting on a 'Needs attention' result.",
        "limit_crop": "The photo check for {crop} has not been validated on labelled photos.",
        "limit_crop_not_reliable": "For {crop}, this check was measured as NOT reliable: in our tests it called most "
        "healthy leaves diseased.",
        "next_leaves": "For leaf health, take a close photo of the leaves.",
        "score_method": "Visual condition score: starts at 10 and loses points for each visible sign, more for "
        "serious or widespread signs. It rates only what this photo shows. It is not the chance of a disease and not "
        "how sure the AI is.",
        "band_none_visible": "No visible damage in this photo",
        "band_minor": "Minor visible signs",
        "band_moderate": "Moderate visible damage",
        "band_severe": "Severe visible damage",
        "withheld_not_a_plant": "No score: the photo does not show a crop plant.",
        "withheld_photo": "No score: the photo is not clear or close enough to rate the plant. Retake it.",
        "withheld_unclear": "No score: the AI could not judge this photo clearly.",
        "withheld_produce_colour": "No score: a colour change alone on the {part} cannot be rated.",
        "withheld_crop_mismatch": "No score: the photo may not show the crop you chose.",
        "withheld_no_ai": "No score: no AI model was used, and colours alone cannot rate a plant's condition.",
        "withheld_specialist": "No score: this crop is not rated from photos.",
    },
    "kn": {
        "photo": "ಫೋಟೋ ಪರಿಶೀಲನೆ",
        "identity": "ಬೆಳೆ ಮತ್ತು ಗಿಡದ ಭಾಗ (AI ಊಹೆ, ಖಚಿತವಲ್ಲ)",
        "observations": "ಕಾಣುತ್ತಿರುವುದು",
        "explanations": "ಸಂಭವನೀಯ ಕಾರಣಗಳು (ರೋಗನಿರ್ಣಯವಲ್ಲ)",
        "limitations": "ಈ ಪರಿಶೀಲನೆಯ ಮಿತಿಗಳು",
        "next": "ಮುಂದೆ ಏನು ಮಾಡಬೇಕು",
        "usable": "ಫೋಟೋದಲ್ಲಿ ಗಿಡ ಹತ್ತಿರದಿಂದ ಕಾಣುತ್ತಿದೆ ಮತ್ತು ನೋಡಲು ಸಾಕಷ್ಟು ಸ್ಪಷ್ಟವಾಗಿದೆ.",
        "not_a_plant": "ಫೋಟೋದಲ್ಲಿ ಬೆಳೆ ಗಿಡ ಕಾಣುತ್ತಿಲ್ಲ.",
        "too_dark": "ಫೋಟೋ ತುಂಬಾ ಕತ್ತಲಾಗಿದೆ; ನಿರ್ಣಯಿಸಲು ಆಗುವುದಿಲ್ಲ.",
        "blurry": "ಫೋಟೋ ತುಂಬಾ ಮಸುಕಾಗಿದೆ; ನಿರ್ಣಯಿಸಲು ಆಗುವುದಿಲ್ಲ.",
        "poor_photo": "AI ಪ್ರಕಾರ ಫೋಟೋದ ಗುಣಮಟ್ಟ ಕಡಿಮೆ (ಬೆಳಕು, ಫೋಕಸ್ ಅಥವಾ ಕೋನ).",
        "not_close_up": "ಗಿಡ ತುಂಬಾ ದೂರದಲ್ಲಿದೆ; ಎಲೆಯ ವಿವರ ಕಾಣುವುದಿಲ್ಲ.",
        "part_not_leaves": "ಫೋಟೋದಲ್ಲಿ ಹೆಚ್ಚಾಗಿ {part} ಕಾಣುತ್ತಿದೆ, ಎಲೆಗಳಲ್ಲ; {part} ಅನ್ನು ಮಾತ್ರ ಪರಿಶೀಲಿಸಲಾಗಿದೆ.",
        "no_ai": "ಈ ಫೋಟೋಗೆ AI ಮಾದರಿ ಬಳಸಿಲ್ಲ: ಬಣ್ಣಗಳನ್ನು ಮಾತ್ರ ಅಳೆಯಲಾಗಿದೆ.",
        "specialist": "ಈ ಬೆಳೆಯನ್ನು ಫೋಟೋದಿಂದ ಪರಿಶೀಲಿಸುವುದಿಲ್ಲ.",
        "chosen": "ನಿಮ್ಮ ಬೆಳೆ: {crop}.",
        "seen": "AI ಪ್ರಕಾರ ಇದು ಹೀಗಿರಬಹುದು: {seen}. ಇದು ಊಹೆ ಮಾತ್ರ (ನಮ್ಮ ಪರೀಕ್ಷೆಯಲ್ಲಿ {rate} ಎಲೆ ಫೋಟೋದಲ್ಲಿ ಮಾತ್ರ ಬೆಳೆಯನ್ನು ಸರಿಯಾಗಿ ಹೇಳಿತು).",
        "not_seen": "ಇದು ಯಾವ ಬೆಳೆ ಎಂದು AI ಗೆ ಹೇಳಲು ಆಗಲಿಲ್ಲ.",
        "match": "ಇದು ನೀವು ಆಯ್ಕೆ ಮಾಡಿದ ಬೆಳೆಗೆ ಹೊಂದುತ್ತದೆ.",
        "mismatch": "ಇದು ನೀವು ಆಯ್ಕೆ ಮಾಡಿದ ಬೆಳೆಗೆ ಹೊಂದುವುದಿಲ್ಲ: ಬೆಳೆ ಅಥವಾ ಫೋಟೋವನ್ನು ಪರಿಶೀಲಿಸಿ.",
        "part": "ಫೋಟೋದಲ್ಲಿರುವ ಗಿಡದ ಭಾಗ: {part}.",
        "none_seen": "ಈ ಫೋಟೋದಲ್ಲಿ ಕಲೆ, ಹಳದಿ, ರಂಧ್ರ, ಒಣಗುವಿಕೆ ಅಥವಾ ಇತರ ಹಾನಿ ಕಂಡುಬಂದಿಲ್ಲ.",
        "nothing_read": "ಈ ಫೋಟೋದಿಂದ ಯಾವುದೇ ಸ್ಪಷ್ಟ ಲಕ್ಷಣವನ್ನು ಓದಲು ಆಗಲಿಲ್ಲ.",
        "no_explanation": "ವಿವರಿಸಬೇಕಾದ ಯಾವುದೇ ಲಕ್ಷಣ ಕಾಣಲಿಲ್ಲ.",
        "produce_colour": "{part} ಮೇಲಿನ ಬಣ್ಣ ಬದಲಾವಣೆ ಹೆಚ್ಚಾಗಿ ಸಹಜವಾಗಿ ಹಣ್ಣಾಗುವಿಕೆ ಅಥವಾ ತಳಿಯ ಸ್ವಂತ ಬಣ್ಣ; ಒಂದು ಫೋಟೋದಿಂದ "
        "ಅದನ್ನು ಸಮಸ್ಯೆಯಿಂದ ಬೇರ್ಪಡಿಸಲು ಆಗುವುದಿಲ್ಲ.",
        "limit_photo": "ಈ ಒಂದು ಫೋಟೋದಲ್ಲಿ ಕಾಣುವುದನ್ನು ಮಾತ್ರ ಪರಿಶೀಲಿಸಲಾಗಿದೆ; ಎಲೆಯ ಕೆಳಭಾಗ, ಬೇರು, ಕಾಂಡ ಮತ್ತು ಉಳಿದ ಹೊಲವನ್ನು ಪರಿಶೀಲಿಸಿಲ್ಲ.",
        "limit_healthy": "ಲಕ್ಷಣ ಕಾಣದಿದ್ದರೂ ಗಿಡ ಆರೋಗ್ಯವಾಗಿದೆ ಎಂದು ಖಚಿತವಲ್ಲ: ಆರಂಭಿಕ ಸೋಂಕು, ಬೇರಿನ ಸಮಸ್ಯೆ ಮತ್ತು ಕೆಲವು ಕೀಟಗಳು ಇನ್ನೂ ಕಾಣದಿರಬಹುದು.",
        "limit_problem": "ನಮ್ಮ ಪರೀಕ್ಷೆಗಳಲ್ಲಿ ಈ AI ಆರೋಗ್ಯಕರ ಎಲೆಗಳಲ್ಲೂ ಹಲವು ಬಾರಿ ಸಮಸ್ಯೆ ಎಂದು ಹೇಳಿದೆ; ಕ್ರಮ ಕೈಗೊಳ್ಳುವ "
        "ಮೊದಲು ಗಿಡವನ್ನು ಹೊಲದಲ್ಲಿ ನೀವೇ ಪರಿಶೀಲಿಸಿ.",
        "limit_crop": "{crop} ಗಾಗಿ ಫೋಟೋ ಪರಿಶೀಲನೆಯನ್ನು ಲೇಬಲ್ ಮಾಡಿದ ಫೋಟೋಗಳಲ್ಲಿ ದೃಢೀಕರಿಸಿಲ್ಲ.",
        "limit_crop_not_reliable": "{crop} ಗೆ ಈ ಪರಿಶೀಲನೆ ವಿಶ್ವಾಸಾರ್ಹವಲ್ಲ ಎಂದು ಅಳೆಯಲಾಗಿದೆ: ನಮ್ಮ ಪರೀಕ್ಷೆಯಲ್ಲಿ ಇದು ಹೆಚ್ಚಿನ "
        "ಆರೋಗ್ಯಕರ ಎಲೆಗಳನ್ನು ರೋಗಗ್ರಸ್ತ ಎಂದು ಹೇಳಿತು.",
        "next_leaves": "ಎಲೆಗಳ ಆರೋಗ್ಯಕ್ಕಾಗಿ ಎಲೆಗಳ ಹತ್ತಿರದ ಫೋಟೋ ತೆಗೆಯಿರಿ.",
        "score_method": "ದೃಶ್ಯ ಸ್ಥಿತಿ ಅಂಕ: 10 ರಿಂದ ಆರಂಭವಾಗಿ, ಕಾಣುವ ಪ್ರತಿಯೊಂದು ಲಕ್ಷಣಕ್ಕೆ ಅಂಕ ಕಡಿಮೆಯಾಗುತ್ತದೆ; ತೀವ್ರ ಅಥವಾ "
        "ವ್ಯಾಪಕ ಲಕ್ಷಣಕ್ಕೆ ಹೆಚ್ಚು. ಇದು ಈ ಫೋಟೋದಲ್ಲಿ ಕಾಣುವುದನ್ನು ಮಾತ್ರ ಅಳೆಯುತ್ತದೆ. ಇದು ರೋಗದ ಸಾಧ್ಯತೆ ಅಲ್ಲ, AI ಎಷ್ಟು "
        "ಖಚಿತ ಎಂಬುದೂ ಅಲ್ಲ.",
        "band_none_visible": "ಈ ಫೋಟೋದಲ್ಲಿ ಕಾಣುವ ಹಾನಿ ಇಲ್ಲ",
        "band_minor": "ಸ್ವಲ್ಪ ಲಕ್ಷಣಗಳು ಕಾಣುತ್ತಿವೆ",
        "band_moderate": "ಮಧ್ಯಮ ಪ್ರಮಾಣದ ಹಾನಿ ಕಾಣುತ್ತಿದೆ",
        "band_severe": "ತೀವ್ರ ಹಾನಿ ಕಾಣುತ್ತಿದೆ",
        "withheld_not_a_plant": "ಅಂಕ ಇಲ್ಲ: ಫೋಟೋದಲ್ಲಿ ಬೆಳೆ ಗಿಡ ಕಾಣುತ್ತಿಲ್ಲ.",
        "withheld_photo": "ಅಂಕ ಇಲ್ಲ: ಗಿಡವನ್ನು ಅಳೆಯಲು ಫೋಟೋ ಸಾಕಷ್ಟು ಸ್ಪಷ್ಟ ಅಥವಾ ಹತ್ತಿರವಾಗಿಲ್ಲ. ಮತ್ತೆ ತೆಗೆಯಿರಿ.",
        "withheld_unclear": "ಅಂಕ ಇಲ್ಲ: ಈ ಫೋಟೋವನ್ನು AI ಸ್ಪಷ್ಟವಾಗಿ ನಿರ್ಣಯಿಸಲು ಆಗಲಿಲ್ಲ.",
        "withheld_produce_colour": "ಅಂಕ ಇಲ್ಲ: {part} ಮೇಲಿನ ಬಣ್ಣ ಬದಲಾವಣೆಯನ್ನು ಮಾತ್ರ ನೋಡಿ ಅಂಕ ನೀಡಲು ಆಗುವುದಿಲ್ಲ.",
        "withheld_crop_mismatch": "ಅಂಕ ಇಲ್ಲ: ಫೋಟೋದಲ್ಲಿ ನೀವು ಆಯ್ಕೆ ಮಾಡಿದ ಬೆಳೆ ಇಲ್ಲದಿರಬಹುದು.",
        "withheld_no_ai": "ಅಂಕ ಇಲ್ಲ: AI ಮಾದರಿ ಬಳಸಿಲ್ಲ; ಬಣ್ಣಗಳಿಂದ ಮಾತ್ರ ಗಿಡದ ಸ್ಥಿತಿಯನ್ನು ಅಳೆಯಲು ಆಗುವುದಿಲ್ಲ.",
        "withheld_specialist": "ಅಂಕ ಇಲ್ಲ: ಈ ಬೆಳೆಗೆ ಫೋಟೋದಿಂದ ಅಂಕ ನೀಡುವುದಿಲ್ಲ.",
    },
}


def _lang(language: str) -> str:
    return language if language in T else "en"


def observations_of(features: dict[str, Any]) -> list[dict[str, str | None]]:
    """Visible signs with colour and extent where the model gave them (prompt v2), else just the sign."""
    detail = {o["sign"]: o for o in features.get("observations") or [] if isinstance(o, dict) and "sign" in o}
    return [
        {"sign": s, "colour": detail.get(s, {}).get("colour"), "extent": detail.get(s, {}).get("extent")}
        for s in features.get("symptoms") or []
        if s in SIGN_WEIGHT
    ]


def condition_score(observations: list[dict[str, str | None]], healthy_tissue: str | None = None) -> int:
    """Visual condition 1-10 from visible signs only (rubric in the module docstring)."""
    loss = sum(SIGN_WEIGHT[o["sign"] or ""] * EXTENT_FACTOR.get(o.get("extent") or "", 1.0) for o in observations)
    score = int(10 - loss + 0.5)
    if healthy_tissue in TISSUE_CAP:
        score = min(score, TISSUE_CAP[healthy_tissue])
    return max(1, min(10, score))


def band(score: int, has_signs: bool) -> str:
    if score >= 10 and not has_signs:
        return "none_visible"
    if score >= 8:
        return "minor"
    if score >= 5:
        return "moderate"
    return "severe"


def withheld_reason(result: HealthAssessment) -> str | None:
    """Why no condition score can be given, or None when the photo gives enough evidence."""
    f, flags = result.features, set(result.quality_flags)
    if "specialist_needed" in flags or f.get("assessment") == "specialist_needed":
        return "specialist"
    if f.get("mode") == "measurements_only" or f.get("ai_unavailable"):
        return "no_ai"
    if "not_a_plant" in flags:
        return "not_a_plant"
    if flags & {"too_dark", "blurry", "poor_photo", "not_close_up", "too_bright", "little_plant_visible"}:
        return "photo"
    if "crop_mismatch" in flags:
        return "crop_mismatch"
    if f.get("produce_colour_only"):
        return "produce_colour"
    if result.label is CropHealthClass.UNKNOWN:
        return "unclear"
    return None


def build_report(
    result: HealthAssessment,
    language: str,
    validation: dict[str, Any] | None = None,
    crop_name: str | None = None,
) -> dict[str, Any]:
    """The structured report stored with the analysis and shown by the app (texts in the request's language).
    `validation` is the crop's measured validation status (domain.crop_health_validation), when the crop is known."""
    lang = _lang(language)
    t, f, flags = T[lang], result.features, result.quality_flags
    part_id = str(f.get("plant_part") or "unknown")
    part = PART_NAME[lang].get(part_id, PART_NAME[lang]["unknown"])
    observations = observations_of(f)
    signs = {o["sign"] for o in observations}

    photo = [t[x] for x in PHOTO_FLAGS if x in flags]
    if "part_not_leaves" in flags:
        photo.append(t["part_not_leaves"].format(part=part))
    reason = withheld_reason(result)
    if reason == "no_ai":
        photo.append(t["no_ai"])
    elif reason == "specialist":
        photo.append(t["specialist"])
    elif not photo:
        photo.append(t["usable"])

    identity: list[str] = []
    if f.get("expected_crop"):
        identity.append(t["chosen"].format(crop=f["expected_crop"]))
    if reason not in ("no_ai", "specialist", "not_a_plant") and "precheck" not in f:
        seen = f.get("crop_seen")
        guessed = is_crop_guess(seen)
        identity.append(t["seen"].format(seen=seen, rate=CROP_ID_MEASURED[lang]) if guessed else t["not_seen"])
        if f.get("crop_match") is True:
            identity.append(t["match"])
        elif f.get("crop_match") is False:
            identity.append(t["mismatch"])
        identity.append(t["part"].format(part=part))

    seen_items = []
    for o in observations:
        bits = [SIGN_NAME[lang][o["sign"] or ""]]
        if o.get("colour") in COLOURS:
            bits.append(COLOUR_NAME[lang][o["colour"] or ""])
        if o.get("extent") in EXTENT_FACTOR:
            bits.append(EXTENT_NAME[lang][o["extent"] or ""])
        seen_items.append(", ".join(bits))
    if not seen_items and reason is None and result.label is CropHealthClass.HEALTHY:
        seen_items.append(t["none_seen"])
    elif not seen_items and reason not in ("no_ai", "specialist"):
        seen_items.append(t["nothing_read"])

    explanations = [text_en if lang == "en" else text_kn for keys, text_en, text_kn in EXPLAIN.values() if keys & signs]
    if f.get("produce_colour_only"):
        explanations.insert(0, t["produce_colour"].format(part=part))
    if not explanations and reason is None:
        explanations.append(t["no_explanation"])

    confidence = str(f.get("ai_confidence") or "low")
    crop = crop_name or f.get("expected_crop")
    # the farmer-facing result; its next steps are the report's "What to do next", and the limits and the score
    # follow it (a doubtful "healthy" that became "clearer photo needed" gets neither "limit_healthy" nor 10/10)
    from app.domain.crop_health_decision import decide  # it imports the sign names from this module

    decision = decide(result.label, f, flags, lang, part_name=part, crop_name=str(crop or ""))
    status = decision["status"]
    limitations = [t["limit_photo"]]
    if status == "healthy":
        limitations.append(t["limit_healthy"])
    elif status == "needs_attention":
        limitations.append(t["limit_problem"])
    if validation and crop and validation.get("verdict") != "reliable":
        key = "limit_crop_not_reliable" if validation.get("verdict") == "not_reliable" else "limit_crop"
        limitations.append(t[key].format(crop=crop))
    nxt = list(decision["next_steps"])
    if "part_not_leaves" in flags and status != "retake_photo":
        nxt.append(t["next_leaves"])

    if reason is None and status not in ("healthy", "needs_attention"):
        reason = "unclear"
    score = None if reason else condition_score(observations, f.get("healthy_tissue"))
    condition: dict[str, Any] = {"score": score, "out_of": 10, "method": t["score_method"]}
    if score is None:
        condition |= {"band": None, "text": t[f"withheld_{reason}"].format(part=part), "withheld_reason": reason}
    else:
        b = band(score, bool(signs))
        condition |= {"band": b, "text": t[f"band_{b}"], "withheld_reason": None}

    return {
        "version": REPORT_VERSION,
        "language": lang,
        "condition": condition,
        "assessment_confidence": None if reason in ("no_ai", "specialist") else confidence,
        "decision": decision,
        "sections": [
            {"id": "photo", "title": t["photo"], "items": photo},
            *([{"id": "identity", "title": t["identity"], "items": identity}] if identity else []),
            {"id": "observations", "title": t["observations"], "items": seen_items},
            *([{"id": "explanations", "title": t["explanations"], "items": explanations}] if explanations else []),
            {"id": "limitations", "title": t["limitations"], "items": limitations},
            {"id": "next", "title": t["next"], "items": nxt},
        ],
    }
