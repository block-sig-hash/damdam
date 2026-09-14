"""Response shapes for the operational metrics endpoint (US-42, chunk 26C)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class OperationalMetricsResponse(BaseModel):
    """One observation of the system.

    Every "oldest" and "lag" field is nullable, and **null is not zero**. A
    system that has never observed usage and one whose usage is perfectly fresh
    would otherwise report the same number, and they could not be more
    different — one is healthy, the other has a poller that never started.
    """

    observed_at: datetime
    oldest_unprovisioned_order_seconds: float | None = None
    unknown_supplier_outcomes: int
    #: Counted apart from `unknown_supplier_outcomes` on purpose: a stalled eSIM
    #: issuance and a lost call outcome need different people and different
    #: runbooks, and one combined number would be green while either was on fire.
    unknown_call_outcomes: int
    webhook_lag_seconds: float | None = None
    quarantined_events: int
    unmatched_events: int
    usage_staleness_seconds: float | None = None
    open_exceptions: dict[str, int] = {}
