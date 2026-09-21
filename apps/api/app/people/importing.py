"""Reading an uploaded people file, strictly and without touching a database.

Pure parsing and validation. The database decides what is *possible*; this
decides what a row **means**, and keeping it pure is what makes the preview
truthful: the same function produces the preview and the applied result, so the
preview cannot promise something the apply then refuses.

Four rules earn their complexity.

**A row is validated for every reason it is wrong, not the first.** An
administrator fixing a two-thousand-line file one error per upload is an
administrator who gives up around the fourth round trip.

**Duplicates inside one file are found before duplicates against the database.**
Two lines claiming the same email is a mistake in the file, and reporting it as
a conflict with an existing person sends somebody looking for a colleague who
does not exist.

**The header is matched loosely and the values are not.** Spreadsheet exports
carry `Email Address`, `email_address`, a UTF-8 BOM and trailing spaces in the
header row, and refusing those is refusing the customer's actual file. The
*values* get no such generosity: a phone number that is nearly E.164 is a wrong
number, and guessing produces service delivered to a stranger.

**Nothing here grants anything.** A parsed row becomes an `OrganizationPerson`,
which carries no authority. There is no field in this format that can make
somebody an administrator, and that is a property of the format rather than of
the code that reads it.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import Enum

#: What a customer's header might reasonably say for each field we accept.
#: Matched after lowercasing, stripping and collapsing separators.
_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "full_name": ("full name", "name", "employee name", "staff name"),
    "email": ("email", "email address", "work email", "e mail"),
    "phone_number": ("phone number", "phone", "mobile", "msisdn", "telephone"),
    "external_reference": (
        "employee id",
        "employee number",
        "staff id",
        "staff number",
        "reference",
        "service number",
    ),
    # Deliberately **not** "role". The word is overloaded in exactly the
    # dangerous direction here: a customer writing `Role,owner` means a job
    # title to themselves and reads as an access grant to anybody skimming the
    # file. Matching nothing is the honest answer — "Job Title", "Title" and
    # "Position" all still work.
    "job_title": ("job title", "title", "position"),
    "team": ("team", "department", "unit", "division"),
    "cost_centre": ("cost centre", "cost center", "cost code", "budget code"),
}

#: E.164: a leading `+`, a non-zero country-code digit, then at most 14 more.
#: The same shape `app/calling/policy.py` enforces, for the same reason.
_E164 = re.compile(r"^\+[1-9]\d{6,14}$")

#: Deliberately permissive on the local part and strict about structure. A
#: validator that rejects unusual but legal addresses rejects real employees.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")

#: Above this, the file is refused whole rather than parsed. The number is a
#: product decision recorded here rather than a limit discovered at timeout:
#: an organization importing more than this in one file should be talking to
#: somebody, and a 50MB spreadsheet uploaded twice is an outage.
MAX_ROWS = 5_000
MAX_BYTES = 5 * 1024 * 1024
MAX_FIELD_LENGTH = 200


class RejectionCode(str, Enum):
    """Why a whole file was refused."""

    NOT_CSV = "not_csv"
    NO_HEADER = "no_header"
    #: No column we recognise as a name, so nothing in the file identifies a
    #: person. Matching nothing is different from matching badly.
    NO_IDENTIFYING_COLUMN = "no_identifying_column"
    TOO_MANY_ROWS = "too_many_rows"
    TOO_LARGE = "too_large"
    EMPTY = "empty"


class RowError(str, Enum):
    """Why one row cannot become a person. Stable codes; the UI localizes."""

    MISSING_NAME = "missing_name"
    #: Nothing to deliver service to and nothing to recognise them by later.
    NO_IDENTIFIER = "no_identifier"
    INVALID_EMAIL = "invalid_email"
    INVALID_PHONE = "invalid_phone"
    #: Another row in *this file* already claimed this identity.
    DUPLICATE_IN_FILE = "duplicate_in_file"
    #: Different identifiers on one row resolve to different existing people.
    #: Guessing which person wins would merge two identities.
    IDENTITY_COLLISION = "identity_collision"
    FIELD_TOO_LONG = "field_too_long"
    UNKNOWN_TEAM = "unknown_team"
    UNKNOWN_COST_CENTRE = "unknown_cost_centre"


class FileRejected(Exception):
    def __init__(self, code: RejectionCode, detail: str | None = None) -> None:
        super().__init__(detail or code.value)
        self.code = code
        self.detail = detail


@dataclass
class ParsedRow:
    """One line, as we understand it, with everything wrong with it."""

    row_number: int
    full_name: str = ""
    email: str | None = None
    phone_number: str | None = None
    external_reference: str | None = None
    job_title: str | None = None
    team: str | None = None
    cost_centre: str | None = None
    errors: list[RowError] = field(default_factory=list)
    #: What the customer actually wrote, kept for the preview and for a later
    #: explanation. Never rendered into an export without `csv_safe`.
    raw: dict[str, str] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return not self.errors


@dataclass
class ParsedFile:
    rows: list[ParsedRow]
    #: Header columns we recognised, so the preview can say what was ignored.
    recognised_columns: dict[str, str]
    ignored_columns: list[str]

    @property
    def valid_rows(self) -> list[ParsedRow]:
        return [row for row in self.rows if row.is_valid]

    @property
    def invalid_rows(self) -> list[ParsedRow]:
        return [row for row in self.rows if not row.is_valid]


def _normalise_header(value: str) -> str:
    cleaned = value.replace("﻿", "").strip().lower()
    cleaned = re.sub(r"[_\-./]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned)


def _map_headers(fieldnames: Sequence[str]) -> tuple[dict[str, str], list[str]]:
    """Match the customer's columns to ours, keeping the first of each.

    A second column matching the same field is *ignored* rather than an error:
    spreadsheets routinely carry `Phone` and `Phone 2`, and refusing the file
    over the second one helps nobody.
    """
    recognised: dict[str, str] = {}
    ignored: list[str] = []
    for name in fieldnames:
        if name is None:
            continue
        normalised = _normalise_header(name)
        for field_name, aliases in _HEADER_ALIASES.items():
            if normalised in aliases and field_name not in recognised:
                recognised[field_name] = name
                break
        else:
            ignored.append(name)
    return recognised, ignored


def _clean(value: str | None) -> str:
    if value is None:
        return ""
    # Zero-width and non-breaking spaces arrive from copy-paste and make two
    # visually identical values compare unequal — including two "duplicate"
    # rows that then both import.
    cleaned = value.replace("​", "").replace("\xa0", " ")
    return cleaned.strip()


def parse(
    content: bytes,
    *,
    known_teams: Iterable[str] = (),
    known_cost_centres: Iterable[str] = (),
) -> ParsedFile:
    """Read a whole file, or refuse it and say why.

    `known_teams` and `known_cost_centres` are names that already exist for this
    organization. A row naming something else is an **error rather than a
    silent creation**: an import that invents a department from a typo produces
    a structure nobody chose and a cost centre nobody is watching.
    """
    if len(content) > MAX_BYTES:
        raise FileRejected(RejectionCode.TOO_LARGE)
    if not content.strip():
        raise FileRejected(RejectionCode.EMPTY)

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        # Excel on a Windows machine in this market commonly writes cp1252.
        # Trying it is the difference between working and "not a CSV".
        try:
            text = content.decode("cp1252")
        except UnicodeDecodeError:
            raise FileRejected(RejectionCode.NOT_CSV, str(error)) from error

    reader = csv.DictReader(io.StringIO(text, newline=""))
    if not reader.fieldnames:
        raise FileRejected(RejectionCode.NO_HEADER)

    recognised, ignored = _map_headers(reader.fieldnames)
    if "full_name" not in recognised:
        raise FileRejected(RejectionCode.NO_IDENTIFYING_COLUMN)

    teams = {name.casefold() for name in known_teams}
    centres = {name.casefold() for name in known_cost_centres}

    rows: list[ParsedRow] = []
    seen_emails: dict[str, int] = {}
    seen_phones: dict[str, int] = {}
    seen_references: dict[str, int] = {}

    for index, raw in enumerate(reader, start=2):  # line 1 is the header
        if len(rows) >= MAX_ROWS:
            raise FileRejected(RejectionCode.TOO_MANY_ROWS)
        row = _parse_row(index, raw, recognised, teams, centres)
        _check_duplicates(row, seen_emails, seen_phones, seen_references)
        rows.append(row)

    if not rows:
        raise FileRejected(RejectionCode.EMPTY)
    return ParsedFile(rows=rows, recognised_columns=recognised, ignored_columns=ignored)


def _parse_row(
    row_number: int,
    raw: dict[str, str | None],
    recognised: dict[str, str],
    teams: set[str],
    centres: set[str],
) -> ParsedRow:
    def value_of(field_name: str) -> str:
        column = recognised.get(field_name)
        return _clean(raw.get(column)) if column else ""

    row = ParsedRow(
        row_number=row_number,
        raw={key: _clean(value) for key, value in raw.items() if key},
    )
    row.full_name = value_of("full_name")
    email = value_of("email").casefold()
    phone = value_of("phone_number")
    reference = value_of("external_reference")
    row.job_title = value_of("job_title") or None
    row.team = value_of("team") or None
    row.cost_centre = value_of("cost_centre") or None

    if not row.full_name:
        row.errors.append(RowError.MISSING_NAME)
    if any(
        len(candidate) > MAX_FIELD_LENGTH
        for candidate in (row.full_name, email, phone, reference)
    ):
        row.errors.append(RowError.FIELD_TOO_LONG)

    if email:
        if _EMAIL.match(email):
            row.email = email
        else:
            row.errors.append(RowError.INVALID_EMAIL)
    if phone:
        # Spaces and dashes are how people write numbers; they are not part of
        # one. Everything else is left alone so a wrong number stays wrong.
        candidate = re.sub(r"[ \-()]", "", phone)
        if _E164.match(candidate):
            row.phone_number = candidate
        else:
            row.errors.append(RowError.INVALID_PHONE)
    if reference:
        row.external_reference = reference

    if not (row.email or row.phone_number or row.external_reference):
        row.errors.append(RowError.NO_IDENTIFIER)

    if row.team and row.team.casefold() not in teams:
        row.errors.append(RowError.UNKNOWN_TEAM)
    if row.cost_centre and row.cost_centre.casefold() not in centres:
        row.errors.append(RowError.UNKNOWN_COST_CENTRE)
    return row


def _check_duplicates(
    row: ParsedRow,
    seen_emails: dict[str, int],
    seen_phones: dict[str, int],
    seen_references: dict[str, int],
) -> None:
    """Flag the *later* row, so the first occurrence still imports."""
    for value, seen in (
        (row.email, seen_emails),
        (row.phone_number, seen_phones),
        (row.external_reference, seen_references),
    ):
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            if RowError.DUPLICATE_IN_FILE not in row.errors:
                row.errors.append(RowError.DUPLICATE_IN_FILE)
        else:
            seen[key] = row.row_number
