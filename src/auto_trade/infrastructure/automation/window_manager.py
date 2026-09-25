from __future__ import annotations

import importlib
import re
import time
from decimal import Decimal
from typing import Any

from ...domain.enums import AccountType
from ...domain.exceptions import AutomationError
from ...domain.models import (
    AccountSnapshot,
    ExecutionResult,
    OrderRequest,
    PositionSnapshot,
    TerminalProfile,
)
from ..terminal.discovery import WindowsTerminalDiscovery


class MT5WindowManager:
    def __init__(self) -> None:
        self._window: Any | None = None
        self._order_dialog: Any | None = None

    def find(self, profile: TerminalProfile) -> Any:
        try:
            pywinauto = importlib.import_module("pywinauto")
        except ImportError as exc:
            raise AutomationError("pywinauto is required for real terminal inspection") from exc
        windows = pywinauto.Desktop(backend="uia").windows()
        matches = [window for window in windows if self._matches(window.window_text(), profile)]
        if not matches:
            raise AutomationError("configured MT5 window was not found")
        self._window = matches[0]
        return self._window

    @staticmethod
    def _matches(title: str, profile: TerminalProfile) -> bool:
        normalized = title.lower()
        words = [word for word in re.split(r"[^a-z0-9]+", profile.instance_name.lower()) if word]
        return "terminal64" not in normalized and all(word in normalized for word in words)

    @property
    def root(self) -> Any:
        if self._window is None:
            raise AutomationError("MT5 window is not connected")
        return self._window

    @property
    def title(self) -> str:
        if self._window is None:
            raise AutomationError("MT5 window is not connected")
        return str(self._window.window_text())

    def contains_symbol(self, symbol: str) -> bool:
        match = re.search(r"\[([A-Za-z0-9._#]+),", self.title)
        return match is not None and match.group(1).upper() == symbol.upper()

    def open_order_dialog(self, timeout_seconds: float = 5.0) -> Any:
        if self._order_dialog is not None:
            return self._order_dialog
        if self._window is None:
            raise AutomationError("MT5 window is not connected")
        menu_items = [
            control
            for control in self._window.descendants()
            if control.element_info.control_type == "MenuItem"
            and control.window_text() == "New Order"
        ]
        if not menu_items:
            raise AutomationError("New Order control was not found")
        menu_item = menu_items[0]
        invoke = getattr(menu_item, "invoke", None)
        if callable(invoke):
            invoke()
        else:
            menu_item.click_input()
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            dialogs = [
                control
                for control in self._window.descendants()
                if control.element_info.control_type == "Window"
                and control.window_text().startswith("Order:")
            ]
            if dialogs:
                self._order_dialog = dialogs[0]
                return self._order_dialog
            time.sleep(0.1)
        raise AutomationError("MT5 order dialog did not become ready")

    def close_order_dialog(self, timeout_seconds: float = 5.0) -> None:
        if self._order_dialog is None:
            return
        close_buttons = [
            control
            for control in self._order_dialog.descendants()
            if control.element_info.control_type == "Button"
            and control.window_text() == "Close"
        ]
        if not close_buttons:
            raise AutomationError("order dialog close control was not found")
        close_buttons[-1].click_input()
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if not self._is_order_dialog_open():
                self._order_dialog = None
                return
            time.sleep(0.1)
        raise AutomationError("order dialog did not close")

    def select_market_execution(self) -> None:
        dialog = self.open_order_dialog()
        buttons = [
            control
            for control in dialog.descendants()
            if control.element_info.control_type == "Button"
            and control.window_text() == "Market Execution"
        ]
        if not buttons:
            raise AutomationError("Market Execution control was not found")
        buttons[0].click_input()

    def set_field(self, automation_id: str, value: str) -> None:
        dialog = self.open_order_dialog()
        control = self._find_edit(dialog, automation_id)
        try:
            control.set_edit_text(value)
        except AttributeError as exc:
            raise AutomationError(f"field {automation_id} is not editable") from exc

    def read_field(self, automation_id: str) -> str:
        dialog = self.open_order_dialog()
        control = self._find_edit(dialog, automation_id)
        try:
            return str(control.get_value()).strip()
        except AttributeError as exc:
            raise AutomationError(f"field {automation_id} cannot be read") from exc

    @staticmethod
    def _find_edit(dialog: Any, automation_id: str) -> Any:
        for control in dialog.descendants():
            if (
                control.element_info.control_type == "Edit"
                and control.element_info.automation_id == automation_id
            ):
                return control
        raise AutomationError(f"order field {automation_id} was not found")

    def _is_order_dialog_open(self) -> bool:
        if self._window is None:
            return False
        return any(
            control.element_info.control_type == "Window"
            and control.window_text().startswith("Order:")
            for control in self._window.descendants()
        )


class MT5DesktopAdapter:
    def __init__(
        self,
        profile: TerminalProfile,
        window_manager: MT5WindowManager | None = None,
    ) -> None:
        self.profile = profile
        self.window_manager = window_manager or MT5WindowManager()
        from .positions import MT5PositionSnapshotProvider

        self.position_provider = MT5PositionSnapshotProvider(self.window_manager)
        self.connected = False
        self.selected_symbol: str | None = None
        self.prepared: OrderRequest | None = None

    def connect(self) -> AccountSnapshot:
        WindowsTerminalDiscovery().discover(self.profile)
        self.window_manager.find(self.profile)
        title = self.window_manager.title
        if "demo" not in title.lower():
            raise AutomationError("configured MT5 window is not identified as a demo account")
        self.connected = True
        return AccountSnapshot(AccountType.DEMO, connected=True)

    def get_terminal_state(self) -> str:
        return "CONNECTED_DEMO" if self.connected else "DISCONNECTED"

    def select_symbol(self, symbol: str) -> None:
        if not self.connected:
            raise AutomationError("MT5 terminal is not connected")
        self.window_manager.open_order_dialog()
        self.window_manager.set_field("10325", symbol.upper())
        if not self.window_manager.read_field("10325").upper().startswith(symbol.upper()):
            raise AutomationError(f"symbol field did not accept {symbol}")
        self.selected_symbol = symbol.upper()

    def prepare_order(self, request: OrderRequest) -> None:
        if self.selected_symbol != request.symbol:
            raise AutomationError("symbol was not selected")
        try:
            self.window_manager.select_market_execution()
            self.window_manager.set_field("10333", self._format_decimal(request.volume))
            if request.stop_loss is not None:
                self.window_manager.set_field("10334", self._format_decimal(request.stop_loss))
            if request.take_profit is not None:
                self.window_manager.set_field("10336", self._format_decimal(request.take_profit))
            if request.signal.comment:
                self.window_manager.set_field("1001", request.signal.comment)
            if self.window_manager.read_field("10333") != self._format_decimal(request.volume):
                raise AutomationError("volume field did not accept the request")
            self.prepared = request
        finally:
            self.window_manager.close_order_dialog()

    @staticmethod
    def _format_decimal(value: Decimal) -> str:
        return format(value, "f")

    def capture_positions(self) -> tuple[PositionSnapshot, ...]:
        if not self.connected:
            raise AutomationError("MT5 terminal is not connected")
        return self.position_provider.positions()

    def execute_order(self, request: OrderRequest) -> ExecutionResult:
        raise AutomationError("real MT5 execution is not enabled; final controls are blocked")

    def verify_execution(self, request: OrderRequest) -> ExecutionResult:
        raise AutomationError("real MT5 verification is not implemented")

    def close_position(self, position_id: str) -> ExecutionResult:
        raise AutomationError("real MT5 position closing is not implemented")
