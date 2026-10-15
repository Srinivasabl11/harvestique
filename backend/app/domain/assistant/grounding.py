"""Grounding check for optional LLM wording: every number in the LLM text must appear in the tool facts.

If the check fails, the deterministic template answer is used instead. This prevents an LLM from inventing
weather, market, prediction or availability numbers.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, InvalidOperation

NUMBER = re.compile(r"(?<![\w.])-?\d+(?:[.,]\d+)*(?![\w])")
KANNADA_DIGITS = str.maketrans("೦೧೨೩೪೫೬೭೮೯", "0123456789")


def numbers_in(text: str) -> set[Decimal]:
    out: set[Decimal] = set()
    for raw in NUMBER.findall(text.translate(KANNADA_DIGITS)):
        try:
            out.add(Decimal(raw.replace(",", "")).normalize())
        except InvalidOperation:
            continue
    return out


def fact_numbers(values: Iterable[object]) -> set[Decimal]:
    out: set[Decimal] = set()
    for v in values:
        if isinstance(v, bool):
            continue
        if isinstance(v, int | float | Decimal):
            d = Decimal(str(v))
            out.add(d.normalize())
            for step in (Decimal(1), Decimal("0.1")):  # allow rounding either way
                out.add(d.quantize(step, rounding=ROUND_FLOOR).normalize())
                out.add(d.quantize(step, rounding=ROUND_CEILING).normalize())
        elif isinstance(v, str):
            for n in numbers_in(v):
                out |= fact_numbers([n])
    return out


def grounded(text: str, facts: Iterable[object], *, max_chars: int = 1200) -> bool:
    if not text.strip() or len(text) > max_chars:
        return False
    allowed = fact_numbers(facts) | {Decimal(n) for n in range(0, 11)} | {Decimal(100)}
    return numbers_in(text) <= allowed
