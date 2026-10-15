import pytest

from app.core.phone import normalize_phone


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("9876543210", "+919876543210"),
        ("98765 43210", "+919876543210"),
        ("098765-43210", "+919876543210"),
        ("919876543210", "+919876543210"),
        ("+91 98765 43210", "+919876543210"),
        ("0091 9876543210", "+919876543210"),
        ("+14155552671", "+14155552671"),
        ("  +919876543210  ", "+919876543210"),
    ],
)
def test_normalises_to_e164(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "12345", "5876543210", "+0123456789", "+91 98765", "9876543210123456789"])
def test_rejects_invalid(raw):
    with pytest.raises(ValueError, match="valid phone"):
        normalize_phone(raw)
