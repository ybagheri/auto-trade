from __future__ import annotations

import importlib
import re
from typing import Any

from ...domain.enums import AccountType
from ...domain.exceptions import AutomationError
from ...domain.models import AccountSnapshot, ExecutionResult, OrderRequest, TerminalProfile
from ..terminal.discovery import WindowsTerminalDiscovery


class MT5WindowManager:
    def __init__(self) -> None:
        self._window: Any | None = None

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
    def title(self) -> str:
        if self._window is None:
            raise AutomationError("MT5 window is not connected")
        return str(self._window.window_text())

    def contains_symbol(self, symbol: str) -> bool:
        match = re.search(r"\[([A-Za-z0-9._#]+),", self.title)
        return match is not None and match.group(1).upper() == symbol.upper()


class MT5DesktopAdapter:
    def __init__(
        self,
        profile: TerminalProfile,
        window_manager: MT5WindowManager | None = None,
    ) -> None:
        self.profile = profile
        self.window_manager = window_manager or MT5WindowManager()
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
        if not self.window_manager.contains_symbol(symbol):
            raise AutomationError(f"symbol is not visible in the active MT5 chart: {symbol}")
        self.selected_symbol = symbol.upper()

    def prepare_order(self, request: OrderRequest) -> None:
        if self.selected_symbol != request.symbol:
            raise AutomationError("symbol was not selected")
        self.prepared = request

    def execute_order(self, request: OrderRequest) -> ExecutionResult:
        raise AutomationError("real MT5 execution is not enabled; final controls are blocked")

    def verify_execution(self, request: OrderRequest) -> ExecutionResult:
        raise AutomationError("real MT5 verification is not implemented")

    def close_position(self, position_id: str) -> ExecutionResult:
        raise AutomationError("real MT5 position closing is not implemented")
