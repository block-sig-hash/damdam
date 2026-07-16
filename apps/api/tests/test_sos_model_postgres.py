import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlmodel import Session, SQLModel, col, create_engine, select

from app.auth.models import User
from app.sos.models import SOSAlert, SOSNotification
from app.sos.schemas import SOSCreate
from app.sos.service import SOSService


class RecordingScheduler:
    def __init__(self) -> None:
        self.dispatched: list[UUID] = []

    def schedule_dispatch(self, notification_id: UUID, channel) -> None:
        del channel
        self.dispatched.append(notification_id)


@pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="real PostgreSQL SOS idempotency race runs in CI",
)
def test_concurrent_same_uuid_creates_one_alert_and_four_notifications() -> None:
    """AC-16.7: rapid concurrent retries cannot duplicate alert dispatch."""
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    SQLModel.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        user = User(phone_number=f"+23480{uuid4().hex[:8]}", platform="android")
        session.add(user)
        session.commit()
        session.refresh(user)
        session.expunge(user)
    scheduler = RecordingScheduler()
    service = SOSService(scheduler, lambda: now)
    payload = SOSCreate(client_generated_id=uuid4(), timestamp=now)
    barrier = Barrier(2)

    def create() -> UUID:
        with Session(engine) as session:
            barrier.wait()
            return service.create(session, user, payload).id

    with ThreadPoolExecutor(max_workers=2) as executor:
        ids = list(executor.map(lambda _: create(), range(2)))

    assert ids[0] == ids[1]
    with Session(engine) as session:
        alerts = session.exec(select(SOSAlert).where(SOSAlert.user_id == user.id)).all()
        notifications = session.exec(
            select(SOSNotification).where(
                col(SOSNotification.sos_alert_id).in_([alert.id for alert in alerts])
            )
        ).all()
        assert len(alerts) == 1
        assert len(notifications) == 4
    assert len(scheduler.dispatched) == 4
