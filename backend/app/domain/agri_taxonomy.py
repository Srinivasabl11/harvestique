"""Which agricultural item a photo shows, its parent category, and the A/B/C health category (pure, no I/O).

ITEMS come from the crop catalogue in the database (app.models.crop.Crop: name, Kannada/local name, aliases, group),
so the taxonomy grows when an admin adds a crop; nothing here lists crops. Each catalogue group maps to one PARENT
CATEGORY shown to farmers (English and Kannada). On 2026-10-16 the production catalogue had 213 active items in 17
groups, 86 of them with a Kannada name; an item missing from the catalogue is reported as not identified.

IDENTIFICATION matches the vision model's free-text guess against every name, local name and alias. A guess that
fits two different items equally well (e.g. "gram") is ambiguous and not identified; the farmer is asked for a closer
photo or to open the check from their crop. The model's guess is a guess: it is never presented as verified.

HEALTH SCORE (0-100 %): how healthy the plant or produce LOOKS in this photo. 100 % = no visible damage, 0 % =
severely damaged. Computed from the visible signs only (crop_health_report rubric: each sign's weight x extent,
10 points of the 0-10 condition scale = 100 %), capped when the AI said little of the tissue looks normal. It is NOT
the AI's confidence (reported separately) and not the probability of a disease.

HEALTH CATEGORY, three equal bands with non-overlapping boundaries (every valid score is in exactly one):
  A  66.66 < score <= 100     very good
  B  33.33 < score <= 66.66   good
  C   0    <= score <= 33.33  moderate
Scores are clamped to 0-100; a missing or non-numeric score, or a photo without enough evidence, gets NO category
("Unable to classify"), never a guess.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Literal

Category = Literal["A", "B", "C"]
A_ABOVE = 66.66
B_ABOVE = 33.33

PARENT: dict[str, dict[str, str]] = {
    "vegetables": {"en": "Vegetables", "kn": "ತರಕಾರಿಗಳು"},
    "fruits": {"en": "Fruits and nuts", "kn": "ಹಣ್ಣುಗಳು ಮತ್ತು ಬೀಜಗಳು"},
    "cereals_grains": {"en": "Cereals and grains", "kn": "ಧಾನ್ಯಗಳು"},
    "pulses": {"en": "Pulses and legumes", "kn": "ಬೇಳೆಕಾಳುಗಳು"},
    "oilseeds": {"en": "Oilseeds", "kn": "ಎಣ್ಣೆಕಾಳುಗಳು"},
    "spices": {"en": "Spices and condiments", "kn": "ಸಾಂಬಾರ ಪದಾರ್ಥಗಳು"},
    "plantation_commercial": {"en": "Plantation and commercial crops", "kn": "ತೋಟ ಮತ್ತು ವಾಣಿಜ್ಯ ಬೆಳೆಗಳು"},
    "flowers_ornamental": {"en": "Flowers and ornamental crops", "kn": "ಹೂವು ಮತ್ತು ಅಲಂಕಾರಿಕ ಬೆಳೆಗಳು"},
    "fodder": {"en": "Fodder and forage crops", "kn": "ಮೇವಿನ ಬೆಳೆಗಳು"},
    "roots_tubers": {"en": "Roots and tubers", "kn": "ಗೆಡ್ಡೆ ಮತ್ತು ಬೇರು ಬೆಳೆಗಳು"},
    "medicinal_aromatic": {"en": "Medicinal and aromatic plants", "kn": "ಔಷಧೀಯ ಮತ್ತು ಸುಗಂಧ ಸಸ್ಯಗಳು"},
    "trees_agroforestry": {"en": "Trees and agroforestry", "kn": "ಮರ ಮತ್ತು ಕೃಷಿ ಅರಣ್ಯ"},
    "mushrooms": {"en": "Mushrooms", "kn": "ಅಣಬೆಗಳು"},
    "other": {"en": "Other agricultural produce", "kn": "ಇತರ ಕೃಷಿ ಉತ್ಪನ್ನಗಳು"},
}
# catalogue group (app.core.enums.CropGroup) -> parent category; an unknown group is "other"
GROUP_PARENT: dict[str, str] = {
    "vegetables": "vegetables",
    "fruits": "fruits",
    "cereals": "cereals_grains",
    "millets": "cereals_grains",
    "pulses": "pulses",
    "oilseeds": "oilseeds",
    "spices": "spices",
    "plantation": "plantation_commercial",
    "beverage": "plantation_commercial",
    "fibre": "plantation_commercial",
    "sugar_starch": "plantation_commercial",
    "ornamental": "flowers_ornamental",
    "fodder": "fodder",
    "roots_tubers": "roots_tubers",
    "medicinal_aromatic": "medicinal_aromatic",
    "agroforestry": "trees_agroforestry",
    "mushrooms": "mushrooms",
    "other": "other",
}
CATEGORY_TEXT = {
    "en": {"A": "Very good", "B": "Good", "C": "Moderate", None: "Unable to classify"},
    "kn": {"A": "ತುಂಬಾ ಉತ್ತಮ", "B": "ಉತ್ತಮ", "C": "ಮಧ್ಯಮ", None: "ವರ್ಗೀಕರಿಸಲು ಆಗಲಿಲ್ಲ"},
}


def parent_of(group: str | None) -> str:
    return GROUP_PARENT.get(group or "", "other")


def parent_name(parent: str, language: str) -> str:
    return PARENT.get(parent, PARENT["other"])["kn" if language == "kn" else "en"]


# ------------------------------------------------------------------------------------------- score -> category
def normalize_score(value: Any) -> float | None:
    """A health score as a number clamped to 0-100, or None when it is not a usable number. Not rounded: the band is
    decided on the exact value (66.661 is above 66.66), and only the displayed score is rounded."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return min(100.0, max(0.0, float(value)))


