"""Per-device client credentials and the short sessions issued from them.

One rule, from V01 §7 and reuse item F3: **one provider credential belongs to one
device or browser installation, and can be revoked without changing the user's
other credentials.** The retired model gave each *user* one credential, which
Telnyx's own guidance advises against and which makes revocation useless in
practice — signing out a lost phone would sign out every device the customer
owns, so nobody ever does it.

What this module never does is hand a client anything reusable. A session is a
short-lived token bounded by the credential's own stated expiry, and the account
API key stays on the server. That is not defence in depth; it is the only defence
there is, because V01 established that a Telnyx JWT carries no per-destination
scope — a leaked long-lived one is a funded dialler.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlmodel import Session, select

from app.auth.models import User, utc_now
from app.calling.contract import (
    CallingAdapter,
    CallingError,
    CallOutcomeUnknown,
    IssuedClientSession,
)
from app.calling.models import CallingClientCredential, CredentialState


class ClientSessionError(Exception):
    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail or code)


@dataclass(frozen=True)
class ClientSession:
    """What the client receives. Deliberately three fields.

    No connection id, no credential id, no account reference. A client that knows
    only its token and its own identity cannot be talked into using any of them
    for something else, and nothing in the calling flow needs it to.
    """

    token: str
    sip_identity: str
    expires_at: datetime

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"ClientSession(<redacted>, identity={self.sip_identity!r})"

    __str__ = __repr__


class ClientSessionService:
    def __init__(
        self,
        adapter: CallingAdapter,
        *,
        clock: Callable[[], datetime] = utc_now,
        sessions_per_hour: int = 20,
    ) -> None:
        self.adapter = adapter
        self.clock = clock
        self.sessions_per_hour = sessions_per_hour

    def issue(
        self,
        session: Session,
        user: User,
        *,
        device_id: str,
        device_label: str | None = None,
    ) -> tuple[CallingClientCredential, ClientSession]:
        """Issue a session for this device, creating its credential if needed.

        The rate limit is counted on the credential row rather than in Redis.
        The amendment requires credential issuance to be rate limited, and a
        counter a process restart clears is not a limit — it is a speed bump that
        disappears the moment anybody is deliberately attacking it.
        """
        if not device_id.strip():
            raise ClientSessionError("device_id_required")
        credential = self._live_credential(session, user, device_id)
        self._check_rate(credential)

        operation_reference = uuid4()
        try:
            issued = self.adapter.issue_client_session(
                operation_reference=operation_reference,
                device_label=device_label or device_id,
            )
        except CallOutcomeUnknown as exc:
            # A credential may or may not exist at the provider now. Creating a
            # second one would leave an unrevocable orphan able to register, so
            # this stops and says so.
            raise ClientSessionError(
                "session_outcome_unknown",
                f"the provider's response was lost: {exc.reason}",
            ) from exc
        except CallingError as exc:
            raise ClientSessionError(exc.code, exc.detail) from exc

        credential = self._record(
            session, user, credential, device_id, device_label, issued
        )
        return credential, ClientSession(
            token=issued.token,
            sip_identity=issued.identity,
            expires_at=self._bounded_expiry(issued, credential),
        )

    def revoke(
        self,
        session: Session,
        user: User,
        *,
        device_id: str | None = None,
        credential_id: UUID | None = None,
        reason: str = "revoked",
    ) -> list[CallingClientCredential]:
        """Withdraw one device's credential, or all of this user's.

        Revocation is local-first and deliberately tolerant of a provider error:
        the row is marked revoked whatever the provider says, because a
        credential we have stopped honouring is more useful than one we failed to
        delete remotely and therefore left active in our own records. The
        provider call is best-effort and its failure is not hidden — it is left
        on the row.
        """
        statement = select(CallingClientCredential).where(
            CallingClientCredential.user_id == user.id,
            CallingClientCredential.state == CredentialState.ACTIVE,
        )
        if credential_id is not None:
            statement = statement.where(CallingClientCredential.id == credential_id)
        elif device_id is not None:
            statement = statement.where(
                CallingClientCredential.device_id == device_id
            )
        revoked: list[CallingClientCredential] = []
        for credential in session.exec(statement).all():
            detail = reason
            try:
                self.adapter.revoke_client_credential(
                    credential.provider_credential_id
                )
            except (CallingError, CallOutcomeUnknown) as exc:
                detail = f"{reason}; provider revocation unconfirmed: {exc}"
            credential.state = CredentialState.REVOKED
            credential.revoked_at = self.clock()
            credential.revoked_reason = detail[:200]
            session.add(credential)
            revoked.append(credential)
        session.flush()
        return revoked

    def active(
        self, session: Session, user: User
    ) -> list[CallingClientCredential]:
        return list(
            session.exec(
                select(CallingClientCredential).where(
                    CallingClientCredential.user_id == user.id,
                    CallingClientCredential.state == CredentialState.ACTIVE,
                )
            ).all()
        )

    # --- internals ----------------------------------------------------------

    def _live_credential(
        self, session: Session, user: User, device_id: str
    ) -> CallingClientCredential | None:
        return session.exec(
            select(CallingClientCredential).where(
                CallingClientCredential.user_id == user.id,
                CallingClientCredential.device_id == device_id,
                CallingClientCredential.state == CredentialState.ACTIVE,
            )
        ).first()

    def _check_rate(self, credential: CallingClientCredential | None) -> None:
        if credential is None or credential.last_session_issued_at is None:
            return
        window_start = self.clock() - timedelta(hours=1)
        if _aware(credential.last_session_issued_at) < window_start:
            return
        if credential.sessions_issued >= self.sessions_per_hour:
            raise ClientSessionError(
                "session_rate_limited",
                "too many client sessions issued for this device",
            )

    def _record(
        self,
        session: Session,
        user: User,
        credential: CallingClientCredential | None,
        device_id: str,
        device_label: str | None,
        issued: IssuedClientSession,
    ) -> CallingClientCredential:
        now = self.clock()
        if credential is None:
            credential = CallingClientCredential(
                user_id=user.id,
                device_id=device_id,
                device_label=device_label,
                provider=self.adapter.name,
                provider_credential_id=issued.provider_credential_id,
                provider_connection_id=issued.provider_connection_id,
                sip_identity=issued.identity,
                state=CredentialState.ACTIVE,
                expires_at=issued.expires_at,
                sessions_issued=0,
                created_at=now,
            )
        else:
            credential.provider_credential_id = issued.provider_credential_id
            credential.provider_connection_id = issued.provider_connection_id
            credential.sip_identity = issued.identity
            credential.expires_at = issued.expires_at
        within_window = (
            credential.last_session_issued_at is not None
            and _aware(credential.last_session_issued_at)
            >= now - timedelta(hours=1)
        )
        credential.sessions_issued = (
            credential.sessions_issued + 1 if within_window else 1
        )
        credential.last_session_issued_at = now
        session.add(credential)
        session.flush()
        return credential

    def _bounded_expiry(
        self, issued: IssuedClientSession, credential: CallingClientCredential
    ) -> datetime:
        """A session never outlives its parent credential.

        Telnyx documents a JWT lifetime of at most 24 hours *or* the parent
        credential's earlier expiry. Reporting the token's own claim when the
        credential dies sooner would tell a client it has a working session for
        hours after it has stopped working.
        """
        if credential.expires_at is None:
            return issued.expires_at
        return min(_aware(issued.expires_at), _aware(credential.expires_at))


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
