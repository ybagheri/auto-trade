from __future__ import annotations

from typing import Any

import pytest

from auto_trade.domain.enums import ExecutionStatus
from auto_trade.domain.exceptions import AutomationError
from auto_trade.domain.models import OrderRequest, TerminalProfile, TradeSignal
from auto_trade.infrastructure.automation import MT5DesktopAdapter, MT5WindowManager

from ..helpers import signal_data


class FakeWindow:
    def window_text(self) -> str:
        return "123 - Alpari-MT5-Demo: Demo Account - [XAUUSD,M5]"


class FakeManager(MT5WindowManager):
    def find(self, profile: TerminalProfile, process_id: int | None = None) -> FakeWindow:
        self._window = FakeWindow()
        return self._window


# -- tidying up after a dialog this code did not recognise -----------------


class FakeInfo:
    def __init__(self, kind: str, name: str) -> None:
        self.control_type = kind
        self.name = name
        self.automation_id = ""
        self.process_id = 1


class FakeControl:
    def __init__(self, kind: str, name: str) -> None:
        self.element_info = FakeInfo(kind, name)
        self.clicked = False
        self.children: list[Any] = []

    def window_text(self) -> str:
        return str(self.element_info.name)

    def descendants(self) -> list[Any]:
        """Real pywinauto wrappers expose this on leaves too, returning []."""
        return list(self.children)

    def click_input(self, **_kwargs: Any) -> None:
        self.clicked = True


class FakeTree:
    """A window holding one order dialog, as build 6090 presents it."""

    def __init__(self, dialog_title: str = "Order") -> None:
        self.close_button = FakeControl("Button", "Close")
        self.dialog = FakeControl("Window", dialog_title)
        self.dialog.children = [self.close_button]
        self.children = [self.dialog]

    def descendants(self) -> list[Any]:
        return list(self.children)


class ClosingTree(FakeTree):
    """The same tree, but the Close button really removes the dialog."""

    def __init__(self, dialog_title: str = "Order") -> None:
        super().__init__(dialog_title)
        original = self.close_button.click_input

        def click(**kwargs: Any) -> None:
            original(**kwargs)
            self.children = []

        self.close_button.click_input = click  # type: ignore[method-assign]


def manager_for(tree: FakeTree) -> MT5WindowManager:
    manager = MT5WindowManager()
    manager._window = tree  # type: ignore[assignment]
    return manager


def test_a_dialog_the_code_did_not_recognise_is_still_closed() -> None:
    """Recognition failing must not leave a dialog over a trading terminal.

    On this build the dialog is titled plain `Order` and a single click on it is
    a market order, so a probe that raised before recording the handle would
    otherwise leave a one-click order form on screen.
    """
    tree = ClosingTree("Order")
    manager = manager_for(tree)

    assert manager.close_any_order_dialog() is True
    assert tree.close_button.clicked
    assert tree.children == []


def test_the_older_dialog_title_is_also_closed() -> None:
    tree = ClosingTree("Order: EURUSD")
    manager = manager_for(tree)

    assert manager.close_any_order_dialog() is True
    assert tree.children == []


def test_closing_reports_failure_when_the_dialog_stays() -> None:
    """A dialog that will not close is reported, not reported as tidy."""
    manager = manager_for(FakeTree("Order"))

    assert manager.close_any_order_dialog(timeout_seconds=0.2) is False


def test_closing_reports_failure_when_there_is_no_close_control() -> None:
    tree = FakeTree("Order")
    tree.dialog.children = []
    manager = manager_for(tree)

    assert manager.close_any_order_dialog() is False


def test_nothing_to_close_is_reported_rather_than_raising() -> None:
    manager = manager_for(FakeTree())

    assert manager.close_any_order_dialog() is False


def test_tidying_up_does_not_raise_when_the_window_is_gone() -> None:
    """A destroyed element must not turn tidying up into a second failure."""
    manager = MT5WindowManager()
    manager._window = None  # type: ignore[assignment]

    assert manager.close_any_order_dialog() is False


def profile() -> TerminalProfile:
    return TerminalProfile(
        name="alpari-demo",
        terminal_path="terminal64.exe",
        data_path="data",
        instance_name="Alpari Demo",
    )


def test_window_manager_matches_demo_instance() -> None:
    assert MT5WindowManager._matches(FakeWindow().window_text(), profile())


def test_real_adapter_refuses_final_execution_by_default() -> None:
    """A fresh adapter must refuse, and must say why."""
    adapter = MT5DesktopAdapter(profile(), FakeManager())
    request = OrderRequest(TradeSignal.from_dict(signal_data()))

    result = adapter.execute_order(request)

    assert result.status is ExecutionStatus.REJECTED
    assert "AUTO_TRADE_ENABLE_EXECUTION" in result.message
