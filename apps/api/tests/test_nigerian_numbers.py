import pytest

from app.voice.nigerian_numbers import (
    InvalidNigerianNumberError,
    normalize_nigerian_number,
)


@pytest.mark.parametrize(
    "raw",
    [
        "08031234567",
        "2348031234567",
        "+2348031234567",
        "0803 123 4567",
        "0803-123-4567",
        "+234 803 123 4567",
        "(0803) 123-4567",
    ],
)
def test_accepts_common_nigerian_formats(raw: str) -> None:
    assert normalize_nigerian_number(raw) == "+2348031234567"


@pytest.mark.parametrize(
    "raw",
    [
        "12345",  # short code
        "080312345",  # too short
        "080312345678",  # too long
        "+1 555 123 4567",  # non-Nigerian destination
        "07001234567",  # non-geographic/premium 700 range
        "09001234567",  # non-geographic/premium 900 range
        "00001234567",  # starts with 0 after country code
        "01031234567",  # starts with 1 after country code
        "not-a-number",
    ],
)
def test_rejects_invalid_or_unsupported_numbers(raw: str) -> None:
    with pytest.raises(InvalidNigerianNumberError):
        normalize_nigerian_number(raw)
