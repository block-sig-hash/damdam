"""US-30 / AC-30.2 -- retired background work stops, without crashing workers.

The inventory calls the beat entries the highest-risk item in the retirement:
four of them polled every 10-30 seconds. Deleting the tasks outright would leave
an already-running beat sending messages for names no worker knows, and a queued
message from before the deploy would crash its worker in a retry loop. So the
task names stay registered and become refusals: they dispatch nothing, and they
do not even open a database session.
"""

from uuid import uuid4

import pytest

import app.worker as worker

RETIRED_BEAT_ENTRIES = (
    "enqueue-due-checkin-fallbacks",
    "enqueue-pending-checkin-notifications",
    "enqueue-pending-sos-notifications",
    "enqueue-due-sos-fallbacks",
)

RETAINED_BEAT_ENTRIES = (
    "enqueue-due-esim-issuance",
    "retention-null-checkin-locations",
    "retention-delete-sos-alerts",
    "retention-collapse-usage-polls",
    "retention-delete-call-logs",
    "retention-hard-delete-accounts",
    "retention-strip-device-user-links",
    "retention-delete-device-logs",
    "retention-delete-transactions",
)

RETIRED_TASKS = (
    "dispatch_sos_notification",
    "send_sos_sms_fallback",
    "enqueue_pending_sos_notifications",
    "enqueue_due_sos_fallbacks",
    "dispatch_checkin_notification",
    "send_checkin_sms_fallback",
    "enqueue_due_checkin_fallbacks",
    "enqueue_pending_checkin_notifications",
)


def test_retired_features_are_no_longer_scheduled() -> None:
    for entry in RETIRED_BEAT_ENTRIES:
        assert entry not in worker.celery_app.conf.beat_schedule


def test_retention_and_esim_work_stays_scheduled() -> None:
    """Retiring a feature must not switch off unrelated protection."""
    for entry in RETAINED_BEAT_ENTRIES:
        assert entry in worker.celery_app.conf.beat_schedule


def test_retired_tasks_are_still_registered() -> None:
    """An in-flight message from before the deploy must not crash its worker."""
    for name in RETIRED_TASKS:
        assert hasattr(worker, name), name


def test_retired_tasks_dispatch_nothing_and_touch_no_database(monkeypatch) -> None:
    def explode(*args, **kwargs):
        raise AssertionError("a retired task opened a database session")

    monkeypatch.setattr(worker, "create_session_factory", explode)
    monkeypatch.setattr(
        worker.celery_app,
        "send_task",
        lambda *args, **kwargs: pytest.fail("a retired task dispatched work"),
    )

    assert worker.dispatch_sos_notification(str(uuid4()), "whatsapp") is False
    assert worker.send_sos_sms_fallback(str(uuid4())) is False
    assert worker.enqueue_pending_sos_notifications() == 0
    assert worker.enqueue_due_sos_fallbacks() == 0
    assert worker.dispatch_checkin_notification(str(uuid4())) is False
    assert worker.send_checkin_sms_fallback(str(uuid4())) is False
    assert worker.enqueue_due_checkin_fallbacks() == 0
    assert worker.enqueue_pending_checkin_notifications() == 0


def test_retired_tasks_do_not_import_dispatch_machinery() -> None:
    """The dispatch services are the thing being retired; keep them unreachable."""
    source = (worker.__file__ or "")
    assert source
    with open(source, encoding="utf-8") as handle:
        text = handle.read()
    for symbol in (
        "SOSNotificationService",
        "CheckInNotificationService",
        "SOSProviderAdapter",
        "CelerySOSScheduler",
        "CeleryCheckInScheduler",
    ):
        assert symbol not in text, f"{symbol} is still wired into the worker"
