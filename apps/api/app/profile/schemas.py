from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.auth.schemas import validate_nigerian_phone


class FamilyContactCreate(BaseModel):
    phone_number: str
    name: str | None = Field(default=None, max_length=100)

    _validate_phone = field_validator("phone_number")(validate_nigerian_phone)


class FamilyContactUpdate(BaseModel):
    phone_number: str | None = None
    name: str | None = Field(default=None, max_length=100)

    @field_validator("phone_number")
    @classmethod
    def validate_optional_phone(cls, value: str | None) -> str | None:
        return validate_nigerian_phone(value) if value is not None else None

    @model_validator(mode="after")
    def require_update(self) -> "FamilyContactUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        return self


class FamilyContactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    phone_number: str
    name: str | None
    notified_of_nomination: bool


class EmergencyContactResponse(BaseModel):
    hto_operator_name: str | None
    hto_operator_phone_number: str | None
