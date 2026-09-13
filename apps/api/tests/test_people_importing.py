"""Parsing an uploaded people file — US-39, chunk 22.

Every test here is a file an enterprise customer actually sends: a spreadsheet
export with a BOM and inconsistent header casing, a column nobody asked for, a
phone number typed with spaces, the same colleague on two lines, and a name
beginning with `=` because somebody's surname does.

Nothing touches a database. The preview and the applied result come from this
same function, so a rule that needed a session could disagree between them —
and the disagreement would surface as an import that previewed clean and then
refused half its rows.
"""

from __future__ import annotations

import pytest

from app.people.importing import (
    MAX_ROWS,
    FileRejected,
    RejectionCode,
    RowError,
    parse,
)


def csv_bytes(*lines: str) -> bytes:
    return "\r\n".join(lines).encode("utf-8")


class TestTheFileAsAWhole:
    def test_a_plain_file_parses_every_row(self) -> None:
        parsed = parse(
            csv_bytes(
                "Full Name,Email,Phone Number",
                "Ada Obi,ada@example.test,+2348031234567",
                "Ben Musa,ben@example.test,+2348031234568",
            )
        )
        assert len(parsed.rows) == 2
        assert parsed.valid_rows == parsed.rows

    def test_headers_are_matched_however_the_spreadsheet_wrote_them(self) -> None:
        """BOM, casing, underscores and trailing spaces all arrive in real files."""
        parsed = parse(
            "﻿EMPLOYEE_ID , Full Name ,E-Mail\r\n"
            "E-1,Ada Obi,ada@example.test\r\n".encode()
        )
        row = parsed.rows[0]
        assert row.external_reference == "E-1"
        assert row.full_name == "Ada Obi"
        assert row.email == "ada@example.test"

    def test_a_column_we_do_not_use_is_reported_not_refused(self) -> None:
        parsed = parse(
            csv_bytes(
                "Full Name,Email,Favourite Colour",
                "Ada Obi,ada@example.test,green",
            )
        )
        assert parsed.ignored_columns == ["Favourite Colour"]
        assert parsed.rows[0].is_valid

    def test_a_second_column_for_the_same_field_is_ignored(self) -> None:
        """`Phone` and `Phone 2` is an ordinary spreadsheet, not a broken file."""
        parsed = parse(
            csv_bytes(
                "Full Name,Phone,Mobile",
                "Ada Obi,+2348031234567,+2348031234599",
            )
        )
        assert parsed.rows[0].phone_number == "+2348031234567"

    def test_a_file_with_no_name_column_identifies_nobody(self) -> None:
        with pytest.raises(FileRejected) as excinfo:
            parse(csv_bytes("Email,Phone", "ada@example.test,+2348031234567"))
        assert excinfo.value.code is RejectionCode.NO_IDENTIFYING_COLUMN

    def test_an_empty_file_is_refused(self) -> None:
        with pytest.raises(FileRejected) as excinfo:
            parse(b"")
        assert excinfo.value.code is RejectionCode.EMPTY

    def test_a_header_with_no_rows_is_refused(self) -> None:
        with pytest.raises(FileRejected) as excinfo:
            parse(csv_bytes("Full Name,Email"))
        assert excinfo.value.code is RejectionCode.EMPTY

    def test_an_oversized_file_is_refused_before_it_is_parsed(self) -> None:
        with pytest.raises(FileRejected) as excinfo:
            parse(b"x" * (5 * 1024 * 1024 + 1))
        assert excinfo.value.code is RejectionCode.TOO_LARGE

    def test_too_many_rows_is_refused_as_a_file_not_row_by_row(self) -> None:
        lines = ["Full Name,Email"] + [
            f"Person {index},p{index}@example.test" for index in range(MAX_ROWS + 1)
        ]
        with pytest.raises(FileRejected) as excinfo:
            parse(csv_bytes(*lines))
        assert excinfo.value.code is RejectionCode.TOO_MANY_ROWS

    def test_a_windows_encoded_file_is_read_rather_than_refused(self) -> None:
        """Excel on a Windows machine writes cp1252, and the customer cannot tell."""
        content = "Full Name,Email\r\nZoë Obi,zoe@example.test\r\n".encode("cp1252")
        parsed = parse(content)
        assert parsed.rows[0].full_name == "Zoë Obi"


