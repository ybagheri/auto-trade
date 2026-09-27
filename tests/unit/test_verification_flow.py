from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from auto_trade.domain.enums import ExecutionStatus
from auto_trade.domain.exceptions import AutomationError, PositionSnapshotUnavailable
from auto_trade.domain.models import OrderRequest, PositionSnapshot, TradeSignal
from auto_trade.infrastructure.automation import MT5DesktopAdapter, MT5WindowManager

from ..helpers import signal_data


class ScriptedProvider:
    """Yields a queued sequence of snapshots, then fails closed."""

    def __init__(self, *snapshots: tuple[PositionSnapshot, ...]) -> None:
        self.snapshots = list(snapshots)
        self.calls = 0

    def positions(self) -> tuple[PositionSnapshot, ...]:
        self.calls += 1
        if not self.snapshots:
            raise PositionSnapshotUnavailable("observer snapshot is unavailable")
        return self.snapshots.pop(0)


class FakeManager(MT5WindowManager):
    def find(self, profile: Any) -> Any:
        raise AssertionError("connect is not exercised in these tests")


def profile() -> Any:
    from auto_trade.domain.models import TerminalProfile

    return TerminalProfile(
        name="alpari-demo",
        terminal_path="terminal64.exe",
        data_path="data",
        instance_name="Alpari Demo",
    )


def request(symbol: str = "BITCOIN", side: str = "BUY", volume: str = "0.01") -> OrderRequest:
    data = signal_data() | {"symbol": symbol, "action": side, "volume": float(volume)}
    return OrderRequest(TradeSignal.from_dict(data))


def snapshot(ticket: str, symbol: str = "BITCOIN", side: str = "BUY") -> PositionSnapshot:
    return PositionSnapshot(ticket, symbol, side, Decimal("0.01"))


def connected(provider: ScriptedProvider) -> MT5DesktopAdapter:
    adapter = MT5DesktopAdapter(profile(), FakeManager(), position_provider=provider)
    adapter.connected = True
    return adapter


def test_verification_accepts_exactly_one_new_matching_position() -> None:
    existing = snapshot("111", side="SELL")
    provider = ScriptedProvider((existing, snapshot("555")))
    adapter = connected(provider)
    adapter._baseline = (existing,)
    adapter._baseline_error = None

    result = adapter.verify_execution(request())

    assert result.status is ExecutionStatus.ACCEPTED
    assert result.order_reference == "555"


def test_verification_reports_unknown_when_nothing_appeared() -> None:
    existing = snapshot("111", side="SELL")
    provider = ScriptedProvider((existing,))
    adapter = connected(provider)
    adapter._baseline = (existing,)

    result = adapter.verify_execution(request())

    assert result.status is ExecutionStatus.UNKNOWN
    assert result.order_reference is None


def test_verification_reports_unknown_on_ambiguous_match() -> None:
    provider = ScriptedProvider((snapshot("555"), snapshot("556")))
    adapter = connected(provider)
    adapter._baseline = ()

    result = adapter.verify_execution(request())

    assert result.status is ExecutionStatus.UNKNOWN
    assert "multiple" in result.message


def test_verification_reports_unknown_when_snapshot_fails() -> None:
    provider = ScriptedProvider()
    adapter = connected(provider)
    adapter._baseline = ()

    result = adapter.verify_execution(request())

    assert result.status is ExecutionStatus.UNKNOWN
    assert "unavailable" in result.message


def test_verification_reports_unknown_without_a_baseline() -> None:
    provider = ScriptedProvider((snapshot("555"),))
    adapter = connected(provider)
    adapter._baseline = None
    adapter._baseline_error = "no observer snapshot found"

    result = adapter.verify_execution(request())

    assert result.status is ExecutionStatus.UNKNOWN
    assert "baseline unavailable" in result.message


def test_verification_ignores_wrong_side() -> None:
    provider = ScriptedProvider((snapshot("555", side="SELL"),))
    adapter = connected(provider)
    adapter._baseline = ()

    result = adapter.verify_execution(request(side="BUY"))

    assert result.status is ExecutionStatus.UNKNOWN


def test_verification_ignores_wrong_volume() -> None:
    provider = ScriptedProvider(
        (PositionSnapshot("555", "BITCOIN", "BUY", Decimal("0.50")),)
    )
    adapter = connected(provider)
    adapter._baseline = ()

    result = adapter.verify_execution(request(volume="0.01"))

    assert result.status is ExecutionStatus.UNKNOWN


def test_verification_ignores_wrong_symbol() -> None:
    provider = ScriptedProvider((snapshot("555", symbol="EURUSD"),))
    adapter = connected(provider)
    adapter._baseline = ()

    result = adapter.verify_execution(request())

    assert result.status is ExecutionStatus.UNKNOWN


def test_execution_controls_remain_blocked() -> None:
    adapter = connected(ScriptedProvider())

    with pytest.raises(AutomationError, match="final controls are blocked"):
        adapter.execute_order(request())
