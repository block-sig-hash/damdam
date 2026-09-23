"""Activation-material key rotation — US-42, chunk 26D.

Chunk 15 built the vault; this covers the property it did not have. The key
reference recorded on every sealed row told an operator *which* rows a rotation
had made unreadable, which is not the same as not making them unreadable.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.connectivity.credentials import CredentialError, CredentialVault
from app.connectivity.models import EsimActivationCredential

#: Shaped like an activation string and deliberately unusable. It installs
#: nothing; it exists to be sealed and read back.
HARNESS_SECRET = "LPA:1$smdp.example.invalid$HARNESSMATCHING000"


class TestKeyRotation:
    """US-42, chunk 26D — rotating the key must not destroy what it sealed.

    Before this, `unseal` refused any reference but the current one. Rotating
    the activation-material key therefore made every previously sealed profile
    permanently unreadable — and a Telnyx eSIM profile is one-time-use, so that
    is a customer's paid-for line gone, with buying another as the only remedy.
    """

    def _vault(self, key: bytes, reference: str, retired=None) -> CredentialVault:
        return CredentialVault(key, reference, retired_keys=retired)

    def test_material_sealed_before_a_rotation_is_still_readable(self) -> None:
        old_key, new_key = b"o" * 32, b"n" * 32
        installation = uuid4()
        before = self._vault(old_key, "material-v1")
        sealed = before.seal(HARNESS_SECRET, installation)

        after = self._vault(new_key, "material-v2", {"material-v1": old_key})
        credential = EsimActivationCredential(
            esim_installation_id=installation,
            key_reference=sealed.key_reference,
            ciphertext=sealed.ciphertext,
            fingerprint=sealed.fingerprint,
        )

        assert after.unseal(credential) == HARNESS_SECRET

    def test_rotation_preserves_existing_credential_and_grant_fingerprints(
        self,
    ) -> None:
        old_key, new_key = b"o" * 32, b"n" * 32
        before = self._vault(old_key, "material-v1")
        after = self._vault(new_key, "material-v2", {"material-v1": old_key})

        assert after.fingerprint(HARNESS_SECRET, "material-v1") == before.fingerprint(
            HARNESS_SECRET
        )
        old_grant = before._token_fingerprint("still-open-grant")
        candidates = {
            after._token_fingerprint("still-open-grant", reference)
            for reference in after.known_key_references
        }
        assert old_grant in candidates

    def test_new_material_is_sealed_under_the_current_key(self) -> None:
        old_key, new_key = b"o" * 32, b"n" * 32
        after = self._vault(new_key, "material-v2", {"material-v1": old_key})

        sealed = after.seal(HARNESS_SECRET, uuid4())

        # A vault that still sealed under the retired key would make the
        # rotation cosmetic.
        assert sealed.key_reference == "material-v2"

    def test_a_reference_nobody_configured_is_named_rather_than_guessed(
        self,
    ) -> None:
        vault = self._vault(b"n" * 32, "material-v2", {"material-v1": b"o" * 32})
        credential = EsimActivationCredential(
            esim_installation_id=uuid4(),
            key_reference="material-v0",
            ciphertext=b"\x00" * 40,
            fingerprint="x",
        )

        with pytest.raises(CredentialError) as excinfo:
            vault.unseal(credential)

        # Selected by reference rather than tried in turn: trying every key
        # would turn "a row names a key nobody configured" into a slow
        # decryption failure, which is the wrong thing to tell an operator.
        assert excinfo.value.code == "key_reference_mismatch"
        assert "material-v2" in str(excinfo.value)
        assert "material-v1" in str(excinfo.value)

    def test_a_retired_key_of_the_wrong_length_is_refused_at_construction(
        self,
    ) -> None:
        with pytest.raises(CredentialError) as excinfo:
            self._vault(b"n" * 32, "material-v2", {"material-v1": b"short"})

        assert excinfo.value.code == "invalid_key"

    def test_one_reference_cannot_name_two_keys(self) -> None:
        """The premise of the scheme is that a row's reference identifies a key."""
        with pytest.raises(CredentialError) as excinfo:
            self._vault(b"n" * 32, "material-v2", {"material-v2": b"o" * 32})

        assert excinfo.value.code == "duplicate_key_reference"

    def test_the_vault_reports_what_it_can_read(self) -> None:
        vault = self._vault(b"n" * 32, "material-v2", {"material-v1": b"o" * 32})

        assert vault.known_key_references == ("material-v2", "material-v1")
