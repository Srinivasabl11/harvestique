"""Produce quality grading (A / B / C) of HARVESTED produce: pure rules, no model call, no database.

This is about the produce a farmer sells (size, ripeness, damage, freshness, cleanliness), not plant health:
a perfectly healthy crop can give grade C produce (harvested too late, bruised in transport) and the reverse.

* Each crop group uses one PROFILE: a list of observable attributes, each rated on three levels (0 best, 2 worst).
  The level texts carry the indicative thresholds (e.g. "up to about 10 in 100 damaged"), so the criteria are
  configured in one place (PROFILES / GROUP_PROFILE) and shown to the farmer exactly as they are applied.
* The grade is the worst level over all attributes: all level 0 -> A, worst level 1 -> B, any level 2 -> C.
* No grade without evidence for EVERY attribute. A photo can rate only what it shows (moisture, smell or the inside
  of a sack are not visible): the rest stays open and the farmer must check it. Missing ratings -> no grade, and the
  answer says which checks are missing; it never fills a gap with a guess.
* The farmer has the final word on the ratings (they see the produce); they may lower the grade, with a reason, but
  not raise it above what the ratings support.

These are Harvestique's own indicative criteria, NOT an official AGMARK / BIS grade or certificate. The hub's quality
check, made when produce is received, is measured and decides acceptance.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from app.core.enums import QualityGrade

CRITERIA_VERSION = 1
Lang = Literal["en", "kn"]
GRADE_FOR_LEVEL = (QualityGrade.A, QualityGrade.B, QualityGrade.C)
GRADE_RANK = {QualityGrade.A: 0, QualityGrade.B: 1, QualityGrade.C: 2}


@dataclass(frozen=True)
class Attribute:
    id: str
    photo_visible: bool  # can a photo of the produce show it at all?
    title: dict[str, str]
    levels: tuple[dict[str, str], dict[str, str], dict[str, str]]  # level 0 (best), 1, 2 (worst), per language


def _a(id: str, visible: bool, en: str, kn: str, levels: tuple[tuple[str, str], ...]) -> Attribute:
    assert len(levels) == 3
    lv = tuple({"en": e, "kn": k} for e, k in levels)
    return Attribute(id, visible, {"en": en, "kn": kn}, lv)  # type: ignore[arg-type]


FRESH: tuple[Attribute, ...] = (
    _a(
        "size",
        True,
        "Size and uniformity",
        "ಗಾತ್ರ ಮತ್ತು ಏಕರೂಪತೆ",
        (
            ("Even, full size for the variety", "ತಳಿಗೆ ತಕ್ಕ ಪೂರ್ಣ ಗಾತ್ರ, ಸಮವಾಗಿದೆ"),
            ("Some smaller or uneven pieces", "ಕೆಲವು ಸಣ್ಣ ಅಥವಾ ಅಸಮ ತುಂಡುಗಳು"),
            ("Mostly small, misshapen or very mixed", "ಹೆಚ್ಚಾಗಿ ಸಣ್ಣ, ವಿಕಾರ ಅಥವಾ ತುಂಬಾ ಮಿಶ್ರ"),
        ),
    ),
    _a(
        "maturity",
        True,
        "Ripeness and colour",
        "ಪಕ್ವತೆ ಮತ್ತು ಬಣ್ಣ",
        (
            ("Right stage for sale, even colour", "ಮಾರಾಟಕ್ಕೆ ಸರಿಯಾದ ಹಂತ, ಸಮ ಬಣ್ಣ"),
            ("Somewhat uneven ripeness or colour", "ಸ್ವಲ್ಪ ಅಸಮ ಪಕ್ವತೆ ಅಥವಾ ಬಣ್ಣ"),
            ("Many over-ripe or unripe pieces", "ಹಲವು ಅತಿ ಹಣ್ಣಾದ ಅಥವಾ ಕಾಯಿಯಾದ ತುಂಡುಗಳು"),
        ),
    ),
    _a(
        "damage",
        True,
        "Damage (bruises, cuts, cracks, rot, insect holes)",
        "ಹಾನಿ (ಜಜ್ಜು, ಕತ್ತರಿಸಿದ, ಬಿರುಕು, ಕೊಳೆತ, ಕೀಟದ ರಂಧ್ರ)",
        (
            ("Almost none (under about 2 in 100)", "ಬಹುತೇಕ ಇಲ್ಲ (100 ರಲ್ಲಿ ಸುಮಾರು 2 ಕ್ಕಿಂತ ಕಡಿಮೆ)"),
            ("A few (up to about 10 in 100)", "ಕೆಲವು (100 ರಲ್ಲಿ ಸುಮಾರು 10 ರವರೆಗೆ)"),
            ("Many (more than about 10 in 100), or any rot", "ಹಲವು (100 ರಲ್ಲಿ ಸುಮಾರು 10 ಕ್ಕಿಂತ ಹೆಚ್ಚು), ಅಥವಾ ಯಾವುದೇ ಕೊಳೆತ"),
        ),
    ),
    _a(
        "freshness",
        True,
        "Freshness",
        "ತಾಜಾತನ",
        (
            ("Firm and fresh, harvested within a day or two", "ಗಟ್ಟಿ ಮತ್ತು ತಾಜಾ, ಒಂದೆರಡು ದಿನಗಳಲ್ಲಿ ಕೊಯ್ದದ್ದು"),
            ("Slightly soft or wilted", "ಸ್ವಲ್ಪ ಮೆತ್ತಗೆ ಅಥವಾ ಬಾಡಿದೆ"),
            ("Wilted, shrivelled or stale", "ಬಾಡಿದ, ಸುಕ್ಕುಗಟ್ಟಿದ ಅಥವಾ ಹಳಸಿದ"),
        ),
    ),
)

DRY: tuple[Attribute, ...] = (
    _a(
        "size",
        True,
        "Grain / seed size and uniformity",
        "ಕಾಳು / ಬೀಜದ ಗಾತ್ರ ಮತ್ತು ಏಕರೂಪತೆ",
        (
            ("Bold and even", "ದಪ್ಪ ಮತ್ತು ಸಮ"),
            ("Some small or shrivelled grains", "ಕೆಲವು ಸಣ್ಣ ಅಥವಾ ಸುಕ್ಕು ಕಾಳುಗಳು"),
            ("Many small, shrivelled or immature grains", "ಹಲವು ಸಣ್ಣ, ಸುಕ್ಕು ಅಥವಾ ಬಲಿಯದ ಕಾಳುಗಳು"),
        ),
    ),
    _a(
        "colour",
        True,
        "Colour and lustre",
        "ಬಣ್ಣ ಮತ್ತು ಹೊಳಪು",
        (
            ("Natural colour of the variety, bright", "ತಳಿಯ ಸಹಜ ಬಣ್ಣ, ಹೊಳಪು"),
            ("Slightly dull or a few discoloured grains", "ಸ್ವಲ್ಪ ಮಂದ ಅಥವಾ ಕೆಲವು ಬಣ್ಣಗೆಟ್ಟ ಕಾಳುಗಳು"),
            ("Dull, or many discoloured or mouldy grains", "ಮಂದ, ಅಥವಾ ಹಲವು ಬಣ್ಣಗೆಟ್ಟ ಅಥವಾ ಬೂಸ್ಟ್ ಹಿಡಿದ ಕಾಳುಗಳು"),
        ),
    ),
    _a(
        "damage",
        True,
        "Broken, insect-damaged or sprouted grains",
        "ಒಡೆದ, ಕೀಟ ಹಾನಿಯಾದ ಅಥವಾ ಮೊಳಕೆಯೊಡೆದ ಕಾಳುಗಳು",
        (
            ("Almost none (under about 2 in 100)", "ಬಹುತೇಕ ಇಲ್ಲ (100 ರಲ್ಲಿ ಸುಮಾರು 2 ಕ್ಕಿಂತ ಕಡಿಮೆ)"),
            ("A few (up to about 5 in 100)", "ಕೆಲವು (100 ರಲ್ಲಿ ಸುಮಾರು 5 ರವರೆಗೆ)"),
            ("Many (more than about 5 in 100)", "ಹಲವು (100 ರಲ್ಲಿ ಸುಮಾರು 5 ಕ್ಕಿಂತ ಹೆಚ್ಚು)"),
        ),
    ),
    _a(
        "foreign_matter",
        True,
        "Cleanliness (stones, soil, husk, other seeds)",
        "ಸ್ವಚ್ಛತೆ (ಕಲ್ಲು, ಮಣ್ಣು, ಹೊಟ್ಟು, ಇತರ ಬೀಜ)",
        (
            ("Clean", "ಸ್ವಚ್ಛ"),
            ("A little foreign matter", "ಸ್ವಲ್ಪ ಕಸ"),
            ("Clearly visible foreign matter", "ಸ್ಪಷ್ಟವಾಗಿ ಕಾಣುವ ಕಸ"),
        ),
    ),
    _a(
        "dryness",
        False,  # moisture cannot be seen in a photo: the farmer checks it (bite / squeeze test, or a moisture meter)
        "Dryness",
        "ಒಣಗಿರುವಿಕೆ",
        (
            ("Well dried (hard, rattles, does not stick)", "ಚೆನ್ನಾಗಿ ಒಣಗಿದೆ (ಗಟ್ಟಿ, ಸದ್ದು ಮಾಡುತ್ತದೆ, ಅಂಟುವುದಿಲ್ಲ)"),
            ("Slightly damp in places", "ಕೆಲವೆಡೆ ಸ್ವಲ್ಪ ತೇವ"),
            ("Damp, soft or smells musty", "ತೇವ, ಮೆತ್ತಗೆ ಅಥವಾ ಬೂಸ್ಟ್ ವಾಸನೆ"),
        ),
    ),
)

PROFILES: dict[str, tuple[Attribute, ...]] = {"fresh": FRESH, "dry": DRY}
# crop group (app.core.enums.CropGroup) -> profile; anything not listed is graded as fresh produce
GROUP_PROFILE: dict[str, str] = {
    "cereals": "dry",
    "millets": "dry",
    "pulses": "dry",
    "oilseeds": "dry",
    "spices": "dry",
    "beverage": "dry",
    "fibre": "dry",
    "fodder": "dry",
    "plantation": "dry",
    "agroforestry": "dry",
    "medicinal_aromatic": "dry",
}
PROFILE_NAME = {
    "fresh": {"en": "Fresh produce", "kn": "ತಾಜಾ ಉತ್ಪನ್ನ"},
    "dry": {"en": "Grain, seed or dried produce", "kn": "ಕಾಳು, ಬೀಜ ಅಥವಾ ಒಣ ಉತ್ಪನ್ನ"},
}
TEXT = {
    "en": {
        "rule": "The grade is the lowest level of any check: all checks at the best level give A, any middle level "
        "gives B, any lowest level gives C.",
        "not_official": "Harvestique's own indicative grade from what you see, not an official AGMARK grade or "
        "certificate. The collection hub's quality check decides acceptance.",
        "grade_A": "Grade A: meets the highest quality checks.",
        "grade_B": "Grade B: acceptable standard quality.",
        "grade_C": "Grade C: lower quality or visible defects; may still sell, depending on the buyer.",
        "missing": "No grade yet: these checks are still open: {checks}.",
    },
    "kn": {
        "rule": "ಗ್ರೇಡ್ ಯಾವುದೇ ಪರಿಶೀಲನೆಯ ಕಡಿಮೆ ಮಟ್ಟ: ಎಲ್ಲವೂ ಉತ್ತಮ ಮಟ್ಟದಲ್ಲಿದ್ದರೆ A, ಯಾವುದಾದರೂ ಮಧ್ಯಮ ಮಟ್ಟದಲ್ಲಿದ್ದರೆ B, ಯಾವುದಾದರೂ ಕಡಿಮೆ ಮಟ್ಟದಲ್ಲಿದ್ದರೆ C.",
        "not_official": "ನೀವು ನೋಡುವುದರ ಆಧಾರದ ಮೇಲೆ Harvestique ನ ಸೂಚಕ ಗ್ರೇಡ್; ಅಧಿಕೃತ AGMARK ಗ್ರೇಡ್ ಅಥವಾ ಪ್ರಮಾಣಪತ್ರ ಅಲ್ಲ. "
        "ಸಂಗ್ರಹ ಕೇಂದ್ರದ ಗುಣಮಟ್ಟ ಪರಿಶೀಲನೆ ಸ್ವೀಕಾರವನ್ನು ನಿರ್ಧರಿಸುತ್ತದೆ.",
        "grade_A": "ಗ್ರೇಡ್ A: ಅತ್ಯುತ್ತಮ ಗುಣಮಟ್ಟದ ಪರಿಶೀಲನೆಗಳನ್ನು ಪೂರೈಸುತ್ತದೆ.",
        "grade_B": "ಗ್ರೇಡ್ B: ಸ್ವೀಕಾರಾರ್ಹ ಸಾಮಾನ್ಯ ಗುಣಮಟ್ಟ.",
        "grade_C": "ಗ್ರೇಡ್ C: ಕಡಿಮೆ ಗುಣಮಟ್ಟ ಅಥವಾ ಕಾಣುವ ದೋಷಗಳು; ಖರೀದಿದಾರರನ್ನು ಅವಲಂಬಿಸಿ ಮಾರಾಟವಾಗಬಹುದು.",
        "missing": "ಇನ್ನೂ ಗ್ರೇಡ್ ಇಲ್ಲ: ಈ ಪರಿಶೀಲನೆಗಳು ಬಾಕಿ ಇವೆ: {checks}.",
    },
}


def lang_of(language: str) -> Lang:
    return "kn" if language == "kn" else "en"


def profile_for(group: str | None) -> str:
    return GROUP_PROFILE.get(group or "", "fresh")


def attributes(profile: str) -> tuple[Attribute, ...]:
    return PROFILES[profile]


def grade_for(profile: str, levels: Mapping[str, int | None]) -> tuple[QualityGrade | None, list[str]]:
    """(grade, missing attribute ids). No grade unless every attribute of the profile has a level 0, 1 or 2."""
    ids = [a.id for a in PROFILES[profile]]
    missing = [i for i in ids if levels.get(i) not in (0, 1, 2)]
    if missing:
        return None, missing
    return GRADE_FOR_LEVEL[max(int(levels[i]) for i in ids)], []  # type: ignore[arg-type]


def clean_levels(profile: str, raw: dict[str, Any]) -> dict[str, int]:
    """Only known attributes with a valid level; raises ValueError naming the first bad entry."""
    known = {a.id for a in PROFILES[profile]}
    out: dict[str, int] = {}
    for key, value in raw.items():
        if key not in known:
            raise ValueError(f"unknown check {key!r} for {profile} produce")
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value not in (0, 1, 2):
            raise ValueError(f"check {key!r} must be 0, 1 or 2")
        out[key] = value
    return out


def criteria(profile: str, language: str) -> dict[str, Any]:
    """The checks and their levels, as shown to the farmer (and applied by grade_for)."""
    lang = lang_of(language)
    t = TEXT[lang]
    return {
        "version": CRITERIA_VERSION,
        "profile": profile,
        "profile_name": PROFILE_NAME[profile][lang],
        "attributes": [
            {
                "id": a.id,
                "title": a.title[lang],
                "photo_visible": a.photo_visible,
                "levels": [{"level": i, "text": lv[lang]} for i, lv in enumerate(a.levels)],
            }
            for a in PROFILES[profile]
        ],
        "grades": {g.value: t[f"grade_{g.value}"] for g in QualityGrade},
        "rule": t["rule"],
        "note": t["not_official"],
    }


def missing_text(profile: str, missing: list[str], language: str) -> str:
    lang = lang_of(language)
    titles = {a.id: a.title[lang] for a in PROFILES[profile]}
    return TEXT[lang]["missing"].format(checks=", ".join(titles[m] for m in missing))


def grade_text(grade: QualityGrade, language: str) -> str:
    return TEXT[lang_of(language)][f"grade_{grade.value}"]
