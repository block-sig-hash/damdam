from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.auth.models import ManifestStatus, ManifestValidationStatus


class ManifestCreateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ManifestCreateResponse(BaseModel):
    manifest_id: UUID
    status: Literal[ManifestStatus.DRAFT] = ManifestStatus.DRAFT


class ManifestIssue(BaseModel):
    row_number: int
    reason: str


class ManifestPreviewRow(BaseModel):
    id: UUID
    row_number: int
    first_name: str
    last_name: str
    phone_number: str
    passport_number: str | None
    seat_number: str | None
    validation_status: Literal[
        ManifestValidationStatus.VALID, ManifestValidationStatus.DUPLICATE_WARNING
    ]
    warning: str | None = None


class ManifestUploadResponse(BaseModel):
    total_rows: int
    valid_rows: int
    invalid_rows: list[ManifestIssue]
    preview: list[ManifestPreviewRow]


class ManifestConfirmResponse(BaseModel):
    status: Literal[ManifestStatus.VALIDATED] = ManifestStatus.VALIDATED
    pilgrim_count: int


class ManifestSummary(BaseModel):
    id: UUID
    name: str | None
    status: ManifestStatus
    valid_rows: int
    created_at: datetime


class ManifestListResponse(BaseModel):
    manifests: list[ManifestSummary]
