import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError

from app.auth.models import HTOApprovalStatus, Platform

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


class HTORegistrationRequest(BaseModel):
    business_name: str = Field(min_length=1, max_length=255)
    operator_name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    phone_number: str
    nahcon_licence_number: str = Field(min_length=1, max_length=50)

    _validate_phone = field_validator("phone_number")(validate_nigerian_phone)

    @field_validator("business_name", "operator_name", "nahcon_licence_number")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Field cannot be blank")
        return value.strip()

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
            raise ValueError("Enter a valid email address")
        return normalized


class HTOVerifyEmailRequest(BaseModel):
    token: str = Field(min_length=1)


class HTOLoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class HTOOperatorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    business_name: str = Field(validation_alias="name")
    operator_name: str = Field(validation_alias="primary_contact_name")
    email: str
    phone_number: str
    nahcon_licence_number: str
    email_verified: bool
    approval_status: HTOApprovalStatus
    created_at: datetime


class HTOLoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    operator: HTOOperatorResponse


class HTOOperatorListResponse(BaseModel):
    operators: list[HTOOperatorResponse]


class HTOApprovalResponse(BaseModel):
    approval_status: HTOApprovalStatus


class HTORejectionRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Field cannot be blank")
        return stripped
