"""Apple Pay and Google Pay availability, feature-gated (US-33, chunk 13).

These are **presentation methods on a processor's hosted checkout**, not
separate payment rails and emphatically not Apple's or Google's in-app billing.
The assignment is explicit on the last point — *"Do not implement Apple/Google
store billing for carrier bundles"* — because store billing takes a commission
on the sale and applies store rules to a service the stores do not provide.

Availability is a conjunction of four things, and every one of them can be
false today:

1. a **selected processor** that supports the wallet — D4 is open, so there is
   none;
2. a **live merchant account** — D3/D4, so there is none;
3. **domain or app registration** with the wallet provider, which is a manual
   step with an external approval attached;
4. the **device actually offering it**, which only the client knows.

`is_available` returns false unless all four hold, and the reason it returns is
the one a support engineer needs. Nothing here makes a wallet appear; it decides
whether one may be *offered*, and until D4 closes the answer is no.
"""

from dataclasses import dataclass
from enum import Enum


class Wallet(str, Enum):
    APPLE_PAY = "apple_pay"
    GOOGLE_PAY = "google_pay"


class WalletUnavailableReason(str, Enum):
    NO_PROCESSOR_SELECTED = "no_processor_selected"
    PROCESSOR_DOES_NOT_SUPPORT = "processor_does_not_support"
    MERCHANT_NOT_LIVE = "merchant_not_live"
    DOMAIN_NOT_REGISTERED = "domain_not_registered"
    DEVICE_DOES_NOT_OFFER = "device_does_not_offer"


@dataclass(frozen=True)
class WalletAvailability:
    available: bool
    reason: WalletUnavailableReason | None = None

    @property
    def explanation(self) -> str:
        if self.available:
            return "available"
        return (self.reason or WalletUnavailableReason.NO_PROCESSOR_SELECTED).value


@dataclass(frozen=True)
class WalletConfiguration:
    """What has actually been set up. Every field defaults to "nothing".

    Defaulting to configured would make a wallet appear the moment somebody
    added a processor, before the domain registration a wallet provider
    requires — and the customer would see a payment button that fails.
    """

    #: The processor D4 selects. `None` today.
    processor: str | None = None
    supported_wallets: frozenset[Wallet] = frozenset()
    merchant_is_live: bool = False
    #: Domains (web) or bundle identifiers (app) registered with the wallet
    #: provider. A manual step with an external approval attached.
    registered_domains: frozenset[str] = frozenset()


def is_available(
    configuration: WalletConfiguration,
    wallet: Wallet,
    domain: str,
    device_offers_wallet: bool,
) -> WalletAvailability:
    """All four conditions, checked in the order a person would ask them.

    Order matters for the message: "no processor is selected" is more useful to
    whoever is debugging than "your device does not offer Apple Pay", and both
    are true today.
    """
    if configuration.processor is None:
        return WalletAvailability(False, WalletUnavailableReason.NO_PROCESSOR_SELECTED)
    if wallet not in configuration.supported_wallets:
        return WalletAvailability(
            False, WalletUnavailableReason.PROCESSOR_DOES_NOT_SUPPORT
        )
    if not configuration.merchant_is_live:
        return WalletAvailability(False, WalletUnavailableReason.MERCHANT_NOT_LIVE)
    if domain not in configuration.registered_domains:
        return WalletAvailability(
            False, WalletUnavailableReason.DOMAIN_NOT_REGISTERED
        )
    if not device_offers_wallet:
        # Only the client knows this, and it is last because it is the only one
        # that is not a configuration problem.
        return WalletAvailability(
            False, WalletUnavailableReason.DEVICE_DOES_NOT_OFFER
        )
    return WalletAvailability(True)


#: The live configuration. Empty, and deliberately not a placeholder pointing at
#: a candidate processor: a default that names Stripe would be a decision D4 has
#: not made, sitting in code where it reads like one that was.
CURRENT_CONFIGURATION = WalletConfiguration()


def card_fallback_required(availability: WalletAvailability) -> bool:
    """Whenever a wallet is unavailable, card must still be offered.

    Which is always, today. A checkout that offers only a wallet on a device
    that does not have one is a checkout nobody can complete.
    """
    return not availability.available
