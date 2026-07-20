import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func
from sqlmodel import Session, SQLModel, create_engine, select

from app.audit.models import AuditEventType, AuditLog, AuditOutcome
from app.auth.models import PricingTier, RefreshToken, User, UserStatus
from app.checkins.models import CheckIn
from app.esim.models import (
    DailyUsageSummary,
    DeviceCompatibilityLog,
    EsimAggregator,
    EsimProfile,
    EsimProfileStatus,
    UsagePoll,
)
from app.packages.models import (
    Package,
    PackageSource,
    PackageStatus,
    PaymentProcessor,
    Transaction,
    TransactionStatus,
)
from app.retention.service import RetentionService
from app.sos.models import SOSAlert
from app.voice.models import CallDirection, CallLog, CallType

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="real PostgreSQL retention tests run in CI",
)

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def postgres_engine():
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    SQLModel.metadata.create_all(engine)
    return engine


def _user(session: Session, label: str) -> User:
    suffix = uuid4().hex[:8]
    user = User(
        phone_number=f"+23480{suffix}",
        first_name=label,
        platform="android",
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _package(
    session: Session, user: User, purchased_at: datetime, expires_at: datetime
) -> Package:
    suffix = uuid4().hex
    tier = PricingTier(
        name=f"Retention-{suffix}",
        usd_reference_price=Decimal("10.00"),
        data_gb=1,
        pstn_minutes=10,
        wholesale_usd_price=Decimal("8.00"),
        ngn_price=Decimal("1000.00"),
    )
    session.add(tier)
    session.commit()
    session.refresh(tier)
    package = Package(
        user_id=user.id,
        pricing_tier_id=tier.id,
        source=PackageSource.RETAIL,
        status=PackageStatus.ACTIVE,
        data_gb_total=1,
        data_gb_remaining=Decimal("1.00"),
        pstn_minutes_total=10,
        pstn_minutes_remaining=Decimal("10.00"),
        purchased_at=purchased_at,
        expires_at=expires_at,
    )
    session.add(package)
    session.commit()
    session.refresh(package)
    return package


def _profile(session: Session, package: Package) -> EsimProfile:
    suffix = uuid4().hex
    profile = EsimProfile(
        package_id=package.id,
        aggregator=EsimAggregator.MONTY_MOBILE,
        iccid=suffix[:20],
        activation_code_lpa=f"LPA:1$retention.example${suffix}",
        qr_code_url=f"https://retention.example/{suffix}.png",
        status=EsimProfileStatus.ACTIVATED,
    )
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile


def _audit_references(
    session: Session, outcome: AuditOutcome, references: list[UUID]
) -> list[str]:
    rows = session.exec(
        select(AuditLog).where(
            AuditLog.event_type == AuditEventType.DATA_RETENTION.value,
            AuditLog.outcome == outcome.value,
            AuditLog.reference.in_([str(reference) for reference in references]),
        )
    ).all()
    return [row.reference for row in rows if row.reference is not None]


def test_checkin_locations_are_nulled_90_days_after_trip_expiry(
    postgres_engine,
) -> None:
    cutoff = NOW - timedelta(days=90)
    seeded: list[CheckIn] = []
    with Session(postgres_engine) as session:
        for label, expiry in (
            ("newer", cutoff + timedelta(seconds=1)),
            ("exact", cutoff),
            ("older", cutoff - timedelta(seconds=1)),
        ):
            user = _user(session, f"checkin-{label}")
            package = _package(
                session, user, expiry - timedelta(days=30), expiry
            )
            checkin = CheckIn(
                user_id=user.id,
                client_generated_id=uuid4(),
                timestamp=package.purchased_at + timedelta(days=1),
                latitude=Decimal("21.422500"),
                longitude=Decimal("39.826200"),
                received_at=package.purchased_at + timedelta(days=1),
                location_retention_due_at=expiry + timedelta(days=90),
            )
            session.add(checkin)
            session.commit()
            session.refresh(checkin)
            seeded.append(checkin)

        unmatched_user = _user(session, "checkin-unmatched")
        unmatched = CheckIn(
            user_id=unmatched_user.id,
            client_generated_id=uuid4(),
            timestamp=cutoff - timedelta(days=1),
            latitude=Decimal("21.422500"),
            longitude=Decimal("39.826200"),
            received_at=cutoff - timedelta(days=1),
            location_retention_due_at=NOW,
        )
        session.add(unmatched)
        session.commit()
        session.refresh(unmatched)
        seeded.append(unmatched)

        service = RetentionService(lambda: NOW)
        assert service.null_expired_checkin_locations(session) == 3
        assert service.null_expired_checkin_locations(session) == 0
        refreshed = [session.get(CheckIn, row.id) for row in seeded]
        assert refreshed[0] is not None and refreshed[0].latitude is not None
        assert refreshed[1] is not None and refreshed[1].latitude is None
        assert refreshed[2] is not None and refreshed[2].longitude is None
        assert refreshed[3] is not None and refreshed[3].latitude is None
        assert sorted(
            _audit_references(
                session,
                AuditOutcome.CHECKIN_LOCATION_NULLED,
                [seeded[1].id, seeded[2].id, seeded[3].id],
            )
        ) == sorted(
            [str(seeded[1].id), str(seeded[2].id), str(seeded[3].id)]
        )


def test_sos_alerts_are_deleted_at_three_years_without_premature_deletion(
    postgres_engine,
) -> None:
    cutoff = NOW.replace(year=NOW.year - 3)
    with Session(postgres_engine) as session:
        user = _user(session, "sos-retention")
        alerts = [
            SOSAlert(
                user_id=user.id,
                client_generated_id=uuid4(),
                timestamp=timestamp,
            )
            for timestamp in (
                cutoff + timedelta(seconds=1),
                cutoff,
                cutoff - timedelta(seconds=1),
            )
        ]
        session.add_all(alerts)
        session.commit()
        ids = [alert.id for alert in alerts]

        service = RetentionService(lambda: NOW)
        assert service.delete_expired_sos_alerts(session) == 2
        assert service.delete_expired_sos_alerts(session) == 0
        assert session.get(SOSAlert, ids[0]) is not None
        assert session.get(SOSAlert, ids[1]) is None
        assert session.get(SOSAlert, ids[2]) is None
        assert len(
            _audit_references(
                session, AuditOutcome.SOS_ALERT_DELETED, ids[1:]
            )
        ) == 2


def test_usage_polls_collapse_to_daily_summary_at_30_days(
    postgres_engine,
) -> None:
    cutoff = NOW - timedelta(days=30)
    with Session(postgres_engine) as session:
        user = _user(session, "usage-retention")
        package = _package(
            session, user, NOW - timedelta(days=60), NOW + timedelta(days=1)
        )
        profile = _profile(session, package)
        polls = [
            UsagePoll(
                esim_profile_id=profile.id,
                polled_at=timestamp,
                data_used_gb=amount,
                poll_success=success,
            )
            for timestamp, amount, success in (
                (cutoff + timedelta(seconds=1), Decimal("3.00"), True),
                (cutoff, Decimal("2.00"), False),
                (cutoff - timedelta(seconds=1), Decimal("1.00"), True),
            )
        ]
        session.add_all(polls)
        session.commit()
        ids = [poll.id for poll in polls]

        service = RetentionService(lambda: NOW)
        assert service.collapse_expired_usage_polls(session) == 2
        assert service.collapse_expired_usage_polls(session) == 0
        assert session.get(UsagePoll, ids[0]) is not None
        assert session.get(UsagePoll, ids[1]) is None
        assert session.get(UsagePoll, ids[2]) is None
        summary = session.exec(
            select(DailyUsageSummary).where(
                DailyUsageSummary.esim_profile_id == profile.id
            )
        ).one()
        assert summary.first_data_used_gb == Decimal("1.00")
        assert summary.last_data_used_gb == Decimal("2.00")
        assert summary.successful_poll_count == 1
        assert summary.failed_poll_count == 1
        assert len(
            _audit_references(
                session, AuditOutcome.USAGE_POLL_COLLAPSED, ids[1:]
            )
        ) == 2


def test_call_logs_are_deleted_at_12_months(postgres_engine) -> None:
    cutoff = NOW.replace(year=NOW.year - 1)
    with Session(postgres_engine) as session:
        user = _user(session, "call-retention")
        logs = [
            CallLog(
                user_id=user.id,
                telnyx_call_leg_id=f"retention-{uuid4().hex}",
                direction=CallDirection.OUTBOUND,
                call_type=CallType.PSTN,
                to_number="+2349012345678",
                duration_seconds=30,
                pstn_minutes_charged=Decimal("0.50"),
                started_at=timestamp,
            )
            for timestamp in (
                cutoff + timedelta(seconds=1),
                cutoff,
                cutoff - timedelta(seconds=1),
            )
        ]
        session.add_all(logs)
        session.commit()
        ids = [row.id for row in logs]

        service = RetentionService(lambda: NOW)
        assert service.delete_expired_call_logs(session) == 2
        assert service.delete_expired_call_logs(session) == 0
        assert session.get(CallLog, ids[0]) is not None
        assert session.get(CallLog, ids[1]) is None
        assert session.get(CallLog, ids[2]) is None
        assert len(
            _audit_references(session, AuditOutcome.CALL_LOG_DELETED, ids[1:])
        ) == 2


def test_soft_delete_request_is_idempotent_and_revokes_refresh_tokens(
    postgres_engine,
) -> None:
    with Session(postgres_engine) as session:
        user = _user(session, "soft-delete")
        token = RefreshToken(
            user_id=user.id,
            token_hash=uuid4().hex + uuid4().hex,
            expires_at=NOW + timedelta(days=30),
        )
        session.add(token)
        session.commit()

        service = RetentionService(lambda: NOW)
        first = service.request_account_deletion(session, user.id)
        second = service.request_account_deletion(session, user.id)
        assert first.deletion_requested_at == NOW
        assert second.deletion_requested_at == NOW
        session.refresh(token)
        assert token.revoked_at == NOW
        assert len(
            _audit_references(
                session, AuditOutcome.ACCOUNT_SOFT_DELETED, [user.id]
            )
        ) == 1


def test_accounts_hard_delete_at_30_days_but_preserve_sos_and_payment_records(
    postgres_engine,
) -> None:
    cutoff = NOW - timedelta(days=30)
    with Session(postgres_engine) as session:
        users = [
            _user(session, label)
            for label in ("account-newer", "account-exact", "account-older")
        ]
        for user, requested_at in zip(
            users,
            (
                cutoff + timedelta(seconds=1),
                cutoff,
                cutoff - timedelta(seconds=1),
            ),
            strict=True,
        ):
            user.status = UserStatus.PENDING_DELETION
            user.deletion_requested_at = requested_at
            session.add(user)
        exact_sos = SOSAlert(
            user_id=users[1].id,
            client_generated_id=uuid4(),
            timestamp=NOW - timedelta(days=1),
        )
        exact_checkin = CheckIn(
            user_id=users[1].id,
            client_generated_id=uuid4(),
            timestamp=NOW - timedelta(days=1),
            latitude=Decimal("21.422500"),
            longitude=Decimal("39.826200"),
            received_at=NOW - timedelta(days=1),
        )
        session.add_all([exact_sos, exact_checkin])
        session.commit()
        exact_package = _package(
            session,
            users[1],
            NOW - timedelta(days=10),
            NOW + timedelta(days=20),
        )
        transaction = Transaction(
            package_id=exact_package.id,
            processor=PaymentProcessor.PAYSTACK,
            processor_reference=f"retention-{uuid4().hex}",
            amount_ngn=Decimal("1000.00"),
            status=TransactionStatus.SUCCESS,
            created_at=NOW - timedelta(days=1),
        )
        profile = _profile(session, exact_package)
        usage_poll = UsagePoll(
            esim_profile_id=profile.id,
            polled_at=NOW - timedelta(days=1),
            data_used_gb=Decimal("0.50"),
            poll_success=True,
        )
        usage_summary = DailyUsageSummary(
            esim_profile_id=profile.id,
            summary_date=(NOW - timedelta(days=31)).date(),
            first_polled_at=NOW - timedelta(days=31, hours=1),
            last_polled_at=NOW - timedelta(days=31),
            first_data_used_gb=Decimal("0.10"),
            last_data_used_gb=Decimal("0.20"),
            successful_poll_count=2,
            failed_poll_count=0,
        )
        session.add_all([transaction, usage_poll, usage_summary])
        session.commit()
        user_ids = [user.id for user in users]
        sos_id, checkin_id, transaction_id, profile_id = (
            exact_sos.id,
            exact_checkin.id,
            transaction.id,
            profile.id,
        )
        usage_poll_id, usage_summary_id = usage_poll.id, usage_summary.id

        service = RetentionService(lambda: NOW)
        assert service.hard_delete_expired_accounts(session) == 2
        assert service.hard_delete_expired_accounts(session) == 0
        assert session.get(User, user_ids[0]) is not None
        assert session.get(User, user_ids[1]) is None
        assert session.get(User, user_ids[2]) is None
        retained_sos = session.get(SOSAlert, sos_id)
        assert retained_sos is not None and retained_sos.user_id is None
        retained_checkin = session.get(CheckIn, checkin_id)
        assert retained_checkin is not None
        assert retained_checkin.user_id is None
        assert retained_checkin.latitude is None
        retained_transaction = session.get(Transaction, transaction_id)
        assert retained_transaction is not None
        assert retained_transaction.package_id is None
        assert session.get(EsimProfile, profile_id) is None
        assert session.get(UsagePoll, usage_poll_id) is not None
        assert session.get(DailyUsageSummary, usage_summary_id) is not None
        assert len(
            _audit_references(
                session, AuditOutcome.ACCOUNT_HARD_DELETED, user_ids[1:]
            )
        ) == 2


def test_device_log_pii_strip_and_full_deletion_are_independent(
    postgres_engine,
) -> None:
    strip_cutoff = NOW - timedelta(days=90)
    delete_cutoff = NOW.replace(year=NOW.year - 2)
    with Session(postgres_engine) as session:
        user = _user(session, "device-retention")
        rows = [
            DeviceCompatibilityLog(
                user_id=user.id,
                platform="android",
                device_model=label,
                esim_supported=True,
                checked_at=timestamp,
            )
            for label, timestamp in (
                ("strip-newer", strip_cutoff + timedelta(seconds=1)),
                ("strip-exact", strip_cutoff),
                ("strip-older", strip_cutoff - timedelta(seconds=1)),
                ("delete-exact", delete_cutoff),
                ("delete-older", delete_cutoff - timedelta(seconds=1)),
            )
        ]
        session.add_all(rows)
        session.commit()
        ids = [row.id for row in rows]

        service = RetentionService(lambda: NOW)
        assert service.strip_expired_device_user_links(session) == 4
        assert service.strip_expired_device_user_links(session) == 0
        assert session.get(DeviceCompatibilityLog, ids[0]).user_id == user.id
        for row_id in ids[1:]:
            assert session.get(DeviceCompatibilityLog, row_id).user_id is None

        assert service.delete_expired_device_logs(session) == 2
        assert service.delete_expired_device_logs(session) == 0
        assert session.get(DeviceCompatibilityLog, ids[1]) is not None
        assert session.get(DeviceCompatibilityLog, ids[2]) is not None
        assert session.get(DeviceCompatibilityLog, ids[3]) is None
        assert session.get(DeviceCompatibilityLog, ids[4]) is None
        assert len(
            _audit_references(
                session, AuditOutcome.DEVICE_USER_LINK_STRIPPED, ids[1:]
            )
        ) == 4
        assert len(
            _audit_references(
                session, AuditOutcome.DEVICE_LOG_DELETED, ids[3:]
            )
        ) == 2


def test_transactions_are_deleted_at_six_years_without_premature_deletion(
    postgres_engine,
) -> None:
    cutoff = NOW.replace(year=NOW.year - 6)
    with Session(postgres_engine) as session:
        transactions = [
            Transaction(
                processor=PaymentProcessor.PAYSTACK,
                processor_reference=f"retention-{uuid4().hex}",
                amount_ngn=Decimal("1000.00"),
                status=TransactionStatus.SUCCESS,
                created_at=timestamp,
            )
            for timestamp in (
                cutoff + timedelta(seconds=1),
                cutoff,
                cutoff - timedelta(seconds=1),
            )
        ]
        session.add_all(transactions)
        session.commit()
        ids = [row.id for row in transactions]

        service = RetentionService(lambda: NOW)
        assert service.delete_expired_transactions(session) == 2
        assert service.delete_expired_transactions(session) == 0
        assert session.get(Transaction, ids[0]) is not None
        assert session.get(Transaction, ids[1]) is None
        assert session.get(Transaction, ids[2]) is None
        assert len(
            _audit_references(
                session, AuditOutcome.TRANSACTION_DELETED, ids[1:]
            )
        ) == 2


def test_retention_sweeps_do_not_overlap(postgres_engine) -> None:
    with Session(postgres_engine) as seed_session:
        user = _user(seed_session, "retention-lock")
        row = DeviceCompatibilityLog(
            user_id=user.id,
            platform="android",
            device_model="lock-test",
            esim_supported=True,
            checked_at=NOW - timedelta(days=90),
        )
        seed_session.add(row)
        seed_session.commit()
        row_id, user_id = row.id, user.id

    service = RetentionService(lambda: NOW)
    with Session(postgres_engine) as lock_session:
        lock_session.exec(
            select(
                func.pg_advisory_xact_lock(RetentionService._SWEEP_LOCK_ID)
            )
        ).one()
        with Session(postgres_engine) as competing_session:
            assert service.strip_expired_device_user_links(competing_session) == 0
            retained = competing_session.get(DeviceCompatibilityLog, row_id)
            assert retained is not None and retained.user_id == user_id
        lock_session.rollback()

    with Session(postgres_engine) as session:
        assert service.strip_expired_device_user_links(session) == 1
        retained = session.get(DeviceCompatibilityLog, row_id)
        assert retained is not None and retained.user_id is None
