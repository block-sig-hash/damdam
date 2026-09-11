"""Money and rate column types (US-28, data-model.md §6.44).

The legacy schema stores every amount as NGN because that was the only currency
the product sold in: `pricing_tiers.ngn_price`, `transactions.amount_ngn`. The
reset sells in several, so an amount without its currency is no longer a number
anyone can add up.

Two rules follow, and both are enforced by the database rather than promised by
a service:

1. **Every amount carries its ISO 4217 currency**, in a column beside it, and
   the currency is upper-case three letters. There is no default currency.
2. **Amounts are exact decimals**, never floats. Metered usage and FX rates need
   more precision than a presentation amount, so rates get their own scale.

Cross-currency arithmetic is not a column type's job to prevent. Owning models
must bind related amounts to a currency identity: for example, an order item
references its parent order by both id and currency. The ledger in chunk 10
applies the same rule to balances and postings.
"""

import re
from collections.abc import Iterable
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from sqlalchemy import CheckConstraint, Column, Numeric, String

# 20 digits with 6 after the point. Six is chosen for metered usage, not for
# display: a per-megabyte rate in a low-value currency needs more than the two
# decimal places NGN and USD present. Presentation scale is per currency and is
# a formatting concern -- see data-model.md §6.44 for the rounding rule.
MONEY_PRECISION = 20
MONEY_SCALE = 6

# Rates multiply, so their error compounds. Ten places keeps an FX or tariff
# rate exact through a conversion chain that a 6-place amount would round.
RATE_PRECISION = 20
RATE_SCALE = 10

CURRENCY_LENGTH = 3

_ISO_SHAPE = re.compile(r"[A-Z]{3}")


def money_column(nullable: bool = False) -> "Column[Any]":
    return Column(Numeric(MONEY_PRECISION, MONEY_SCALE), nullable=nullable)


def rate_column(nullable: bool = False) -> "Column[Any]":
    return Column(Numeric(RATE_PRECISION, RATE_SCALE), nullable=nullable)


def currency_column(nullable: bool = False) -> "Column[Any]":
    return Column(String(CURRENCY_LENGTH), nullable=nullable)


def currency_check(table: str, column: str = "currency") -> CheckConstraint:
    """Reject anything that is not an upper-case ISO 4217 alphabetic code.

    Deliberately a shape check, not a list of valid codes: a database constraint
    that enumerates currencies has to be migrated every time the product sells
    somewhere new, and it would fail closed on a currency the catalog already
    accepted. Which currencies may be *sold in* is catalog policy (chunk 09).
    """
    # `~` is PostgreSQL's regex operator. The constraint is emitted only for
    # PostgreSQL, which is the database this runs on; the SQLite engine used by
    # the fast unit tests would fail to parse the DDL. Anything that depends on
    # the constraint being enforced must therefore be tested against PostgreSQL
    # -- see tests/test_core_domain_postgres.py.
    return CheckConstraint(
        f"{column} ~ '^[A-Z]{{{CURRENCY_LENGTH}}}$'",
        name=f"ck_{table}_{column}_iso4217",
    ).ddl_if(dialect="postgresql")


# --- currency-aware rounding (US-31, chunk 09) ------------------------------


class CurrencyError(ValueError):
    """A currency that cannot be priced in, or an amount that is not money."""


#: Minor-unit exponents that are not 2, per ISO 4217. Listing the exceptions
#: rather than every currency keeps the table short, but the default is
#: deliberately *not* applied to unknown codes -- see `currency_exponent`.
#:
#: Source: ISO 4217 Table A.1, "Currency, fund and precious metal codes".
#: Checked 10 September 2026.
_EXPONENT_EXCEPTIONS: dict[str, int] = {
    # No minor unit.
    "BIF": 0,
    "CLP": 0,
    "DJF": 0,
    "GNF": 0,
    "ISK": 0,
    "JPY": 0,
    "KMF": 0,
    "KRW": 0,
    "PYG": 0,
    "RWF": 0,
    "UGX": 0,
    "UYI": 0,
    "VND": 0,
    "VUV": 0,
    "XAF": 0,
    "XOF": 0,
    "XPF": 0,
    # Three minor digits.
    "BHD": 3,
    "IQD": 3,
    "JOD": 3,
    "KWD": 3,
    "LYD": 3,
    "OMR": 3,
    "TND": 3,
    # Four minor digits.
    "CLF": 4,
    "UYW": 4,
}

#: Currencies with the ordinary two-digit minor unit that this product may
#: quote in today. Kept explicit so an unknown code fails loudly rather than
#: being assumed to have two decimal places, which would undercharge by a
#: factor of a hundred in a zero-exponent currency and look like a price.
_TWO_DIGIT: frozenset[str] = frozenset(
    {
        "AED", "AUD", "BRL", "CAD", "CHF", "CNY", "DKK", "EGP", "EUR", "GBP",
        "GHS", "HKD", "IDR", "ILS", "INR", "KES", "MAD", "MXN", "MYR", "NGN",
        "NOK", "NZD", "PHP", "PLN", "QAR", "RON", "SAR", "SEK", "SGD", "THB",
        "TRY", "TZS", "USD", "ZAR",
    }
)


def currency_exponent(currency: str) -> int:
    """How many decimal places this currency actually has.

    Raises rather than defaulting to 2. A default is the dangerous answer here:
    an unknown zero-exponent currency would be charged a hundred times over, and
    the result would look like a pricing decision rather than a bug.
    """
    if not isinstance(currency, str) or not _ISO_SHAPE.fullmatch(currency):
        raise CurrencyError(
            f"{currency!r} is not an ISO 4217 alphabetic code"
        )
    if currency in _EXPONENT_EXCEPTIONS:
        return _EXPONENT_EXCEPTIONS[currency]
    if currency in _TWO_DIGIT:
        return 2
    raise CurrencyError(
        f"{currency} has no recorded minor unit; add it to app/money.py with "
        "its ISO 4217 exponent before quoting in it"
    )


def _quantum(currency: str) -> Decimal:
    return Decimal(1).scaleb(-currency_exponent(currency))


def round_money(amount: Decimal, currency: str) -> Decimal:
    """Round to the currency's minor unit, half-to-even.

    Half-to-even rather than half-up because half-up drifts consistently in the
    seller's favour across many lines, and "we round in our own favour, a
    little, every time" is a question nobody wants to answer.

    The result carries the currency's exponent as its scale, so a stored amount
    and a formatted one agree rather than differing by a trailing zero.
    """
    if not isinstance(amount, Decimal):
        raise CurrencyError(
            f"money must be a Decimal, got {type(amount).__name__}; a float "
            "price is already wrong before it is rounded"
        )
    if not amount.is_finite():
        raise CurrencyError(f"{amount} is not a finite amount")
    return amount.quantize(_quantum(currency), rounding=ROUND_HALF_EVEN)


def sum_money(amounts: Iterable[Decimal], currency: str) -> Decimal:
    """Add amounts that are already known to share one currency.

    Takes the currency explicitly so the caller has to have decided what it is.
    This function cannot check that the amounts belong to it -- a `Decimal`
    carries no currency -- so the models bind amount to currency instead (see
    the module docstring); this is the arithmetic, not the guard.
    """
    total = Decimal(0)
    for amount in amounts:
        if not isinstance(amount, Decimal):
            raise CurrencyError("money must be a Decimal")
        total += amount
    return round_money(total, currency)
