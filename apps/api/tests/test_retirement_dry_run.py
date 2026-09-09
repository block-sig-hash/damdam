"""US-30 -- the retirement cleanup plan reports, and must never execute.

The point of the dry run is that a founder decision about welfare data can be
taken against real numbers. A script that quietly deleted anything while
answering that question would be the worst possible failure, so the strongest
assertion here is the one that no row count changes.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlmodel import Session, func, select

from app.auth.models import User
from app.checkins.models import CheckIn
from app.profile.models import FamilyContact

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.retirement_dry_run import (  # noqa: E402
    RETIRED_TABLES,
    counts,
    locations_still_held,
)


def _seed(session: Session) -> None:
    user = User(phone_number="+2348012345678", platform="android")
    session.add(user)
    session.flush()
    session.add(
        CheckIn(
            user_id=user.id,
            client_generated_id=uuid4(),
            timestamp=datetime(2026, 7, 1, tzinfo=timezone.utc),
            received_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            latitude=21.42,
            longitude=39.82,
            location_retention_due_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
    )
    session.add(
        FamilyContact(
            user_id=user.id,
            name="Amina",
            phone_number="+2348087654321",
        )
    )
    session.commit()


def test_dry_run_counts_every_retired_table(session_factory) -> None:
    with session_factory() as session:
        _seed(session)
        report = counts(session)

    by_table = {row["table"]: row for row in report}
    assert by_table["check_ins"]["rows"] == 1
    assert by_table["family_contacts"]["rows"] == 1
    assert by_table["sos_alerts"]["rows"] == 0
    # Every entry explains why the data is still there, not just how much.
    assert all(row["note"] for row in report)


def test_dry_run_reports_locations_the_sweep_has_not_nulled(session_factory) -> None:
    with session_factory() as session:
        _seed(session)
        assert locations_still_held(session) == 1


def test_dry_run_deletes_nothing(session_factory) -> None:
    """The load-bearing assertion: reporting must not be destructive."""
    with session_factory() as session:
        _seed(session)
        before = {
            name: session.exec(select(func.count()).select_from(model)).one()
            for name, model, _ in RETIRED_TABLES
        }

        counts(session)
        locations_still_held(session)

        after = {
            name: session.exec(select(func.count()).select_from(model)).one()
            for name, model, _ in RETIRED_TABLES
        }
        assert after == before
        checkin = session.exec(select(CheckIn)).one()
        assert checkin.latitude is not None
        assert checkin.longitude is not None
