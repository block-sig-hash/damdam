"""US-29 chunk 07B — recipient-bound, expiring invitations.

Written before the implementation, per the strict-TDD policy for tenant
isolation and object-level authorization.

An invitation is a credential that grants standing access to an organization's
data. The failure modes are therefore the same as any other credential's, plus
one that is specific to invitations: a link forwarded, leaked or guessed by
somebody other than the intended recipient must be worth nothing. That is why
holding the link is *not* what proves you may accept it -- holding the verified
identifier it was addressed to is.
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
from app.identity.models import AccountIdentifier, IdentifierKind
from app.organizations.invitations import InvitationError, InvitationService
from app.organizations.models import (
    InvitationStatus,
    MembershipStatus,
    OrganizationInvitation,
    OrganizationMember,
    OrganizationRole,
)
from app.organizations.service import MembershipService

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="invitation races and partial indexes require PostgreSQL",
)

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
INVITED = "newjoiner@example.test"
STRANGER = "stranger@example.test"


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


def _truncate(session: Session) -> None:
    session.exec(
        text(
            "TRUNCATE organization_invitations, organization_members, "
            "organizations, account_identifiers, identity_tokens, "
            "refresh_tokens, users RESTART IDENTITY CASCADE"
        )
    )
    session.commit()


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        _truncate(session)
        yield session
        session.rollback()


@pytest.fixture
def clock():
    return FrozenClock()


@pytest.fixture
def memberships(clock):
    return MembershipService(clock=clock)


@pytest.fixture
def service(clock, memberships):
    return InvitationService(memberships=memberships, clock=clock)


def _user(session: Session, label: str, email: str | None = None) -> User:
    user = User(
        phone_number=f"+23481{abs(hash(label)) % 10**8:08d}",
        first_name=label,
        platform=Platform.ANDROID,
    )
    session.add(user)
    session.flush()
    if email is not None:
        session.add(
            AccountIdentifier(
                user_id=user.id,
                kind=IdentifierKind.EMAIL,
                value=email.lower(),
                verified_at=NOW,
                is_primary=True,
            )
        )
        session.flush()
    return user


def _unverified_claim(session: Session, user: User, email: str) -> None:
    session.add(
        AccountIdentifier(
            user_id=user.id, kind=IdentifierKind.EMAIL, value=email.lower()
        )
    )
    session.flush()


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


def _owner(session, memberships, organization):
    user = _user(session, f"owner-{uuid4().hex[:6]}")
    return memberships.seed_member(
        session, organization, user, OrganizationRole.OWNER
    )


# --- who may invite, and to what ------------------------------------------


def test_a_member_cannot_invite_anyone(session, service, memberships):
    organization = _organization(session)
    _owner(session, memberships, organization)
    plain = memberships.seed_member(
        session, organization, _user(session, "plain"), OrganizationRole.MEMBER
    )
    session.commit()

    with pytest.raises(InvitationError) as excinfo:
        service.invite(
            session, actor=plain, email=INVITED, role=OrganizationRole.MEMBER
        )
    assert excinfo.value.code == "permission_denied"


def test_an_administrator_cannot_invite_an_owner(session, service, memberships):
    """Otherwise "invite" is a one-step escalation to the top of the account."""
    organization = _organization(session)
    _owner(session, memberships, organization)
    admin = memberships.seed_member(
        session,
        organization,
        _user(session, "admin"),
        OrganizationRole.ADMINISTRATOR,
    )
    session.commit()

    with pytest.raises(InvitationError) as excinfo:
        service.invite(
            session, actor=admin, email=INVITED, role=OrganizationRole.OWNER
        )
    assert excinfo.value.code == "role_change_forbidden"
    assert session.exec(select(OrganizationInvitation)).all() == []


# --- recipient binding is the whole point ---------------------------------


def test_a_leaked_link_is_worthless_to_anyone_else(session, service, memberships):
    organization = _organization(session)
    owner = _owner(session, memberships, organization)
    session.commit()
    token = service.invite(
        session, actor=owner, email=INVITED, role=OrganizationRole.MEMBER
    ).token
    session.commit()

    interceptor = _user(session, "interceptor", STRANGER)
    session.commit()

    with pytest.raises(InvitationError) as excinfo:
        service.accept_by_token(session, user=interceptor, token=token)
    assert excinfo.value.code == "invitation_recipient_mismatch"
    assert session.exec(select(OrganizationMember)).all() == [owner]


def test_an_unverified_claim_on_the_invited_address_does_not_accept_it(
    session, service, memberships
):
    """Claiming an address must never be as good as proving it."""
    organization = _organization(session)
    owner = _owner(session, memberships, organization)
    session.commit()
    token = service.invite(
        session, actor=owner, email=INVITED, role=OrganizationRole.MEMBER
    ).token
    session.commit()

    squatter = _user(session, "squatter")
    _unverified_claim(session, squatter, INVITED)
    session.commit()

    with pytest.raises(InvitationError) as excinfo:
        service.accept_by_token(session, user=squatter, token=token)
    assert excinfo.value.code == "invitation_recipient_mismatch"


def test_the_intended_recipient_joins_with_exactly_the_invited_role(
    session, service, memberships
):
    organization = _organization(session)
    owner = _owner(session, memberships, organization)
    session.commit()
    token = service.invite(
        session, actor=owner, email=INVITED, role=OrganizationRole.BILLING
    ).token
    session.commit()

    joiner = _user(session, "joiner", INVITED)
    session.commit()
    membership = service.accept_by_token(session, user=joiner, token=token)
    session.commit()

    assert membership.role is OrganizationRole.BILLING
    assert membership.status is MembershipStatus.ACTIVE
    assert membership.organization_id == organization.id
    assert membership.invited_by_user_id == owner.user_id


def test_the_address_is_matched_case_insensitively(session, service, memberships):
    organization = _organization(session)
    owner = _owner(session, memberships, organization)
    session.commit()
    token = service.invite(
        session, actor=owner, email="Mixed.Case@Example.Test",
        role=OrganizationRole.MEMBER,
    ).token
    session.commit()

    joiner = _user(session, "mixed", "mixed.case@example.test")
    session.commit()
    membership = service.accept_by_token(session, user=joiner, token=token)
    assert membership.role is OrganizationRole.MEMBER


# --- expiry and replay -----------------------------------------------------


def test_expiry_is_exclusive_at_the_exact_boundary(
    session, service, memberships, clock
):
    organization = _organization(session)
    owner = _owner(session, memberships, organization)
    session.commit()
    issued = service.invite(
        session, actor=owner, email=INVITED, role=OrganizationRole.MEMBER
    )
    session.commit()
    joiner = _user(session, "late", INVITED)
    session.commit()

    clock.value = issued.invitation.expires_at.replace(tzinfo=timezone.utc)
    with pytest.raises(InvitationError) as excinfo:
        service.accept_by_token(session, user=joiner, token=issued.token)
    assert excinfo.value.code == "invitation_expired"


def test_an_invitation_cannot_be_accepted_twice(session, service, memberships):
    organization = _organization(session)
    owner = _owner(session, memberships, organization)
    session.commit()
    token = service.invite(
        session, actor=owner, email=INVITED, role=OrganizationRole.MEMBER
    ).token
    session.commit()
    joiner = _user(session, "joiner", INVITED)
    session.commit()

    service.accept_by_token(session, user=joiner, token=token)
    session.commit()
    with pytest.raises(InvitationError) as excinfo:
        service.accept_by_token(session, user=joiner, token=token)
    assert excinfo.value.code == "invitation_invalid"


def test_a_revoked_invitation_cannot_be_accepted(session, service, memberships):
    organization = _organization(session)
    owner = _owner(session, memberships, organization)
    session.commit()
    issued = service.invite(
        session, actor=owner, email=INVITED, role=OrganizationRole.MEMBER
    )
    session.commit()
    service.revoke(session, actor=owner, invitation_id=issued.invitation.id)
    session.commit()

    joiner = _user(session, "joiner", INVITED)
    session.commit()
    with pytest.raises(InvitationError) as excinfo:
        service.accept_by_token(session, user=joiner, token=issued.token)
    assert excinfo.value.code == "invitation_invalid"


def test_the_raw_token_is_never_stored(session, service, memberships):
    organization = _organization(session)
    owner = _owner(session, memberships, organization)
    session.commit()
    issued = service.invite(
        session, actor=owner, email=INVITED, role=OrganizationRole.MEMBER
    )
    session.commit()

    stored = session.get(OrganizationInvitation, issued.invitation.id)
    assert stored.token_hash != issued.token
    assert issued.token not in str(stored.model_dump())


def test_concurrent_acceptance_creates_exactly_one_membership(
    engine, service, memberships
):
    """Two clicks on the same link, at the same moment, from the same mailbox."""
    with Session(engine) as setup:
        _truncate(setup)
        organization = _organization(setup)
        owner = _owner(setup, memberships, organization)
        setup.commit()
        token = service.invite(
            setup, actor=owner, email=INVITED, role=OrganizationRole.MEMBER
        ).token
        setup.commit()
        joiner = _user(setup, "joiner", INVITED)
        setup.commit()
        organization_id = organization.id
        joiner_id = joiner.id

    barrier = Barrier(2)

    def accept(_: int) -> str:
        with Session(engine) as scoped:
            user = scoped.get(User, joiner_id)
            barrier.wait(timeout=10)
            try:
                service.accept_by_token(scoped, user=user, token=token)
                scoped.commit()
                return "ok"
            except InvitationError as exc:
                scoped.rollback()
                return exc.code
            except Exception:
                scoped.rollback()
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(accept, range(2)))

    assert outcomes.count("ok") == 1, outcomes
    with Session(engine) as check:
        members = check.exec(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.user_id == joiner_id,
            )
        ).all()
    assert len(members) == 1


def test_a_second_pending_invitation_to_the_same_address_is_refused(
    session, service, memberships
):
    organization = _organization(session)
    owner = _owner(session, memberships, organization)
    session.commit()
    service.invite(
        session, actor=owner, email=INVITED, role=OrganizationRole.MEMBER
    )
    session.commit()

    with pytest.raises(InvitationError) as excinfo:
        service.invite(
            session, actor=owner, email=INVITED, role=OrganizationRole.ADMINISTRATOR
        )
    assert excinfo.value.code == "invitation_already_pending"


def test_the_database_refuses_two_pending_invitations_for_one_address(
    session, service, memberships
):
    organization = _organization(session)
    owner = _owner(session, memberships, organization)
    session.commit()
    service.invite(
        session, actor=owner, email=INVITED, role=OrganizationRole.MEMBER
    )
    session.commit()

    session.add(
        OrganizationInvitation(
            organization_id=organization.id,
            role=OrganizationRole.MEMBER,
            invited_kind=IdentifierKind.EMAIL,
            invited_value=INVITED,
            token_hash=uuid4().hex,
            expires_at=NOW + timedelta(days=7),
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


# --- cross-tenant ----------------------------------------------------------


def test_an_invitation_cannot_be_revoked_from_another_organization(
    session, service, memberships
):
    acme = _organization(session, "Acme")
    other = _organization(session, "Other")
    acme_owner = _owner(session, memberships, acme)
    other_owner = _owner(session, memberships, other)
    session.commit()
    issued = service.invite(
        session, actor=acme_owner, email=INVITED, role=OrganizationRole.MEMBER
    )
    session.commit()

    with pytest.raises(InvitationError) as excinfo:
        service.revoke(session, actor=other_owner, invitation_id=issued.invitation.id)
    assert excinfo.value.code == "invitation_not_found"
    session.rollback()
    assert (
        session.get(OrganizationInvitation, issued.invitation.id).status
        is InvitationStatus.PENDING
    )


def test_accepting_when_already_a_member_is_refused(session, service, memberships):
    organization = _organization(session)
    owner = _owner(session, memberships, organization)
    session.commit()
    token = service.invite(
        session, actor=owner, email=INVITED, role=OrganizationRole.ADMINISTRATOR
    ).token
    session.commit()

    joiner = _user(session, "joiner", INVITED)
    memberships.seed_member(
        session, organization, joiner, OrganizationRole.MEMBER
    )
    session.commit()

    with pytest.raises(InvitationError) as excinfo:
        service.accept_by_token(session, user=joiner, token=token)
    assert excinfo.value.code == "already_a_member"
    session.rollback()
    membership = memberships.active_membership(
        session, organization.id, joiner.id
    )
    assert membership.role is OrganizationRole.MEMBER


def test_a_revoked_member_rejoins_through_the_same_membership_row(
    session, service, memberships
):
    organization = _organization(session)
    owner = _owner(session, memberships, organization)
    session.commit()
    joiner = _user(session, "returner", INVITED)
    membership = memberships.seed_member(
        session, organization, joiner, OrganizationRole.ADMINISTRATOR
    )
    session.commit()
    memberships.revoke(session, actor=owner, target_user_id=joiner.id)
    session.commit()

    token = service.invite(
        session, actor=owner, email=INVITED, role=OrganizationRole.MEMBER
    ).token
    session.commit()
    rejoined = service.accept_by_token(session, user=joiner, token=token)
    session.commit()

    assert rejoined.id == membership.id
    assert rejoined.role is OrganizationRole.MEMBER
    assert rejoined.status is MembershipStatus.ACTIVE


# --- bootstrap invitations for existing organizations ---------------------


def test_a_bootstrap_invitation_is_claimed_by_the_verified_contact(
    session, service, memberships
):
    """The controlled migration path: no token, no auto-promotion.

    An organization that predates memberships gets one *pending owner
    invitation* addressed to its recorded contact address. Nobody is made an
    owner by the migration; the contact becomes one only by proving they can
    read that mailbox and claiming it.
    """
    organization = _organization(session)
    invitation = service.seed_bootstrap_owner_invitation(session, organization)
    session.commit()

    assert invitation.expires_at is None
    assert invitation.token_hash is None
    assert invitation.is_bootstrap is True
    assert invitation.role is OrganizationRole.OWNER

    contact = _user(session, "contact", organization.email)
    session.commit()
    pending = service.list_for_user(session, contact)
    assert [item.id for item in pending] == [invitation.id]

    membership = service.accept(session, user=contact, invitation_id=invitation.id)
    session.commit()
    assert membership.role is OrganizationRole.OWNER


def test_a_bootstrap_invitation_is_not_offered_to_a_stranger(
    session, service, memberships
):
    organization = _organization(session)
    service.seed_bootstrap_owner_invitation(session, organization)
    session.commit()

    stranger = _user(session, "stranger", STRANGER)
    session.commit()
    assert service.list_for_user(session, stranger) == []


def test_seeding_a_bootstrap_invitation_twice_is_idempotent(
    session, service, memberships
):
    organization = _organization(session)
    first = service.seed_bootstrap_owner_invitation(session, organization)
    session.commit()
    second = service.seed_bootstrap_owner_invitation(session, organization)
    session.commit()
    assert first.id == second.id


def test_no_bootstrap_invitation_once_the_organization_has_an_owner(
    session, service, memberships
):
    """A migration re-run must not offer ownership of a live organization."""
    organization = _organization(session)
    _owner(session, memberships, organization)
    session.commit()
    assert service.seed_bootstrap_owner_invitation(session, organization) is None
