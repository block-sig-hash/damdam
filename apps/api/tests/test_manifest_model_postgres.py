import os

import pytest
from sqlalchemy import delete
from sqlmodel import Session, SQLModel, col, create_engine, select

from app.auth.models import (
    Manifest,
    ManifestPilgrim,
    ManifestValidationStatus,
    Organization,
    OrganizationType,
)


@pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="real PostgreSQL cascade test runs in CI",
)
def test_manifest_rows_are_owned_by_and_cascade_with_organization() -> None:
    """US-05 isolation: staged PII cannot outlive its owning organization."""
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        organization = Organization(
            org_type=OrganizationType.HTO_OPERATOR,
            name="Manifest HTO",
            primary_contact_name="Amina Yusuf",
            email="manifest-model@example.com",
            password_hash="hash",
            phone_number="+2348012345678",
            nahcon_licence_number="NAHCON-MANIFEST",
        )
        session.add(organization)
        session.commit()
        session.refresh(organization)
        manifest = Manifest(organization_id=organization.id, name="Test manifest")
        session.add(manifest)
        session.commit()
        session.refresh(manifest)
        manifest_id = manifest.id
        session.add(
            ManifestPilgrim(
                manifest_id=manifest.id,
                first_name="Aisha",
                last_name="Bello",
                phone_number="+2348012345678",
                row_number=2,
                validation_status=ManifestValidationStatus.VALID,
            )
        )
        session.commit()

        session.execute(
            delete(Organization).where(col(Organization.id) == organization.id)
        )
        session.commit()

        assert session.get(Manifest, manifest_id) is None
        assert session.exec(
            select(ManifestPilgrim).where(
                ManifestPilgrim.manifest_id == manifest_id
            )
        ).all() == []
