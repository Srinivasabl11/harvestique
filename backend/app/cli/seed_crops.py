"""Load a starter crop catalog (idempotent: crops that already exist are left untouched).

    python -m app.cli.seed_crops
    python -m app.cli.seed_crops --reconcile   # A-Z additions + scientific names, aliases, groups

Durations are *indicative* typical sowing-to-end-of-harvest periods for common Karnataka crops and
local-language names are for display; an admin should review both (PATCH /crops/{id}).
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.composition import build_crop_service
from app.core.config import get_settings
from app.core.container import Container, build_container
from app.core.enums import CropCategory as C
from app.core.enums import CropSeason as S
from app.core.errors import ConflictError
from app.domain.crop_catalog import EXISTING, NEW
from app.models.crop import Crop
from app.repositories.crops import CropRepository
from app.schemas.crops import CropCreate

# INDICATIVE reference yields (kg/acre), year-to-year CV and season water need (mm). Rough Karnataka-level
# magnitudes for planning defaults ONLY: unverified, ASSUMPTION-grade, superseded by a farmer's own records.
_REFERENCES: dict[str, tuple[str, str, str]] = {
    "Tomato": ("10000", "0.35", "500"),
    "Onion": ("8000", "0.30", "450"),
    "Potato": ("8000", "0.30", "500"),
    "Brinjal": ("8000", "0.30", "600"),
    "Cabbage": ("10000", "0.30", "400"),
    "Cauliflower": ("7000", "0.30", "400"),
    "Carrot": ("8000", "0.30", "350"),
    "Beans": ("4000", "0.30", "350"),
    "Cucumber": ("6000", "0.30", "400"),
    "Okra": ("4000", "0.30", "450"),
    "Green Chilli": ("4000", "0.35", "600"),
    "Paddy": ("2000", "0.20", "1200"),
    "Ragi": ("1000", "0.25", "350"),
    "Maize": ("2000", "0.25", "500"),
    "Groundnut": ("600", "0.30", "450"),
    "Red Gram": ("400", "0.35", "400"),
    "Cotton": ("700", "0.30", "700"),
    "Sugarcane": ("35000", "0.20", "1800"),
    "Marigold": ("5000", "0.30", "500"),
}

# (name, Kannada name, category, typical duration in days, season)
_SEED: list[tuple[str, str | None, C, int, S | None]] = [
    ("Tomato", "ಟೊಮೆಟೊ", C.VEGETABLE, 120, S.YEAR_ROUND),
    ("Onion", "ಈರುಳ್ಳಿ", C.VEGETABLE, 120, S.YEAR_ROUND),
    ("Potato", "ಆಲೂಗಡ್ಡೆ", C.VEGETABLE, 100, None),
    ("Brinjal", "ಬದನೆಕಾಯಿ", C.VEGETABLE, 150, S.YEAR_ROUND),
    ("Cabbage", "ಎಲೆಕೋಸು", C.VEGETABLE, 90, None),
    ("Cauliflower", "ಹೂಕೋಸು", C.VEGETABLE, 100, None),
    ("Carrot", "ಕ್ಯಾರೆಟ್", C.VEGETABLE, 100, None),
    ("Beans", "ಬೀನ್ಸ್", C.VEGETABLE, 75, S.YEAR_ROUND),
    ("Cucumber", "ಸೌತೆಕಾಯಿ", C.VEGETABLE, 75, S.YEAR_ROUND),
    ("Okra", "ಬೆಂಡೆಕಾಯಿ", C.VEGETABLE, 90, S.YEAR_ROUND),
    ("Green Chilli", "ಮೆಣಸಿನಕಾಯಿ", C.SPICE, 180, S.YEAR_ROUND),
    ("Paddy", "ಭತ್ತ", C.CEREAL, 135, None),
    ("Ragi", "ರಾಗಿ", C.CEREAL, 120, S.KHARIF),
    ("Maize", "ಮೆಕ್ಕೆಜೋಳ", C.CEREAL, 110, None),
    ("Groundnut", "ಶೇಂಗಾ", C.OILSEED, 110, None),
    ("Red Gram", "ತೊಗರಿ", C.PULSE, 170, S.KHARIF),
    ("Cotton", "ಹತ್ತಿ", C.CASH_CROP, 180, S.KHARIF),
    ("Sugarcane", "ಕಬ್ಬು", C.CASH_CROP, 365, S.YEAR_ROUND),
    ("Marigold", "ಚೆಂಡು ಹೂ", C.FLOWER, 110, None),
]

INDICATIVE = "Indicative duration for planning only; check it against your variety and local practice."
PERENNIAL = (
    "Perennial crop: record one year's crop as one cycle. The 365-day duration is a record-keeping convention, "
    "not an agronomic value."
)
# Expanded catalogue (stage 3). Kannada names only where the common name is well established; otherwise None (the
# English name is shown). No reference yields or water needs: those are not invented here, the predictor then relies
# on the farmer's own records and says so.
_MORE: list[tuple[str, str | None, C, int, S | None, str]] = [
    # vegetables
    ("Bitter Gourd", "ಹಾಗಲಕಾಯಿ", C.VEGETABLE, 90, None, INDICATIVE),
    ("Bottle Gourd", "ಸೋರೆಕಾಯಿ", C.VEGETABLE, 100, None, INDICATIVE),
    ("Ridge Gourd", "ಹೀರೆಕಾಯಿ", C.VEGETABLE, 90, None, INDICATIVE),
    ("Snake Gourd", "ಪಡವಲಕಾಯಿ", C.VEGETABLE, 100, None, INDICATIVE),
    ("Pumpkin", "ಕುಂಬಳಕಾಯಿ", C.VEGETABLE, 120, None, INDICATIVE),
    ("Radish", "ಮೂಲಂಗಿ", C.VEGETABLE, 50, None, INDICATIVE),
    ("Beetroot", "ಬೀಟ್‌ರೂಟ್", C.VEGETABLE, 70, None, INDICATIVE),
    ("Capsicum", "ದೊಣ್ಣೆ ಮೆಣಸಿನಕಾಯಿ", C.VEGETABLE, 150, None, INDICATIVE),
    ("Cluster Beans", "ಗೋರಿಕಾಯಿ", C.VEGETABLE, 90, None, INDICATIVE),
    ("Sweet Potato", "ಸಿಹಿ ಗೆಣಸು", C.VEGETABLE, 120, None, INDICATIVE),
    ("Spinach", "ಪಾಲಕ್", C.VEGETABLE, 45, None, INDICATIVE),
    ("Amaranthus", "ಹರಿವೆ ಸೊಪ್ಪು", C.VEGETABLE, 35, None, INDICATIVE),
    # spices
    ("Coriander", "ಕೊತ್ತಂಬರಿ", C.SPICE, 45, None, INDICATIVE),
    ("Fenugreek", "ಮೆಂತ್ಯ", C.SPICE, 40, None, INDICATIVE),
    ("Garlic", "ಬೆಳ್ಳುಳ್ಳಿ", C.SPICE, 150, S.RABI, INDICATIVE),
    ("Ginger", "ಶುಂಠಿ", C.SPICE, 240, None, INDICATIVE),
    ("Turmeric", "ಅರಿಶಿನ", C.SPICE, 270, None, INDICATIVE),
    ("Black Pepper", "ಕರಿಮೆಣಸು", C.SPICE, 365, S.YEAR_ROUND, PERENNIAL),
    ("Cardamom", "ಏಲಕ್ಕಿ", C.SPICE, 365, S.YEAR_ROUND, PERENNIAL),
    # fruits
    ("Banana", "ಬಾಳೆ", C.FRUIT, 365, S.YEAR_ROUND, INDICATIVE),
    ("Papaya", "ಪರಂಗಿ", C.FRUIT, 365, S.YEAR_ROUND, INDICATIVE),
    ("Watermelon", "ಕಲ್ಲಂಗಡಿ", C.FRUIT, 90, None, INDICATIVE),
    ("Muskmelon", "ಕರಬೂಜ", C.FRUIT, 90, None, INDICATIVE),
    ("Mango", "ಮಾವು", C.FRUIT, 365, S.YEAR_ROUND, PERENNIAL),
    ("Guava", "ಸೀಬೆ", C.FRUIT, 365, S.YEAR_ROUND, PERENNIAL),
    ("Pomegranate", "ದಾಳಿಂಬೆ", C.FRUIT, 365, S.YEAR_ROUND, PERENNIAL),
    ("Grapes", "ದ್ರಾಕ್ಷಿ", C.FRUIT, 365, S.YEAR_ROUND, PERENNIAL),
    ("Sapota", "ಸಪೋಟ", C.FRUIT, 365, S.YEAR_ROUND, PERENNIAL),
    ("Jackfruit", "ಹಲಸು", C.FRUIT, 365, S.YEAR_ROUND, PERENNIAL),
    # cereals and millets
    ("Jowar", "ಜೋಳ", C.CEREAL, 110, None, INDICATIVE),
    ("Wheat", "ಗೋಧಿ", C.CEREAL, 120, S.RABI, INDICATIVE),
    ("Bajra", "ಸಜ್ಜೆ", C.CEREAL, 90, S.KHARIF, INDICATIVE),
    ("Foxtail Millet", "ನವಣೆ", C.CEREAL, 90, S.KHARIF, INDICATIVE),
    ("Little Millet", "ಸಾಮೆ", C.CEREAL, 85, S.KHARIF, INDICATIVE),
    ("Kodo Millet", "ಹಾರಕ", C.CEREAL, 110, S.KHARIF, INDICATIVE),
    ("Proso Millet", "ಬರಗು", C.CEREAL, 70, S.KHARIF, INDICATIVE),
    ("Barnyard Millet", "ಊದಲು", C.CEREAL, 75, S.KHARIF, INDICATIVE),
    ("Browntop Millet", "ಕೊರಲೆ", C.CEREAL, 80, S.KHARIF, INDICATIVE),
    # pulses
    ("Bengal Gram", "ಕಡಲೆ", C.PULSE, 100, S.RABI, INDICATIVE),
    ("Green Gram", "ಹೆಸರು", C.PULSE, 70, S.KHARIF, INDICATIVE),
    ("Black Gram", "ಉದ್ದು", C.PULSE, 80, S.KHARIF, INDICATIVE),
    ("Horse Gram", "ಹುರುಳಿ", C.PULSE, 100, None, INDICATIVE),
    ("Cowpea", "ಅಲಸಂದೆ", C.PULSE, 90, None, INDICATIVE),
    ("Field Bean", "ಅವರೆ", C.PULSE, 120, None, INDICATIVE),
    # oilseeds
    ("Sunflower", "ಸೂರ್ಯಕಾಂತಿ", C.OILSEED, 100, None, INDICATIVE),
    ("Sesame", "ಎಳ್ಳು", C.OILSEED, 90, None, INDICATIVE),
    ("Soybean", "ಸೋಯಾಬೀನ್", C.OILSEED, 100, S.KHARIF, INDICATIVE),
    ("Mustard", "ಸಾಸಿವೆ", C.OILSEED, 110, S.RABI, INDICATIVE),
    ("Safflower", "ಕುಸುಬೆ", C.OILSEED, 130, S.RABI, INDICATIVE),
    ("Castor", "ಹರಳು", C.OILSEED, 150, None, INDICATIVE),
    # cash crops
    ("Tobacco", "ತಂಬಾಕು", C.CASH_CROP, 150, None, INDICATIVE),
    # plantation crops (migration 0013 moves the first three from cash_crop on existing installs)
    ("Coconut", "ತೆಂಗು", C.PLANTATION, 365, S.YEAR_ROUND, PERENNIAL),
    ("Arecanut", "ಅಡಿಕೆ", C.PLANTATION, 365, S.YEAR_ROUND, PERENNIAL),
    ("Coffee", "ಕಾಫಿ", C.PLANTATION, 365, S.YEAR_ROUND, PERENNIAL),
    ("Tea", "ಚಹಾ", C.PLANTATION, 365, S.YEAR_ROUND, PERENNIAL),
    ("Rubber", "ರಬ್ಬರ್", C.PLANTATION, 365, S.YEAR_ROUND, PERENNIAL),
    ("Cashew", "ಗೇರು", C.PLANTATION, 365, S.YEAR_ROUND, PERENNIAL),
    # flowers
    ("Chrysanthemum", "ಸೇವಂತಿಗೆ", C.FLOWER, 150, None, INDICATIVE),
    ("Jasmine", "ಮಲ್ಲಿಗೆ", C.FLOWER, 365, S.YEAR_ROUND, PERENNIAL),
    ("Rose", "ಗುಲಾಬಿ", C.FLOWER, 365, S.YEAR_ROUND, PERENNIAL),
    ("Crossandra", "ಕನಕಾಂಬರ", C.FLOWER, 365, S.YEAR_ROUND, PERENNIAL),
    # fodder
    ("Fodder Maize", "ಮೇವಿನ ಮೆಕ್ಕೆಜೋಳ", C.FODDER, 60, None, INDICATIVE),
    ("Fodder Sorghum", "ಮೇವಿನ ಜೋಳ", C.FODDER, 70, None, INDICATIVE),
    ("Napier Grass", None, C.FODDER, 365, S.YEAR_ROUND, PERENNIAL),
    ("Lucerne", None, C.FODDER, 365, S.YEAR_ROUND, PERENNIAL),
    # medicinal and aromatic
    ("Ashwagandha", "ಅಶ್ವಗಂಧ", C.MEDICINAL, 180, None, INDICATIVE),
    ("Tulsi", "ತುಳಸಿ", C.MEDICINAL, 90, None, INDICATIVE),
    ("Aloe Vera", "ಲೋಳೆಸರ", C.MEDICINAL, 365, S.YEAR_ROUND, PERENNIAL),
    ("Lemongrass", "ನಿಂಬೆ ಹುಲ್ಲು", C.MEDICINAL, 365, S.YEAR_ROUND, PERENNIAL),
]


def seed_payloads() -> list[CropCreate]:
    def build(
        name: str, local: str | None, category: C, days: int, season: S | None, notes: str | None = None
    ) -> CropCreate:
        data: dict[str, Any] = {
            "name": name,
            "local_name": local,
            "category": category,
            "typical_duration_days": days,
            "season": season,
            "notes": notes,
        }
        if name in _REFERENCES:
            y, cv, water = _REFERENCES[name]
            data |= {"reference_yield_kg_per_acre": y, "reference_yield_cv": cv, "water_need_mm": water}
        if (meta := EXISTING.get(name)) is not None:
            data |= {"scientific_name": meta.scientific, "aliases": list(meta.aliases), "crop_group": meta.group}
        return CropCreate.model_validate(data)

    def build_new(c: Any) -> CropCreate:
        # Kannada name deliberately empty: not invented; an admin adds a verified one (PATCH /crops/{id})
        return CropCreate.model_validate(
            {
                "name": c.name,
                "local_name": None,
                "category": c.category,
                "typical_duration_days": c.days,
                "season": c.season,
                "notes": c.notes,
                "scientific_name": c.meta.scientific,
                "aliases": list(c.meta.aliases),
                "crop_group": c.meta.group,
            }
        )

    return [build(*row) for row in _SEED] + [build(*row) for row in _MORE] + [build_new(c) for c in NEW]


def taken_names(session: Any) -> dict[str, str]:
    """Every name and alias already in the catalogue (lower case) -> the crop that owns it."""
    out: dict[str, str] = {}
    for crop in session.scalars(select(Crop)):
        for word in (crop.name, *(crop.aliases or [])):
            out[word.lower()] = crop.name
    return out


def reconcile(container: Container) -> tuple[int, int, list[str]]:
    """Fill EMPTY scientific name / aliases / group of existing crops and add missing A-Z crops. Never renames,
    re-categorises or overwrites an admin's values; a new crop whose name or alias already belongs to another crop is
    skipped (no duplicates). Returns (fields filled, crops created, skipped with reason)."""
    filled, skipped = 0, []
    with container.session_factory() as session:
        for crop in session.scalars(select(Crop)):
            meta = EXISTING.get(crop.name)
            if meta is None:
                continue
            if not crop.scientific_name:
                crop.scientific_name, filled = meta.scientific, filled + 1
            if not crop.aliases and meta.aliases:
                crop.aliases, filled = list(meta.aliases), filled + 1
            if crop.crop_group is None:
                crop.crop_group, filled = meta.group, filled + 1  # type: ignore[assignment]
        session.commit()
    created = 0
    for payload in seed_payloads():
        with container.session_factory() as session:
            taken = taken_names(session)
            if payload.name.lower() in taken and taken[payload.name.lower()] == payload.name:
                continue  # already present
            clash = [w for w in (payload.name, *payload.aliases) if w.lower() in taken]
            if clash:
                skipped.append(f"{payload.name}: '{clash[0]}' already belongs to {taken[clash[0].lower()]}")
                continue
            try:
                build_crop_service(session).create_crop(payload)
                created += 1
            except ConflictError:
                skipped.append(f"{payload.name}: name already exists")
    return filled, created, skipped


def seed_if_empty(container: Container) -> int:
    """Create the standard catalog when the crops table is completely EMPTY (a fresh install). Returns the number
    created. Never runs on a non-empty catalog, so crops an admin removed or renamed are never re-added."""
    with container.session_factory() as session:
        if session.scalar(select(func.count()).select_from(Crop)):
            return 0
    created = 0
    for payload in seed_payloads():
        with container.session_factory() as session:
            try:
                build_crop_service(session).create_crop(payload)
                created += 1
            except ConflictError:  # another worker seeded it at the same moment
                continue
    if created:
        with container.session_factory() as session:  # reference yields help the first predictions
            repo = CropRepository(session)
            for name, (y, cv, water) in _REFERENCES.items():
                crop = repo.get_by_name(name)
                if crop is not None:
                    crop.reference_yield_kg_per_acre = crop.reference_yield_kg_per_acre or Decimal(y)
                    crop.reference_yield_cv = crop.reference_yield_cv or Decimal(cv)
                    crop.water_need_mm = crop.water_need_mm or Decimal(water)
            session.commit()
    return created


def main(argv: Sequence[str] | None = None, container: Container | None = None) -> int:
    """Insert missing catalog crops. With --fill-references, also fill EMPTY reference fields of existing
    crops (never overwriting values an admin has set)."""
    fill = "--fill-references" in (argv or [])
    owns_container = container is None
    container = container or build_container(get_settings())
    created = skipped = filled = 0
    if "--reconcile" in (argv or []):
        try:
            done, added, refused = reconcile(container)
            print(f"Crop catalog reconciled: {done} empty metadata fields filled, {added} crops added")
            for line in refused:
                print(f"  skipped {line}")
            return 0
        finally:
            if owns_container:
                container.shutdown()
    try:
        for payload in seed_payloads():
            with container.session_factory() as session:
                try:
                    build_crop_service(session).create_crop(payload)
                    created += 1
                except ConflictError:
                    skipped += 1
        if fill:
            with container.session_factory() as session:
                repo = CropRepository(session)
                for name, (y, cv, water) in _REFERENCES.items():
                    crop = repo.get_by_name(name)
                    if crop is None:
                        continue
                    for field, value in (
                        ("reference_yield_kg_per_acre", y),
                        ("reference_yield_cv", cv),
                        ("water_need_mm", water),
                    ):
                        if getattr(crop, field) is None:
                            setattr(crop, field, Decimal(value))
                            filled += 1
                session.commit()
        suffix = f", {filled} empty reference fields filled" if fill else ""
        print(f"Crop catalog: {created} created, {skipped} already present{suffix}")
        return 0
    finally:
        if owns_container:
            container.shutdown()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
