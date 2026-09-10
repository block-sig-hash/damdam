"""US-29 chunk 07C — administrator MFA and immediate revocation (AC-29.5).

Written before the implementation, per the strict-TDD policy for authentication
and sessions.

AC-29.5 has two halves and they fail differently. "Administrator MFA is
required" fails open -- a privileged action that runs because nobody enrolled.
"Revocation takes effect immediately" fails late -- access that keeps working
until a token happens to expire, which is exactly the window an incident
response is trying to close. Both are tested here against a real database,
because both are decided by a row read inside the request's transaction.
"""

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

from app.auth.models import (
    Locale,
    Organization,
    OrganizationType,
    Platform,
    User,
)
from app.mfa.models import MfaRecoveryCode, MfaStatus, UserMfaCredential
from app.mfa.service import MfaError, MfaService
from app.mfa.totp import generate
from app.organizations.models import OrganizationRole
from app.organizations.permissions import Permission
from app.organizations.service import MembershipError, MembershipService

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="elevation expiry and revocation require PostgreSQL",
)

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


class FrozenClock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: float) -> None:
        self.value += timedelta(**kwargs)


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
                "TRUNCATE organization_elevations, mfa_recovery_codes, "
                "user_mfa_credentials, organization_invitations, "
                "organization_members, organizations, account_identifiers, "
                "identity_tokens, refresh_tokens, users RESTART IDENTITY CASCADE"
            )
        )
        session.commit()
        yield session
        session.rollback()


@pytest.fixture
def clock():
    return FrozenClock()


@pytest.fixture
def memberships(clock):
    return MembershipService(clock=clock)


@pytest.fixture
def mfa(clock):
    return MfaService(clock=clock)


