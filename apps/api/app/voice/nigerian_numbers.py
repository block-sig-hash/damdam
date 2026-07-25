import re

_LOCAL_FORMAT = re.compile(r"0\d{10}")
_BARE_COUNTRY_CODE_FORMAT = re.compile(r"234\d{10}")
_PLUS_COUNTRY_CODE_FORMAT = re.compile(r"\+234\d{10}")

# NCC reserves these national-significant-number prefixes for non-geographic
# special/premium services rather than mobile subscriber lines, even though
# they fall inside the 70X/90X mobile network-code ranges.
_RESERVED_NON_SUBSCRIBER_PREFIXES = ("700", "900")


class InvalidNigerianNumberError(ValueError):
    pass


def normalize_nigerian_number(raw: str) -> str:
    compact = re.sub(r"[\s()-]", "", raw)

    if _LOCAL_FORMAT.fullmatch(compact):
        national = compact[1:]
    elif _PLUS_COUNTRY_CODE_FORMAT.fullmatch(compact):
        national = compact[4:]
    elif _BARE_COUNTRY_CODE_FORMAT.fullmatch(compact):
        national = compact[3:]
    else:
        raise InvalidNigerianNumberError(
            "Enter a Nigerian number in 0XXXXXXXXXX or +234XXXXXXXXXX format"
        )

    if national[0] not in "789":
        raise InvalidNigerianNumberError("Not a recognized Nigerian mobile prefix")
    if national[:3] in _RESERVED_NON_SUBSCRIBER_PREFIXES:
        raise InvalidNigerianNumberError(
            "Non-geographic/premium-rate numbers are not supported"
        )

    return "+234" + national
