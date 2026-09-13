"""eSIM installation material: sealed at rest, delivered under a short grant.

US-35, chunk 15. `security.md` keeps activation material out of code, logs,
fixtures and evidence; this module is where that stops being a rule people
remember and becomes a shape the code has.

The property that drives every decision here: **a Telnyx eSIM activation code
is one-time use.** Telnyx documents that a lost profile cannot be re-downloaded
and needs a fresh purchase. So the usual reasoning about secrets — rotate it if
it leaks — does not apply. There is nothing to rotate. A leaked activation code
is a paid-for profile that somebody else can install instead of the customer,
and the only remedy is buying another one.

That gives three requirements, each of which is met structurally rather than by
convention:

1. **Plaintext is never at rest.** `seal` encrypts with AES-256-GCM under a key
   named by a reference; a database dump on its own is not a set of working
   eSIMs. The row stores the reference, not the key.
2. **The value never needs to be handled to be talked about.** `fingerprint` is
   a keyed BLAKE2b hash. Support, tests and audit records compare fingerprints;
   nothing outside this module ever sees a code in order to identify one.
3. **Delivery is authorized, short and single-use.** A `CredentialGrant` is
   bound to a person, expires in minutes, and is redeemable exactly once. The
   alternative — returning the code to anyone holding a session — makes the
   profile as durable as the session, and sessions last a month.

`AAD` is worth one line of explanation: AES-GCM authenticates additional data
alongside the ciphertext, and binding the installation id into it means a
ciphertext moved from one row to another fails to decrypt. Without it, an
attacker with write access could swap two customers' profiles and both would
decrypt cleanly.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlmodel import Session, col, select

from app.auth.models import utc_now
from app.connectivity.models import (
    CredentialGrant,
    Entitlement,
    EsimActivationCredential,
    EsimInstallation,
)

#: 96 bits, the AES-GCM standard nonce length. A nonce is generated per seal and
#: prefixed to the ciphertext; reusing one under the same key destroys the
#: cipher's security entirely, so it is never derived from anything.
_NONCE_BYTES = 12

#: How long a delivery grant lives. Long enough to open an app and scan a code,
#: short enough that a link left in a chat is worthless by the time anyone finds
#: it.
DEFAULT_GRANT_TTL = timedelta(minutes=10)


class CredentialError(Exception):
    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail or code)


@dataclass(frozen=True)
class SealedCredential:
    key_reference: str
    ciphertext: bytes
    fingerprint: str


@dataclass(frozen=True)
class IssuedGrant:
    """A grant and its one-time token.

    The token is returned here and **never stored**. The row keeps only its
    fingerprint, so a compromised database cannot mint deliveries of profiles
    it holds.
    """

    grant: CredentialGrant
    token: str

    def __repr__(self) -> str:
        return f"IssuedGrant(grant_id={self.grant.id!r}, token=<redacted>)"

    __str__ = __repr__


class CredentialVault:
    """Seals, unseals and fingerprints installation material.

    The key is passed in rather than read from settings so that a test, a
    rotation script and the application all get their key the same way and
    nothing acquires a quiet fallback to a development default. A vault with no
    key refuses to seal rather than storing plaintext, which is the one failure
    mode that must never be silent.
    """

    def __init__(
        self,
        key: bytes,
        key_reference: str,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if len(key) != 32:
            raise CredentialError(
                "invalid_key",
                "the activation-material key must be exactly 32 bytes "
                "(AES-256); a shorter one is not a weaker key, it is a "
                "misconfiguration",
            )
        if not key_reference:
            raise CredentialError(
                "missing_key_reference",
                "a sealed credential must name the key it was sealed under, or "
                "a rotation makes every profile unreadable with no way to tell "
                "which rows are affected",
            )
        self._key = key
        self.key_reference = key_reference
        self.clock = clock

    # --- sealing ----------------------------------------------------------

    def seal(self, secret: str, installation_id: UUID) -> SealedCredential:
        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = AESGCM(self._key).encrypt(
            nonce, secret.encode("utf-8"), _aad(installation_id)
        )
        return SealedCredential(
            key_reference=self.key_reference,
            ciphertext=nonce + ciphertext,
            fingerprint=self.fingerprint(secret),
        )

    def unseal(self, credential: EsimActivationCredential) -> str:
        if credential.key_reference != self.key_reference:
            raise CredentialError(
                "key_reference_mismatch",
                f"credential was sealed under {credential.key_reference!r} and "
                f"this vault holds {self.key_reference!r}",
            )
        blob = credential.ciphertext
        if len(blob) <= _NONCE_BYTES:
            raise CredentialError("ciphertext_truncated")
        try:
            plaintext = AESGCM(self._key).decrypt(
                blob[:_NONCE_BYTES],
                blob[_NONCE_BYTES:],
                _aad(credential.esim_installation_id),
            )
        except InvalidTag as exc:
            # Either the key is wrong or the row was moved. Both are the same
            # answer to the caller: this is not a credential we can vouch for.
            raise CredentialError(
                "authentication_failed",
                "the sealed credential did not authenticate; it was either "
                "sealed under a different key or moved between installations",
            ) from exc
        return plaintext.decode("utf-8")

    def fingerprint(self, secret: str) -> str:
        """Keyed, so it cannot be brute-forced from a stolen database alone.

        An unkeyed hash of an activation code would be reversible by anyone who
        could guess the code space, which for a structured LPA string is not a
        large space.
        """
        return hashlib.blake2b(
            secret.encode("utf-8"), key=self._key, digest_size=32
        ).hexdigest()

    # --- storage ----------------------------------------------------------

    def store(
        self,
        session: Session,
        installation: EsimInstallation,
        secret: str,
        one_time_use: bool = True,
    ) -> EsimActivationCredential:
        """Seal and record. Replaces nothing: one profile, one credential.

        A second call for the same installation returns the existing row rather
        than overwriting it. Overwriting would be the wrong answer twice over —
        the old profile is not recoverable, and a supplier repeating itself is
        far more likely than a customer legitimately having two codes for one
        installation.
        """
        existing = session.exec(
            select(EsimActivationCredential).where(
                EsimActivationCredential.esim_installation_id == installation.id
            )
        ).first()
        if existing is not None:
            if existing.fingerprint != self.fingerprint(secret):
                raise CredentialError(
                    "credential_conflict",
                    f"installation {installation.id} already holds a different "
                    "activation credential; a one-time-use profile cannot be "
                    "silently replaced",
                )
            return existing
        sealed = self.seal(secret, installation.id)
        credential = EsimActivationCredential(
            esim_installation_id=installation.id,
            key_reference=sealed.key_reference,
            ciphertext=sealed.ciphertext,
            fingerprint=sealed.fingerprint,
            one_time_use=one_time_use,
            created_at=self.clock(),
        )
        session.add(credential)
        session.flush()
        return credential

    # --- authorized delivery ----------------------------------------------

    def issue_grant(
        self,
        session: Session,
        credential: EsimActivationCredential,
        subject_user_id: UUID,
        ttl: timedelta | None = None,
    ) -> IssuedGrant:
        """Mint a single-use, time-boxed authorization for one person."""
        if not self._subject_holds_credential(session, credential, subject_user_id):
            raise CredentialError("grant_not_authorized")
        token = secrets.token_urlsafe(32)
        now = self.clock()
        grant = CredentialGrant(
            credential_id=credential.id,
            subject_user_id=subject_user_id,
            token_fingerprint=self._token_fingerprint(token),
            issued_at=now,
            expires_at=now + (ttl or DEFAULT_GRANT_TTL),
        )
        session.add(grant)
        session.flush()
        return IssuedGrant(grant=grant, token=token)

    def redeem(
        self, session: Session, token: str, subject_user_id: UUID,
        *, expected_credential_id: UUID | None = None,
    ) -> str:
        """Spend a grant and return the profile. Once, by the right person.

        The lookup is by token fingerprint under `SELECT … FOR UPDATE`, so two
        concurrent redemptions of one token cannot both succeed — which is the
        whole meaning of single-use, and is not something a read-then-write
        would give.
        """
        fingerprint = self._token_fingerprint(token)
        grant = session.exec(
            select(CredentialGrant)
            .where(CredentialGrant.token_fingerprint == fingerprint)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        if grant is None:
            # Deliberately the same error as an expired or spent grant. An
            # attacker learning that a token *existed* learns something.
            raise CredentialError("grant_not_redeemable")
        if grant.subject_user_id != subject_user_id:
            raise CredentialError("grant_not_redeemable")
        if (
            expected_credential_id is not None
            and grant.credential_id != expected_credential_id
        ):
            raise CredentialError("grant_not_redeemable")
        if grant.redeemed_at is not None:
            raise CredentialError("grant_not_redeemable")
        if _aware(grant.expires_at) <= self.clock():
            raise CredentialError("grant_not_redeemable")

        credential = session.exec(
            select(EsimActivationCredential)
            .where(EsimActivationCredential.id == grant.credential_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        if credential is None:  # pragma: no cover - FK guarantees this
            raise CredentialError("credential_not_found")
        if not self._subject_holds_credential(session, credential, subject_user_id):
            raise CredentialError("grant_not_redeemable")

        secret = self.unseal(credential)
        grant.redeemed_at = self.clock()
        credential.delivery_count += 1
        credential.last_delivered_at = grant.redeemed_at
        session.add(grant)
        session.add(credential)
        session.flush()
        return secret

    def revoke_open_grants(
        self, session: Session, credential: EsimActivationCredential
    ) -> int:
        """Burn every unredeemed grant for one credential.

        Used when a profile is re-delivered or a device is reported lost: the
        outstanding links stop working immediately rather than remaining valid
        for the rest of their window.
        """
        now = self.clock()
        open_grants = session.exec(
            select(CredentialGrant).where(
                CredentialGrant.credential_id == credential.id,
                col(CredentialGrant.redeemed_at).is_(None),
            )
        ).all()
        for grant in open_grants:
            # Expiring rather than deleting: the audit trail of who was granted
            # access to a profile is worth more than a tidy table.
            grant.expires_at = min(_aware(grant.expires_at), now)
            grant.issued_at = min(
                _aware(grant.issued_at), grant.expires_at - timedelta(seconds=1)
            )
            session.add(grant)
        session.flush()
        return len(open_grants)

    def _token_fingerprint(self, token: str) -> str:
        return hashlib.blake2b(
            token.encode("utf-8"), key=self._key, digest_size=32
        ).hexdigest()

    @staticmethod
    def _subject_holds_credential(
        session: Session,
        credential: EsimActivationCredential,
        subject_user_id: UUID,
    ) -> bool:
        installation = session.get(
            EsimInstallation, credential.esim_installation_id
        )
        if installation is None:  # pragma: no cover - FK guarantees this
            return False
        entitlement = session.get(Entitlement, installation.entitlement_id)
        return (
            entitlement is not None
            and entitlement.holder_user_id == subject_user_id
        )


def _aad(installation_id: UUID) -> bytes:
    """Binds a ciphertext to its row, so a moved credential fails to decrypt."""
    return f"esim-installation:{installation_id}".encode()


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def constant_time_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)
