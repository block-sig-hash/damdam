"""What has to be true before an account can be deleted, and who says so.

Deletion is the one account operation that cannot be undone by support, so this
module is built around a single idea: **a deletion request is answered with a
list of reasons, not a boolean.** A customer told "you cannot delete your
account" closes the app; a customer told "your work line is still paying for two
other people, and a refund of NGN 4,000 is still in progress" knows what to do.

Three rules decide what blocks:

1. **Money that has not finished moving blocks deletion.** A pending refund, an
   unsettled liability or a payment we have not reconciled is a conversation
   still in progress, and erasing the person it is with does not end it — it
   ends our ability to finish it. `AGENTS.md`: order and audit history is never
   erased because a screen was removed.
2. **Other people's service blocks deletion.** An organization owner whose
   members hold live lines cannot delete themselves out from under them. The
   assignment is explicit: *do not erase other members' services.*
3. **Nothing else does.** Everything that only concerns the person asking — old
   orders, closed tickets, expired sessions — is retained or erased per the
   recorded retention policy, and never used as a reason to refuse.

The checks are a **registry**, not a hard-coded list, and that is deliberate.
Chunk 21's base does not contain the calling tables: V02 and V03 are unmerged
branches, and the calling amendment requires active call liabilities and grant
revocation to be part of deletion. A registry lets that chunk add its probe
where it lives, rather than this module importing a table that does not exist
yet or, worse, a later chunk quietly forgetting. `LIABILITY_PROBES` is the seam;
`docs/implementation/handoffs/21.md` names it as the thing V03 must plug into.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from sqlmodel import Session, col, select

from app.auth.models import User, utc_now
from app.connectivity.models import Entitlement
from app.organizations.models import (
    MembershipStatus,
    OrganizationMember,
    OrganizationRole,
)


class BlockerKind(str, Enum):
    """Why a deletion cannot proceed yet. Each one is actionable by the customer."""

    #: A refund, dispute or payment that has not reached a final state.
    UNSETTLED_MONEY = "unsettled_money"
    #: Live service that other people are using, owned by this account.
    OTHERS_DEPEND_ON_THIS_ACCOUNT = "others_depend_on_this_account"
    #: A liability this deployment knows about through a registered probe —
    #: an active call, an open grant — contributed by the chunk that owns it.
    ACTIVE_LIABILITY = "active_liability"
    ACTIVE_SERVICE = "active_service"


@dataclass(frozen=True)
class DeletionBlocker:
    """One reason, in words the customer can act on."""

    kind: BlockerKind
    #: A stable code the app maps to a localized string. The `detail` below is
    #: for the audit record and for support, never for display: it can name
    #: another member's line, and the person deleting their account does not
    #: need to be told what somebody else is using.
    code: str
    detail: str
    amount: Decimal | None = None
    currency: str | None = None


@dataclass(frozen=True)
class DeletionAssessment:
    """The answer to "may I delete this account?" — with its reasons."""

    blockers: Sequence[DeletionBlocker] = field(default_factory=tuple)

    @property
    def may_delete(self) -> bool:
        return not self.blockers


#: Probes contributed by other chunks. Each takes a session and a user and
#: returns whatever it considers blocking. Registered at import time by the
#: module that owns the table, so a chunk that is not deployed contributes
#: nothing rather than raising.
LiabilityProbe = Callable[[Session, User], Sequence[DeletionBlocker]]
LIABILITY_PROBES: list[LiabilityProbe] = []


def register_liability_probe(probe: LiabilityProbe) -> LiabilityProbe:
    """Add a blocking check without this module importing the chunk that owns it.

    Idempotent by identity so a module imported twice — which happens under
    test collection — does not register its probe twice and report every
    blocker in duplicate.
    """
    if probe not in LIABILITY_PROBES:
        LIABILITY_PROBES.append(probe)
    return probe


def assess(
    session: Session, user: User, now: datetime | None = None
) -> DeletionAssessment:
    """Everything standing between this account and erasure, gathered once."""
    blockers: list[DeletionBlocker] = []
    blockers.extend(_unsettled_money(session, user))
    blockers.extend(_active_services(session, user, now or utc_now()))
    blockers.extend(_others_depend_on(session, user))
    for probe in LIABILITY_PROBES:
        blockers.extend(probe(session, user))
    return DeletionAssessment(tuple(blockers))


def _active_services(
    session: Session, user: User, now: datetime
) -> Sequence[DeletionBlocker]:
    """A live personal or work entitlement cannot be orphaned by deletion."""
    active = session.exec(
        select(Entitlement).where(
            Entitlement.holder_user_id == user.id,
            (col(Entitlement.expires_at).is_(None))
            | (col(Entitlement.expires_at) > now),
        )
    ).first()
    if active is None:
        return ()
    return (
        DeletionBlocker(
            BlockerKind.ACTIVE_SERVICE,
            "active_service",
            f"entitlement {active.id} is still active",
        ),
    )


def _unsettled_money(
    session: Session, user: User
) -> Sequence[DeletionBlocker]:
    """Refunds that have not reached a final state.

    Imported lazily for the same reason the probes exist: this module is about
    the *rule*, and a top-level import of every financial table would make it
    the module that knows about all of them.

    `UNKNOWN` counts as open, and that is the important one. A refund whose
    outcome we lost is the case where deleting the customer is most expensive:
    the money may or may not have moved, and the only person who could tell us
    is the account being erased.
    """
    from app.orders.models import Order
    from app.payments.contract import AttemptStatus, PaymentAttempt, PaymentIntent
    from app.refunds.models import Refund, RefundStatus

    open_states = [
        RefundStatus.REQUESTED,
        RefundStatus.PENDING,
        RefundStatus.UNKNOWN,
    ]
    refunds = session.exec(
        select(Refund)
        .join(PaymentAttempt, col(Refund.payment_attempt_id) == col(PaymentAttempt.id))
        .join(PaymentIntent, col(PaymentAttempt.intent_id) == col(PaymentIntent.id))
        .join(Order, col(PaymentIntent.order_id) == col(Order.id))
        .where(
            Order.payer_user_id == user.id,
            col(Refund.status).in_(open_states),
        )
    ).all()
    blockers = list(
        DeletionBlocker(
            BlockerKind.UNSETTLED_MONEY,
            "refund_in_progress",
            f"refund {refund.id} is {refund.status.value}",
            amount=refund.amount,
            currency=refund.currency,
        )
        for refund in refunds
    )
    attempts = session.exec(
        select(PaymentAttempt, PaymentIntent)
        .join(PaymentIntent, col(PaymentAttempt.intent_id) == col(PaymentIntent.id))
        .join(Order, col(PaymentIntent.order_id) == col(Order.id))
        .where(
            Order.payer_user_id == user.id,
            col(PaymentAttempt.status).in_(
                [AttemptStatus.CREATED, AttemptStatus.PENDING, AttemptStatus.UNKNOWN]
            ),
        )
    ).all()
    blockers.extend(
        DeletionBlocker(
            BlockerKind.UNSETTLED_MONEY,
            "payment_in_progress",
            f"payment attempt {attempt.id} is {attempt.status.value}",
            amount=intent.amount,
            currency=intent.currency,
        )
        for attempt, intent in attempts
    )
    return tuple(blockers)


def _others_depend_on(session: Session, user: User) -> Sequence[DeletionBlocker]:
    """Organizations this person owns that still have other active members.

    An owner is not refused because they are an owner. They are refused because
    leaving would strand somebody — so an organization whose only active member
    is the person asking does not block anything.
    """
    owned = session.exec(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.role == OrganizationRole.OWNER,
            OrganizationMember.status == MembershipStatus.ACTIVE,
        )
    ).all()
    blockers: list[DeletionBlocker] = []
    for membership in owned:
        others = session.exec(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == membership.organization_id,
                OrganizationMember.user_id != user.id,
                OrganizationMember.status == MembershipStatus.ACTIVE,
            )
        ).all()
        if others:
            blockers.append(
                DeletionBlocker(
                    BlockerKind.OTHERS_DEPEND_ON_THIS_ACCOUNT,
                    "organization_has_other_members",
                    f"organization {membership.organization_id} has "
                    f"{len(others)} other active members; transfer ownership "
                    "before deleting this account",
                )
            )
    return tuple(blockers)


def organization_ids_owned(session: Session, user_id: UUID) -> list[UUID]:
    """Used by the export, which includes what this person owns."""
    rows = session.exec(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.role == OrganizationRole.OWNER,
            OrganizationMember.status == MembershipStatus.ACTIVE,
        )
    ).all()
    return [row.organization_id for row in rows]
