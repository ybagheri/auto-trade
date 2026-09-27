from __future__ import annotations

from datetime import UTC, datetime
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
from auto_trade.infrastructure.automation.positions_file import ObserverSnapshot

from ..helpers import signal_data

NOW = datetime(2026, 9, 26, 12, 0, 0, tzinfo=UTC)


def snapshot(ticket: str, symbol: str = "BITCOIN", side: str = "BUY") -> PositionSnapshot:
    return PositionSnapshot(ticket, symbol, side, Decimal("0.01"))


def reading(sequence: int, *positions: PositionSnapshot) -> ObserverSnapshot:
    """An observer reading whose sequence makes the reference distinguishable."""
    return ObserverSnapshot(
        sequence=sequence,
        written_at=NOW,
        account=53145727,
        server="Alpari-MT5-Demo",
        positions=tuple(positions),
    )


class ScriptedProvider:
    """Yields a queued sequence of readings, then fails closed."""

    def __init__(self, *readings: ObserverSnapshot) -> None:
        self.readings = list(readings)
        self.calls = 0

    def snapshot(self) -> ObserverSnapshot:
        self.calls += 1
        if not self.readings:
            raise PositionSnapshotUnavailable("observer snapshot is unavailable")
        return self.readings.pop(0)

    def positions(self) -> tuple[PositionSnapshot, ...]:
        return self.snapshot().positions


class PositionsOnlyProvider:
    """A provider with no snapshot() method, exercising the adapter's fallback."""

    def __init__(self, *positions: PositionSnapshot) -> None:
        self.result = tuple(positions)

    def positions(self) -> tuple[PositionSnapshot, ...]:
        return self.result


class FakeManager(MT5WindowManager):
    def find(self, profile: TerminalProfile) -> Any:
        raise AssertionError("connect is not exercised in these tests")


def profile() -> TerminalProfile:
    return TerminalProfile(
        name="alpari-demo",
        terminal_path="terminal64.exe",
        data_path="data",
        instance_name="Alpari Demo",
    )


def request(symbol: str = "BITCOIN", side: str = "BUY", volume: str = "0.01") -> OrderRequest:
    data = signal_data() | {"symbol": symbol, "action": side, "volume": float(volume)}
    return OrderRequest(TradeSignal.from_dict(data))


def connected(provider: Any) -> MT5DesktopAdapter:
    adapter = MT5DesktopAdapter(profile(), FakeManager(), position_provider=provider)
    adapter.connected = True
    return adapter


def prepared(adapter: MT5DesktopAdapter, *readings: ObserverSnapshot) -> MT5DesktopAdapter:
    """Give the adapter a provider queue and a baseline, as prepare_order would.

    The first reading is consumed as the baseline, so the next read the adapter
    performs is the "after" state.
    """
    provider = ScriptedProvider(*readings)
    adapter.position_provider = provider
    adapter._baseline = provider.readings.pop(0) if provider.readings else None
    adapter._baseline_error = None
    return adapter


def test_verification_accepts_exactly_one_new_matching_position() -> None:
    existing = snapshot("111", side="SELL")
    adapter = connected(ScriptedProvider())
    adapter = prepared(adapter, reading(10, existing), reading(11, existing, snapshot("555")))

    result = adapter.verify_execution(request())

    assert result.status is ExecutionStatus.ACCEPTED
    assert result.order_reference == "555"


def test_accepted_result_carries_both_snapshot_references() -> None:
    existing = snapshot("111", side="SELL")
    adapter = connected(ScriptedProvider())
    adapter = prepared(adapter, reading(10, existing), reading(11, existing, snapshot("555")))

    result = adapter.verify_execution(request())

    evidence = result.evidence
    assert isinstance(evidence, VerificationEvidence)
    assert "sequence=10" in evidence.baseline
    assert "sequence=11" in evidence.observed
    assert "positions=1" in evidence.baseline
    assert "positions=2" in evidence.observed
    assert "account=53145727" in evidence.baseline
    assert evidence.position_id == "555"
    assert evidence.to_dict()["position_id"] == "555"


