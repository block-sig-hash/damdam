import pytest
from pydantic import ValidationError

from app.auth.schemas import OTPRequest


@pytest.mark.parametrize(
    "phone_number",
    ["07012345678", "08012345678", "08112345678", "09012345678", "09112345678"],
)
def test_accepts_valid_nigerian_mobile_numbers(phone_number: str) -> None:
    """AC-01.1: accepted prefixes are local-format Nigerian mobile numbers."""
    assert OTPRequest(phone_number=phone_number).phone_number == phone_number


@pytest.mark.parametrize(
    "phone_number",
    [
        "+2348012345678",
        "2348012345678",
        "0801234567",
        "080123456789",
        "07112345678",
        "080 1234 5678",
        "0801234567a",
    ],
)
def test_rejects_international_and_invalid_numbers(phone_number: str) -> None:
    """AC-01.2: international and malformed numbers are rejected at entry."""
    with pytest.raises(ValidationError):
        OTPRequest(phone_number=phone_number)
