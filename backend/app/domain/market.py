"""Choosing the market price for an estimate from stored AGMARKNET reports. Deterministic and testable.

Order: the farm's district (its APMC markets), else the farm's state, else neighbouring states. Within that scope the
latest reporting day is used; several markets on that day give the median of their min / modal / max prices.
Reports older than MAX_AGE_DAYS are not used. Prices are INR per quintal (100 kg) as reported; per kg = / 100.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from statistics import median


@dataclass(frozen=True, slots=True)
class MandiPrice:
    """One AGMARKNET report: a market's price for a commodity on one day, INR per quintal."""

    state: str
    district: str
    market: str
    commodity: str
    variety: str
    grade: str
    arrival_date: date
    min_price: Decimal  # INR per quintal
    modal_price: Decimal
    max_price: Decimal


FRESH_DAYS = 3  # reported within 3 days: "latest"
MAX_AGE_DAYS = 30  # older reports are not used for an estimate
NEIGHBOURS = {
    "Karnataka": ("Tamil Nadu", "Andhra Pradesh", "Telangana", "Kerala", "Keralam", "Maharashtra", "Goa"),
}
DEFAULT_STATE = "Karnataka"

# Harvestique crop name -> AGMARKNET commodity names. "Tomato", "Maize", "Jowar(Sorghum)" and
# "Red gram/Arhar/Tur(whole)" were seen in live data on 2026-10-14; the others follow AGMARKNET's published list and
# simply find no rows if a spelling differs (then the farmer is asked for a price).
AGMARKNET_NAMES: dict[str, tuple[str, ...]] = {
    "Tomato": ("Tomato",),
    "Onion": ("Onion",),
    "Potato": ("Potato",),
    "Brinjal": ("Brinjal",),
    "Cabbage": ("Cabbage",),
    "Cauliflower": ("Cauliflower",),
    "Carrot": ("Carrot",),
    "Beans": ("Beans",),
    "Cucumber": ("Cucumbar(Kheera)",),
    "Chilli": ("Green Chilli", "Dry Chillies"),
    "Green Chilli": ("Green Chilli",),
    "Okra": ("Bhindi(Ladies Finger)",),
    "Beetroot": ("Beetroot",),
    "Pumpkin": ("Pumpkin",),
    "Drumstick": ("Drumstick",),
    "Garlic": ("Garlic",),
    "Ginger": ("Ginger(Green)",),
    "Banana": ("Banana",),
    "Mango": ("Mango",),
    "Coconut": ("Coconut",),
    "Arecanut": ("Arecanut(Betelnut/Supari)",),
    "Paddy": ("Paddy(Dhan)(Common)",),
    "Rice": ("Rice",),
    "Ragi": ("Ragi (Finger Millet)",),
    "Maize": ("Maize",),
    "Jowar": ("Jowar(Sorghum)",),
    "Wheat": ("Wheat",),
    "Groundnut": ("Groundnut",),
    "Sunflower": ("Sunflower/Sunflower Seed", "Sunflower"),
    "Soybean": ("Soyabean",),
    "Cotton": ("Cotton",),
    "Red Gram": ("Red gram/Arhar/Tur(whole)", "Arhar (Tur/Red Gram)(Whole)"),
    "Tur": ("Red gram/Arhar/Tur(whole)", "Arhar (Tur/Red Gram)(Whole)"),
    "Bengal Gram": ("Bengal Gram(Gram)(Whole)",),
    "Green Gram": ("Green Gram (Moong)(Whole)",),
    "Black Gram": ("Black Gram (Urd Beans)(Whole)",),
    "Turmeric": ("Turmeric",),
}


def commodity_names(crop_name: str) -> tuple[str, ...]:
    return AGMARKNET_NAMES.get(crop_name, (crop_name,))


@dataclass(frozen=True, slots=True)
class PriceQuote:
    commodity: str
    scope: str  # "district" | "state" | "nearby"
    place: str  # e.g. "Kolar district" / "Karnataka" / "Tamil Nadu, Andhra Pradesh"
    markets: tuple[str, ...]
    arrival_date: date
    age_days: int
    min_per_quintal: Decimal
    modal_per_quintal: Decimal
    max_per_quintal: Decimal
    variety: str = ""

    @property
    def fresh(self) -> bool:
        return self.age_days <= FRESH_DAYS

    def per_kg(self) -> tuple[Decimal, Decimal, Decimal]:
        return (self.min_per_quintal / 100, self.modal_per_quintal / 100, self.max_per_quintal / 100)


# varieties that stand for the ordinary produce; specialty ones ("Popcorn" maize, "Basmati") are priced very
# differently and must not be mixed into one median (seen live: Hungund maize Local 2,450 vs Popcorn 4,700)
GENERIC_VARIETIES = frozenset(
    {"local", "other", "faq", "hybrid", "medium", "deshi", "common", "yellow", "red", "white"}
)


def _one_variety(rows: list[MandiPrice]) -> list[MandiPrice]:
    """The rows of ONE variety: generic varieties first, then the most reported one (ties: alphabetical)."""
    generic = [r for r in rows if r.variety.strip().lower() in GENERIC_VARIETIES or r.variety.strip() == r.commodity]
    pool = generic or rows
    counts: dict[str, int] = {}
    for r in pool:
        counts[r.variety.strip()] = counts.get(r.variety.strip(), 0) + 1
    if len({r.variety.strip().lower() for r in pool}) <= 1 or generic:
        # generic names (Local / Other / the commodity itself) describe the same ordinary produce
        return pool
    best = sorted(counts, key=lambda v: (-counts[v], v))[0]
    return [r for r in pool if r.variety.strip() == best]


def choose_quote(
    records: list[MandiPrice], *, state: str | None, district: str | None, today: date
) -> PriceQuote | None:
    """The price to use, or None when no usable report exists (then the farmer is asked)."""
    state = state or DEFAULT_STATE
    usable = [r for r in records if 0 <= (today - r.arrival_date).days <= MAX_AGE_DAYS]
    scopes: list[tuple[str, str, list[MandiPrice]]] = []
    if district:
        d = district.strip().lower()
        scopes.append(("district", f"{district} district", [r for r in usable if r.district.strip().lower() == d]))
    scopes.append(("state", state, [r for r in usable if r.state == state]))
    near = NEIGHBOURS.get(state, ())
    scopes.append(("nearby", "", [r for r in usable if r.state in near]))
    for scope, place, rows in scopes:
        if not rows:
            continue
        latest = max(r.arrival_date for r in rows)
        day_rows = _one_variety([r for r in rows if r.arrival_date == latest])
        if scope == "nearby":
            place = ", ".join(sorted({r.state for r in day_rows}))
        return PriceQuote(
            commodity=day_rows[0].commodity,
            scope=scope,
            place=place,
            markets=tuple(sorted({" ".join(r.market.split()) for r in day_rows})),
            variety=day_rows[0].variety.strip(),
            arrival_date=latest,
            age_days=(today - latest).days,
            min_per_quintal=Decimal(median(r.min_price for r in day_rows)),
            modal_per_quintal=Decimal(median(r.modal_price for r in day_rows)),
            max_per_quintal=Decimal(median(r.max_price for r in day_rows)),
        )
    return None
