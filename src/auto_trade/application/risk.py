from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from ..domain.models import AccountSnapshot, RiskLimits, TradeSignal, utc_now
from ..domain.protocols import RiskDecision


class RiskEngine:
    def __init__(self, limits: RiskLimits) -> None:
        self.limits = limits

    def validate(
        self,
        signal: TradeSignal,
        account: AccountSnapshot | None = None,
        seen_signal_ids: Iterable[str] = (),
        recent_executions: Iterable[datetime] = (),
        now: datetime | None = None,
    ) -> RiskDecision:
        current = now or utc_now()
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        if signal.signal_id in set(seen_signal_ids):
            return RiskDecision(False, "duplicate signal id")
        if signal.symbol not in self.limits.allowed_symbols:
            return RiskDecision(False, "symbol is not allowed")
        if signal.volume <= 0 or signal.volume > self.limits.max_volume:
            return RiskDecision(False, "volume exceeds configured limit")
        expiration = signal.expiration or signal.timestamp + timedelta(
            seconds=self.limits.expiration_seconds
        )
        if current >= expiration:
            return RiskDecision(False, "signal is expired")
        cutoff = current - timedelta(minutes=1)
        recent_count = len([value for value in recent_executions if value >= cutoff])
        if recent_count >= self.limits.max_orders_per_minute:
            return RiskDecision(False, "order rate limit reached")
        if account is not None:
            if not account.connected:
                return RiskDecision(False, "account is not connected")
            if (
                self.limits.max_open_positions is not None
                and account.open_positions >= self.limits.max_open_positions
            ):
                return RiskDecision(False, "maximum open positions reached")
        return RiskDecision(True)
