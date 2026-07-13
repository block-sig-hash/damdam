import os
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine

from app.auth.models import HTOOperator, HTORefreshToken


@pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="real PostgreSQL constraint test runs in CI",
)
def test_hto_unique_constraints_against_postgres() -> None:
    """AC-04.1: operator emails and refresh-token hashes are unique."""
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        first = HTOOperator(
            business_name="First HTO",
            operator_name="First Operator",
            email="unique@example.com",
            password_hash="hash",
            phone_number="+2348012345678",
            nahcon_licence_number="LIC-ONE",
        )
        session.add(first)
        session.commit()
        session.refresh(first)

        session.add(
            HTOOperator(
                business_name="Second HTO",
                operator_name="Second Operator",
                email="unique@example.com",
                password_hash="hash",
                phone_number="+2348012345679",
                nahcon_licence_number="LIC-TWO",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        token_hash = "b" * 64
        session.add(
            HTORefreshToken(
                id=uuid4(),
                hto_operator_id=first.id,
                token_hash=token_hash,
                expires_at=first.created_at,
            )
        )
        session.commit()
        session.add(
            HTORefreshToken(
                id=uuid4(),
                hto_operator_id=first.id,
                token_hash=token_hash,
                expires_at=first.created_at,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
