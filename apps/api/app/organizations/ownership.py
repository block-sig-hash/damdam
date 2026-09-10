"""Who a purchased line may belong to (US-29, chunk 07 outcome 5).

Two rules, and both of them are about a request *parameter* being trusted:

1. **A resource is reached only through its own tenant.** Looking an order up
   by id and then checking who owns it is the right shape; looking it up and
   assuming the caller's organization owns it is the breach. `resolve_order`
   takes the organization from the caller's membership, never from the body.
2. **A recipient must be a member of the paying organization.** Otherwise
   changing `recipient_user_id` moves a line -- and the service, usage and
   personal data attached to it -- to somebody in another tenant, or to a
   private individual who never agreed to be enrolled.

Personal ownership stays separate on purpose. An order a person paid for
themselves has `payer_user_id` set and no organization, and no organization
actor can reassign it at all: an employer must not be able to take over a line
their employee bought, and "our administrator can edit any order with our
domain in it" is how that happens.

No endpoint calls this yet. Bulk assignment is chunk 23's surface, and
inventing the route here would put an unreviewed endpoint in the spec. The rule
and its tests exist now because chunk 23 must not have to re-derive it.
"""

from uuid import UUID

from sqlmodel import Session, select

from app.orders.models import Order, OrderItem
from app.organizations.models import MembershipStatus, OrganizationMember


class OwnershipError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def resolve_order(
    session: Session, organization_id: UUID, order_id: UUID
) -> Order:
    """Load an order *as* this organization, or report it as absent.

    Absent, not forbidden: distinguishing the two would confirm that an order
    id exists in some other tenant, which is the same oracle AC-29.4 closes on
    organizations themselves.
    """
    order = session.exec(
        select(Order).where(
            Order.id == order_id,
            Order.payer_organization_id == organization_id,
        )
    ).first()
    if order is None:
        raise OwnershipError("order_not_found")
    return order


def resolve_order_item(
    session: Session, organization_id: UUID, order_item_id: UUID
) -> OrderItem:
    item = session.get(OrderItem, order_item_id)
    if item is None:
        raise OwnershipError("order_item_not_found")
    # The join is the check. Reading the item first and trusting an
    # `organization_id` from the request body is the defect this prevents.
    try:
        resolve_order(session, organization_id, item.order_id)
    except OwnershipError as exc:
        raise OwnershipError("order_item_not_found") from exc
    return item


def assert_assignable_recipient(
    session: Session, organization_id: UUID, recipient_user_id: UUID
) -> None:
    membership = session.exec(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == recipient_user_id,
            OrganizationMember.status == MembershipStatus.ACTIVE,
        )
    ).first()
    if membership is None:
        raise OwnershipError("recipient_not_in_organization")


def assign_recipient(
    session: Session,
    organization_id: UUID,
    order_item_id: UUID,
    recipient_user_id: UUID,
) -> OrderItem:
    """Both checks, in the only order that is safe.

    The item is resolved through the caller's own tenant first, so a foreign
    item is refused before its recipient is even considered; then the recipient
    is checked against that same tenant, so an item can never be pointed at
    somebody outside it.
    """
    item = resolve_order_item(session, organization_id, order_item_id)
    assert_assignable_recipient(session, organization_id, recipient_user_id)
    item.recipient_user_id = recipient_user_id
    session.add(item)
    session.flush()
    return item
