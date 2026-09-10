"""RFC 6238 time-based one-time passwords, on the standard library.

Written rather than pulled in because the algorithm is twenty lines of HMAC and
a modulus, and because a dependency here would have to be checked for an
`aarch64` wheel before it could reach the Ampere instance
(`scaling-infrastructure.md` §12.2) for no benefit.

Correctness is not asserted by round-tripping this module against itself --
that would pass for any self-consistent generator, including a wrong one. It is
asserted against the published RFC 6238 Appendix B vectors in
`tests/test_totp.py`, which are what the authenticator on the customer's phone
implements.
"""

import hashlib
import hmac
from datetime import datetime
from enum import Enum

DEFAULT_STEP_SECONDS = 30
DEFAULT_DIGITS = 6
#: One step either side. Enough for a phone whose clock has drifted or a person
#: typing slowly; widening it multiplies the guessing surface for nothing.
DEFAULT_DRIFT_STEPS = 1


class Algorithm(str, Enum):
    SHA1 = "SHA1"
    SHA256 = "SHA256"
    SHA512 = "SHA512"


_DIGEST = {
    Algorithm.SHA1: hashlib.sha1,
    Algorithm.SHA256: hashlib.sha256,
    Algorithm.SHA512: hashlib.sha512,
}


def counter_at(
    moment: datetime, step_seconds: int = DEFAULT_STEP_SECONDS
) -> int:
    return int(moment.timestamp()) // step_seconds


def hotp(
    secret: bytes,
    counter: int,
    digits: int = DEFAULT_DIGITS,
    algorithm: Algorithm = Algorithm.SHA1,
) -> str:
    mac = hmac.new(secret, counter.to_bytes(8, "big"), _DIGEST[algorithm]).digest()
    offset = mac[-1] & 0x0F
    truncated = int.from_bytes(mac[offset : offset + 4], "big") & 0x7FFFFFFF
    # Zero-padded: a six-digit code that renders as five is refused by the
    # phone, and the mismatch looks like a wrong secret rather than a bug.
    return str(truncated % (10**digits)).zfill(digits)


def generate(
    secret: bytes,
    moment: datetime,
    digits: int = DEFAULT_DIGITS,
    algorithm: Algorithm = Algorithm.SHA1,
    step_seconds: int = DEFAULT_STEP_SECONDS,
) -> str:
    return hotp(secret, counter_at(moment, step_seconds), digits, algorithm)


def verify(
    secret: bytes,
    code: str,
    moment: datetime,
    digits: int = DEFAULT_DIGITS,
    algorithm: Algorithm = Algorithm.SHA1,
    step_seconds: int = DEFAULT_STEP_SECONDS,
    drift_steps: int = DEFAULT_DRIFT_STEPS,
) -> int | None:
    """Return the counter the code belongs to, or `None`.

    The counter is returned rather than a boolean because replay protection
    needs to know *which* step was used: accepting the same code twice inside
    its thirty-second window would make a shoulder-surfed code reusable.

    Every candidate step is compared even after a match, and each comparison is
    `hmac.compare_digest`, so neither the answer nor the drift offset leaks
    through timing.
    """
    if len(code) != digits or not code.isdigit():
        return None
    centre = counter_at(moment, step_seconds)
    matched: int | None = None
    for offset in range(-drift_steps, drift_steps + 1):
        candidate = centre + offset
        if hmac.compare_digest(hotp(secret, candidate, digits, algorithm), code):
            matched = candidate
    return matched
