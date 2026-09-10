"""What this account has, and whether any of it works yet (US-37).

Read-only. Every field it returns is a fact some other chunk recorded; the only
thing this module decides is which of those facts the customer's Home screen is
allowed to treat as "you have service".

The rule it exists to enforce, from the approved calling amendment: *"Internet
calling must not require an eSIM installation or carrier line foreign key."* An
internet-only account that is asked to install a profile has been sent to look
for something that was never created. So `ServiceDelivery` is derived from
whether provisioning actually produced a `carrier_lines` row -- an observed fact
-- and not from the product's kind, its name, or what a sales page said.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlmodel import Session, col, select

from app.auth.models import Organization, User
from app.catalog.models import Product
from app.connectivity.models import (
    ActivationState,
    CarrierLine,
    Entitlement,
    EsimInstallation,
    InstallationState,
)
from app.consumer.schemas import (
    InvitationPreviewResponse,
    InvitationPreviewState,
    OrganizationMembershipSummary,
    ServiceDelivery,
    ServiceOwner,
    ServiceState,
    ServiceSummary,
)
from app.identity.models import AccountIdentifier, IdentifierKind
from app.orders.models import Order, OrderItem, ProvisioningState
from app.organizations.invitations import InvitationError, InvitationService
from app.organizations.models import (
    InvitationStatus,
    MembershipStatus,
    OrganizationMember,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


def mask_identifier(kind: IdentifierKind, value: str) -> str:
    """Enough for the owner to recognize; not enough for anyone else to learn.

    An email keeps its first and last local character and its full domain, so
    the invited person sees their own address and a finder of the link sees a
    shape. A phone keeps its last two digits only -- country codes and prefixes
    are guessable, so revealing more of a number reveals most of it.
    """
    if kind is IdentifierKind.PHONE:
        return f"{'•' * max(len(value) - 2, 0)}{value[-2:]}" if value else ""
    local, _, domain = value.partition("@")
    if not domain:
        return "•" * len(value)
    if len(local) <= 2:
        return f"{local[:1]}{'•' * 3}@{domain}"
    return f"{local[0]}{'•' * 3}{local[-1]}@{domain}"


@dataclass(frozen=True)
class ServicesView:
    state: ServiceState
    services: tuple[ServiceSummary, ...]


class ConsumerService:
    def __init__(self, clock: Callable[[], datetime] = utc_now) -> None:
        self.clock = clock

    # --- services ---------------------------------------------------------

    def services(self, session: Session, user: User) -> ServicesView:
        """Every service this account holds, personal and organization-provided.

        Ownership is taken from two independent places on purpose. `OrderItem.
        recipient_user_id` is who the line was *bought for*; `Entitlement.
        holder_user_id` is who currently *holds* it. They agree for a consumer
        purchase and can diverge for an enterprise assignment, and a customer who
        holds a reassigned line must still see it.
        """
        now = self.clock()
        rows = session.exec(
            select(OrderItem, Order, Product)
            .join(Order, col(Order.id) == col(OrderItem.order_id))
            .join(Product, col(Product.id) == col(OrderItem.product_id))
            .where(col(OrderItem.recipient_user_id) == user.id)
            .order_by(col(Order.placed_at).desc())
        ).all()
        by_item: dict[UUID, tuple[OrderItem, Order, Product]] = {
            item.id: (item, order, product) for item, order, product in rows
        }

        held = session.exec(
            select(Entitlement, OrderItem, Order, Product)
            .join(OrderItem, col(OrderItem.id) == col(Entitlement.order_item_id))
            .join(Order, col(Order.id) == col(OrderItem.order_id))
            .join(Product, col(Product.id) == col(OrderItem.product_id))
            .where(col(Entitlement.holder_user_id) == user.id)
        ).all()
        for _entitlement, item, order, product in held:
            by_item.setdefault(item.id, (item, order, product))

        if not by_item:
            return ServicesView(state=ServiceState.NONE, services=())

        entitlements = self._entitlements(session, by_item)
        installations = self._installations(session, entitlements.values())
        carrier_lines = self._carrier_lines(session, entitlements.values())
        organizations = self._organizations(
            session,
            {
                order.payer_organization_id
                for _item, order, _product in by_item.values()
                if order.payer_organization_id is not None
            },
        )

        summaries = []
        for item, order, product in by_item.values():
            entitlement = entitlements.get(item.id)
            entitlement_id = entitlement.id if entitlement is not None else None
            summaries.append(
                self._summarize(
                    item=item,
                    order=order,
                    product=product,
                    entitlement=entitlement,
                    installation=installations.get(entitlement_id),
                    carrier_line=carrier_lines.get(entitlement_id),
                    organization=organizations.get(order.payer_organization_id),
                    now=now,
                )
            )
        summaries.sort(
            key=lambda summary: (not summary.ready_to_use, summary.order_reference)
        )
        return ServicesView(state=self._state(summaries), services=tuple(summaries))

    @staticmethod
    def _state(summaries: Iterable[ServiceSummary]) -> ServiceState:
        """`ACTIVE` if anything is usable, else `PENDING` if anything is coming.

        A cancelled or failed item alone does not make an account "pending": the
        customer is not waiting for it, and telling them to wait for something
        that already failed is the dead end AC-37.5 is about. It still appears
        in the list, with its own state, so the failure has a route out.
        """
        state = ServiceState.NONE
        for summary in summaries:
            if summary.ready_to_use:
                return ServiceState.ACTIVE
            if summary.provisioning_state in {
                ProvisioningState.FAILED.value,
                ProvisioningState.CANCELLED.value,
            }:
                continue
            if summary.expired:
                continue
            state = ServiceState.PENDING
        return state

    def _summarize(
        self,
        *,
        item: OrderItem,
        order: Order,
        product: Product,
        entitlement: Entitlement | None,
        installation: EsimInstallation | None,
        carrier_line: CarrierLine | None,
        organization: Organization | None,
        now: datetime,
    ) -> ServiceSummary:
        # The carrier line is the discriminator, not the product kind. A voice
        # bundle sold for an eSIM and one sold for internet calling are the same
        # `ProductKind`; only one of them has a line the customer must install.
        delivery = (
            ServiceDelivery.CARRIER_ESIM
            if carrier_line is not None or installation is not None
            else ServiceDelivery.INTERNET
        )
        expires_at = _aware(entitlement.expires_at) if entitlement else None
        expired = expires_at is not None and expires_at <= now

        if delivery is ServiceDelivery.CARRIER_ESIM:
            requires_installation = True
            ready = (
                not expired
                and installation is not None
                and installation.installation_state is InstallationState.INSTALLED
                and carrier_line is not None
                and carrier_line.activation_state is ActivationState.ACTIVE
            )
        else:
            # No profile, no installation step. The grant itself is the service:
            # once it exists and has not expired, the customer can place a call.
            requires_installation = False
            ready = entitlement is not None and not expired

        return ServiceSummary(
            order_item_id=item.id,
            order_id=order.id,
            order_reference=order.reference,
            product_name=product.name,
            delivery=delivery,
            owner=(
                ServiceOwner.ORGANIZATION
                if order.payer_organization_id is not None
                else ServiceOwner.PERSONAL
            ),
            organization_id=order.payer_organization_id,
            organization_name=organization.name if organization is not None else None,
            payment_state=order.payment_state.value,
            provisioning_state=item.provisioning_state.value,
            installation_state=(
                installation.installation_state.value
                if installation is not None
                else None
            ),
            activation_state=(
                carrier_line.activation_state.value
                if carrier_line is not None
                else None
            ),
            requires_installation=requires_installation,
            ready_to_use=ready,
            granted_at=_aware(entitlement.granted_at) if entitlement else None,
            expires_at=expires_at,
            expired=expired,
        )

    @staticmethod
    def _entitlements(
        session: Session, by_item: dict[UUID, tuple[OrderItem, Order, Product]]
    ) -> dict[UUID, Entitlement]:
        rows = session.exec(
            select(Entitlement).where(
                col(Entitlement.order_item_id).in_(list(by_item))
            )
        ).all()
        return {row.order_item_id: row for row in rows}

    @staticmethod
    def _installations(
        session: Session, entitlements: Iterable[Entitlement]
    ) -> dict[UUID | None, EsimInstallation]:
        ids = [entitlement.id for entitlement in entitlements]
        if not ids:
            return {}
        rows = session.exec(
            select(EsimInstallation).where(
                col(EsimInstallation.entitlement_id).in_(ids)
            )
        ).all()
        return {row.entitlement_id: row for row in rows}

    @staticmethod
    def _carrier_lines(
        session: Session, entitlements: Iterable[Entitlement]
    ) -> dict[UUID | None, CarrierLine]:
        ids = [entitlement.id for entitlement in entitlements]
        if not ids:
            return {}
        rows = session.exec(
            select(CarrierLine).where(col(CarrierLine.entitlement_id).in_(ids))
        ).all()
        return {row.entitlement_id: row for row in rows}

    @staticmethod
    def _organizations(
        session: Session, ids: set[UUID]
    ) -> dict[UUID | None, Organization]:
        if not ids:
            return {}
        rows = session.exec(
            select(Organization).where(col(Organization.id).in_(list(ids)))
        ).all()
        return {row.id: row for row in rows}

    # --- session ----------------------------------------------------------

    def verified_identifiers(
        self, session: Session, user: User
    ) -> tuple[list[str], list[str]]:
        rows = session.exec(
            select(AccountIdentifier).where(
                AccountIdentifier.user_id == user.id,
                col(AccountIdentifier.verified_at).is_not(None),
            )
        ).all()
        emails = [row.value for row in rows if row.kind is IdentifierKind.EMAIL]
        phones = [row.value for row in rows if row.kind is IdentifierKind.PHONE]
        return sorted(emails), sorted(phones)

    def memberships(
        self, session: Session, user: User
    ) -> list[OrganizationMembershipSummary]:
        rows = session.exec(
            select(OrganizationMember, Organization)
            .join(
                Organization,
                col(Organization.id) == col(OrganizationMember.organization_id),
            )
            .where(
                OrganizationMember.user_id == user.id,
                OrganizationMember.status == MembershipStatus.ACTIVE,
            )
            .order_by(col(Organization.name))
        ).all()
        return [
            OrganizationMembershipSummary(
                organization_id=organization.id,
                name=organization.name,
                role=member.role.value,
            )
            for member, organization in rows
        ]

    # --- invitations ------------------------------------------------------

    def preview_invitation(
        self,
        session: Session,
        user: User,
        token: str,
        invitations: InvitationService,
    ) -> InvitationPreviewResponse:
        """Describe an invitation without claiming it (AC-37.3, AC-37.4).

        Needed because the app must be able to show *who a link is for* before
        the recipient signs in as anybody. Without it, the only way to find out
        an invitation belongs to someone else is to attempt acceptance -- and a
        person holding two accounts would discover the mistake only after the
        membership had been created on the wrong one.

        A missing token is reported as `invitation_invalid` by the caller, not
        here: this returns a preview or raises, and never invents a state.
        """
        invitation = invitations.find_by_token(session, token)
        if invitation is None:
            raise InvitationError("invitation_invalid")

        organization = session.get(Organization, invitation.organization_id)
        if organization is None:  # pragma: no cover - FK makes this unreachable
            raise InvitationError("invitation_invalid")

        now = self.clock()
        expires_at = _aware(invitation.expires_at)
        if invitation.status is InvitationStatus.ACCEPTED:
            state = InvitationPreviewState.ACCEPTED
        elif invitation.status is InvitationStatus.REVOKED:
            state = InvitationPreviewState.REVOKED
        elif expires_at is not None and now >= expires_at:
            state = InvitationPreviewState.EXPIRED
        else:
            state = InvitationPreviewState.PENDING

        owned = {
            (row.kind, row.value)
            for row in session.exec(
                select(AccountIdentifier).where(
                    AccountIdentifier.user_id == user.id,
                    col(AccountIdentifier.verified_at).is_not(None),
                )
            ).all()
        }
        member = session.exec(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == invitation.organization_id,
                OrganizationMember.user_id == user.id,
                OrganizationMember.status == MembershipStatus.ACTIVE,
            )
        ).first()

        return InvitationPreviewResponse(
            state=state,
            organization_name=organization.name,
            role=invitation.role.value,
            invited_kind=invitation.invited_kind.value,
            invited_value_masked=mask_identifier(
                invitation.invited_kind, invitation.invited_value
            ),
            expires_at=expires_at,
            recipient_matches=(invitation.invited_kind, invitation.invited_value)
            in owned,
            already_a_member=member is not None,
        )

    def pending_invitation_count(
        self, session: Session, user: User, invitations: InvitationService
    ) -> int:
        return len(invitations.list_for_user(session, user))
