import os
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine

from app.auth.models import Platform, RefreshToken, User


@pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="real PostgreSQL constraint test runs in CI",
)
def test_auth_unique_constraints_against_postgres() -> None:
    """US-01: phone numbers and hashed refresh tokens remain globally unique."""
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    SQLModel.metadata.create_all(engine)
    phone_number = "+2348012345678"

    with Session(engine) as session:
        first = User(
            phone_number=phone_number,
            first_name="",
            last_name="",
            platform=Platform.ANDROID,
        )
        session.add(first)
        session.commit()
        session.refresh(first)

        session.add(
            User(
                phone_number=phone_number,
                first_name="",
                last_name="",
                platform=Platform.IOS,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        token_hash = "a" * 64
        session.add(
            RefreshToken(
                id=uuid4(),
                user_id=first.id,
                token_hash=token_hash,
                expires_at=first.created_at,
            )
        )
        session.commit()
        session.add(
            RefreshToken(
                id=uuid4(),
                user_id=first.id,
                token_hash=token_hash,
                expires_at=first.created_at,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
