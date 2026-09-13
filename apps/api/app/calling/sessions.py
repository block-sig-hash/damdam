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

from sqlalchemy import text
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
        device_id = device_id.strip()
        if not device_id:
            raise ClientSessionError("device_id_required")
        self._lock_device(session, user.id, device_id)
        return self._issue_locked(
            session, user, device_id=device_id, device_label=device_label
        )

    def _issue_locked(
        self,
        session: Session,
        user: User,
        *,
        device_id: str,
        device_label: str | None,
    ) -> tuple[CallingClientCredential, ClientSession]:
        credential = self._credential(session, user, device_id)
        now = self.clock()
        if (
            credential is not None
            and credential.state is CredentialState.OUTCOME_UNKNOWN
        ):
            raise ClientSessionError("session_outcome_unknown")
        if (
            credential is not None
            and credential.state is CredentialState.PROVISIONING
            and credential.issuance_dispatched_at is not None
        ):
            if _aware(credential.issuance_dispatched_at) >= now - timedelta(minutes=2):
                raise ClientSessionError("session_outcome_unknown")
            credential.state = CredentialState.OUTCOME_UNKNOWN
            credential.issuance_detail = "process stopped after provider dispatch"
            session.add(credential)
            session.commit()
            raise ClientSessionError("session_outcome_unknown")
        self._check_rate(credential)
        if credential is None:
            credential = CallingClientCredential(
                user_id=user.id,
                device_id=device_id,
                device_label=device_label,
                provider=self.adapter.name,
                state=CredentialState.PROVISIONING,
                created_at=now,
            )
            session.add(credential)
        credential.issuance_reference = uuid4()
        credential.issuance_dispatched_at = now
        credential.issuance_detail = None
        self._count_session(credential, now)
        session.add(credential)
        # Persist the exact request and the rate-limit debit before the external
        # effect. A crash after this point is ambiguous and must not create a
        # second provider credential.
        session.commit()
        try:
            issued = self.adapter.issue_client_session(
                operation_reference=credential.issuance_reference,
                device_label=device_label or device_id,
                provider_credential_id=credential.provider_credential_id,
                sip_identity=credential.sip_identity,
                credential_expires_at=credential.expires_at,
            )
        except CallOutcomeUnknown as exc:
            # A credential may or may not exist at the provider now. Creating a
            # second one would leave an unrevocable orphan able to register, so
            # this stops and says so.
            if credential.provider_credential_id is None:
                credential.state = CredentialState.OUTCOME_UNKNOWN
            credential.issuance_detail = exc.reason[:500]
            session.add(credential)
            session.commit()
            raise ClientSessionError(
                "session_outcome_unknown",
                f"the provider's response was lost: {exc.reason}",
            ) from exc
        except CallingError as exc:
            if credential.provider_credential_id is None:
                credential.state = CredentialState.REVOKED
                credential.revoked_at = self.clock()
                credential.revoked_reason = "provider rejected credential issuance"
            credential.issuance_detail = (exc.detail or exc.code)[:500]
            session.add(credential)
            session.commit()
            raise ClientSessionError(exc.code, exc.detail) from exc
        credential.provider_credential_id = issued.provider_credential_id
        credential.provider_connection_id = issued.provider_connection_id
        credential.sip_identity = issued.identity
        credential.expires_at = issued.expires_at
        credential.state = CredentialState.ACTIVE
        credential.issuance_detail = None
        session.add(credential)
        session.flush()
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
            CallingClientCredential.state != CredentialState.REVOKED,
        )
        if credential_id is not None:
            statement = statement.where(CallingClientCredential.id == credential_id)
        elif device_id is not None:
            statement = statement.where(
                CallingClientCredential.device_id == device_id
            )
        revoked = list(session.exec(statement.with_for_update()).all())
        for credential in revoked:
            credential.state = CredentialState.REVOKED
            credential.revoked_at = self.clock()
            credential.revoked_reason = reason[:200]
            session.add(credential)
        # Make local withdrawal durable before asking the provider to delete.
        # A lost delete response must never leave our own grant path trusting it.
        session.commit()
        for credential in revoked:
            detail = reason
            try:
                if credential.provider_credential_id is None:
                    detail = f"{reason}; provider credential id unknown"
                else:
                    self.adapter.revoke_client_credential(
                        credential.provider_credential_id
                    )
            except (CallingError, CallOutcomeUnknown) as exc:
                detail = f"{reason}; provider revocation unconfirmed: {exc}"
            credential.revoked_reason = detail[:200]
            session.add(credential)
        session.flush()
        return revoked

    def on_account_recovered(
        self, session: Session, user: User, at: datetime
    ) -> None:
        """Recovery invalidates every provider credential for the account."""
        del at
        self.revoke(session, user, reason="account_recovered")

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

    def _credential(
        self, session: Session, user: User, device_id: str
    ) -> CallingClientCredential | None:
        return session.exec(
            select(CallingClientCredential).where(
                CallingClientCredential.user_id == user.id,
                CallingClientCredential.device_id == device_id,
                CallingClientCredential.state != CredentialState.REVOKED,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()

    @staticmethod
    def _lock_device(session: Session, user_id: UUID, device_id: str) -> None:
        """Serialize creation through the committed provisioning marker."""
        bind = session.get_bind()
        if bind.dialect.name == "postgresql":
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"calling-credential:{user_id}:{device_id}"},
            )

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

    @staticmethod
    def _count_session(
        credential: CallingClientCredential, now: datetime
    ) -> None:
        within_window = (
            credential.last_session_issued_at is not None
            and _aware(credential.last_session_issued_at)
            >= now - timedelta(hours=1)
        )
        credential.sessions_issued = (
            credential.sessions_issued + 1 if within_window else 1
        )
        credential.last_session_issued_at = now

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
