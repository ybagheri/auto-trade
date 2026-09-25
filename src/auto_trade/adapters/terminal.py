from __future__ import annotations

from ..domain.enums import AccountType
from ..domain.exceptions import AutomationError
from ..domain.models import AccountSnapshot, ExecutionResult, OrderRequest


class DryRunTerminalAdapter:
    def __init__(self) -> None:
        self.connected = False
        self.selected_symbol: str | None = None
        self.prepared: OrderRequest | None = None

    def connect(self) -> AccountSnapshot:
        self.connected = True
        return AccountSnapshot(AccountType.DEMO, connected=True)

    def get_terminal_state(self) -> str:
        return "DRY_RUN_CONNECTED" if self.connected else "DISCONNECTED"

    def select_symbol(self, symbol: str) -> None:
        if not self.connected:
            raise AutomationError("terminal is not connected")
        self.selected_symbol = symbol.upper()

    def prepare_order(self, request: OrderRequest) -> None:
        if self.selected_symbol != request.symbol:
            raise AutomationError("symbol was not selected")
        self.prepared = request

    def execute_order(self, request: OrderRequest) -> ExecutionResult:
        raise AutomationError("dry-run adapter must never execute an order")

    def verify_execution(self, request: OrderRequest) -> ExecutionResult:
        raise AutomationError("dry-run adapter has no broker execution to verify")

    def close_position(self, position_id: str) -> ExecutionResult:
        raise AutomationError("dry-run adapter cannot close positions")


class UnavailableMT5DesktopAdapter:
    def connect(self) -> AccountSnapshot:
        raise AutomationError("real MT5 desktop execution is not enabled in this phase")

    def get_terminal_state(self) -> str:
        return "UNAVAILABLE"

    def select_symbol(self, symbol: str) -> None:
        raise AutomationError("real MT5 desktop execution is not enabled in this phase")

    def prepare_order(self, request: OrderRequest) -> None:
        raise AutomationError("real MT5 desktop execution is not enabled in this phase")

    def execute_order(self, request: OrderRequest) -> ExecutionResult:
        raise AutomationError("real MT5 desktop execution is not enabled in this phase")

    def verify_execution(self, request: OrderRequest) -> ExecutionResult:
        raise AutomationError("real MT5 desktop execution is not enabled in this phase")

    def close_position(self, position_id: str) -> ExecutionResult:
        raise AutomationError("real MT5 desktop execution is not enabled in this phase")
