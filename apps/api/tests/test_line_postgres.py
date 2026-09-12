"""US-38 chunk 20 — installation material under concurrency, on PostgreSQL.

One property, and it is the reason the delivery path is two calls rather than
one: **a grant is spent exactly once, even when two connections spend it at the
same moment.**

That matters more here than almost anywhere else in the product. A Telnyx eSIM
profile is one-time use; Telnyx documents that a downloaded profile cannot be
re-downloaded. So a race that delivers the same profile to two places is not a
double-read — it is a paid-for line that somebody else may install, with no
remedy short of another purchase.

SQLite cannot show this. The guarantee is a `SELECT … FOR UPDATE` on the grant
row, which needs two real connections actually contending.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Barrier
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

from app import model_registry  # noqa: F401  -- completes SQLModel.metadata
from app.auth.models import Locale, User, UserStatus
from app.catalog.models import LegalEntity, Product, ProductKind
from app.connectivity.credentials import CredentialError, CredentialVault
from app.connectivity.models import (
    CredentialGrant,
    Entitlement,
    EsimActivationCredential,
    EsimInstallation,
    InstallationState,
)
from app.orders.models import Order, OrderItem, PaymentState, ProvisioningState

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="single-use delivery is enforced by row locking, not by convention",
)

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
LPA = "LPA:1$rsp.example.test$CONCURRENCY-TEST-CODE"
TABLES = (
    "esim_credential_grants, esim_activation_credentials, esim_installations, "
    "entitlements, order_items, orders, products, legal_entities, users"
)


class Clock:
    def __init__(self) -> None:
        self.value = NOW

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: Any) -> None:
        self.value += timedelta(**kwargs)


@pytest.fixture(scope="module")
def engine():
    url = os.environ["TEST_DATABASE_URL"]
    engine = create_engine(url)
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine) -> Session:
    with Session(engine) as session:
        session.exec(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
        session.commit()
        yield session


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def vault(clock: Clock) -> CredentialVault:
    # A per-run key from the OS, never a constant: a key in a fixture is a key
    # in the repository, and `security.md` keeps activation material out of both.
    return CredentialVault(os.urandom(32), "test-key", clock=clock)


def _user(session: Session, phone: str) -> User:
    user = User(
        phone_number=phone,
        email=f"holder{phone[-4:]}@example.test",
        locale=Locale.EN,
        status=UserStatus.ACTIVE,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _installation(session: Session, holder: User) -> EsimInstallation:
    entity = LegalEntity(code=uuid4().hex[:8], name="Seller", country="NG")
    product = Product(sku=uuid4().hex[:12], name="Travel", kind=ProductKind.BUNDLE)
    session.add(entity)
    session.add(product)
    session.commit()
    session.refresh(entity)
    session.refresh(product)

    order = Order(
        reference=f"OR-{uuid4().hex[:8].upper()}",
        seller_legal_entity_id=entity.id,
        payer_user_id=holder.id,
        currency="NGN",
        total_amount=Decimal("10000.00"),
        payment_state=PaymentState.PAID,
        placed_at=NOW,
    )
    session.add(order)
    session.commit()
    session.refresh(order)

    item = OrderItem(
        order_id=order.id,
        product_id=product.id,
        recipient_user_id=holder.id,
        quantity=1,
        unit_currency="NGN",
        unit_amount=Decimal("10000.00"),
        provisioning_state=ProvisioningState.PROVISIONED,
    )
    session.add(item)
    session.commit()
    session.refresh(item)

    entitlement = Entitlement(
        order_item_id=item.id,
        holder_user_id=holder.id,
        product_id=product.id,
        data_bytes_total=1_073_741_824,
        voice_seconds_total=600,
        granted_at=NOW,
    )
    session.add(entitlement)
    session.commit()
    session.refresh(entitlement)

    installation = EsimInstallation(
        entitlement_id=entitlement.id,
        installation_state=InstallationState.NOT_INSTALLED,
        profile_released_at=NOW,
    )
    session.add(installation)
    session.commit()
    session.refresh(installation)
    return installation


def test_two_simultaneous_redemptions_deliver_one_profile(
    engine, session: Session, vault: CredentialVault, clock: Clock
) -> None:
    """The race that would hand a one-time eSIM to two places.

    Both threads hold a valid token for the same grant and hit `redeem` at the
    same instant. Exactly one gets the profile; the other gets the same refusal
    an expired grant gets, and `delivery_count` moves by one.
    """
    holder = _user(session, "+2348010000101")
    installation = _installation(session, holder)
    credential = vault.store(session, installation, LPA)
    issued = vault.issue_grant(session, credential, holder.id)
    session.commit()
    token = issued.token
    credential_id = credential.id
    holder_id = holder.id

    barrier = Barrier(2)

    def redeem() -> tuple[bool, str]:
        with Session(engine) as own:
            worker = CredentialVault(vault._key, "test-key", clock=clock)  # noqa: SLF001
            barrier.wait(timeout=10)
            try:
                secret = worker.redeem(own, token, holder_id)
                own.commit()
                return True, secret
            except CredentialError as error:
                own.rollback()
                return False, error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(redeem) for _ in range(2)]
        outcomes = [future.result() for future in futures]

    succeeded = [outcome for outcome in outcomes if outcome[0]]
    refused = [outcome for outcome in outcomes if not outcome[0]]
    assert len(succeeded) == 1
    assert succeeded[0][1] == LPA
    assert len(refused) == 1
    assert refused[0][1] == "grant_not_redeemable"

    session.expire_all()
    stored = session.get(EsimActivationCredential, credential_id)
    assert stored.delivery_count == 1


def test_a_second_grant_is_a_second_delivery_not_a_second_profile(
    session: Session, vault: CredentialVault
) -> None:
    """Two grants for one credential still yield the same one-time code.

    Worth stating because a customer who taps "show my eSIM" twice does mint two
    grants, and the profile they get must be the profile they bought — not a
    second one, which does not exist, and not a refusal, which would strand
    somebody whose screen locked mid-scan.
    """
    holder = _user(session, "+2348010000102")
    installation = _installation(session, holder)
    credential = vault.store(session, installation, LPA)
    first = vault.issue_grant(session, credential, holder.id)
    second = vault.issue_grant(session, credential, holder.id)
    session.commit()

    assert vault.redeem(session, first.token, holder.id) == LPA
    assert vault.redeem(session, second.token, holder.id) == LPA
    session.commit()

    session.refresh(credential)
    assert credential.delivery_count == 2


def test_an_expired_grant_is_refused_the_same_way_as_an_unknown_one(
    session: Session, vault: CredentialVault, clock: Clock
) -> None:
    holder = _user(session, "+2348010000103")
    installation = _installation(session, holder)
    credential = vault.store(session, installation, LPA)
    issued = vault.issue_grant(session, credential, holder.id)
    session.commit()

    clock.advance(minutes=11)

    with pytest.raises(CredentialError) as expired:
        vault.redeem(session, issued.token, holder.id)
    with pytest.raises(CredentialError) as unknown:
        vault.redeem(session, "a-token-that-was-never-issued", holder.id)

    # Identical. An attacker learning that a token *existed* learns something.
    assert expired.value.code == unknown.value.code == "grant_not_redeemable"


def test_a_grant_does_not_survive_the_credential_changing_hands(
    session: Session, vault: CredentialVault
) -> None:
    """Ownership is re-derived at redemption, not trusted from issue time."""
    holder = _user(session, "+2348010000104")
    stranger = _user(session, "+2348010000105")
    installation = _installation(session, holder)
    credential = vault.store(session, installation, LPA)
    issued = vault.issue_grant(session, credential, holder.id)
    session.commit()

    entitlement = session.get(Entitlement, installation.entitlement_id)
    entitlement.holder_user_id = stranger.id
    session.add(entitlement)
    session.commit()

    with pytest.raises(CredentialError) as raised:
        vault.redeem(session, issued.token, holder.id)

    assert raised.value.code == "grant_not_redeemable"


def test_the_plaintext_profile_is_never_stored(
    session: Session, vault: CredentialVault
) -> None:
    """A database dump is not a set of working eSIMs."""
    holder = _user(session, "+2348010000106")
    installation = _installation(session, holder)
    credential = vault.store(session, installation, LPA)
    issued = vault.issue_grant(session, credential, holder.id)
    session.commit()

    assert LPA.encode() not in credential.ciphertext
    assert LPA not in credential.fingerprint
    grant = session.exec(
        select(CredentialGrant).where(CredentialGrant.credential_id == credential.id)
    ).first()
    # The token is returned once and never stored in a usable form, so a
    # compromised database cannot mint deliveries of the profiles it holds.
    assert grant.token_fingerprint != issued.token
    assert issued.token not in grant.token_fingerprint
