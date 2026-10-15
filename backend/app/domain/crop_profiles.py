"""What the crop-health check needs to know about the crop in a photo: its names, the part it is grown for and how
that part should be judged. Generic for every catalogue entry (built from name, aliases, category and group), with
part-specific guidance instead of applying leaf rules to fruit, tubers, bulbs or rhizomes."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.domain.crop_catalog import group_and_part

# what is NORMAL vs what to look for, per part (sent to the vision model when the crop is known)
PART_GUIDANCE: dict[str, str] = {
    "leaf": "Judge the leaves.",
    "fruit": (
        "Fruit colour changes as it ripens and is not a symptom. On fruit look for rot, soft or sunken spots, "
        "cracks, mould and insect damage; on leaves look for spots and yellowing."
    ),
    "grain": "Judge the leaves, stems and ears or panicles; grain colour changes as it matures.",
    "pod": "Judge the leaves and pods; pods dry and change colour as they mature.",
    "seed": "Judge the leaves, stems and seed heads or pods.",
    "root": "Soil on the surface and the variety's own skin colour are normal. Look for rot, soft or sunken areas, "
    "cracks, mould and insect holes; on leaves look for spots and yellowing.",
    "tuber": "Soil on the surface and the natural skin colour are normal. Look for rot, soft or sunken areas, cracks, "
    "mould and insect holes; on leaves look for spots and yellowing.",
    "bulb": "Dry outer skins are normal. Look for rot, soft areas, mould and sprouting; on leaves look for spots, "
    "yellowing and drying tips.",
    "rhizome": "Soil and the natural skin colour are normal. Look for rot, soft or shrivelled areas and mould; on "
    "leaves look for spots and yellowing.",
    "corm": "Soil and the natural skin colour are normal. Look for rot, soft areas and mould; on leaves look for spots "
    "and yellowing.",
    "flower": "Petal colour depends on the variety. Look for spots, blight, rot, mould and insects on flowers and "
    "leaves.",
    "stem": "Judge the stems and leaves: look for rot, cracks, holes, wilting and spots.",
    "latex": "Judge the leaves and the trunk: look for spots, leaf fall, bark rot or cracks.",
    "whole_plant": "Judge the leaves and stems of the plants.",
}


@dataclass(frozen=True, slots=True)
class CropContext:
    """The crop a photo is supposed to show (from the farmer's crop cycle or choice)."""

    name: str
    names: tuple[str, ...]  # name, Kannada name, aliases, scientific genus: used to check the model's crop guess
    part: str
    group: str
    scientific: str | None = None
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def specialist_only(self) -> bool:
        """Mushrooms are fungi: a green-plant photo check does not apply."""
        return self.group == "mushrooms" or self.part == "fungus"

    def prompt_note(self) -> str:
        sci = f" ({self.scientific})" if self.scientific else ""
        return (
            f"The farmer says this is {self.name}{sci}, grown for its {self.part.replace('_', ' ')}. "
            f"{PART_GUIDANCE.get(self.part, PART_GUIDANCE['leaf'])}"
        )


def context_for(
    name: str,
    *,
    category: str | None,
    group: str | None,
    local_name: str | None = None,
    aliases: list[str] | None = None,
    scientific: str | None = None,
) -> CropContext:
    g, part = group_and_part(name, category, group)
    genus = scientific.split()[0].lower() if scientific else None
    names = tuple(
        dict.fromkeys(x.lower() for x in (name, local_name or "", *(aliases or []), genus or "") if x and x.strip())
    )
    return CropContext(name=name, names=names, part=part, group=g, scientific=scientific)


_NO_CLAIM = re.compile(r"^(unknown|unclear|not sure|plant|leaf|leaves|crop|vegetable|fruit|tree|grass|weed|n/?a|none)$")


def _normal(seen: str) -> str:
    return " ".join(seen.lower().replace("_", " ").split()).strip(" .")


def is_crop_guess(seen: str | None) -> bool:
    """True when the model named a crop (not 'unknown', 'plant', 'leaf' and the like)."""
    return bool(seen) and bool(_normal(seen or "")) and not _NO_CLAIM.match(_normal(seen or ""))


def crop_matches(seen: str | None, crop: CropContext) -> bool | None:
    """Does the model's crop guess fit the expected crop? None when it made no real guess ('unknown', 'plant')."""
    if not is_crop_guess(seen):
        return None
    s = _normal(seen or "")
    for name in crop.names:
        if not name:
            continue
        if re.search(rf"\b{re.escape(name)}(s|es)?\b", s) or re.search(rf"\b{re.escape(s)}\b", name):
            return True
    return False
