import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from uuid import UUID, uuid4

import fakeredis
import pytest
from sqlmodel import Session, SQLModel, col, create_engine, select

from app.auth.models import User
from app.checkins.models import CheckIn, CheckInNotification
from app.checkins.schemas import CheckInCreate
from app.checkins.service import CheckInService
from app.profile.models import FamilyContact


class RecordingScheduler:
    def __init__(self) -> None:
        self.dispatched: list[UUID] = []

    def schedule_dispatch(self, notification_id: UUID) -> None:
        self.dispatched.append(notification_id)

    def schedule_fallback(self, notification_id: UUID, countdown: int) -> None:
        del notification_id, countdown


@pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="real PostgreSQL check-in idempotency race runs in CI",
)
def test_concurrent_same_uuid_creates_one_checkin_and_one_notification() -> None:
    """AC-15.4: concurrent lost-response retries cannot duplicate WhatsApp."""
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    SQLModel.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    suffix = uuid4().hex[:8]
    with Session(engine) as session:
        user = User(phone_number=f"+23480{suffix}", platform="android")
        session.add(user)
        session.flush()
        session.add(FamilyContact(user_id=user.id, phone_number="+2349012345678"))
        session.commit()
        session.refresh(user)
        session.expunge(user)

    scheduler = RecordingScheduler()
    service = CheckInService(
        fakeredis.FakeRedis(decode_responses=True), scheduler, lambda: now
    )
    payload = CheckInCreate(client_generated_id=uuid4(), timestamp=now)
    barrier = Barrier(2)

    def create() -> UUID:
        with Session(engine) as session:
            barrier.wait()
            return service.create(session, user, payload).id

    with ThreadPoolExecutor(max_workers=2) as executor:
        ids = list(executor.map(lambda _: create(), range(2)))

    assert ids[0] == ids[1]
    with Session(engine) as session:
        checkins = session.exec(
            select(CheckIn).where(CheckIn.user_id == user.id)
        ).all()
        notifications = session.exec(
            select(CheckInNotification).where(
                col(CheckInNotification.check_in_id).in_(
                    [checkin.id for checkin in checkins]
                )
            )
        ).all()
        assert len(checkins) == 1
        assert len(notifications) == 1
    assert len(scheduler.dispatched) == 1
