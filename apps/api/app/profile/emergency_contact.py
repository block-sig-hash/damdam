from dataclasses import dataclass
from uuid import UUID

from sqlmodel import Session, col, select

from app.auth.models import Manifest, ManifestPilgrim, Organization


@dataclass(frozen=True)
class EmergencyContact:
    hto_operator_name: str | None
    hto_operator_phone_number: str | None


class EmergencyContactService:
    """US-12 AC-12.2: the HTO operator's number is per-pilgrim, not static
    content, so it's read live from the pilgrim's assigned organization
    rather than bundled — see data-model.md §6.20."""

    def get(self, session: Session, user_id: UUID) -> EmergencyContact:
        organization = session.exec(
            select(Organization)
            .join(Manifest, col(Manifest.organization_id) == col(Organization.id))
            .join(
                ManifestPilgrim, col(ManifestPilgrim.manifest_id) == col(Manifest.id)
            )
            .where(col(ManifestPilgrim.user_id) == user_id)
            .order_by(col(ManifestPilgrim.id))
        ).first()
        if organization is None:
            # A direct/retail pilgrim (AC-07 account_source=direct) has no
            # manifest_pilgrims row and therefore no HTO — both fields are
            # null rather than an error, so the client just hides that row.
            return EmergencyContact(
                hto_operator_name=None, hto_operator_phone_number=None
            )
        return EmergencyContact(
            hto_operator_name=organization.name,
            hto_operator_phone_number=organization.phone_number,
        )
