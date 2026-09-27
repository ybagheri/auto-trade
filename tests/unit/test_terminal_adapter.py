from __future__ import annotations

from auto_trade.domain.enums import ExecutionStatus
from auto_trade.domain.models import OrderRequest, TerminalProfile, TradeSignal
from auto_trade.infrastructure.automation import MT5DesktopAdapter, MT5WindowManager

from ..helpers import signal_data


class FakeWindow:
    def window_text(self) -> str:
        return "123 - Alpari-MT5-Demo: Demo Account - [XAUUSD,M5]"


class FakeManager(MT5WindowManager):
    def find(self, profile: TerminalProfile) -> FakeWindow:
        self._window = FakeWindow()
        return self._window


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
