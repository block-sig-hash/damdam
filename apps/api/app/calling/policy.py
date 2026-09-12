"""Which destinations may be dialled at all, decided before the SDK is touched.

This module is the answer to one finding in V01's reviewed contract
(`docs/implementation/voice/API-CONTRACTS.md` §2): Telnyx parks ordinary
client-originated calls so the backend can authorize them, **but routes calls it
classifies as emergency calls for the caller's country normally**. Parking is
therefore not a complete control. A destination the server would refuse has to
be refused before the client is ever told to dial it, because for that one class
of number the backend's later decision point does not exist.

Everything here is pure: no session, no provider, no clock. A refusal must be
computable at authorization time from the number alone, and a rule that needed a
database round trip would be a rule somebody eventually skips on a fast path.

**This is not a claim of emergency-call containment.** Blocker B1 is open: only
an account-level test can prove the credential connection cannot route an
emergency number that never reaches this code. This module reduces exposure; it
does not close the gate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.catalog.tariffs import DestinationKind

#: E.164: a leading `+`, a non-zero country-code digit, then at most 14 more.
#: Matches the `ck_assigned_numbers_e164` constraint chunk 15 put on the
#: numbers we own, so an identity and a destination are validated the same way.
_E164 = re.compile(r"^\+[1-9][0-9]{6,14}$")

#: Characters a person or a contact list puts in a number that carry no meaning.
#: Note what is *not* here: a leading `0`, national prefixes and separators that
#: change which subscriber is dialled are never stripped or rewritten.
_COSMETIC = re.compile(r"[\s()\-. ]")

#: Short emergency and service numbers, by the country whose network defines
#: them. Sourced from the numbering plans of the markets the product may sell
#: into; the list is deliberately generous, because a false refusal costs a
#: customer one call and a false acceptance costs an emergency service a
#: misrouted one.
_EMERGENCY_NATIONAL = {
    "NG": frozenset({"112", "199", "122", "123", "767", "911"}),
    "US": frozenset({"911", "988", "933"}),
    "GB": frozenset({"999", "112", "101", "111"}),
    "FR": frozenset({"112", "15", "17", "18", "114", "115"}),
}

#: Emergency numbers dialled as if they were country codes. `+911` is not a
#: North American number; it is somebody's dialler prepending `+` to what the
#: user typed. It is refused rather than interpreted.
_EMERGENCY_BARE = frozenset({"+112", "+911", "+999", "+000", "+110", "+119"})

#: Country code → ISO country, for the markets this product can price. Kept
#: small on purpose: an unlisted code is refused, not guessed, because a
#: destination we cannot name is a destination we cannot rate (B2).
_COUNTRY_CODES: tuple[tuple[str, str], ...] = (
    ("+234", "NG"),
    ("+44", "GB"),
    ("+33", "FR"),
    ("+1", "US"),
)

#: Nigerian national-significant-number prefixes the NCC reserves for
#: non-geographic premium and special services rather than subscriber lines.
#: Carried forward from `app/voice/nigerian_numbers.py` (reuse item F7), which
#: is the only part of that module this chunk keeps.
_NG_PREMIUM_PREFIXES = ("700", "900")
_NG_MOBILE_FIRST_DIGITS = frozenset({"7", "8", "9"})

#: Below this, a national number in a known country is a service code rather
#: than a subscriber line. Seven is the shortest national subscriber length in
#: any market this product prices.
_MIN_NATIONAL_DIGITS = 7

_BYPASS_REASON = (
    "emergency and short service numbers bypass the provider's parked-call "
    "control, so they are refused before the client SDK is invoked"
)


class DestinationRefused(Exception):
    """This number will not be dialled, and the caller is told which rule said so.

    `code` is stable and safe to show a client; `detail` explains the decision to
    an operator reading a log. Neither ever contains the number, because a
    refused destination is still somebody's phone number.
    """

    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail or code)


@dataclass(frozen=True)
class DestinationDecision:
    """A destination that passed policy, in the form the rest of the chunk uses.

    Frozen and returned by value so that the number stored on the attempt is the
    number policy approved. Nothing downstream re-derives it from client input —
    N4 in V01's negative matrix is exactly the case where a later component
    substitutes its own idea of the destination.
    """

    e164: str
    country: str
    kind: DestinationKind


def normalize_destination(raw: str) -> str:
    """Remove cosmetic characters and require full E.164. Never expand.

    An internet call originates from a data connection, not from a SIM in a home
    network, so there is no country from which a national number like
    `08031234567` could be expanded. Expanding it against the *seller's* country
    would dial a different subscriber whenever those differ, and the customer
    would have no way to see that it had happened.

    Short codes reach here too, and they are refused as special numbers rather
    than as malformed ones — see `_refuse_emergency`, which runs first.
    """
    compact = _COSMETIC.sub("", raw or "")
    _refuse_emergency(compact)
    if not _E164.fullmatch(compact):
        raise DestinationRefused(
            "destination_not_e164",
            "an internet call has no home network to expand a national number "
            "from, so the destination must already be in full E.164 form",
        )
    return compact


def classify_destination(
    raw: str, *, supported_countries: frozenset[str]
) -> DestinationDecision:
    """Normalize, refuse what must never be dialled, then name what is left.

    Order matters and is not an implementation detail. Emergency and special
    numbers are tested *before* country support, so a short code in an unsold
    market is refused as an emergency number rather than as an unsupported
    country — the two produce different operator responses, and the emergency
    one is the one that needs to be visible.
    """
    e164 = normalize_destination(raw)

    country = _country_of(e164)
    if country is None:
        raise DestinationRefused(
            "destination_country_unknown",
            "no country is resolvable for this number, so it cannot be rated; "
            "unknown means unavailable",
        )
    if country not in supported_countries:
        raise DestinationRefused(
            "destination_country_not_supported",
            f"{country} is not a published destination for this product",
        )

    kind = _kind_of(e164, country)
    if kind is DestinationKind.PREMIUM:
        # Premium ranges are where an unbounded bill comes from, and chunk 09's
        # `DestinationKind` documents them as "by default, not sold at all".
        raise DestinationRefused(
            "destination_premium",
            "premium and non-geographic ranges are not sold on this route",
        )
    return DestinationDecision(e164=e164, country=country, kind=kind)


def _refuse_emergency(compact: str) -> None:
    """Refuse emergency and short service numbers, before E.164 validation.

    Running before the format check is the whole point. An emergency number is
    *shorter* than E.164 allows, so a format check placed first would report
    `+234112` as a malformed number — a refusal that reads like a typo, gets
    retried in a different format, and never tells an operator that somebody
    tried to reach emergency services through a route that must not carry them.

    Three rules, narrowest first:

    1. a bare emergency number somebody's dialler prefixed with `+`;
    2. a known emergency code behind a recognised country code, with or without
       a trunk `0` still attached;
    3. anything in a recognised country whose national part is too short to be a
       subscriber line. Short national numbers *are* service codes; refusing the
       range is what stops an unlisted one from being dialled.
    """
    if compact in _EMERGENCY_BARE:
        raise DestinationRefused("destination_emergency_or_special", _BYPASS_REASON)
    for code, country in sorted(_COUNTRY_CODES, key=lambda pair: -len(pair[0])):
        if not compact.startswith(code):
            continue
        national = compact[len(code) :]
        if not national.isdigit():
            return
        candidates = {national, national.lstrip("0")}
        if candidates & _EMERGENCY_NATIONAL.get(country, frozenset()):
            raise DestinationRefused("destination_emergency_or_special", _BYPASS_REASON)
        if len(national) < _MIN_NATIONAL_DIGITS:
            raise DestinationRefused("destination_emergency_or_special", _BYPASS_REASON)
        return


def _country_of(e164: str) -> str | None:
    # Longest prefix first, so `+1` never claims a number that `+123` owns if a
    # longer code is added later.
    for code, country in sorted(_COUNTRY_CODES, key=lambda pair: -len(pair[0])):
        if e164.startswith(code):
            return country
    return None


def _kind_of(e164: str, country: str) -> DestinationKind:
    if country == "NG":
        national = e164[len("+234") :]
        if national[:3] in _NG_PREMIUM_PREFIXES:
            return DestinationKind.PREMIUM
        if national[:1] in _NG_MOBILE_FIRST_DIGITS and len(national) == 10:
            return DestinationKind.MOBILE
        return DestinationKind.LANDLINE
    # Outside Nigeria the product has no verified numbering analysis yet, and
    # a guessed kind selects a rate. Landline is not a default chosen for being
    # safe — it is the kind a market must publish a rate for before the country
    # can appear in `supported_countries` at all.
    return DestinationKind.LANDLINE