class TestOneRowAtATime:
    def test_a_row_is_numbered_the_way_the_spreadsheet_numbers_it(self) -> None:
        """"Row 3" has to mean row 3 in the customer's own window."""
        parsed = parse(
            csv_bytes(
                "Full Name,Email",
                "Ada Obi,ada@example.test",
                "Ben Musa,ben@example.test",
            )
        )
        assert [row.row_number for row in parsed.rows] == [2, 3]

    def test_a_row_with_no_name_is_invalid(self) -> None:
        parsed = parse(csv_bytes("Full Name,Email", ",ada@example.test"))
        assert RowError.MISSING_NAME in parsed.rows[0].errors

    def test_a_row_with_nothing_to_deliver_to_is_invalid(self) -> None:
        parsed = parse(csv_bytes("Full Name,Email", "Ada Obi,"))
        assert RowError.NO_IDENTIFIER in parsed.rows[0].errors

    def test_every_reason_a_row_is_wrong_is_reported_at_once(self) -> None:
        """One error per upload is four round trips for a file with four faults."""
        parsed = parse(csv_bytes("Full Name,Email,Phone", ",not-an-email,12345"))
        codes = set(parsed.rows[0].errors)
        assert {
            RowError.MISSING_NAME,
            RowError.INVALID_EMAIL,
            RowError.INVALID_PHONE,
            RowError.NO_IDENTIFIER,
        } <= codes

    def test_a_phone_number_written_the_way_people_write_it_is_accepted(self) -> None:
        parsed = parse(
            csv_bytes("Full Name,Phone", "Ada Obi,+234 803 123-4567")
        )
        assert parsed.rows[0].phone_number == "+2348031234567"
        assert parsed.rows[0].is_valid

    def test_a_national_format_number_is_refused_rather_than_guessed(self) -> None:
        """Guessing a country code delivers somebody else's service to a stranger."""
        parsed = parse(csv_bytes("Full Name,Phone", "Ada Obi,08031234567"))
        assert RowError.INVALID_PHONE in parsed.rows[0].errors

    def test_an_email_is_stored_folded_so_two_cases_are_one_person(self) -> None:
        parsed = parse(csv_bytes("Full Name,Email", "Ada Obi,Ada@Example.Test"))
        assert parsed.rows[0].email == "ada@example.test"

    def test_an_over_long_field_is_refused(self) -> None:
        parsed = parse(
            csv_bytes("Full Name,Email", f"{'a' * 500},ada@example.test")
        )
        assert RowError.FIELD_TOO_LONG in parsed.rows[0].errors

    def test_invisible_whitespace_does_not_create_two_people(self) -> None:
        """A zero-width space from a copy-paste makes two identical rows unequal."""
        parsed = parse(
            csv_bytes(
                "Full Name,Email",
                "Ada Obi,ada@example.test",
                "Ada Obi,​ada@example.test ",
            )
        )
        assert RowError.DUPLICATE_IN_FILE in parsed.rows[1].errors

    def test_a_name_that_looks_like_a_formula_is_kept_as_written(self) -> None:
        """Parsing does not defuse it; `csv_safe` does, on the way out."""
        parsed = parse(csv_bytes("Full Name,Email", "=Ada Obi,ada@example.test"))
        assert parsed.rows[0].full_name == "=Ada Obi"
        assert parsed.rows[0].is_valid


class TestDuplicatesInsideOneFile:
    def test_the_second_row_is_flagged_and_the_first_still_imports(self) -> None:
        parsed = parse(
            csv_bytes(
                "Full Name,Email",
                "Ada Obi,ada@example.test",
                "Ada Obi Again,ada@example.test",
            )
        )
        assert parsed.rows[0].is_valid
        assert RowError.DUPLICATE_IN_FILE in parsed.rows[1].errors

    def test_a_repeated_employee_number_is_a_duplicate(self) -> None:
        parsed = parse(
            csv_bytes(
                "Full Name,Employee ID",
                "Ada Obi,E-1",
                "Ben Musa,E-1",
            )
        )
        assert RowError.DUPLICATE_IN_FILE in parsed.rows[1].errors

    def test_two_people_sharing_nothing_are_not_duplicates(self) -> None:
        parsed = parse(
            csv_bytes(
                "Full Name,Email,Employee ID",
                "Ada Obi,ada@example.test,E-1",
                "Ben Musa,ben@example.test,E-2",
            )
        )
        assert all(row.is_valid for row in parsed.rows)


class TestStructureIsNeverInvented:
    def test_a_team_the_organization_does_not_have_is_an_error(self) -> None:
        """An import that creates a department from a typo builds a structure
        nobody chose and a cost centre nobody is watching."""
        parsed = parse(
            csv_bytes("Full Name,Email,Department", "Ada Obi,ada@example.test,Finence"),
            known_teams=["Finance"],
        )
        assert RowError.UNKNOWN_TEAM in parsed.rows[0].errors

    def test_a_known_team_is_accepted_whatever_its_casing(self) -> None:
        parsed = parse(
            csv_bytes("Full Name,Email,Department", "Ada Obi,ada@example.test,finance"),
            known_teams=["Finance"],
        )
        assert parsed.rows[0].is_valid
        assert parsed.rows[0].team == "finance"

    def test_an_unknown_cost_centre_is_an_error(self) -> None:
        parsed = parse(
            csv_bytes("Full Name,Email,Cost Code", "Ada Obi,ada@example.test,CC-9"),
            known_cost_centres=["CC-1"],
        )
        assert RowError.UNKNOWN_COST_CENTRE in parsed.rows[0].errors

    def test_no_column_in_this_format_can_grant_access(self) -> None:
        """The format has no role field. That is the point, so it is asserted."""
        parsed = parse(
            csv_bytes(
                "Full Name,Email,Role,Is Admin",
                "Ada Obi,ada@example.test,owner,true",
            )
        )
        row = parsed.rows[0]
        assert row.is_valid
        assert not hasattr(row, "role")
        # The claim is carried as ignored raw data, never as a decision.
        assert "Role" in parsed.ignored_columns
        assert "Is Admin" in parsed.ignored_columns
