"""Out-of-band delivery of identity tokens, behind a transport abstraction.

The launch channel is undecided, and live sending is explicitly not authorised
by chunk 06. So the service depends on this Protocol, never on an email client:
choosing email later means supplying a transport, not rewriting the flow.

`RecordingDeliveryTransport` is the test transport. It is the only
implementation this chunk ships that actually does anything, and it sends
nothing anywhere.
"""

from dataclasses import dataclass, field
from typing import Protocol

from app.auth.models import Locale
from app.identity.models import IdentifierKind, IdentityTokenPurpose


@dataclass(frozen=True)
class DeliveryRequest:
    kind: IdentifierKind
    value: str
    purpose: IdentityTokenPurpose
    token: str
    locale: Locale


class DeliveryTransport(Protocol):
    def send(self, request: DeliveryRequest) -> None: ...


@dataclass
class RecordingDeliveryTransport:
    """Records what would have been sent. Sends nothing."""

    sent: list[DeliveryRequest] = field(default_factory=list)

    def send(self, request: DeliveryRequest) -> None:
        self.sent.append(request)

    def last_token(self) -> str:
        if not self.sent:
            raise AssertionError("no identity message was delivered")
        return self.sent[-1].token

    def clear(self) -> None:
        self.sent.clear()


@dataclass
class NullDeliveryTransport:
    """Discards messages.

    The default wiring until a channel is adopted and its provider configured.
    Deliberately not an error: the identity flows must be exercisable in staging
    without live delivery, and a silent drop is safer than a half-configured
    provider that emails real people from a test environment.
    """

    def send(self, request: DeliveryRequest) -> None:
        return None
