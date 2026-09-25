from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from auto_trade.application.risk import RiskEngine
from auto_trade.domain.models import AccountSnapshot, RiskLimits, TradeSignal

from ..helpers import signal_data


def limits() -> RiskLimits:
    return RiskLimits({"EURUSD"}, Decimal("0.10"), 1, 10)


def test_risk_accepts_valid_signal() -> None:
    signal = TradeSignal.from_dict(signal_data())
    decision = RiskEngine(limits()).validate(
        signal,
        account=AccountSnapshot(connected=True),
        now=datetime.now(UTC),
    )
    assert decision.accepted


def test_risk_rejects_duplicate_and_oversized_signal() -> None:
    signal = TradeSignal.from_dict(signal_data())
    engine = RiskEngine(limits())
    assert not engine.validate(signal, seen_signal_ids={signal.signal_id}).accepted
    signal.volume = Decimal("1.00")
    assert not engine.validate(signal).accepted


def test_risk_rejects_expired_signal() -> None:
    now = datetime.now(UTC)
    signal = TradeSignal.from_dict(signal_data(now=now - timedelta(seconds=30)))
    decision = RiskEngine(limits()).validate(signal, now=now)
    assert not decision.accepted
