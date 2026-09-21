"""Calling liabilities contributed to the account deletion/export boundary."""

from sqlmodel import Session, col, select

from app.account.deletion import (
    BlockerKind,
    DeletionBlocker,
    register_liability_probe,
)
from app.auth.models import User
from app.calling.models import (
    TERMINAL_ATTEMPT_STATES,
    CallAttempt,
    CallCharge,
    ChargeState,
)


@register_liability_probe
def calling_liabilities(
    session: Session, user: User
) -> tuple[DeletionBlocker, ...]:
    """Block while a call or its customer settlement can still change."""
    live = session.exec(
        select(CallAttempt).where(
            CallAttempt.owner_user_id == user.id,
            col(CallAttempt.state).not_in(list(TERMINAL_ATTEMPT_STATES)),
        )
    ).first()
    if live is not None:
        return (
            DeletionBlocker(
                BlockerKind.ACTIVE_LIABILITY,
                "call_in_progress",
                f"call attempt {live.id} is {live.state.value}",
                amount=live.max_charge_amount,
                currency=live.currency,
            ),
        )

    provisional = session.exec(
        select(CallCharge)
        .join(CallAttempt, col(CallAttempt.id) == col(CallCharge.attempt_id))
        .where(
            CallAttempt.owner_user_id == user.id,
            CallCharge.state == ChargeState.PROVISIONAL,
        )
    ).first()
    if provisional is not None:
        return (
            DeletionBlocker(
                BlockerKind.ACTIVE_LIABILITY,
                "call_settlement_pending",
                f"call charge {provisional.id} is provisional",
                amount=provisional.charged_amount,
                currency=provisional.currency,
            ),
        )
    return ()


__all__ = ["calling_liabilities"]
