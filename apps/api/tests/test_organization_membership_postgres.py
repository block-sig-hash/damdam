"""US-29 chunk 07A — memberships, the permission matrix and safe transitions.

Written before the implementation, per the repository's strict-TDD policy for
tenant isolation and object-level authorization.

Every test here is an escalation or a lockout: a role change that hands someone
more than the actor holds, a revocation that leaves an organization with nobody
who can administer it, or a membership that keeps working after it was taken
away. All three are the ways a membership model fails in production, and none
of them are caught by exercising the happy path.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

from app.auth.models import (
    Locale,
    Organization,
    OrganizationType,
    Platform,
    User,
)
from app.organizations.models import (
    MembershipStatus,
    OrganizationMember,
    OrganizationRole,
)
from app.organizations.permissions import Permission, permissions_for
from app.organizations.service import MembershipError, MembershipService

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="membership uniqueness and races require PostgreSQL",
)

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def engine():
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        session.exec(
            text(
                "TRUNCATE organization_members, organizations, "
                "refresh_tokens, users RESTART IDENTITY CASCADE"
            )
        )
        session.commit()
        yield session
        session.rollback()


@pytest.fixture
def service():
    return MembershipService(clock=lambda: NOW)


def _user(session: Session, label: str) -> User:
    user = User(
        phone_number=f"+23480{abs(hash(label)) % 10**8:08d}",
        first_name=label,
        platform=Platform.ANDROID,
    )
    session.add(user)
    session.flush()
    return user


def _organization(session: Session, name: str = "Acme") -> Organization:
    organization = Organization(
        org_type=OrganizationType.ENTERPRISE,
        name=name,
        primary_contact_name="Contact",
        email=f"{name.lower()}-{uuid4().hex[:8]}@example.test",
        password_hash="unused",
        phone_number="+2348000000000",
        locale=Locale.EN,
    )
    session.add(organization)
    session.flush()
    return organization


def _seed(session, service, roles: dict[str, OrganizationRole]):
    organization = _organization(session)
    members = {}
    for label, role in roles.items():
        user = _user(session, label)
        members[label] = service.seed_member(session, organization, user, role)
    session.commit()
    return organization, members


# --- the matrix is data, and it is enforced server-side --------------------


def test_every_role_has_an_explicit_permission_set():
    """A role with no entry must not silently fall through to "allowed"."""
    for role in OrganizationRole:
        assert permissions_for(role), f"{role} has no permissions declared"


def test_a_member_cannot_manage_people_billing_or_orders():
    granted = permissions_for(OrganizationRole.MEMBER)
    for permission in (
        Permission.MEMBER_INVITE,
        Permission.MEMBER_ROLE_CHANGE,
        Permission.MEMBER_REVOKE,
        Permission.BILLING_MANAGE,
        Permission.ORDER_PLACE,
        Permission.PEOPLE_MANAGE,
        Permission.REPORT_EXPORT,
    ):
        assert permission not in granted


def test_billing_manages_money_but_never_people():
    granted = permissions_for(OrganizationRole.BILLING)
    assert Permission.BILLING_MANAGE in granted
    assert Permission.MEMBER_INVITE not in granted
    assert Permission.MEMBER_ROLE_CHANGE not in granted
    assert Permission.MEMBER_REVOKE not in granted


def test_only_the_owner_may_transfer_ownership():
    assert Permission.ORG_TRANSFER_OWNERSHIP in permissions_for(
        OrganizationRole.OWNER
    )
    for role in (
        OrganizationRole.ADMINISTRATOR,
        OrganizationRole.BILLING,
        OrganizationRole.MEMBER,
    ):
        assert Permission.ORG_TRANSFER_OWNERSHIP not in permissions_for(role)


# --- privilege escalation --------------------------------------------------


def test_an_administrator_cannot_create_an_owner(session, service):
    organization, members = _seed(
        session,
        service,
        {
            "owner": OrganizationRole.OWNER,
            "admin": OrganizationRole.ADMINISTRATOR,
            "member": OrganizationRole.MEMBER,
        },
    )
    with pytest.raises(MembershipError) as excinfo:
        service.change_role(
            session,
            actor=members["admin"],
            target_user_id=members["member"].user_id,
            new_role=OrganizationRole.OWNER,
        )
    assert excinfo.value.code == "role_change_forbidden"
    session.rollback()
    fresh = session.get(OrganizationMember, members["member"].id)
    assert fresh.role is OrganizationRole.MEMBER


def test_an_administrator_cannot_touch_an_owners_membership(session, service):
    organization, members = _seed(
        session,
        service,
        {"owner": OrganizationRole.OWNER, "admin": OrganizationRole.ADMINISTRATOR},
    )
    with pytest.raises(MembershipError) as excinfo:
        service.change_role(
            session,
            actor=members["admin"],
            target_user_id=members["owner"].user_id,
            new_role=OrganizationRole.MEMBER,
        )
    assert excinfo.value.code == "role_change_forbidden"


def test_nobody_may_change_their_own_role(session, service):
    """Self-service promotion is the shortest escalation path there is."""
    organization, members = _seed(
        session, service, {"owner": OrganizationRole.OWNER}
    )
    with pytest.raises(MembershipError) as excinfo:
        service.change_role(
            session,
            actor=members["owner"],
            target_user_id=members["owner"].user_id,
            new_role=OrganizationRole.OWNER,
        )
    assert excinfo.value.code == "cannot_modify_own_membership"


def test_a_member_cannot_change_anyone(session, service):
    organization, members = _seed(
        session,
        service,
        {
            "owner": OrganizationRole.OWNER,
            "a": OrganizationRole.MEMBER,
            "b": OrganizationRole.MEMBER,
        },
    )
    with pytest.raises(MembershipError) as excinfo:
        service.change_role(
            session,
            actor=members["a"],
            target_user_id=members["b"].user_id,
            new_role=OrganizationRole.ADMINISTRATOR,
        )
    assert excinfo.value.code == "permission_denied"


# --- the last owner --------------------------------------------------------


def test_the_last_owner_cannot_be_demoted(session, service):
    organization, members = _seed(
        session,
        service,
        {"owner": OrganizationRole.OWNER, "second": OrganizationRole.OWNER},
    )
    service.change_role(
        session,
        actor=members["owner"],
        target_user_id=members["second"].user_id,
        new_role=OrganizationRole.ADMINISTRATOR,
    )
    session.commit()
    with pytest.raises(MembershipError) as excinfo:
        service.change_role(
            session,
            actor=members["second"],
            target_user_id=members["owner"].user_id,
            new_role=OrganizationRole.ADMINISTRATOR,
        )
    assert excinfo.value.code in {"last_owner", "role_change_forbidden"}


def test_the_last_owner_cannot_be_revoked(session, service):
    organization, members = _seed(
        session,
        service,
        {"owner": OrganizationRole.OWNER, "admin": OrganizationRole.ADMINISTRATOR},
    )
    with pytest.raises(MembershipError) as excinfo:
        service.revoke(
            session,
            actor=members["owner"],
            target_user_id=members["owner"].user_id,
        )
    assert excinfo.value.code in {"last_owner", "cannot_modify_own_membership"}
    session.rollback()

    owner = session.get(OrganizationMember, members["owner"].id)
    assert owner.status is MembershipStatus.ACTIVE


def test_an_owner_may_be_revoked_once_another_owner_exists(session, service):
    organization, members = _seed(
        session,
        service,
        {"owner": OrganizationRole.OWNER, "second": OrganizationRole.OWNER},
    )
    service.revoke(
        session, actor=members["owner"], target_user_id=members["second"].user_id
    )
    session.commit()
    revoked = session.get(OrganizationMember, members["second"].id)
    assert revoked.status is MembershipStatus.REVOKED
    assert revoked.revoked_at == NOW


# --- revocation takes effect immediately -----------------------------------


def test_a_revoked_membership_grants_nothing(session, service):
    organization, members = _seed(
        session,
        service,
        {"owner": OrganizationRole.OWNER, "admin": OrganizationRole.ADMINISTRATOR},
    )
    service.revoke(
        session, actor=members["owner"], target_user_id=members["admin"].user_id
    )
    session.commit()

    assert (
        service.active_membership(
            session, organization.id, members["admin"].user_id
        )
        is None
    )
    with pytest.raises(MembershipError) as excinfo:
        service.require_permission(
            session,
            organization.id,
            members["admin"].user_id,
            Permission.PEOPLE_READ,
        )
    assert excinfo.value.code == "not_a_member"


def test_reinstatement_reuses_the_membership_rather_than_duplicating_it(
    session, service
):
    organization, members = _seed(
        session,
        service,
        {"owner": OrganizationRole.OWNER, "admin": OrganizationRole.ADMINISTRATOR},
    )
    service.revoke(
        session, actor=members["owner"], target_user_id=members["admin"].user_id
    )
    session.commit()
    reinstated = service.reinstate(
        session,
        actor=members["owner"],
        target_user_id=members["admin"].user_id,
        role=OrganizationRole.MEMBER,
    )
    session.commit()

    assert reinstated.id == members["admin"].id
    assert reinstated.role is OrganizationRole.MEMBER
    assert reinstated.revoked_at is None
    rows = session.exec(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization.id,
            OrganizationMember.user_id == members["admin"].user_id,
        )
    ).all()
    assert len(rows) == 1


# --- the database, not the service, is the last line -----------------------


def test_the_database_refuses_two_memberships_for_one_person(session, service):
    organization, members = _seed(
        session, service, {"owner": OrganizationRole.OWNER}
    )
    session.add(
        OrganizationMember(
            organization_id=organization.id,
            user_id=members["owner"].user_id,
            role=OrganizationRole.MEMBER,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_concurrent_role_changes_do_not_strand_an_ownerless_organization(
    engine, service
):
    """Two administrators demoting the two owners at the same moment.

    Reading the owner count and then writing would let both pass, and the
    organization would be left with nobody who can administer it.
    """
    with Session(engine) as setup:
        setup.exec(
            text(
                "TRUNCATE organization_members, organizations, "
                "refresh_tokens, users RESTART IDENTITY CASCADE"
            )
        )
        setup.commit()
        organization, members = _seed(
            setup,
            service,
            {"a": OrganizationRole.OWNER, "b": OrganizationRole.OWNER},
        )
        organization_id = organization.id
        targets = [members["b"].user_id, members["a"].user_id]
        actors = [members["a"].id, members["b"].id]

    barrier = Barrier(2)

    def demote(index: int) -> str:
        with Session(engine) as scoped:
            actor = scoped.get(OrganizationMember, actors[index])
            barrier.wait(timeout=10)
            try:
                service.change_role(
                    scoped,
                    actor=actor,
                    target_user_id=targets[index],
                    new_role=OrganizationRole.ADMINISTRATOR,
                )
                scoped.commit()
                return "ok"
            except MembershipError as exc:
                scoped.rollback()
                return exc.code
            except Exception:
                scoped.rollback()
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(demote, range(2)))

    assert outcomes.count("ok") == 1, outcomes
    with Session(engine) as check:
        owners = check.exec(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.role == OrganizationRole.OWNER,
                OrganizationMember.status == MembershipStatus.ACTIVE,
            )
        ).all()
    assert len(owners) == 1


def test_expired_or_foreign_organization_is_never_matched(session, service):
    """A membership in one organization must not authorize another."""
    _, members = _seed(session, service, {"owner": OrganizationRole.OWNER})
    other = _organization(session, "Other")
    session.commit()

    assert (
        service.active_membership(session, other.id, members["owner"].user_id)
        is None
    )
    with pytest.raises(MembershipError) as excinfo:
        service.require_permission(
            session, other.id, members["owner"].user_id, Permission.ORG_READ
        )
    assert excinfo.value.code == "not_a_member"


def test_seeded_membership_records_when_it_started(session, service):
    _, members = _seed(session, service, {"owner": OrganizationRole.OWNER})
    joined = members["owner"].joined_at
    assert joined is not None
    assert joined.replace(tzinfo=timezone.utc) - NOW < timedelta(seconds=1)


# --- what else a revoked membership takes with it -------------------------


class _RecordingListener:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def on_membership_revoked(self, session, organization_id, user_id, at) -> None:
        del session
        self.calls.append((organization_id, user_id, at))


def test_revocation_notifies_listeners_scoped_to_the_tenant_and_person(session):
    """`VOICE-EXPANSION.md` chunks 06-07: losing a membership must withdraw the
    work-call grants and credentials it was holding open. Chunk 07 owns the
    moment; V02 registers what to withdraw.

    The listener is handed an organization *and* a person, so it has no way to
    reach that person's personal service -- "without affecting personal
    service" is a property of the seam, not of each listener remembering.
    """
    listener = _RecordingListener()
    service = MembershipService(clock=lambda: NOW, revocation_listeners=[listener])
    organization, members = _seed(
        session,
        service,
        {"owner": OrganizationRole.OWNER, "admin": OrganizationRole.ADMINISTRATOR},
    )

    service.revoke(
        session, actor=members["owner"], target_user_id=members["admin"].user_id
    )
    session.commit()

    assert listener.calls == [
        (organization.id, members["admin"].user_id, NOW)
    ]


def test_a_failing_listener_aborts_the_revocation(session):
    """Better a refused revocation than a removed membership with live grants."""

    class _Failing:
        def on_membership_revoked(self, session, organization_id, user_id, at):
            raise RuntimeError("grant withdrawal unavailable")

    service = MembershipService(clock=lambda: NOW, revocation_listeners=[_Failing()])
    _, members = _seed(
        session,
        service,
        {"owner": OrganizationRole.OWNER, "admin": OrganizationRole.ADMINISTRATOR},
    )

    with pytest.raises(RuntimeError):
        service.revoke(
            session, actor=members["owner"], target_user_id=members["admin"].user_id
        )
    session.rollback()
    still_active = service.active_membership(
        session, members["admin"].organization_id, members["admin"].user_id
    )
    assert still_active is not None
    assert still_active.status is MembershipStatus.ACTIVE


def test_a_role_change_does_not_fire_the_revocation_seam(session):
    """A demotion is not an offboarding; V02 decides what a role change means."""
    listener = _RecordingListener()
    service = MembershipService(clock=lambda: NOW, revocation_listeners=[listener])
    _, members = _seed(
        session,
        service,
        {"owner": OrganizationRole.OWNER, "admin": OrganizationRole.ADMINISTRATOR},
    )
    service.change_role(
        session,
        actor=members["owner"],
        target_user_id=members["admin"].user_id,
        new_role=OrganizationRole.MEMBER,
    )
    session.commit()
    assert listener.calls == []
