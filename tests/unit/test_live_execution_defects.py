"""The three defects a real demo order exposed on 2026-09-28.

A guarded BUY was clicked on Alpari MT5 6184, the broker filled it, and the
application still reported UNKNOWN. Each test below reproduces one cause, so the
behaviour that was wrong cannot come back unnoticed.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

import pytest

from auto_trade.application.workflow import ExecutionWorkflow
from auto_trade.domain.enums import AccountType, ExecutionState, ExecutionStatus
from auto_trade.domain.exceptions import (
    AutomationError,
    PositionSnapshotUnavailable,
)
from auto_trade.domain.models import (
    AccountSnapshot,
    AuditEvent,
    ExecutionPolicy,
    OrderRequest,
    PositionSnapshot,
    RiskLimits,
    TerminalProfile,
    TradeSignal,
)
from auto_trade.domain.protocols import KillSwitch
from auto_trade.infrastructure.automation import MT5DesktopAdapter, MT5WindowManager
from auto_trade.infrastructure.automation import window_manager as window_manager_module
from auto_trade.infrastructure.automation.execution import (
    BUY_BUTTON_ID,
    BUY_BUTTON_NAME,
    ExecutionGate,
    wait_for_dialog_to_close,
)

from ..helpers import signal_data

OPEN_GATE = ExecutionGate(enabled=True, dry_run=False, demo_only=True, kill_switch_active=False)


class ElementGone(Exception):
    """Stands in for the pywinauto error raised once MT5 destroys an element."""


@pytest.fixture(autouse=True)
def element_gone_is_recognised(monkeypatch: pytest.MonkeyPatch) -> None:
    """Teach the window manager this test's error, the way pywinauto's is taught.

    The manager resolves those exception classes at runtime precisely so the
    automation extras stay optional, which also makes them substitutable.
    """
    monkeypatch.setattr(
        window_manager_module, "_element_gone", lambda: (ElementGone,), raising=True
    )


class DestroyedDialog:
    """An order dialog that MT5 closed itself the moment the order was sent."""

    def descendants(self) -> list[Any]:
        raise ElementGone("element is gone")


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


class Dialog:
    def __init__(self, buttons: list[FakeButton]) -> None:
        self._buttons = buttons

    def descendants(self) -> list[FakeButton]:
        return self._buttons


class SelfClosingManager(MT5WindowManager):
    """Clicks the final control and then loses the dialog, exactly like MT5."""

    def __init__(self, fields: dict[str, str]) -> None:
        super().__init__()
        self.fields = fields
        self.button = FakeButton(BUY_BUTTON_NAME, BUY_BUTTON_ID)
        self.dialog = Dialog([self.button])

    def open_order_dialog(self, timeout_seconds: float = 5.0) -> Any:
        return self.dialog

    def read_field(self, automation_id: str) -> str:
        return self.fields[automation_id]

    def close_order_dialog(self, timeout_seconds: float = 5.0) -> None:
        # The click destroys the dialog; the next read of it must not explode.
        if self.button.clicks:
            self._order_dialog = DestroyedDialog()
            return
        self._order_dialog = self.dialog

    def _is_order_dialog_open(self) -> bool:
        return self._order_dialog is not self.dialog


def fields() -> dict[str, str]:
    return {"10325": "EURUSD", "10333": "0.01", "10334": "0.00", "10336": "0.00"}


def request() -> OrderRequest:
    data = signal_data() | {"symbol": "EURUSD", "action": "BUY", "volume": 0.01}
    return OrderRequest(TradeSignal.from_dict(data))


def position(ticket: str = "555") -> PositionSnapshot:
    return PositionSnapshot(ticket, "EURUSD", "BUY", Decimal("0.01"))


class FlakyProvider:
    """Fails the reads that happen while the terminal is busy, then succeeds.

    The real indicator rewrites its snapshot twice a second, so a read right
    after the click can land on a file that is being written.
    """

    def __init__(self, *failures: int) -> None:
        self.failures = list(failures)
        self.reads: list[tuple[PositionSnapshot, ...]] = []

    def positions(self) -> tuple[PositionSnapshot, ...]:
        if self.failures and self.failures.pop(0):
            raise PositionSnapshotUnavailable(
                "position snapshot is not readable JSON: auto_trade_positions_b.json"
            )
        current = self.reads[-1] if self.reads else ()
        return current


def adapter_for(provider: FlakyProvider, timeout: float = 2.0) -> MT5DesktopAdapter:
    manager = SelfClosingManager(fields())
    adapter = MT5DesktopAdapter(
        TerminalProfile("alpari-demo", "terminal64.exe", "data", "Alpari-MT5-Demo"),
        manager,
        position_provider=provider,
        gate=OPEN_GATE,
    )
    adapter.connected = True
    adapter.verification_timeout_seconds = timeout
    adapter._baseline = ()
    return adapter


# -- 1: the dialog MT5 destroys is a closed dialog, not a crash ----------


def test_a_click_is_reported_as_requested_even_when_the_dialog_disappears() -> None:
    """This is the exact 2026-09-28 sequence: the click lands, then MT5 closes it."""
    adapter = adapter_for(FlakyProvider())

    result = adapter.execute_order(request())

    assert result.status is ExecutionStatus.REQUESTED
    assert wait_for_dialog_to_close(adapter.window_manager, timeout_seconds=1.0)


def test_close_order_dialog_treats_a_destroyed_dialog_as_closed() -> None:
    manager = SelfClosingManager(fields())
    manager._order_dialog = DestroyedDialog()

    # The real implementation, not the fake this test's manager overrides.
    MT5WindowManager.close_order_dialog(manager)

    assert manager._order_dialog is None


def test_open_order_dialog_does_not_reuse_a_destroyed_dialog() -> None:
    manager = MT5WindowManager()
    manager._order_dialog = DestroyedDialog()

    with pytest.raises(AutomationError, match="not connected"):
        # The cached dialog is dropped, so a fresh open is attempted and fails
        # honestly instead of reading a dead element.
        manager.open_order_dialog(timeout_seconds=0.2)


def test_window_manager_reads_fail_loudly_when_the_window_is_gone() -> None:
    class Gone:
        def window_text(self) -> str:
            raise ElementGone("gone")

        def descendants(self) -> list[Any]:
            raise ElementGone("gone")

    manager = MT5WindowManager()
    manager._window = Gone()

    with pytest.raises(AutomationError, match="no longer exists"):
        _ = manager.title


# -- 2: one unreadable snapshot is not a failed verification -------------


def test_verification_survives_a_snapshot_that_is_being_rewritten() -> None:
    provider = FlakyProvider(1, 0)
    adapter = adapter_for(provider)
    provider.reads.append((position(),))

    result = adapter.verify_execution(request())

    assert result.status is ExecutionStatus.ACCEPTED
    assert result.order_reference == "555"


def test_verification_still_fails_closed_when_every_read_fails() -> None:
    provider = FlakyProvider(1, 1, 1, 1, 1, 1)
    adapter = adapter_for(provider, timeout=0.3)
    provider.reads.append((position(),))

    result = adapter.verify_execution(request())

    assert result.status is ExecutionStatus.UNKNOWN
    assert "unavailable" in result.message
    assert result.order_reference is None


def test_verification_reports_the_last_observation_error() -> None:
    provider = FlakyProvider(1, 1)
    adapter = adapter_for(provider, timeout=0.1)

    result = adapter.verify_execution(request())

    assert "not readable JSON" in result.message


# -- 3: an unknown outcome names its cause ------------------------------


class RaisingAdapter:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.result_status = ExecutionStatus.REQUESTED

    def connect(self) -> AccountSnapshot:
        return AccountSnapshot(AccountType.DEMO, connected=True)

    def get_terminal_state(self) -> str:
        return "CONNECTED_DEMO"

    def select_symbol(self, symbol: str) -> None:
        return

    def prepare_order(self, order: OrderRequest) -> None:
        return

    def execute_order(self, order: OrderRequest) -> Any:
        raise self.error

    def verify_execution(self, order: OrderRequest) -> Any:
        raise AssertionError("verification must not run after an unknown click")

    def close_position(self, position_id: str) -> Any:
        raise AssertionError("not used")


def workflow_for(adapter: Any) -> tuple[ExecutionWorkflow, list[AuditEvent]]:
    events: list[AuditEvent] = []
    workflow = ExecutionWorkflow(
        adapter=adapter,
        risk_engine=_risk(),
        profile=TerminalProfile("alpari-demo", "terminal64.exe", "data", "demo"),
        policy=ExecutionPolicy(dry_run=False, demo_only=True, execution_enabled=True),
        kill_switch=KillSwitch(),
        audit=events.append,
    )
    return workflow, events


def _risk() -> Any:
    from auto_trade.application.risk import RiskEngine

    return RiskEngine(RiskLimits(frozenset({"EURUSD"}), Decimal("0.10"), 5, 300))


def test_unknown_outcome_names_the_cause_and_never_claims_success() -> None:
    workflow, _ = workflow_for(RaisingAdapter(ElementGone("element is gone")))

    result = workflow.execute(request().signal)

    assert result.status is ExecutionStatus.UNKNOWN
    assert result.state == ExecutionState.UNKNOWN_EXECUTION.value
    assert "ElementGone" in result.message
    assert "element is gone" in result.message
    assert result.order_reference is None


def test_unknown_outcome_keeps_the_audit_reason() -> None:
    workflow, events = workflow_for(RaisingAdapter(RuntimeError("COM failure")))

    workflow.execute(request().signal)

    results = [event for event in events if event.event_type == "result"]
    assert results
    assert "COM failure" in results[-1].message
    assert "COM failure" in (results[-1].error or "")


def test_verification_is_not_reached_after_an_unknown_click() -> None:
    """The observation must never be skipped, and never be asserted either."""
    adapter = RaisingAdapter(AutomationError("dialog is gone"))
    workflow, _ = workflow_for(adapter)

    result = workflow.execute(request().signal)

    assert result.status is ExecutionStatus.UNKNOWN
    assert result.evidence is None


def test_a_slow_but_successful_observation_is_not_cut_short() -> None:
    provider = FlakyProvider(1, 0)
    adapter = adapter_for(provider, timeout=1.0)
    provider.reads.append((position(),))
    started = time.monotonic()

    result = adapter.verify_execution(request())

    assert result.status is ExecutionStatus.ACCEPTED
    assert time.monotonic() - started < 1.0
