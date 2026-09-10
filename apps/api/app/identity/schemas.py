"""Request and response shapes for the email identity endpoints (US-29).

Email is typed as `str` with an explicit validator, matching the convention
already used by the organization registration schemas, rather than pulling in
pydantic's EmailStr and the email-validator dependency for one field.
"""

import re

from pydantic import BaseModel, Field, field_validator

from app.auth.models import Locale
from app.auth.schemas import UserResponse

EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


class EmailIdentifierRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    locale: Locale = Locale.EN

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("Enter a valid email address")
        return normalized


class IdentityTokenRequest(BaseModel):
    token: str = Field(min_length=16, max_length=256)


class IdentityMessageResponse(BaseModel):
    """Deliberately says nothing about whether the address is known.

    The same body is returned for a registered address, an unregistered one and
    an unverified claim, so the response cannot be used to test who has an
    account.
    """

    message: str


class RecoverySessionResponse(BaseModel):
    access_token: str
    refresh_token: str
    user: UserResponse