def test_unknown_result_still_records_the_observed_reference() -> None:
    existing = snapshot("111", side="SELL")
    adapter = connected(ScriptedProvider())
    adapter = prepared(adapter, reading(10, existing), reading(11, existing))

    result = adapter.verify_execution(request())

    assert result.status is ExecutionStatus.UNKNOWN
    evidence = result.evidence
    assert isinstance(evidence, VerificationEvidence)
    assert "sequence=10" in evidence.baseline
    assert "sequence=11" in evidence.observed
    assert evidence.position_id is None


def test_verification_reports_unknown_when_nothing_appeared() -> None:
    existing = snapshot("111", side="SELL")
    adapter = connected(ScriptedProvider())
    adapter = prepared(adapter, reading(10, existing), reading(11, existing))

    result = adapter.verify_execution(request())

    assert result.status is ExecutionStatus.UNKNOWN
    assert result.order_reference is None


def test_verification_reports_unknown_on_ambiguous_match() -> None:
    adapter = connected(ScriptedProvider())
    adapter = prepared(adapter, reading(10), reading(11, snapshot("555"), snapshot("556")))

    result = adapter.verify_execution(request())

    assert result.status is ExecutionStatus.UNKNOWN
    assert "multiple" in result.message


def test_verification_reports_unknown_when_snapshot_fails() -> None:
    adapter = connected(ScriptedProvider())
    adapter = prepared(adapter, reading(10))

    result = adapter.verify_execution(request())

    assert result.status is ExecutionStatus.UNKNOWN
    assert "unavailable" in result.message


def test_verification_reports_unknown_without_a_baseline() -> None:
    adapter = connected(ScriptedProvider(reading(11, snapshot("555"))))
    adapter._baseline = None
    adapter._baseline_error = "no observer snapshot found"

    result = adapter.verify_execution(request())

    assert result.status is ExecutionStatus.UNKNOWN
    assert "baseline unavailable" in result.message
    assert result.evidence is None


def test_verification_ignores_wrong_side() -> None:
    adapter = connected(ScriptedProvider())
    adapter = prepared(adapter, reading(10), reading(11, snapshot("555", side="SELL")))

    assert adapter.verify_execution(request(side="BUY")).status is ExecutionStatus.UNKNOWN


def test_verification_ignores_wrong_volume() -> None:
    wrong = PositionSnapshot("555", "BITCOIN", "BUY", Decimal("0.50"))
    adapter = connected(ScriptedProvider())
    adapter = prepared(adapter, reading(10), reading(11, wrong))

    assert adapter.verify_execution(request(volume="0.01")).status is ExecutionStatus.UNKNOWN


def test_verification_ignores_wrong_symbol() -> None:
    adapter = connected(ScriptedProvider())
    adapter = prepared(adapter, reading(10), reading(11, snapshot("555", symbol="EURUSD")))

    assert adapter.verify_execution(request()).status is ExecutionStatus.UNKNOWN


def test_provider_without_snapshot_method_still_yields_evidence() -> None:
    adapter = connected(PositionsOnlyProvider())
    adapter._baseline = reading(20)
    adapter._baseline_error = None

    result = adapter.verify_execution(request())

    evidence = result.evidence
    assert isinstance(evidence, VerificationEvidence)
    assert evidence.baseline.startswith("sequence=20")
    assert "sequence=-1" in evidence.observed


def test_capture_snapshot_requires_a_connection() -> None:
    adapter = MT5DesktopAdapter(profile(), FakeManager(), position_provider=ScriptedProvider())

    with pytest.raises(AutomationError, match="not connected"):
        adapter.capture_snapshot()


def test_execution_controls_remain_blocked() -> None:
    adapter = connected(ScriptedProvider())

    with pytest.raises(AutomationError, match="final controls are blocked"):
        adapter.execute_order(request())


def test_verification_evidence_requires_both_references() -> None:
    with pytest.raises(ValueError, match="baseline"):
        VerificationEvidence(baseline="", observed="x")
    with pytest.raises(ValueError, match="observed"):
        VerificationEvidence(baseline="x", observed="")
