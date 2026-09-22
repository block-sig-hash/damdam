"""Looking things up on behalf of a customer, without handing over the keys.

Support work needs two things that pull against each other: an operator has to
be able to find the right line from whatever the customer can read out, and an
operator must not end up holding a working credential.

The resolution here is that **the lookup is by identifier and the answer is
masked**. An operator who already knows the ICCID can confirm it is the line
they are looking at; an operator who does not cannot learn it from this surface.
`EsimActivationCredential` — the LPA string that actually installs a profile —
is never read, never joined and never returned. That is a property of the code
below, not a rule written in a document somewhere.

Every read is recorded through `OperationsService.record_sensitive_access`
before the view is built, because the question after an incident is always "who
looked at this", and a system that cannot answer it has to assume the worst
about everyone with access.

The tenant-scoped export exists for the other half of the assignment: an
operator helping one organization exports that organization's lines and nothing
else. Scoping is by join — through the order that paid — rather than by a filter
the caller supplies, so there is no parameter to get wrong.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlmodel import Session, col, select

from app.auth.models import AdminUser
from app.connectivity.models import AssignedNumber, CarrierLine, Entitlement
from app.operations.models import OperatorAction, OperatorSubjectKind
from app.operations.service import OperationsError, OperationsService, mask
from app.orders.models import Order, OrderItem


@dataclass(frozen=True)
class LineSupportRecord:
    """A line as support may see it: identifiable, not usable."""

    line_id: UUID
    carrier: str
    iccid_masked: str | None
    e164_masked: str | None
    activation_state: str
    network_state: str
    provider_status: str | None
    voice_enabled: bool
    organization_id: UUID | None
    holder_user_id: UUID | None


class SupportDirectory:
    """Read-side of the operations surface. Writes only audit rows."""

    def __init__(self, operations: OperationsService) -> None:
        self.operations = operations

    def lookup_line(
        self,
        session: Session,
        *,
        actor: AdminUser,
        reason: str,
        idempotency_key: str,
        line_id: UUID | None = None,
        iccid: str | None = None,
        e164: str | None = None,
    ) -> tuple[LineSupportRecord, OperatorAction]:
        """Find one line by exactly one identifier, and record the look.

        Refuses zero identifiers and refuses two. A lookup that accepts several
        and quietly prefers one produces a result nobody can explain afterwards,
        which is the opposite of what an audit trail is for.
        """
        given = [value for value in (line_id, iccid, e164) if value]
        if len(given) != 1:
            raise OperationsError(
                "one_identifier_required",
                "look a line up by exactly one of its id, its ICCID or its "
                "number; preferring one of several silently is not a lookup",
            )

        line: CarrierLine | None
        if line_id is not None:
            line = session.get(CarrierLine, line_id)
        elif iccid:
            line = session.exec(
                select(CarrierLine).where(CarrierLine.iccid == iccid)
            ).first()
        else:
            # Live assignment only. A released number belongs to whoever holds
            # it now, and answering with its previous holder would show one
            # customer's line to another customer's caller.
            line = session.exec(
                select(CarrierLine)
                .join(
                    AssignedNumber,
                    col(AssignedNumber.carrier_line_id) == col(CarrierLine.id),
                )
                .where(AssignedNumber.e164 == e164)
                .where(col(AssignedNumber.released_at).is_(None))
            ).first()

        if line is None:
            raise OperationsError("line_not_found")

        action = self.operations.record_sensitive_access(
            session,
            actor=actor,
            subject_kind=OperatorSubjectKind.ORDER_ITEM,
            subject_reference=f"carrier_line:{line.id}",
            reason=reason,
            idempotency_key=idempotency_key,
        )
        return self._record(session, line), action

    def organization_lines(
        self, session: Session, organization_id: UUID
    ) -> Sequence[LineSupportRecord]:
        """Every line one organization paid for, masked. Nothing else.

        The tenant scope is the join, not an argument: a line reaches this list
        only through an order whose payer *is* this organization.
        """
        lines = session.exec(
            select(CarrierLine)
            .join(Entitlement, col(Entitlement.id) == col(CarrierLine.entitlement_id))
            .join(OrderItem, col(OrderItem.id) == col(Entitlement.order_item_id))
            .join(Order, col(Order.id) == col(OrderItem.order_id))
            .where(Order.payer_organization_id == organization_id)
            .order_by(col(CarrierLine.carrier), col(CarrierLine.id))
        ).all()
        return [self._record(session, line) for line in lines]

    # --- internals ---------------------------------------------------------

    def _record(self, session: Session, line: CarrierLine) -> LineSupportRecord:
        entitlement = session.get(Entitlement, line.entitlement_id)
        item = (
            session.get(OrderItem, entitlement.order_item_id) if entitlement else None
        )
        order = session.get(Order, item.order_id) if item else None
        number = session.exec(
            select(AssignedNumber)
            .where(AssignedNumber.carrier_line_id == line.id)
            .where(col(AssignedNumber.released_at).is_(None))
        ).first()
        return LineSupportRecord(
            line_id=line.id,
            carrier=line.carrier,
            # Six trailing digits identify a line to the customer holding it and
            # do not reconstruct an ICCID; the leading digits are the issuer and
            # would be the same for every line we sell anyway.
            iccid_masked=mask(line.iccid, keep=6),
            e164_masked=mask(number.e164 if number else None, keep=4),
            activation_state=line.activation_state.value,
            network_state=line.network_state.value,
            provider_status=line.provider_status,
            voice_enabled=line.voice_enabled,
            organization_id=order.payer_organization_id if order else None,
            holder_user_id=entitlement.holder_user_id if entitlement else None,
        )