def _user(session: Session, label: str) -> User:
    user = User(
        phone_number=f"+23482{abs(hash(label)) % 10**8:08d}",
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


def _enrolled(session, mfa, clock, user):
    """Enroll and confirm, returning the secret and the recovery codes."""
    enrollment = mfa.begin_enrollment(session, user)
    session.flush()
    confirmed = mfa.confirm_enrollment(
        session, user, generate(enrollment.secret_bytes, clock.value)
    )
    session.commit()
    return enrollment, confirmed


# --- enrollment ------------------------------------------------------------


def test_an_unconfirmed_enrollment_grants_nothing(session, mfa, clock):
    user = _user(session, "admin")
    mfa.begin_enrollment(session, user)
    session.commit()

    credential = session.exec(select(UserMfaCredential)).one()
    assert credential.status is MfaStatus.PENDING
    assert mfa.is_active(session, user) is False


def test_enrollment_is_confirmed_only_by_a_code_from_the_secret(session, mfa):
    user = _user(session, "admin")
    mfa.begin_enrollment(session, user)
    session.flush()

    with pytest.raises(MfaError) as excinfo:
        mfa.confirm_enrollment(session, user, "000000")
    assert excinfo.value.code == "mfa_code_invalid"
    session.rollback()
    assert mfa.is_active(session, user) is False


def test_confirmation_issues_recovery_codes_stored_only_as_hashes(
    session, mfa, clock
):
    user = _user(session, "admin")
    _, confirmed = _enrolled(session, mfa, clock, user)

    assert len(confirmed.recovery_codes) >= 8
    stored = session.exec(select(MfaRecoveryCode)).all()
    assert len(stored) == len(confirmed.recovery_codes)
    hashes = {row.code_hash for row in stored}
    for plaintext in confirmed.recovery_codes:
        assert plaintext not in hashes


def test_re_enrolling_replaces_the_old_secret_and_its_recovery_codes(
    session, mfa, clock
):
    """A lost authenticator must not leave a working second key behind.

    Asserted by what the old credentials can still *do*, not by whether their
    rows were deleted: the rows are retained so that "this code was spent" has
    an answer, and a test that demanded their absence would be testing the
    storage decision rather than the security property.
    """
    user = _user(session, "admin")
    first, first_confirmed = _enrolled(session, mfa, clock, user)
    organization = _organization(session)
    session.commit()

    second = mfa.begin_enrollment(session, user)
    session.flush()
    clock.advance(seconds=60)
    mfa.confirm_enrollment(session, user, generate(second.secret_bytes, clock.value))
    session.commit()

    assert second.secret_bytes != first.secret_bytes
    clock.advance(seconds=30)
    with pytest.raises(MfaError) as excinfo:
        mfa.elevate(
            session,
            user,
            organization.id,
            generate(first.secret_bytes, clock.value),
        )
    assert excinfo.value.code == "mfa_code_invalid"
    session.commit()
    with pytest.raises(MfaError) as recovery:
        mfa.elevate_with_recovery_code(
            session, user, organization.id, first_confirmed.recovery_codes[0]
        )
    assert recovery.value.code == "mfa_code_invalid"


# --- replay and brute force ------------------------------------------------


def test_the_same_code_cannot_be_used_twice(session, mfa, clock):
    """A code read over a shoulder is good for thirty seconds otherwise."""
    user = _user(session, "admin")
    enrollment, _ = _enrolled(session, mfa, clock, user)
    organization = _organization(session)
    session.commit()

    clock.advance(seconds=30)
    code = generate(enrollment.secret_bytes, clock.value)
    mfa.elevate(session, user, organization.id, code)
    session.commit()
    with pytest.raises(MfaError) as excinfo:
        mfa.elevate(session, user, organization.id, code)
    assert excinfo.value.code == "mfa_code_replayed"


def test_repeated_wrong_codes_lock_the_credential(session, mfa, clock):
    user = _user(session, "admin")
    enrollment, _ = _enrolled(session, mfa, clock, user)
    organization = _organization(session)
    session.commit()

    for _ in range(MfaService.ATTEMPT_LIMIT):
        with pytest.raises(MfaError):
            mfa.elevate(session, user, organization.id, "000000")
        session.commit()

    with pytest.raises(MfaError) as excinfo:
        mfa.elevate(
            session,
            user,
            organization.id,
            generate(enrollment.secret_bytes, clock.value),
        )
    assert excinfo.value.code == "mfa_locked"


def test_the_lock_lifts_after_the_lockout_window(session, mfa, clock):
    user = _user(session, "admin")
    enrollment, _ = _enrolled(session, mfa, clock, user)
    organization = _organization(session)
    session.commit()
    for _ in range(MfaService.ATTEMPT_LIMIT):
        with pytest.raises(MfaError):
            mfa.elevate(session, user, organization.id, "000000")
        session.commit()

    clock.advance(seconds=MfaService.LOCKOUT_SECONDS + 1)
    elevation = mfa.elevate(
        session,
        user,
        organization.id,
        generate(enrollment.secret_bytes, clock.value),
    )
    session.commit()
    assert elevation.revoked_at is None


# --- recovery codes --------------------------------------------------------


def test_a_recovery_code_works_once(session, mfa, clock):
    user = _user(session, "admin")
    _, confirmed = _enrolled(session, mfa, clock, user)
    organization = _organization(session)
    session.commit()

    code = confirmed.recovery_codes[0]
    mfa.elevate_with_recovery_code(session, user, organization.id, code)
    session.commit()
    with pytest.raises(MfaError) as excinfo:
        mfa.elevate_with_recovery_code(session, user, organization.id, code)
    assert excinfo.value.code == "mfa_code_invalid"


def test_a_recovery_code_from_another_account_is_refused(session, mfa, clock):
    victim = _user(session, "victim")
    _, victim_codes = _enrolled(session, mfa, clock, victim)
    attacker = _user(session, "attacker")
    _enrolled(session, mfa, clock, attacker)
    organization = _organization(session)
    session.commit()

    with pytest.raises(MfaError) as excinfo:
        mfa.elevate_with_recovery_code(
            session, attacker, organization.id, victim_codes.recovery_codes[0]
        )
    assert excinfo.value.code == "mfa_code_invalid"


# --- step-up gates privileged permissions ---------------------------------


def test_a_privileged_action_needs_an_enrolled_administrator(
    session, mfa, memberships, clock
):
    """"Required" has to mean refused when absent, not merely offered."""
    organization = _organization(session)
    owner_user = _user(session, "owner")
    owner = memberships.seed_member(
        session, organization, owner_user, OrganizationRole.OWNER
    )
    session.commit()

    with pytest.raises(MembershipError) as excinfo:
        memberships.require_permission(
            session,
            organization.id,
            owner_user.id,
            Permission.MEMBER_INVITE,
            mfa=mfa,
        )
    assert excinfo.value.code == "mfa_enrollment_required"
    assert owner.role is OrganizationRole.OWNER


def test_an_enrolled_administrator_still_needs_a_current_step_up(
    session, mfa, memberships, clock
):
    organization = _organization(session)
    owner_user = _user(session, "owner")
    memberships.seed_member(
        session, organization, owner_user, OrganizationRole.OWNER
    )
    _enrolled(session, mfa, clock, owner_user)
    session.commit()

    with pytest.raises(MembershipError) as excinfo:
        memberships.require_permission(
            session,
            organization.id,
            owner_user.id,
            Permission.MEMBER_INVITE,
            mfa=mfa,
        )
    assert excinfo.value.code == "mfa_required"


def test_reading_never_requires_a_step_up(session, mfa, memberships, clock):
    """Second factors that gate reads get shared, written down or disabled."""
    organization = _organization(session)
    plain = _user(session, "plain")
    memberships.seed_member(session, organization, plain, OrganizationRole.MEMBER)
    session.commit()

    membership = memberships.require_permission(
        session, organization.id, plain.id, Permission.ORG_READ, mfa=mfa
    )
    assert membership.role is OrganizationRole.MEMBER


def test_a_step_up_authorizes_the_privileged_action(
    session, mfa, memberships, clock
):
    organization = _organization(session)
    owner_user = _user(session, "owner")
    memberships.seed_member(
        session, organization, owner_user, OrganizationRole.OWNER
    )
    enrollment, _ = _enrolled(session, mfa, clock, owner_user)
    session.commit()

    clock.advance(seconds=30)
    mfa.elevate(
        session,
        owner_user,
        organization.id,
        generate(enrollment.secret_bytes, clock.value),
    )
    session.commit()
    membership = memberships.require_permission(
        session,
        organization.id,
        owner_user.id,
        Permission.MEMBER_INVITE,
        mfa=mfa,
    )
    assert membership.role is OrganizationRole.OWNER


def test_a_step_up_expires(session, mfa, memberships, clock):
    organization = _organization(session)
    owner_user = _user(session, "owner")
    memberships.seed_member(
        session, organization, owner_user, OrganizationRole.OWNER
    )
    enrollment, _ = _enrolled(session, mfa, clock, owner_user)
    session.commit()
    clock.advance(seconds=30)
    elevation = mfa.elevate(
        session,
        owner_user,
        organization.id,
        generate(enrollment.secret_bytes, clock.value),
    )
    session.commit()

    clock.value = elevation.expires_at.replace(tzinfo=timezone.utc)
    with pytest.raises(MembershipError) as excinfo:
        memberships.require_permission(
            session,
            organization.id,
            owner_user.id,
            Permission.MEMBER_INVITE,
            mfa=mfa,
        )
    assert excinfo.value.code == "mfa_required"


def test_a_step_up_does_not_cross_organizations(session, mfa, memberships, clock):
    """Proving a second factor for one tenant is not proof for another."""
    acme = _organization(session, "Acme")
    other = _organization(session, "Other")
    person = _user(session, "multi")
    memberships.seed_member(session, acme, person, OrganizationRole.OWNER)
    memberships.seed_member(session, other, person, OrganizationRole.OWNER)
    enrollment, _ = _enrolled(session, mfa, clock, person)
    session.commit()

    clock.advance(seconds=30)
    mfa.elevate(
        session, person, acme.id, generate(enrollment.secret_bytes, clock.value)
    )
    session.commit()

    memberships.require_permission(
        session, acme.id, person.id, Permission.MEMBER_INVITE, mfa=mfa
    )
    with pytest.raises(MembershipError) as excinfo:
        memberships.require_permission(
            session, other.id, person.id, Permission.MEMBER_INVITE, mfa=mfa
        )
    assert excinfo.value.code == "mfa_required"


# --- immediate revocation (AC-29.5) ---------------------------------------


def test_revoking_a_membership_kills_its_step_up_in_the_same_transaction(
    session, mfa, memberships, clock
):
    organization = _organization(session)
    owner_user = _user(session, "owner")
    owner = memberships.seed_member(
        session, organization, owner_user, OrganizationRole.OWNER
    )
    admin_user = _user(session, "admin")
    memberships.seed_member(
        session, organization, admin_user, OrganizationRole.ADMINISTRATOR
    )
    owner_enrollment, _ = _enrolled(session, mfa, clock, owner_user)
    admin_enrollment, _ = _enrolled(session, mfa, clock, admin_user)
    session.commit()

    clock.advance(seconds=30)
    mfa.elevate(
        session,
        admin_user,
        organization.id,
        generate(admin_enrollment.secret_bytes, clock.value),
    )
    mfa.elevate(
        session,
        owner_user,
        organization.id,
        generate(owner_enrollment.secret_bytes, clock.value),
    )
    session.commit()

    memberships.revoke(session, actor=owner, target_user_id=admin_user.id, mfa=mfa)
    session.commit()

    with pytest.raises(MembershipError) as excinfo:
        memberships.require_permission(
            session,
            organization.id,
            admin_user.id,
            Permission.ORG_READ,
            mfa=mfa,
        )
    assert excinfo.value.code == "not_a_member"
    assert mfa.active_elevation(session, admin_user.id, organization.id) is None


def test_a_role_change_drops_the_step_up_it_was_granted_under(
    session, mfa, memberships, clock
):
    """New authority, new proof. Otherwise a demotion leaves a live elevation."""
    organization = _organization(session)
    owner_user = _user(session, "owner")
    owner = memberships.seed_member(
        session, organization, owner_user, OrganizationRole.OWNER
    )
    admin_user = _user(session, "admin")
    memberships.seed_member(
        session, organization, admin_user, OrganizationRole.ADMINISTRATOR
    )
    owner_enrollment, _ = _enrolled(session, mfa, clock, owner_user)
    admin_enrollment, _ = _enrolled(session, mfa, clock, admin_user)
    session.commit()
    clock.advance(seconds=30)
    mfa.elevate(
        session,
        admin_user,
        organization.id,
        generate(admin_enrollment.secret_bytes, clock.value),
    )
    mfa.elevate(
        session,
        owner_user,
        organization.id,
        generate(owner_enrollment.secret_bytes, clock.value),
    )
    session.commit()

    memberships.change_role(
        session,
        actor=owner,
        target_user_id=admin_user.id,
        new_role=OrganizationRole.MEMBER,
        mfa=mfa,
    )
    session.commit()
    assert mfa.active_elevation(session, admin_user.id, organization.id) is None


def test_disabling_mfa_revokes_every_elevation_it_granted(
    session, mfa, memberships, clock
):
    organization = _organization(session)
    person = _user(session, "owner")
    memberships.seed_member(session, organization, person, OrganizationRole.OWNER)
    enrollment, _ = _enrolled(session, mfa, clock, person)
    session.commit()
    clock.advance(seconds=30)
    mfa.elevate(
        session, person, organization.id, generate(enrollment.secret_bytes, clock.value)
    )
    session.commit()

    clock.advance(seconds=30)
    mfa.disable(
        session, person, generate(enrollment.secret_bytes, clock.value)
    )
    session.commit()

    assert mfa.active_elevation(session, person.id, organization.id) is None
    assert mfa.is_active(session, person) is False


def test_a_step_up_cannot_be_created_without_an_active_membership(
    session, mfa, memberships, clock
):
    organization = _organization(session)
    outsider = _user(session, "outsider")
    enrollment, _ = _enrolled(session, mfa, clock, outsider)
    session.commit()

    clock.advance(seconds=30)
    with pytest.raises(MfaError) as excinfo:
        mfa.elevate(
            session,
            outsider,
            organization.id,
            generate(enrollment.secret_bytes, clock.value),
            memberships=memberships,
        )
    assert excinfo.value.code == "not_a_member"