def health_category(value: Any) -> Category | None:
    score = normalize_score(value)
    if score is None:
        return None
    if score > A_ABOVE:
        return "A"
    if score > B_ABOVE:
        return "B"
    return "C"


# ------------------------------------------------------------------------------------------- identification
@dataclass(frozen=True)
class CatalogueItem:
    name: str
    local_name: str | None
    aliases: tuple[str, ...]
    group: str | None

    @property
    def parent(self) -> str:
        return parent_of(self.group)


@dataclass(frozen=True)
class Identification:
    item: CatalogueItem
    matched: str  # the name, local name or alias that matched


_NOT_ITEM_WORDS = re.compile(
    r"\b(plant|plants|leaf|leaves|crop|crops|fruit|fruits|tree|trees|field|seedling|seedlings|pods?|grains?|seeds?|"
    r"flowers?|bulbs?|tubers?|roots?|stems?|vine|bush|shrub|produce|harvest|fresh|ripe|unripe|green|red)\b"
)


def _norm(text: str) -> str:
    """Lower case, separators to spaces; Kannada letters are kept as they are."""
    t = re.sub(r"[_\-/(),.;:]+", " ", str(text).lower())
    return " ".join(t.split())


def _forms(name: str) -> set[str]:
    n = _norm(name)
    return {n, n + "s", n + "es"} if n else set()


def identify(seen: str | None, items: list[CatalogueItem]) -> Identification | None:
    """The single catalogue item the guess names, or None (no guess, not in the catalogue, or ambiguous)."""
    s = _norm(seen or "")
    if not s or s in ("unknown", "unclear", "none", "not sure", "n/a"):
        return None
    core = " ".join(_NOT_ITEM_WORDS.sub(" ", s).split()) or s  # "tomato leaf" -> "tomato"
    best: dict[int, list[tuple[CatalogueItem, str, int]]] = {}
    for item in items:
        for name in (item.name, item.local_name or "", *item.aliases):
            forms = _forms(name)
            if not forms:
                continue
            base = _norm(name)
            if s in forms or core in forms:
                rank = 3  # the whole guess is this name
            elif any(re.search(rf"(?<!\w){re.escape(f)}(?!\w)", s) for f in forms):
                rank = 2  # the name appears inside the guess ("ripe alphonso mango")
            else:
                continue
            best.setdefault(rank, []).append((item, name, len(base)))
    if not best:
        return None
    candidates = best[max(best)]
    longest = max(length for _, _, length in candidates)
    top = {(item.name, name) for item, name, length in candidates if length == longest}
    names = {item_name for item_name, _ in top}
    if len(names) != 1:
        return None  # two different items fit equally well: not identified
    item, matched, _ = next(c for c in candidates if c[0].name in names and c[2] == longest)
    return Identification(item, matched)
