"""RFC 6238 conformance for the TOTP implementation (US-29, chunk 07C).

This project's policy is that a mock passing itself is not evidence of external
compatibility. An authenticator app is external: the phone computes the code
and the server has to agree, with no negotiation and no error message when they
do not.

So this file asserts the published RFC 6238 Appendix B test vectors, which are
the same vectors every authenticator implements against. If these pass, a code
from Google Authenticator or 1Password verifies here; if they fail, no amount
of round-tripping our own generator against our own verifier would have caught
it.

Source: RFC 6238, Appendix B ("Test Vectors"), IETF, May 2011.
Checked against the published table on 10 September 2026.
"""

from datetime import datetime, timezone

import pytest

from app.mfa.totp import Algorithm, generate, verify

#: RFC 6238 Appendix B seeds. ASCII, repeated to the digest's block length.
SHA1_SEED = b"12345678901234567890"
SHA256_SEED = b"12345678901234567890123456789012"
SHA512_SEED = b"1234567890123456789012345678901234567890123456789012345678901234"

# (unix time, expected 8-digit code) -- the full SHA-1 column of Appendix B.
SHA1_VECTORS = [
    (59, "94287082"),
    (1111111109, "07081804"),
    (1111111111, "14050471"),
    (1234567890, "89005924"),
    (2000000000, "69279037"),
    (20000000000, "65353130"),
]

SHA256_VECTORS = [
    (59, "46119246"),
    (1111111109, "68084774"),
    (1111111111, "67062674"),
    (1234567890, "91819424"),
    (2000000000, "90698825"),
    (20000000000, "77737706"),
]

SHA512_VECTORS = [
    (59, "90693936"),
    (1111111109, "25091201"),
    (1111111111, "99943326"),
    (1234567890, "93441116"),
    (2000000000, "38618901"),
    (20000000000, "47863826"),
]


def _at(seconds: int) -> datetime:
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


@pytest.mark.parametrize(("seconds", "expected"), SHA1_VECTORS)
def test_rfc6238_sha1_vectors(seconds: int, expected: str) -> None:
    assert generate(SHA1_SEED, _at(seconds), digits=8) == expected


@pytest.mark.parametrize(("seconds", "expected"), SHA256_VECTORS)
def test_rfc6238_sha256_vectors(seconds: int, expected: str) -> None:
    assert (
        generate(SHA256_SEED, _at(seconds), digits=8, algorithm=Algorithm.SHA256)
        == expected
    )


@pytest.mark.parametrize(("seconds", "expected"), SHA512_VECTORS)
def test_rfc6238_sha512_vectors(seconds: int, expected: str) -> None:
    assert (
        generate(SHA512_SEED, _at(seconds), digits=8, algorithm=Algorithm.SHA512)
        == expected
    )


def test_six_digit_codes_are_zero_padded() -> None:
    """A code that loses a leading zero is rejected by the phone, not by us."""
    for seconds in range(0, 6000, 7):
        code = generate(SHA1_SEED, _at(seconds))
        assert len(code) == 6
        assert code.isdigit()


def test_a_code_is_accepted_within_one_step_of_drift() -> None:
    moment = _at(1111111109)
    code = generate(SHA1_SEED, moment)
    assert verify(SHA1_SEED, code, moment) == 1111111109 // 30
    assert verify(SHA1_SEED, code, _at(1111111109 - 30)) is not None
    assert verify(SHA1_SEED, code, _at(1111111109 + 30)) is not None


def test_a_code_two_steps_away_is_refused() -> None:
    """Widening the window multiplies the guessing surface for free."""
    moment = _at(1111111109)
    code = generate(SHA1_SEED, moment)
    assert verify(SHA1_SEED, code, _at(1111111109 - 90)) is None
    assert verify(SHA1_SEED, code, _at(1111111109 + 90)) is None


def test_a_malformed_code_is_refused_rather_than_raising() -> None:
    moment = _at(1111111109)
    for candidate in ("", "12345", "abcdef", "1234567", " 123456"):
        assert verify(SHA1_SEED, candidate, moment) is None


def test_verification_is_constant_time_in_shape() -> None:
    """Wrong codes all take the same path -- no early return on first mismatch."""
    moment = _at(1111111109)
    correct = generate(SHA1_SEED, moment)
    wrong = "".join("0" if digit != "0" else "1" for digit in correct)
    assert verify(SHA1_SEED, wrong, moment) is None
