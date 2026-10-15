"""Phone number normalisation to E.164 (stored form used for uniqueness and login)."""

from __future__ import annotations

import re

_SEPARATORS = re.compile(r"[\s\-().]")
_E164 = re.compile(r"^\+[1-9]\d{7,14}$")
_INDIAN_MOBILE = re.compile(r"^[6-9]\d{9}$")

PHONE_ERROR = "Enter a valid phone number, e.g. +919876543210 or a 10-digit Indian mobile number"


def normalize_phone(raw: str) -> str:
    """Return the E.164 form of `raw` or raise ValueError.

    Accepts: +919876543210, 919876543210, 09876543210, 9876543210 (assumed India),
    00-prefixed international numbers, and common separators (spaces, dashes, brackets).
    """
    s = _SEPARATORS.sub("", raw.strip())
    if _INDIAN_MOBILE.fullmatch(s):
        s = "+91" + s
    elif re.fullmatch(r"0[6-9]\d{9}", s):
        s = "+91" + s[1:]
    elif re.fullmatch(r"91[6-9]\d{9}", s):
        s = "+" + s
    elif s.startswith("00"):
        s = "+" + s[2:]
    if not _E164.fullmatch(s):
        raise ValueError(PHONE_ERROR)
    return s
