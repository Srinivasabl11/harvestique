"""Numbers in income-estimate conversations: what each number IS (price per kg, harvest, cost, income, acres), never
guessed. A number whose meaning the person did not state is returned as `unclear`, so the assistant asks about it.

Works on English and Kannada word order ("price 20 rupees per kg", "ಕೆಜಿಗೆ 20 ರೂಪಾಯಿ"), Indian digit grouping
("1,20,000"), lakh/thousand words, Kannada digits and kg / quintal / tonne / acre / gunta units. Pure functions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from decimal import Decimal

KANNADA_DIGITS = str.maketrans("೦೧೨೩೪೫೬೭೮೯", "0123456789")
_INVISIBLE = re.compile("[​-‍﻿]")

# what a clause is about (a clause = text between commas, "and", "ಮತ್ತು", ";")
COST = re.compile(r"\b(costs?|spend|spending|expenses?|expenditure|investment|invest)\b|ಖರ್ಚ|ವೆಚ್ಚ|ಬಂಡವಾಳ")
INCOME = re.compile(r"\b(income|revenue|earn(ing|ings)?|sales?|sell (it )?for)\b|ಆದಾಯ|ಸಂಪಾದನೆ|ಮಾರಾಟ|ಗಳಿಕೆ")
YIELD = re.compile(r"\b(yield|harvest|produce|production|output|get)\b|ಇಳುವರಿ|ಉತ್ಪಾದನೆ|ಫಸಲು|ಬರುತ್ತ|ಸಿಗುತ್ತ")
PRICE = re.compile(r"\b(price|rate|selling at|sell at)\b|ಬೆಲೆ|ದರ|ರೇಟ್")
TOTAL = re.compile(r"\b(total|in all|altogether|for all)\b|ಒಟ್ಟು|ಎಲ್ಲಾ")
PER_ACRE = re.compile(r"\b(per|an|a|each|every) acre\b|/\s*acre|ಎಕರೆಗೆ|ಪ್ರತಿ ಎಕರೆ")
# a quantity of an INPUT ("50 kg of seed") is not a harvest
INPUTS = re.compile(
    r"\b(seeds?|seedlings?|saplings?|nursery|fertili[sz]ers?|urea|dap|manure|compost|pesticides?)\b"
    r"|ಬೀಜ|ಸಸಿ|ಗೊಬ್ಬರ|ಯೂರಿಯಾ|ಕೀಟನಾಶಕ"
)
# what was ACTUALLY harvested ("I harvested only 50 kg"), not an expected yield
ACTUAL = re.compile(r"\b(harvested|i got|we got|got only|picked|i sold|we sold)\b|ಕೊಯ್ಲು ಮಾಡಿದ|ಸಿಕ್ಕಿತು|ಸಿಕ್ಕಿದೆ|ಬಂತು|ಬಂದಿದೆ")

_NUM = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(lakhs?|lacs?|ಲಕ್ಷ\S*|thousand|ಸಾವಿರ\S*|k\b)?")
_MULT = {"l": Decimal(100000), "ಲ": Decimal(100000), "t": Decimal(1000), "ಸ": Decimal(1000), "k": Decimal(1000)}
_CUR_AFTER = re.compile(r"^(₹|rs\.?(?!\w)|inr\b|rupees?\b|/-|ರೂಪಾಯಿ\S*|ರೂ\.?)\s*")
_CUR_BEFORE = re.compile(r"(₹|\brs\.?|\binr|\brupees?)\s*$")
_MASS = {
    "kg": Decimal(1),
    "kgs": Decimal(1),
    "kilo": Decimal(1),
    "kilos": Decimal(1),
    "kilogram": Decimal(1),
    "kilograms": Decimal(1),
    "ಕೆಜಿ": Decimal(1),
    "ಕಿಲೋ": Decimal(1),
    "quintal": Decimal(100),
    "quintals": Decimal(100),
    "qtl": Decimal(100),
    "qtls": Decimal(100),
    "ಕ್ವಿಂಟಾಲ್": Decimal(100),
    "ಕ್ವಿಂಟಲ್": Decimal(100),
    "tonne": Decimal(1000),
    "tonnes": Decimal(1000),
    "ton": Decimal(1000),
    "tons": Decimal(1000),
    "ಟನ್": Decimal(1000),
}
_MASS_AFTER = re.compile(r"^(kilograms?|kilos?|kgs?|quintals?|qtls?|tonnes?|tons?|ಕೆಜಿ|ಕಿಲೋ|ಕ್ವಿಂಟಾಲ್|ಕ್ವಿಂಟಲ್|ಟನ್)(?![a-z])")
_AREA_AFTER = re.compile(r"^(acres?|ಎಕರೆ|guntas?|ಗುಂಟೆ)")
# "20 rupees per kg", "₹2000/quintal", "50000 per acre"
_PER_AFTER = re.compile(
    r"^(/|per\b|a\b|an\b|each\b|ಪ್ರತಿ)\s*(kgs?|kilos?|ಕೆಜಿ|ಕಿಲೋ|quintals?|qtls?|ಕ್ವಿಂಟಾಲ್|ಕ್ವಿಂಟಲ್|tonnes?|tons?|ಟನ್|acres?|ಎಕರೆ)"
)
# Kannada (and "per kg 20") puts the unit first: "ಕೆಜಿಗೆ 20 ರೂಪಾಯಿ", "ಎಕರೆಗೆ 30000"
_PER_BEFORE = re.compile(r"(ಕೆಜಿಗೆ|ಕಿಲೋಗೆ|ಕ್ವಿಂಟಾಲ್ಗೆ|ಕ್ವಿಂಟಲ್ಗೆ|ಟನ್ಗೆ|ಎಕರೆಗೆ|per (?:kg|quintal|tonne|ton|acre))\s*(?:₹|rs\.?|ರೂ\.?)?\s*$")
_KN_WORDS = {"ಅರ್ಧ": "0.5", "ಒಂದು": "1", "ಒಂದೂವರೆ": "1.5", "ಎರಡು": "2", "ಮೂರು": "3", "ನಾಲ್ಕು": "4", "ಐದು": "5", "ಹತ್ತು": "10"}
_EN_WORDS = {
    "half": "0.5",
    "one": "1",
    "an": "1",
    "a": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "ten": "10",
}
_WORD_ACRES = re.compile(
    r"(?:^|\s)(half|one|an|a|two|three|four|five|ten|ಅರ್ಧ|ಒಂದೂವರೆ|ಒಂದು|ಎರಡು|ಮೂರು|ನಾಲ್ಕು|ಐದು|ಹತ್ತು)\s+(acres?|ಎಕರೆ)"
)


def _unit_factor(unit: str) -> Decimal:
    unit = unit.lower()
    for key, factor in _MASS.items():
        if unit.startswith(key):
            return factor
    if unit.startswith(("quintal", "qtl", "ಕ್ವಿಂ")):
        return Decimal(100)
    if unit.startswith(("ton", "ಟನ್")):
        return Decimal(1000)
    return Decimal(1)


@dataclass(frozen=True)
class Unclear:
    """A number the person gave without saying what it is ('20 kg', '₹50,000')."""

    text: str
    kind: str  # "money" | "mass" | "plain"


@dataclass
class Inputs:
    """What the conversation has established. scope: 'acre' (per acre), 'total' (whole area) or None (not said)."""

    acres: Decimal | None = None
    price_per_kg: Decimal | None = None
    harvest_kg: Decimal | None = None
    harvest_scope: str | None = None
    harvest_actual: bool = False  # what was harvested, not an expected yield
    cost: Decimal | None = None
    cost_scope: str | None = None
    income: Decimal | None = None
    income_scope: str | None = None
    unclear: list[Unclear] = field(default_factory=list)

    def merged_with(self, newer: Inputs) -> Inputs:
        """Newer statements win (corrections); an unclear number is dropped once a newer message states what it is
        (e.g. '20 kg is the harvest')."""
        out = replace(self, unclear=list(self.unclear))
        if newer.acres is not None:
            out.acres = newer.acres
        if newer.price_per_kg is not None:
            out.price_per_kg = newer.price_per_kg
        if newer.harvest_kg is not None:
            out.harvest_kg, out.harvest_scope = newer.harvest_kg, newer.harvest_scope
            out.harvest_actual = newer.harvest_actual
        if newer.cost is not None:
            out.cost, out.cost_scope = newer.cost, newer.cost_scope
        if newer.income is not None:
            out.income, out.income_scope = newer.income, newer.income_scope
        stated = {_digits(v) for v in (newer.price_per_kg, newer.harvest_kg, newer.cost, newer.income) if v is not None}
        stated |= {
            _digits(v * f)
            for v in (newer.harvest_kg, newer.price_per_kg)
            if v is not None
            for f in (Decimal("0.01"), Decimal("0.001"), Decimal(100), Decimal(1000))
        }  # '20 quintal' states the earlier '20'
        out.unclear = [u for u in out.unclear if _digits_of_text(u.text) not in stated] + list(newer.unclear)
        return out


def _digits(v: Decimal) -> str:
    return f"{v.normalize():f}"


def inr(v: Decimal) -> str:
    """Indian digit grouping, at most 2 decimals: 120000 -> '1,20,000'; 12.5 -> '12.5'."""
    v = v.quantize(Decimal("0.01"))
    sign, whole, frac = ("-" if v < 0 else ""), f"{abs(v):f}".split(".")[0], f"{abs(v):f}".split(".")[1].rstrip("0")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = [head[max(0, i - 2) : i] for i in range(len(head), 0, -2)][::-1]
        whole = ",".join([*groups, tail])
    return f"{sign}{whole}{'.' + frac if frac else ''}"


def _digits_of_text(text: str) -> str:
    m = _NUM.search(_prepare(text))
    if not m:
        return ""
    value = Decimal(m.group(1)) * (_MULT.get(m.group(2)[0], Decimal(1)) if m.group(2) else Decimal(1))
    return _digits(value)


def _prepare(text: str) -> str:
    text = _INVISIBLE.sub("", text.lower().translate(KANNADA_DIGITS))
    text = re.sub(r"(?<=\d),(?=\d{2,3}(?!\d))", "", text)  # 50,000 and 1,20,000 -> plain digits
    text = re.sub(r"(?<=\d),(?=\d{2,3}(?!\d))", "", text)
    return text


def _clauses(text: str) -> list[str]:
    return [c.strip() for c in re.split(r"[,;]|\.(?!\d)|\band\b|\bthen\b|ಮತ್ತು|ಹಾಗೂ|\n", text) if c.strip()]


def parse(text: str) -> Inputs:
    """The numbers in ONE message and what each one is. Numbers without a stated meaning go to `unclear`."""
    out = Inputs()
    prepared = _prepare(text)
    if m := _WORD_ACRES.search(prepared):
        word = m.group(1)
        out.acres = Decimal(_KN_WORDS.get(word) or _EN_WORDS.get(word, "1"))
    for clause in _clauses(prepared):
        cost, income, harvest, price = (
            COST.search(clause),
            INCOME.search(clause),
            YIELD.search(clause),
            PRICE.search(clause),
        )
        scope = "acre" if PER_ACRE.search(clause) else ("total" if TOTAL.search(clause) else None)
        for m in _NUM.finditer(clause):
            value = Decimal(m.group(1))
            if m.group(2):
                value *= _MULT.get(m.group(2)[0], Decimal(1))
            before, after = clause[: m.start()], clause[m.end() :].lstrip()
            if a := _AREA_AFTER.match(after):
                out.acres = value / 40 if a.group(1).startswith(("gunta", "ಗುಂಟೆ")) else value
                continue
            money = bool(_CUR_AFTER.match(after) or _CUR_BEFORE.search(before))
            rest = _CUR_AFTER.sub("", after, count=1)
            mass = _MASS_AFTER.match(rest)
            per = _PER_AFTER.match(rest[mass.end() :].lstrip() if mass else rest)
            per_unit = per.group(2) if per else None
            if per_unit is None and (pb := _PER_BEFORE.search(before)):
                per_unit = pb.group(1).replace("per ", "").replace("ಗೆ", "")
            per_acre = per_unit is not None and per_unit.startswith(("acre", "ಎಕರೆ"))
            if (money or price) and per_unit and not per_acre and not mass:
                out.price_per_kg = value / _unit_factor(per_unit)  # "₹2000 per quintal" = ₹20 per kg
                continue
            if mass:
                actual = ACTUAL.search(clause)
                if INPUTS.search(clause):
                    out.unclear.append(Unclear(f"{_digits(value)} {mass.group(1)}", "input"))
                elif harvest or actual or per_acre or (scope is not None and not (cost or income or price)):
                    out.harvest_kg = value * _unit_factor(mass.group(1))
                    # "I harvested 50 kg from one acre": the whole area's harvest unless "per acre" is said
                    out.harvest_scope = "acre" if per_acre else (scope or ("total" if actual else None))
                    out.harvest_actual = bool(actual)
                else:
                    out.unclear.append(Unclear(f"{_digits(value)} {mass.group(1)}", "mass"))
                continue
            own_scope = "acre" if per_acre else scope
            if cost and not income:
                out.cost, out.cost_scope = value, own_scope
            elif income and not cost:
                out.income, out.income_scope = value, own_scope
            else:
                out.unclear.append(
                    Unclear(f"₹{inr(value)}" if money else _digits(value), "money" if money else "plain")
                )
    return out


def conversation_inputs(messages: list[str]) -> Inputs:
    """Merge the estimate messages of the current conversation, oldest first; later statements correct earlier ones."""
    total = Inputs()
    for message in messages:
        total = total.merged_with(parse(message))
    return total


def has_numbers(text: str) -> bool:
    return bool(_NUM.search(_prepare(text)))
