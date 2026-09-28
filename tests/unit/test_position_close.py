"""The guarded position close.

The Trade grid on Alpari MT5 build 6184 exposes row rectangles but no row text,
so these tests pin the rule that makes a close safe: refuse whenever the ticket
cannot be tied to a row without a guess, and accept only when the independent
observation shows the ticket is gone.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from auto_trade.domain.enums import ExecutionStatus
from auto_trade.domain.exceptions import AutomationError, PositionSnapshotUnavailable
from auto_trade.domain.models import PositionSnapshot, TerminalProfile
from auto_trade.infrastructure.automation import MT5DesktopAdapter, MT5WindowManager
from auto_trade.infrastructure.automation.closing import (
    CLOSE_MENU_ITEM_ID,
    CLOSE_MENU_ITEM_NAME,
    CloseGate,
    only_close_entry,
    position_row,
)

OPEN_GATE = CloseGate(enabled=True, dry_run=False, demo_only=True, kill_switch_active=False)


def position(ticket: str = "555", symbol: str = "EURUSD", side: str = "SELL") -> PositionSnapshot:
    return PositionSnapshot(ticket, symbol, side, Decimal("0.01"))


class ScriptedProvider:
    def __init__(self, *readings: tuple[PositionSnapshot, ...]) -> None:
        self.readings = list(readings)
        self.error: Exception | None = None

    def positions(self) -> tuple[PositionSnapshot, ...]:
        if self.error is not None:
            raise self.error
        if not self.readings:
            return ()
        return self.readings.pop(0)


class FakeRow:
    def __init__(self) -> None:
        self.clicks = 0

    def click_input(self, button: str = "left", pressed: str = "") -> None:
        self.clicks += 1


class FakeTradeManager(MT5WindowManager):
    """A Trade tab with a known shape, a known menu, and a click counter."""

    def __init__(
        self,
        rows: int = 1,
        entries: list[tuple[str, str]] | None = None,
        raise_on_rows: Exception | None = None,
    ) -> None:
        super().__init__()
        self._rows = [FakeRow() for _ in range(rows)]
        self._entries = (
            entries
            if entries is not None
            else [("New Order\tF9", "33029"), (CLOSE_MENU_ITEM_NAME, CLOSE_MENU_ITEM_ID)]
        )
        self._raise_on_rows = raise_on_rows
        self.menu_reads = 0
        self.menu_clicks: list[tuple[str, str]] = []
        self.row_clicks = 0

    def trade_rows(self) -> list[Any]:
        if self._raise_on_rows is not None:
            raise self._raise_on_rows
        return list(self._rows)

    def open_row_context_menu(self, row: Any) -> list[tuple[str, str]]:
        self.menu_reads += 1
        setattr(row, "click", lambda *args, **kwargs: None)
        row.clicks += 1
        return list(self._entries)

    def click_row_menu_entry(self, row: Any, name: str, control_id: str) -> None:
        row.clicks += 1
        self.row_clicks += 1
        self.menu_clicks.append((name, control_id))


def adapter_for(
    provider: ScriptedProvider,
    manager: FakeTradeManager | None = None,
    gate: CloseGate = OPEN_GATE,
    timeout: float = 1.0,
) -> MT5DesktopAdapter:
    instance = MT5DesktopAdapter(
        TerminalProfile("alpari-demo", "terminal64.exe", "data", "Alpari-MT5-Demo"),
        manager or FakeTradeManager(),
        position_provider=provider,
        close_gate=gate,
    )
    instance.connected = True
    instance.close_timeout_seconds = timeout
    return instance


# -- the gate ----------------------------------------------------------


def test_close_is_refused_by_default() -> None:
    assert "AUTO_TRADE_ENABLE_CLOSE" in CloseGate().refusal()


@pytest.mark.parametrize(
    ("gate", "fragment"),
    [
        (CloseGate(), "AUTO_TRADE_ENABLE_CLOSE"),
        (CloseGate(enabled=True, kill_switch_active=True), "kill switch"),
        (CloseGate(enabled=True, dry_run=True), "dry-run"),
        (CloseGate(enabled=True, dry_run=False, demo_only=False), "demo-only"),
    ],
)
def test_every_refused_gate_leaves_the_position_open(
    gate: CloseGate, fragment: str
) -> None:
    manager = FakeTradeManager()
    adapter = adapter_for(ScriptedProvider((position(),)), manager, gate=gate)

    result = adapter.close_position("555")

    assert result.status is ExecutionStatus.REJECTED
    assert fragment in result.message
    assert manager.row_clicks == 0


def test_an_order_opt_in_alone_does_not_allow_closing() -> None:
    """Closing has its own opt-in and is never reachable through the order gate."""
    assert CloseGate(enabled=False, dry_run=False, demo_only=True).refusal() != ""


# -- refusing when the row cannot be identified ------------------------


def test_a_ticket_that_is_not_observed_is_refused() -> None:
    manager = FakeTradeManager()
    adapter = adapter_for(ScriptedProvider((position("999"),)), manager)

    result = adapter.close_position("555")

    assert result.status is ExecutionStatus.REJECTED
    assert "not in the observed snapshot" in result.message
    assert manager.row_clicks == 0


def test_more_than_one_open_position_is_refused_rather_than_guessed() -> None:
    manager = FakeTradeManager(rows=2)
    adapter = adapter_for(
        ScriptedProvider((position("555"), position("556"))), manager
    )

    result = adapter.close_position("555")

    assert result.status is ExecutionStatus.REJECTED
    assert "cannot be identified" in result.message
    assert manager.row_clicks == 0


def test_a_grid_with_unexpected_rows_is_refused() -> None:
    manager = FakeTradeManager(rows=3)
    adapter = adapter_for(ScriptedProvider((position(),)), manager)

    result = adapter.close_position("555")

    assert result.status is ExecutionStatus.REJECTED
    assert "refusing to guess" in result.message
    assert manager.row_clicks == 0


def test_an_unreadable_snapshot_before_the_close_is_unknown_not_closed() -> None:
    provider = ScriptedProvider()
    provider.error = PositionSnapshotUnavailable("snapshot is stale")
    manager = FakeTradeManager()
    adapter = adapter_for(provider, manager)

    result = adapter.close_position("555")

    assert result.status is ExecutionStatus.UNKNOWN
    assert manager.row_clicks == 0


def test_a_disconnected_terminal_is_refused() -> None:
    manager = FakeTradeManager()
    adapter = adapter_for(ScriptedProvider((position(),)), manager)
    adapter.connected = False

    result = adapter.close_position("555")

    assert result.status is ExecutionStatus.REJECTED
    assert "not connected" in result.message


# -- the menu entry ----------------------------------------------------


def test_the_close_entry_must_match_name_and_id() -> None:
    assert only_close_entry([(CLOSE_MENU_ITEM_NAME, CLOSE_MENU_ITEM_ID)]) == (
        CLOSE_MENU_ITEM_NAME,
        CLOSE_MENU_ITEM_ID,
    )


def test_a_menu_without_the_close_entry_is_refused() -> None:
    with pytest.raises(LookupError, match="no 'Close Position' entry"):
        only_close_entry([("New Order\tF9", "33029"), ("Modify or Delete", "33028")])


def test_a_close_entry_with_a_wrong_id_is_refused() -> None:
    with pytest.raises(LookupError, match="automation id"):
        only_close_entry([(CLOSE_MENU_ITEM_NAME, "12345")])


def test_near_miss_entries_are_never_matched() -> None:
    for name in ("Close by", "Close 50%", "Close All"):
        with pytest.raises(LookupError, match="no 'Close Position' entry"):
            only_close_entry([(name, CLOSE_MENU_ITEM_ID)])


def test_duplicate_close_entries_are_refused() -> None:
    with pytest.raises(LookupError, match="2 'Close Position' entries"):
        only_close_entry(
            [(CLOSE_MENU_ITEM_NAME, CLOSE_MENU_ITEM_ID)] * 2
        )


def test_a_menu_with_no_close_entry_leaves_the_position_open() -> None:
    manager = FakeTradeManager(entries=[("New Order\tF9", "33029")])
    adapter = adapter_for(ScriptedProvider((position(),)), manager)

    result = adapter.close_position("555")

    assert result.status is ExecutionStatus.REJECTED
    assert "refusing to close" in result.message
    assert manager.row_clicks == 0


# -- the successful path ----------------------------------------------


def test_a_closed_position_is_proven_by_the_snapshot() -> None:
    provider = ScriptedProvider((position("555"),), ())
    manager = FakeTradeManager(rows=2)
    adapter = adapter_for(provider, manager)

    result = adapter.close_position("555")

    assert result.status is ExecutionStatus.CLOSED
    assert result.order_reference == "555"
    assert manager.row_clicks == 1
    assert manager.menu_clicks == [(CLOSE_MENU_ITEM_NAME, CLOSE_MENU_ITEM_ID)]


def test_a_position_that_stays_open_is_unknown() -> None:
    provider = ScriptedProvider((position("555"),))
    provider.readings = [(position("555"),)] * 20
    manager = FakeTradeManager()
    adapter = adapter_for(provider, manager, timeout=0.3)

    result = adapter.close_position("555")

    assert result.status is ExecutionStatus.UNKNOWN
    assert "still present" in result.message
    assert result.order_reference == "555"


def test_a_click_never_claims_a_close_it_could_not_observe() -> None:
    provider = ScriptedProvider((position("555"),))
    manager = FakeTradeManager()
    setattr(manager, "click_row_menu_entry", lambda *args, **kwargs: (_ for _ in ()).throw(
        AutomationError("menu entry was not found")
    ))
    adapter = adapter_for(provider, manager)

    result = adapter.close_position("555")

    assert result.status is ExecutionStatus.UNKNOWN
    assert "could not be used" in result.message


def test_an_unreadable_snapshot_after_the_click_is_unknown() -> None:
    provider = ScriptedProvider((position("555"),))
    manager = FakeTradeManager()
    adapter = adapter_for(provider, manager, timeout=0.3)
    calls = {"count": 0}
    original = provider.positions

    def reading() -> tuple[PositionSnapshot, ...]:
        calls["count"] += 1
        if calls["count"] > 1:
            raise PositionSnapshotUnavailable("snapshot is being rewritten")
        return original()

    provider.positions = reading  # type: ignore[method-assign]
    result = adapter.close_position("555")

    assert result.status is ExecutionStatus.UNKNOWN
    assert "could not be observed" in result.message


# -- the row rule ------------------------------------------------------


def test_one_row_is_the_position_and_two_are_position_plus_summary() -> None:
    assert position_row(["only"]) == "only"
    assert position_row(["position", "balance"]) == "position"


@pytest.mark.parametrize("rows", [[], ["a", "b", "c"]])
def test_any_other_row_count_is_refused(rows: list[str]) -> None:
    with pytest.raises(LookupError, match="refusing to guess"):
        position_row(rows)
