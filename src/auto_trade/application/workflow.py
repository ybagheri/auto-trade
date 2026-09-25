from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from ..domain.enums import AccountType, ExecutionState, ExecutionStatus
from ..domain.exceptions import (
    AutomationError,
    AutomationRejectedError,
    AutomationTimeoutError,
    ExecutionUnknownError,
    SafetyViolation,
    TerminalNotFoundError,
)
from ..domain.models import (
    AccountSnapshot,
    AuditEvent,
    ExecutionPolicy,
    ExecutionResult,
    OrderRequest,
    TerminalProfile,
    TradeSignal,
)
from ..domain.protocols import KillSwitch, TradingTerminalAdapter
from .ledger import ExecutionLedger
from .risk import RiskEngine
from .state_machine import ExecutionStateMachine


class ExecutionWorkflow:
    def __init__(
        self,
        adapter: TradingTerminalAdapter,
        risk_engine: RiskEngine,
        profile: TerminalProfile,
        policy: ExecutionPolicy,
        kill_switch: KillSwitch,
        audit: Callable[[AuditEvent], None],
        now: Callable[[], datetime] | None = None,
        ledger: ExecutionLedger | None = None,
    ) -> None:
        self.adapter = adapter
        self.risk_engine = risk_engine
        self.profile = profile
        self.policy = policy
        self.kill_switch = kill_switch
        self.audit = audit
        self.now = now or (lambda: datetime.now(UTC))
        self.ledger = ledger
        self.seen_signal_ids: set[str] = set()
        self.recent_executions: list[datetime] = []

    def execute(self, signal: TradeSignal) -> ExecutionResult:
        execution_id = str(uuid4())
        machine = ExecutionStateMachine(
            lambda state: self._record(execution_id, signal, "state", state.value)
        )
        self._record(execution_id, signal, "received", "signal received")
        try:
            machine.transition(ExecutionState.SIGNAL_RECEIVED)
            machine.transition(ExecutionState.VALIDATING)
            account = self._account_for_validation()
            decision = self.risk_engine.validate(
                signal,
                account=account,
                seen_signal_ids=(
                    {signal.signal_id}
                    if self.ledger is not None and self.ledger.contains(signal.signal_id)
                    else self.seen_signal_ids
                ),
                recent_executions=self.recent_executions,
                now=self.now(),
            )
            if not decision.accepted:
                machine.transition(ExecutionState.INVALID_SIGNAL)
                return self._result(
                    execution_id,
                    signal,
                    ExecutionStatus.REJECTED,
                    ExecutionState.INVALID_SIGNAL,
                    decision.reason,
                )
            if self.kill_switch.active:
                raise SafetyViolation("kill switch is active")
            if self.policy.demo_only and (
                account is None or account.account_type is not AccountType.DEMO
            ):
                raise SafetyViolation("demo-only policy rejected an unverified account")
            machine.transition(ExecutionState.VALIDATED)
            machine.transition(ExecutionState.LOCATING_TERMINAL)
            machine.transition(ExecutionState.PREPARING_UI)
            self.adapter.select_symbol(signal.symbol)
            request = OrderRequest(signal)
            self.adapter.prepare_order(request)
            machine.transition(ExecutionState.ORDER_READY)
            self.seen_signal_ids.add(signal.signal_id)
            self.recent_executions.append(self.now())
            if self.policy.dry_run:
                machine.transition(ExecutionState.DRY_RUN_COMPLETED)
                return self._result(
                    execution_id,
                    signal,
                    ExecutionStatus.DRY_RUN,
                    ExecutionState.DRY_RUN_COMPLETED,
                    "validated; final execution control not used",
                )
            if self.ledger is not None:
                self.ledger.record_attempt(signal.signal_id, execution_id)
            machine.transition(ExecutionState.EXECUTING)
            try:
                adapter_result = self.adapter.execute_order(request)
            except Exception as exc:
                machine.transition(ExecutionState.UNKNOWN_EXECUTION)
                raise ExecutionUnknownError("execution outcome is unknown") from exc
            if adapter_result.status is ExecutionStatus.REJECTED:
                machine.transition(ExecutionState.ORDER_REJECTED)
                return self._result(
                    execution_id,
                    signal,
                    ExecutionStatus.REJECTED,
                    ExecutionState.ORDER_REJECTED,
                    adapter_result.message,
                )
            machine.transition(ExecutionState.EXECUTION_DETECTED)
            machine.transition(ExecutionState.VERIFYING)
            verified = self.adapter.verify_execution(request)
            if verified.status is not ExecutionStatus.ACCEPTED:
                machine.transition(ExecutionState.VERIFICATION_FAILED)
                return self._result(
                    execution_id,
                    signal,
                    ExecutionStatus.UNKNOWN,
                    ExecutionState.VERIFICATION_FAILED,
                    verified.message,
                )
            machine.transition(ExecutionState.SUCCESS)
            return self._result(
                execution_id,
                signal,
                ExecutionStatus.ACCEPTED,
                ExecutionState.SUCCESS,
                verified.message,
                verified.order_reference,
            )
        except SafetyViolation as exc:
            if machine.state is ExecutionState.VALIDATING:
                machine.transition(ExecutionState.INVALID_SIGNAL)
            return self._result(
                execution_id,
                signal,
                ExecutionStatus.REJECTED,
                ExecutionState.INVALID_SIGNAL,
                str(exc),
            )
        except TerminalNotFoundError as exc:
            if machine.state is ExecutionState.PREPARING_UI:
                machine.transition(ExecutionState.TERMINAL_NOT_FOUND)
            return self._result(
                execution_id,
                signal,
                ExecutionStatus.REJECTED,
                ExecutionState.TERMINAL_NOT_FOUND,
                str(exc),
            )
        except AutomationTimeoutError as exc:
            if machine.state in {
                ExecutionState.PREPARING_UI,
                ExecutionState.EXECUTING,
            }:
                machine.transition(ExecutionState.TIMEOUT)
            return self._result(
                execution_id,
                signal,
                ExecutionStatus.REJECTED,
                ExecutionState.TIMEOUT,
                str(exc),
            )
        except AutomationRejectedError as exc:
            if machine.state in {
                ExecutionState.PREPARING_UI,
                ExecutionState.EXECUTING,
            }:
                machine.transition(ExecutionState.ORDER_REJECTED)
            return self._result(
                execution_id,
                signal,
                ExecutionStatus.REJECTED,
                ExecutionState.ORDER_REJECTED,
                str(exc),
            )
        except AutomationError as exc:
            if machine.state in {
                ExecutionState.PREPARING_UI,
                ExecutionState.EXECUTING,
            }:
                machine.transition(ExecutionState.UNKNOWN_EXECUTION)
            return self._result(
                execution_id,
                signal,
                ExecutionStatus.UNKNOWN,
                ExecutionState.UNKNOWN_EXECUTION,
                str(exc),
            )
        except Exception as exc:
            self._record(execution_id, signal, "error", str(exc), error=str(exc))
            return self._result(
                execution_id,
                signal,
                ExecutionStatus.UNKNOWN,
                ExecutionState.UNKNOWN_STATE,
                str(exc),
                error=str(exc),
            )

    def _account_for_validation(self) -> AccountSnapshot | None:
        try:
            return self.adapter.connect()
        except AutomationError:
            return None

    def _record(
        self,
        execution_id: str,
        signal: TradeSignal,
        event_type: str,
        message: str,
        state: str | None = None,
        error: str | None = None,
    ) -> None:
        self.audit(
            AuditEvent(
                component="execution",
                event_type=event_type,
                message=message,
                signal_id=signal.signal_id,
                execution_id=execution_id,
                symbol=signal.symbol,
                action=signal.action.value,
                volume=signal.volume,
                state=state,
                error=error,
            )
        )

    def _result(
        self,
        execution_id: str,
        signal: TradeSignal,
        status: ExecutionStatus,
        state: ExecutionState,
        message: str,
        order_reference: str | None = None,
        error: str | None = None,
    ) -> ExecutionResult:
        result = ExecutionResult(
            execution_id,
            signal.signal_id,
            status,
            state.value,
            message,
            order_reference,
            error,
        )
        if self.ledger is not None:
            self.ledger.record_result(result)
        self._record(execution_id, signal, "result", message, state.value, error)
        return result
