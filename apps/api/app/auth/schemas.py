import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator
from pydantic_core import PydanticCustomError

from app.auth.models import Platform

NIGERIAN_PHONE_PATTERN = re.compile(r"^0(?:70|80|81|90|91)\d{8}$")


def validate_nigerian_phone(value: str) -> str:
    if not NIGERIAN_PHONE_PATTERN.fullmatch(value):
        raise ValueError("Enter an 11-digit Nigerian mobile number")
    return value


def to_e164(value: str) -> str:
    return "+234" + value[1:]


def is_strong_pin(value: str) -> bool:
    if re.fullmatch(r"\d{4}", value) is None or len(set(value)) == 1:
        return False
    digits = [int(digit) for digit in value]
    differences = [
        right - left for left, right in zip(digits, digits[1:], strict=False)
    ]
    return differences not in ([1, 1, 1], [-1, -1, -1])


class OTPRequest(BaseModel):
    phone_number: str

    _validate_phone = field_validator("phone_number")(validate_nigerian_phone)


class OTPVerifyRequest(OTPRequest):
    otp: str
    platform: Platform

    @field_validator("otp")
    @classmethod
    def validate_otp(cls, value: str) -> str:
        if not re.fullmatch(r"\d{6}", value):
            raise ValueError("OTP must contain exactly 6 digits")
        return value


class RefreshRequest(BaseModel):
    refresh_token: str


class PINPayload(BaseModel):
    pin: str

    @field_validator("pin")
    @classmethod
    def validate_pin(cls, value: str) -> str:
        if not is_strong_pin(value):
            raise PydanticCustomError(
                "pin_too_weak",
                "Choose a non-repeated, non-sequential 4-digit PIN",
            )
        return value


class PINRecoveryRequest(OTPRequest):
    pass


class MessageResponse(BaseModel):
    message: str


class PINVerifyResponse(BaseModel):
    unlocked: Literal[True] = True


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    phone_number: str
    first_name: str
    last_name: str
    email: str | None
    verified_cli: bool
    platform: str
    status: str


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    user: UserResponse
    is_new_user: bool


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
