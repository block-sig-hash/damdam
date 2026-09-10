import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.organizations.models import (
    InvitationStatus,
    MembershipStatus,
    OrganizationRole,
)


class MemberSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    role: OrganizationRole
    status: MembershipStatus
    joined_at: datetime
    revoked_at: datetime | None = None


class MemberListResponse(BaseModel):
    members: list[MemberSummary]


class RoleChangeRequest(BaseModel):
    role: OrganizationRole


class InvitationRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: OrganizationRole

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        # The same shape check and normalisation as the existing auth schemas,
        # so an address invited here matches the verified identifier chunk 06
        # stored for the person who accepts it.
        normalized = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
            raise ValueError("Enter a valid email address")
        return normalized


class InvitationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    role: OrganizationRole
    invited_value: str
    status: InvitationStatus
    expires_at: datetime | None = None
    created_at: datetime


class InvitationListResponse(BaseModel):
    invitations: list[InvitationSummary]


class InvitationCreatedResponse(BaseModel):
    """The raw token is returned to the *caller*, never persisted.

    Chunk 07 has no configured mail provider (chunk 06 left delivery on a
    recording transport), so the token is handed back for the dashboard to send
    rather than fabricating a delivery that did not happen.
    """

    invitation: InvitationSummary
    token: str


class InvitationAcceptRequest(BaseModel):
    token: str | None = None
    invitation_id: UUID | None = None


class MembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    organization_id: UUID
    user_id: UUID
    role: OrganizationRole
    status: MembershipStatus


class OrganizationSummary(BaseModel):
    id: UUID
    name: str
    role: OrganizationRole


class OrganizationListResponse(BaseModel):
    organizations: list[OrganizationSummary]


class MfaEnrollmentResponse(BaseModel):
    """Shown once. The secret is never readable again after this response."""

    secret: str
    otpauth_uri: str


class MfaCodeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=64)


class MfaConfirmedResponse(BaseModel):
    recovery_codes: list[str]


class StepUpRequest(BaseModel):
    code: str | None = Field(default=None, min_length=6, max_length=64)
    recovery_code: str | None = Field(default=None, min_length=8, max_length=64)


class StepUpResponse(BaseModel):
    expires_at: datetime
