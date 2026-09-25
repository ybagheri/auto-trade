from __future__ import annotations

from decimal import Decimal

from auto_trade.adapters.terminal import DryRunTerminalAdapter
from auto_trade.application.risk import RiskEngine
from auto_trade.application.state_machine import ExecutionStateMachine
from auto_trade.application.workflow import ExecutionWorkflow
from auto_trade.domain.enums import ExecutionState, ExecutionStatus
from auto_trade.domain.exceptions import AutomationRejectedError, AutomationTimeoutError
from auto_trade.domain.models import AuditEvent, ExecutionPolicy, RiskLimits, TradeSignal
from auto_trade.domain.protocols import KillSwitch

from ..helpers import signal_data


def limits() -> RiskLimits:
    return RiskLimits({"EURUSD"}, Decimal("0.10"), 5, 10)


class TimeoutAdapter(DryRunTerminalAdapter):
    def select_symbol(self, symbol: str) -> None:
        raise AutomationTimeoutError("symbol lookup timed out")


class RejectedAdapter(DryRunTerminalAdapter):
    def select_symbol(self, symbol: str) -> None:
        raise AutomationRejectedError("broker rejected the request")


def test_state_machine_rejects_invalid_transition() -> None:
    machine = ExecutionStateMachine()
    try:
        machine.transition(ExecutionState.SUCCESS)
    except ValueError as exc:
        assert "invalid transition" in str(exc)
    else:
        raise AssertionError("invalid transition was accepted")


def test_dry_run_workflow_never_executes() -> None:
    adapter = DryRunTerminalAdapter()
    events: list[AuditEvent] = []
    workflow = ExecutionWorkflow(
        adapter=adapter,
        risk_engine=RiskEngine(limits()),
        profile=type("Profile", (), {})(),
        policy=ExecutionPolicy(dry_run=True),
        kill_switch=KillSwitch(),
        audit=events.append,
    )
    result = workflow.execute(TradeSignal.from_dict(signal_data()))
    assert result.status is ExecutionStatus.DRY_RUN
    assert result.state == ExecutionState.DRY_RUN_COMPLETED.value
    assert adapter.prepared is not None
    assert not any(event.event_type == "order_clicked" for event in events)


def test_kill_switch_rejects_execution() -> None:
    switch = KillSwitch()
    switch.activate()
    workflow = ExecutionWorkflow(
        adapter=DryRunTerminalAdapter(),
        risk_engine=RiskEngine(limits()),
        profile=type("Profile", (), {})(),
        policy=ExecutionPolicy(dry_run=False),
        kill_switch=switch,
        audit=lambda event: None,
    )
    result = workflow.execute(TradeSignal.from_dict(signal_data()))
    assert result.status is ExecutionStatus.REJECTED
    assert "kill switch" in result.message


def test_duplicate_signal_is_not_repeated() -> None:
    workflow = ExecutionWorkflow(
        adapter=DryRunTerminalAdapter(),
        risk_engine=RiskEngine(limits()),
        profile=type("Profile", (), {})(),
        policy=ExecutionPolicy(dry_run=True),
        kill_switch=KillSwitch(),
        audit=lambda event: None,
    )
    signal = TradeSignal.from_dict(signal_data())
    assert workflow.execute(signal).status is ExecutionStatus.DRY_RUN
    assert workflow.execute(signal).status is ExecutionStatus.REJECTED


def test_timeout_is_classified_without_success() -> None:
    workflow = ExecutionWorkflow(
        adapter=TimeoutAdapter(),
        risk_engine=RiskEngine(limits()),
        profile=type("Profile", (), {})(),
        policy=ExecutionPolicy(dry_run=True),
        kill_switch=KillSwitch(),
        audit=lambda event: None,
    )
    result = workflow.execute(TradeSignal.from_dict(signal_data()))
    assert result.status is ExecutionStatus.REJECTED
    assert result.state == ExecutionState.TIMEOUT.value


def test_rejection_is_classified_without_success() -> None:
    workflow = ExecutionWorkflow(
        adapter=RejectedAdapter(),
        risk_engine=RiskEngine(limits()),
        profile=type("Profile", (), {})(),
        policy=ExecutionPolicy(dry_run=True),
        kill_switch=KillSwitch(),
        audit=lambda event: None,
    )
    result = workflow.execute(TradeSignal.from_dict(signal_data()))
    assert result.status is ExecutionStatus.REJECTED
    assert result.state == ExecutionState.ORDER_REJECTED.value
