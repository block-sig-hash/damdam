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

Cross-currency arithmetic is not a column type's job to prevent, and nothing
here tries: a balance in two currencies is two balances. That rule belongs to
the ledger in chunk 10, which this module exists to make expressible.
"""

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
