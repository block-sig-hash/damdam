import os

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine

from app.auth.models import Platform, User
from app.profile.models import FamilyContact


@pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="real PostgreSQL constraint test runs in CI",
)
def test_one_family_contact_per_pilgrim_constraint() -> None:
    """AC-03.4: PostgreSQL rejects a second contact for the same pilgrim."""
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(phone_number="+2348012345690", platform=Platform.ANDROID)
        session.add(user)
        session.commit()
        session.refresh(user)

        session.add(
            FamilyContact(
                user_id=user.id,
                phone_number="+2349012345678",
            )
        )
        session.commit()
        session.add(
            FamilyContact(
                user_id=user.id,
                phone_number="+2348123456789",
            )
        )

        with pytest.raises(IntegrityError):
            session.commit()
