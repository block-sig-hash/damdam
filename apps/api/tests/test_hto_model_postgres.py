import os
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine

from app.auth.models import Organization, OrganizationRefreshToken, OrganizationType


@pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="real PostgreSQL constraint test runs in CI",
)
def test_hto_unique_constraints_against_postgres() -> None:
    """AC-04.1: operator emails and refresh-token hashes are unique."""
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        first = Organization(
            org_type=OrganizationType.HTO_OPERATOR,
            name="First HTO",
            primary_contact_name="First Operator",
            email="unique@example.com",
            password_hash="hash",
            phone_number="+2348012345678",
            nahcon_licence_number="LIC-ONE",
        )
        session.add(first)
        session.commit()
        session.refresh(first)

        session.add(
            Organization(
                org_type=OrganizationType.HTO_OPERATOR,
                name="Second HTO",
                primary_contact_name="Second Operator",
                email="unique@example.com",
                password_hash="hash",
                phone_number="+2348012345679",
                nahcon_licence_number="LIC-TWO",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.add(
            Organization(
                org_type=OrganizationType.HTO_OPERATOR,
                name="Unlicensed HTO",
                primary_contact_name="Missing Licence",
                email="unlicensed@example.com",
                password_hash="hash",
                phone_number="+2348012345682",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        token_hash = "b" * 64
        session.add(
            OrganizationRefreshToken(
                id=uuid4(),
                organization_id=first.id,
                token_hash=token_hash,
                expires_at=first.created_at,
            )
        )
        session.commit()
        session.add(
            OrganizationRefreshToken(
                id=uuid4(),
                organization_id=first.id,
                token_hash=token_hash,
                expires_at=first.created_at,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


@pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="real PostgreSQL constraint test runs in CI",
)
@pytest.mark.parametrize(
    "org_type", [OrganizationType.ENTERPRISE, OrganizationType.GOVERNMENT]
)
def test_non_hto_organizations_do_not_require_hajj_credentials(
    org_type: OrganizationType,
) -> None:
    """Reserved organization types keep HTO-only credentials conditional."""
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            Organization(
                org_type=org_type,
                name=f"{org_type.value.title()} Customer",
                primary_contact_name="Future Customer",
                email=f"{org_type.value}@example.com",
                password_hash="hash",
                phone_number="+2348012345680",
            )
        )
        session.commit()

        session.add(
            Organization(
                org_type=org_type,
                name="Invalid Future Customer",
                primary_contact_name="Future Customer",
                email=f"invalid-{org_type.value}@example.com",
                password_hash="hash",
                phone_number="+2348012345681",
                nahcon_licence_number="NOT-APPLICABLE",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
