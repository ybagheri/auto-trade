from __future__ import annotations

from collections.abc import Callable

from ..domain.enums import ExecutionState

_TRANSITIONS: dict[ExecutionState, frozenset[ExecutionState]] = {
    ExecutionState.IDLE: frozenset({ExecutionState.SIGNAL_RECEIVED}),
    ExecutionState.SIGNAL_RECEIVED: frozenset(
        {ExecutionState.VALIDATING, ExecutionState.INVALID_SIGNAL}
    ),
    ExecutionState.VALIDATING: frozenset(
        {ExecutionState.VALIDATED, ExecutionState.INVALID_SIGNAL}
    ),
    ExecutionState.VALIDATED: frozenset({ExecutionState.LOCATING_TERMINAL}),
    ExecutionState.LOCATING_TERMINAL: frozenset(
        {ExecutionState.PREPARING_UI, ExecutionState.TERMINAL_NOT_FOUND}
    ),
    ExecutionState.PREPARING_UI: frozenset(
        {
            ExecutionState.ORDER_READY,
            ExecutionState.WINDOW_NOT_READY,
            ExecutionState.SYMBOL_NOT_FOUND,
            ExecutionState.UI_ELEMENT_NOT_FOUND,
            ExecutionState.TERMINAL_NOT_FOUND,
            ExecutionState.UNKNOWN_EXECUTION,
        }
    ),
    ExecutionState.ORDER_READY: frozenset(
        {ExecutionState.EXECUTING, ExecutionState.DRY_RUN_COMPLETED}
    ),
    ExecutionState.EXECUTING: frozenset(
        {
            ExecutionState.EXECUTION_DETECTED,
            ExecutionState.ORDER_REJECTED,
            ExecutionState.TIMEOUT,
            ExecutionState.UNKNOWN_EXECUTION,
        }
    ),
    ExecutionState.EXECUTION_DETECTED: frozenset(
        {ExecutionState.VERIFYING, ExecutionState.UNKNOWN_EXECUTION}
    ),
    ExecutionState.VERIFYING: frozenset(
        {ExecutionState.SUCCESS, ExecutionState.VERIFICATION_FAILED}
    ),
    ExecutionState.DRY_RUN_COMPLETED: frozenset({ExecutionState.IDLE}),
    ExecutionState.SUCCESS: frozenset({ExecutionState.IDLE}),
    ExecutionState.INVALID_SIGNAL: frozenset({ExecutionState.IDLE}),
    ExecutionState.TERMINAL_NOT_FOUND: frozenset({ExecutionState.IDLE}),
    ExecutionState.WINDOW_NOT_READY: frozenset({ExecutionState.IDLE}),
    ExecutionState.SYMBOL_NOT_FOUND: frozenset({ExecutionState.IDLE}),
    ExecutionState.UI_ELEMENT_NOT_FOUND: frozenset({ExecutionState.IDLE}),
    ExecutionState.ORDER_REJECTED: frozenset({ExecutionState.IDLE}),
    ExecutionState.TIMEOUT: frozenset({ExecutionState.IDLE}),
    ExecutionState.VERIFICATION_FAILED: frozenset({ExecutionState.IDLE}),
    ExecutionState.UNKNOWN_EXECUTION: frozenset(
        {ExecutionState.VERIFYING, ExecutionState.IDLE}
    ),
    ExecutionState.UNKNOWN_STATE: frozenset({ExecutionState.IDLE}),
}


class ExecutionStateMachine:
    def __init__(self, observer: Callable[[ExecutionState], None] | None = None) -> None:
        self.state = ExecutionState.IDLE
        self.observer = observer

    def transition(self, next_state: ExecutionState) -> None:
        if next_state not in _TRANSITIONS[self.state]:
            raise ValueError(f"invalid transition: {self.state.value} -> {next_state.value}")
        self.state = next_state
        if self.observer is not None:
            self.observer(next_state)

    def reset(self) -> None:
        if self.state not in _TRANSITIONS[ExecutionState.IDLE]:
            self.state = ExecutionState.IDLE
