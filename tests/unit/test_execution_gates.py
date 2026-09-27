"""Every gate in front of a final execution control.

No MT5 required. The window manager is a fake, so these tests also prove that
nothing is clicked unless every gate passes.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from auto_trade.domain.enums import ExecutionStatus, OrderAction
from auto_trade.domain.exceptions import AutomationRejectedError
from auto_trade.domain.models import OrderRequest, TerminalProfile, TradeSignal
from auto_trade.infrastructure.automation import MT5DesktopAdapter, MT5WindowManager
from auto_trade.infrastructure.automation.execution import (
    BUY_BUTTON_ID,
    BUY_BUTTON_NAME,
    SELL_BUTTON_ID,
    SELL_BUTTON_NAME,
    ExecutionGate,
    assert_action_supported,
    plain_decimal,
    target_control,
)

from ..helpers import signal_data


class FakeInfo:
    control_type = "Button"

    def __init__(self, automation_id: str) -> None:
        self.automation_id = automation_id


class FakeButton:
    def __init__(self, name: str, automation_id: str) -> None:
        self._name = name
        self._info = FakeInfo(automation_id)
        self.clicks = 0

    def window_text(self) -> str:
        return self._name

    @property
    def element_info(self) -> FakeInfo:
        return self._info

    def click_input(self) -> None:
        self.clicks += 1


class FakeDialog:
    def __init__(self, buttons: list[FakeButton]) -> None:
        self._buttons = buttons

    def descendants(self) -> list[FakeButton]:
        return self._buttons


class FakeManager(MT5WindowManager):
    """Records every click so a test can prove nothing was submitted."""

    def __init__(self, fields: dict[str, str], buttons: list[FakeButton]) -> None:
        super().__init__()
        self.fields = fields
        self.dialog = FakeDialog(buttons)
        self.opened = 0
        self.closed = 0

    def open_order_dialog(self, timeout_seconds: float = 5.0) -> FakeDialog:
        self.opened += 1
        return self.dialog

    def read_field(self, automation_id: str) -> str:
        return self.fields[automation_id]

    def close_order_dialog(self, timeout_seconds: float = 5.0) -> None:
        self.closed += 1


def fields(symbol: str = "BITCOIN, 1 LOT = 1 BITCOIN", volume: str = "0.01") -> dict[str, str]:
    return {"10325": symbol, "10333": volume, "10334": "0.00", "10336": "0.00"}


def buy_button() -> FakeButton:
    return FakeButton(BUY_BUTTON_NAME, BUY_BUTTON_ID)


def profile() -> TerminalProfile:
    return TerminalProfile(
        name="alpari-demo",
        terminal_path="terminal64.exe",
        data_path="data",
        instance_name="Alpari Demo",
    )


def adapter_for(
    manager: FakeManager,
    gate: ExecutionGate,
    baseline: bool = True,
) -> MT5DesktopAdapter:
    adapter = MT5DesktopAdapter(
        profile(),
        manager,
        position_provider=None,
        gate=gate,
    )
    adapter.connected = True
    if baseline:
        adapter._baseline = ()
    return adapter


def request(action: str = "BUY", symbol: str = "BITCOIN", volume: str = "0.01") -> OrderRequest:
    data = signal_data() | {"symbol": symbol, "action": action, "volume": float(volume)}
    return OrderRequest(TradeSignal.from_dict(data))


OPEN_GATE = ExecutionGate(enabled=True, dry_run=False, demo_only=True, kill_switch_active=False)


# -- the gate itself ---------------------------------------------------


def test_gate_refuses_by_default() -> None:
    assert "AUTO_TRADE_ENABLE_EXECUTION" in ExecutionGate().refusal()


def test_gate_refuses_while_dry_run() -> None:
    gate = ExecutionGate(enabled=True, dry_run=True)
    assert "dry-run" in gate.refusal()


def test_gate_refuses_when_kill_switch_is_active() -> None:
    gate = ExecutionGate(enabled=True, dry_run=False, kill_switch_active=True)
    assert "kill switch" in gate.refusal()


def test_gate_refuses_when_demo_only_is_off() -> None:
    gate = ExecutionGate(enabled=True, dry_run=False, demo_only=False)
    assert "demo-only" in gate.refusal()


def test_gate_allows_only_when_every_condition_holds() -> None:
    assert OPEN_GATE.refusal() == ""


# -- refusal paths, and nothing is clicked -----------------------------


@pytest.mark.parametrize(
    ("gate", "fragment"),
    [
        (ExecutionGate(), "AUTO_TRADE_ENABLE_EXECUTION"),
        (ExecutionGate(enabled=True, dry_run=True), "dry-run"),
        (ExecutionGate(enabled=True, dry_run=False, kill_switch_active=True), "kill switch"),
        (ExecutionGate(enabled=True, dry_run=False, demo_only=False), "demo-only"),
    ],
)
def test_every_refused_gate_leaves_the_dialog_untouched(
    gate: ExecutionGate, fragment: str
) -> None:
    button = buy_button()
    manager = FakeManager(fields(), [button])
    adapter = adapter_for(manager, gate)

    result = adapter.execute_order(request())

    assert result.status is ExecutionStatus.REJECTED
    assert fragment in result.message
    assert button.clicks == 0
    assert manager.opened == 0


def test_execution_is_refused_without_an_observed_baseline() -> None:
    button = buy_button()
    manager = FakeManager(fields(), [button])
    adapter = adapter_for(manager, OPEN_GATE, baseline=False)
    adapter._baseline_error = "MT5 position observation is unavailable"

    result = adapter.execute_order(request())

    assert result.status is ExecutionStatus.REJECTED
    assert "unavailable" in result.message
    assert button.clicks == 0


def test_unsupported_action_is_refused_without_clicking() -> None:
    button = buy_button()
    manager = FakeManager(fields(), [button])
    adapter = adapter_for(manager, OPEN_GATE)

    result = adapter.execute_order(request(action="CLOSE"))

    assert result.status is ExecutionStatus.REJECTED
    assert button.clicks == 0


@pytest.mark.parametrize(
    ("shown_symbol", "shown_volume", "fragment"),
    [
        ("EURUSD, 1 LOT = 1 EURUSD", "0.01", "symbol"),
        ("BITCOIN, 1 LOT = 1 BITCOIN", "0.50", "volume"),
    ],
)
def test_mismatched_dialog_is_refused_without_clicking(
    shown_symbol: str, shown_volume: str, fragment: str
) -> None:
    button = buy_button()
    manager = FakeManager(fields(shown_symbol, shown_volume), [button])
    adapter = adapter_for(manager, OPEN_GATE)

    result = adapter.execute_order(request())

    assert result.status is ExecutionStatus.REJECTED
    assert fragment in result.message
    assert button.clicks == 0


# -- the one path that does click --------------------------------------


def test_matching_dialog_is_clicked_and_reported_as_requested_only() -> None:
    button = buy_button()
    manager = FakeManager(fields(), [button])
    adapter = adapter_for(manager, OPEN_GATE)

    result = adapter.execute_order(request())

    assert button.clicks == 1
    assert result.status is ExecutionStatus.REQUESTED
    # A click is an action, never proof of a fill.
    assert "acceptance not yet observed" in result.message
    assert result.order_reference is None


def test_sell_uses_the_sell_control() -> None:
    buy = buy_button()
    sell = FakeButton(SELL_BUTTON_NAME, SELL_BUTTON_ID)
    manager = FakeManager(fields(), [buy, sell])
    adapter = adapter_for(manager, OPEN_GATE)

    result = adapter.execute_order(request(action="SELL"))

    assert sell.clicks == 1
    assert buy.clicks == 0
    assert result.status is ExecutionStatus.REQUESTED


def test_missing_final_control_refuses_rather_than_guessing() -> None:
    manager = FakeManager(fields(), [FakeButton("Something Else", "99999")])
    adapter = adapter_for(manager, OPEN_GATE)

    result = adapter.execute_order(request())

    assert result.status is ExecutionStatus.REJECTED
    assert "was not found" in result.message


def test_ambiguous_final_control_refuses_rather_than_guessing() -> None:
    manager = FakeManager(fields(), [buy_button(), buy_button()])
    adapter = adapter_for(manager, OPEN_GATE)

    result = adapter.execute_order(request())

    assert result.status is ExecutionStatus.REJECTED
    assert "refusing to guess" in result.message


def test_control_must_match_name_and_automation_id() -> None:
    """A same-named button with a different id is not the final control."""
    manager = FakeManager(fields(), [FakeButton(BUY_BUTTON_NAME, "12345")])
    adapter = adapter_for(manager, OPEN_GATE)

    result = adapter.execute_order(request())

    assert result.status is ExecutionStatus.REJECTED


# -- units and helpers -------------------------------------------------


def test_supported_actions() -> None:
    assert target_control(OrderAction.BUY) == (BUY_BUTTON_ID, BUY_BUTTON_NAME)
    assert target_control(OrderAction.SELL) == (SELL_BUTTON_ID, SELL_BUTTON_NAME)


def test_pending_action_has_no_final_control() -> None:
    with pytest.raises(AutomationRejectedError, match="no final control"):
        target_control(OrderAction.BUY_LIMIT)
    with pytest.raises(AutomationRejectedError, match="no guarded final control"):
        assert_action_supported(request(action="BUY_LIMIT"))


def test_decimal_comparison_ignores_trailing_zeros() -> None:
    assert plain_decimal(Decimal("0.010")) == "0.01"
    assert plain_decimal(Decimal("0.10")) == "0.1"
    assert plain_decimal("0.010") == "0.01"
    assert plain_decimal(Decimal("1.00")) == "1"


def test_a_disconnected_adapter_still_refuses_before_touching_anything() -> None:
    """Refusal is decided by the gate, before any connection is required."""
    button = buy_button()
    manager = FakeManager(fields(), [button])
    adapter = MT5DesktopAdapter(profile(), manager, gate=OPEN_GATE)

    result = adapter.execute_order(request())

    assert result.status is ExecutionStatus.REJECTED
    assert button.clicks == 0
    assert manager.opened == 0
