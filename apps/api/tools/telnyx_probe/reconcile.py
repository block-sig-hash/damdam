"""Reconciliation decisions for an eSIM purchase with an unknown outcome.

This is the finding-4 logic expressed against the *documented* Telnyx contract:
`POST /actions/purchase/esims` has no idempotency key, so a lost response cannot
be made safe by retrying. It can only be made safe by looking up what the
supplier actually created, using the per-attempt correlation tag.

Nothing here calls Telnyx. It turns "what did the lookup return" into "what is
the system allowed to do next", so that decision is reviewable and testable
before chunk 15 wires it to a live API.

The bias throughout is: when the evidence is ambiguous, stop and ask a human.
Buying a second eSIM costs a customer money and produces a profile nobody
installs.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from .contracts import ContractViolation, SimCard, operation_tag


class ReconciliationOutcome(str, Enum):
    """What the lookup proved, and therefore what may happen next."""

    #: Exactly the requested number of SIMs carry our tag. Adopt them.
    COMPLETE = "complete"
    #: Nothing carries our tag. The purchase may safely be retried with the
    #: SAME tag -- subject to the consistency caveat below.
    NOT_LANDED = "not_landed"
    #: Some but not all landed. Never auto-retry: a top-up purchase and a
    #: duplicate look identical from here.
    PARTIAL = "partial"
    #: More SIMs than requested carry our tag. A duplicate already happened.
    OVER_DELIVERED = "over_delivered"


@dataclass(frozen=True)
class ReconciliationDecision:
    outcome: ReconciliationOutcome
    matched: tuple[SimCard, ...]
    requested: int
    may_retry_purchase: bool
    requires_manual_review: bool
    reason: str

    @property
    def matched_count(self) -> int:
        return len(self.matched)


def reconcile_purchase(
    *,
    requested_amount: int,
    operation_reference: UUID,
    sim_cards: tuple[SimCard, ...] | list[SimCard],
    lookup_is_trusted: bool,
) -> ReconciliationDecision:
    """Classify a purchase whose response we never saw.

    `sim_cards` is the result of
    `GET /sim_cards?filter[tags][]=damdam-op-<operation_reference>`.

    `lookup_is_trusted` encodes the single most dangerous unknown in this whole
    design: Telnyx does not document whether a just-created eSIM is immediately
    visible to a tag filter. If it is not, an empty result is indistinguishable
    from "the purchase never landed" -- and acting on that would double-purchase,
    which is the exact defect finding 4 describes.

    Until that consistency question is answered live (see API-CONTRACTS.md §2.3
    question 2), callers must pass ``lookup_is_trusted=False``, and an empty
    result is escalated instead of retried.
    """
    if type(requested_amount) is not int or requested_amount < 1:
        raise ContractViolation("requested_amount must be a positive integer")
    if not isinstance(operation_reference, UUID):
        raise ContractViolation("operation_reference must be a UUID")

    expected_tag = operation_tag(operation_reference)
    matched = tuple(card for card in sim_cards if expected_tag in card.tags)

    if len(matched) != len(tuple(sim_cards)):
        # The filter is documented as AND-across-tags, so every row returned
        # should carry our tag. If one does not, we are not looking at what we
        # think we are looking at.
        return ReconciliationDecision(
            outcome=ReconciliationOutcome.PARTIAL,
            matched=matched,
            requested=requested_amount,
            may_retry_purchase=False,
            requires_manual_review=True,
            reason=(
                "lookup returned SIM cards that do not carry the operation tag; "
                "the query or the filter semantics are not what we assumed"
            ),
        )

    if len(matched) == requested_amount:
        return ReconciliationDecision(
            outcome=ReconciliationOutcome.COMPLETE,
            matched=matched,
            requested=requested_amount,
            may_retry_purchase=False,
            requires_manual_review=False,
            reason="every requested eSIM exists and carries the operation tag",
        )

    if len(matched) > requested_amount:
        return ReconciliationDecision(
            outcome=ReconciliationOutcome.OVER_DELIVERED,
            matched=matched,
            requested=requested_amount,
            may_retry_purchase=False,
            requires_manual_review=True,
            reason=(
                f"{len(matched)} eSIMs carry the operation tag but only "
                f"{requested_amount} were requested -- a duplicate purchase has "
                "already occurred and must be unwound by a human"
            ),
        )

    if matched:
        return ReconciliationDecision(
            outcome=ReconciliationOutcome.PARTIAL,
            matched=matched,
            requested=requested_amount,
            may_retry_purchase=False,
            requires_manual_review=True,
            reason=(
                f"{len(matched)} of {requested_amount} eSIMs landed; topping up "
                "the shortfall is a separate decision, not a retry of this "
                "attempt"
            ),
        )

    if not lookup_is_trusted:
        return ReconciliationDecision(
            outcome=ReconciliationOutcome.NOT_LANDED,
            matched=(),
            requested=requested_amount,
            may_retry_purchase=False,
            requires_manual_review=True,
            reason=(
                "no eSIM carries the operation tag, but tag-filter consistency "
                "after purchase is undocumented -- an empty result cannot yet "
                "be distinguished from a purchase that landed and is not yet "
                "visible, so this stops for manual reconciliation"
            ),
        )

    return ReconciliationDecision(
        outcome=ReconciliationOutcome.NOT_LANDED,
        matched=(),
        requested=requested_amount,
        may_retry_purchase=True,
        requires_manual_review=False,
        reason=(
            "no eSIM carries the operation tag and the lookup is trusted to be "
            "immediately consistent; retry with the same operation reference"
        ),
    )
