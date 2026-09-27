from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from auto_trade.domain.enums import ExecutionStatus
from auto_trade.domain.exceptions import AutomationError, PositionSnapshotUnavailable
from auto_trade.domain.models import (
    OrderRequest,
    PositionSnapshot,
    TerminalProfile,
    TradeSignal,
    VerificationEvidence,
)
from auto_trade.infrastructure.automation import MT5DesktopAdapter, MT5WindowManager

from ..helpers import signal_data


def snapshot(ticket: str, symbol: str = "BITCOIN", side: str = "BUY") -> PositionSnapshot:
    return PositionSnapshot(ticket, symbol, side, Decimal("0.01"))


def reading(*positions: PositionSnapshot) -> tuple[PositionSnapshot, ...]:
    return tuple(positions)


class ScriptedProvider:
    def __init__(self, *readings: tuple[PositionSnapshot, ...]) -> None:
        self.readings = list(readings)
        self.calls = 0

    def positions(self) -> tuple[PositionSnapshot, ...]:
        self.calls += 1
        if not self.readings:
            raise PositionSnapshotUnavailable("position observation is unavailable")
        return self.readings.pop(0)


class FakeManager(MT5WindowManager):
    def find(self, profile: TerminalProfile) -> Any:
        raise AssertionError("connect is not exercised in these tests")


def profile() -> TerminalProfile:
    return TerminalProfile(
        name="alpari-demo",
        terminal_path="terminal64.exe",
        data_path="data",
        instance_name="Alpari-MT5-Demo",
    )


def request(symbol: str = "BITCOIN", side: str = "BUY", volume: str = "0.01") -> OrderRequest:
    data = signal_data() | {"symbol": symbol, "action": side, "volume": float(volume)}
    return OrderRequest(TradeSignal.from_dict(data))


def connected(provider: Any) -> MT5DesktopAdapter:
    adapter = MT5DesktopAdapter(profile(), FakeManager(), position_provider=provider)
    adapter.verification_timeout_seconds = 0
    adapter.connected = True
    return adapter


def prepared(
    adapter: MT5DesktopAdapter,
    *readings: tuple[PositionSnapshot, ...],
) -> MT5DesktopAdapter:
    provider = ScriptedProvider(*readings)
    adapter.position_provider = provider
    adapter._baseline = provider.readings.pop(0) if provider.readings else None
    adapter._baseline_error = None
    return adapter


def test_verification_accepts_exactly_one_new_matching_position() -> None:
    existing = snapshot("111", side="SELL")
    adapter = connected(ScriptedProvider())
    adapter = prepared(adapter, reading(existing), reading(existing, snapshot("555")))

    result = adapter.verify_execution(request())

    assert result.status is ExecutionStatus.ACCEPTED
    assert result.order_reference == "555"


def test_accepted_result_carries_position_evidence() -> None:
    existing = snapshot("111", side="SELL")
    adapter = connected(ScriptedProvider())
    adapter = prepared(adapter, reading(existing), reading(existing, snapshot("555")))

    result = adapter.verify_execution(request())

    evidence = result.evidence
    assert isinstance(evidence, VerificationEvidence)
    assert "111:BITCOIN:SELL" in evidence.baseline
    assert "555:BITCOIN:BUY" in evidence.observed
    assert evidence.position_id == "555"
    assert evidence.to_dict()["position_id"] == "555"


def test_unknown_result_still_records_the_observed_reference() -> None:
    existing = snapshot("111", side="SELL")
    adapter = connected(ScriptedProvider())
    adapter = prepared(adapter, reading(existing), reading(existing))

    result = adapter.verify_execution(request())

    assert result.status is ExecutionStatus.UNKNOWN
    evidence = result.evidence
    assert isinstance(evidence, VerificationEvidence)
    assert "111:BITCOIN:SELL" in evidence.baseline
    assert "111:BITCOIN:SELL" in evidence.observed
    assert evidence.position_id is None


def test_verification_reports_unknown_when_nothing_appeared() -> None:
    existing = snapshot("111", side="SELL")
    adapter = connected(ScriptedProvider())
    adapter = prepared(adapter, reading(existing), reading(existing))

    result = adapter.verify_execution(request())

    assert result.status is ExecutionStatus.UNKNOWN
    assert result.order_reference is None


def test_verification_reports_unknown_on_ambiguous_match() -> None:
    adapter = connected(ScriptedProvider())
    adapter = prepared(adapter, reading(), reading(snapshot("555"), snapshot("556")))

    result = adapter.verify_execution(request())

    assert result.status is ExecutionStatus.UNKNOWN
    assert "multiple" in result.message


def test_verification_reports_unknown_when_observation_fails() -> None:
    adapter = connected(ScriptedProvider())
    adapter = prepared(adapter, reading())

    result = adapter.verify_execution(request())

    assert result.status is ExecutionStatus.UNKNOWN
    assert "unavailable" in result.message


def test_verification_reports_unknown_without_a_baseline() -> None:
    adapter = connected(ScriptedProvider(reading(snapshot("555"))))
    adapter._baseline = None
    adapter._baseline_error = "MT5 Trade grid position values are unavailable"

    result = adapter.verify_execution(request())

    assert result.status is ExecutionStatus.UNKNOWN
    assert "baseline unavailable" in result.message
    assert result.evidence is None


def test_verification_ignores_wrong_side() -> None:
    adapter = connected(ScriptedProvider())
    adapter = prepared(adapter, reading(), reading(snapshot("555", side="SELL")))

    assert adapter.verify_execution(request(side="BUY")).status is ExecutionStatus.UNKNOWN


def test_verification_ignores_wrong_volume() -> None:
    wrong = PositionSnapshot("555", "BITCOIN", "BUY", Decimal("0.50"))
    adapter = connected(ScriptedProvider())
    adapter = prepared(adapter, reading(), reading(wrong))

    assert adapter.verify_execution(request(volume="0.01")).status is ExecutionStatus.UNKNOWN


def test_verification_ignores_wrong_symbol() -> None:
    adapter = connected(ScriptedProvider())
    adapter = prepared(adapter, reading(), reading(snapshot("555", symbol="EURUSD")))

    assert adapter.verify_execution(request()).status is ExecutionStatus.UNKNOWN


def test_capture_positions_requires_a_connection() -> None:
    adapter = MT5DesktopAdapter(profile(), FakeManager(), position_provider=ScriptedProvider())

    with pytest.raises(AutomationError, match="not connected"):
        adapter.capture_positions()


def test_execution_controls_remain_refused_without_the_explicit_opt_in() -> None:
    adapter = connected(ScriptedProvider())

    result = adapter.execute_order(request())

    assert result.status is ExecutionStatus.REJECTED
    assert "AUTO_TRADE_ENABLE_EXECUTION" in result.message


def test_verification_evidence_requires_both_references() -> None:
    with pytest.raises(ValueError, match="baseline"):
        VerificationEvidence(baseline="", observed="x")
    with pytest.raises(ValueError, match="observed"):
        VerificationEvidence(baseline="x", observed="")
