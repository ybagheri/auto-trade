from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .models import (
    AccountSnapshot,
    AuditEvent,
    ExecutionResult,
    OrderRequest,
    TerminalProfile,
    TradeSignal,
)


class SignalProvider(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def receive(self) -> TradeSignal: ...


class TradingTerminalAdapter(Protocol):
    def connect(self) -> AccountSnapshot: ...

    def get_terminal_state(self) -> str: ...

    def select_symbol(self, symbol: str) -> None: ...

    def prepare_order(self, request: OrderRequest) -> None: ...

    def execute_order(self, request: OrderRequest) -> ExecutionResult: ...

    def verify_execution(self, request: OrderRequest) -> ExecutionResult: ...

    def close_position(self, position_id: str) -> ExecutionResult: ...


class AuditSink(Protocol):
    def record(self, event: AuditEvent) -> None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class TerminalDiscovery(Protocol):
    def discover(self, profile: TerminalProfile) -> TerminalProfile: ...


class RiskDecision:
    def __init__(self, accepted: bool, reason: str = "") -> None:
        self.accepted = accepted
        self.reason = reason


class KillSwitch:
    def __init__(self) -> None:
        self._active = False

    def activate(self) -> None:
        self._active = True

    def reset(self) -> None:
        self._active = False

    @property
    def active(self) -> bool:
        return self._active
