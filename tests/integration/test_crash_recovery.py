"""A crash between the click and the observation.

This is the one window in this project where a mistake costs money: the final
control has been used, the broker may already have filled the order, and the
process that would have recorded the proof is gone. `docs/STATUS.md` names this
as the untested case, so each test below reproduces a point inside the window
and pins what survives it, what is refused afterwards, and what only a person
may settle.

A crash is simulated with a ``BaseException`` subclass, not an ``Exception``.
Every error path in `ExecutionWorkflow` catches ``Exception``, so a real death
passes straight through all of them and writes no result. A simulated death that
were an ``Exception`` would be caught, reported as ``UNKNOWN_STATE``, and would
therefore test the opposite of what is being claimed here.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from auto_trade.application.ledger import RECONCILED, JsonExecutionLedger
from auto_trade.application.risk import RiskEngine
from auto_trade.application.workflow import ExecutionWorkflow
from auto_trade.cli import main
from auto_trade.domain.enums import AccountType, ExecutionState, ExecutionStatus
from auto_trade.domain.exceptions import PositionSnapshotUnavailable
from auto_trade.domain.models import (
    AccountSnapshot,
    AuditEvent,
    ExecutionPolicy,
    ExecutionResult,
    PositionSnapshot,
    RiskLimits,
    TerminalProfile,
    TradeSignal,
)
from auto_trade.domain.protocols import KillSwitch
from auto_trade.infrastructure.automation import MT5DesktopAdapter, MT5WindowManager
from auto_trade.infrastructure.automation.execution import (
    BUY_BUTTON_ID,
    BUY_BUTTON_NAME,
    STOP_LOSS_FIELD_ID,
    SYMBOL_FIELD_ID,
    TAKE_PROFIT_FIELD_ID,
    VOLUME_FIELD_ID,
    ExecutionGate,
)
from auto_trade.infrastructure.automation.positions_file import (
    MT5FilePositionSnapshotProvider,
)

from ..helpers import signal_data

CRASH_SIGNAL_ID = "signal-crash-1"
FILLED_TICKET = "382631622"


class ProcessDied(BaseException):
    """A killed process, which no `except Exception` in the workflow can see."""


# -- the order dialog, without a terminal behind it ---------------------


class FakeInfo:
    def __init__(self, control_type: str, automation_id: str = "") -> None:
        self.control_type = control_type
        self.automation_id = automation_id


class FakeButton:
    def __init__(self, name: str, automation_id: str) -> None:
        self._name = name
        self._info = FakeInfo("Button", automation_id)
        self.clicks = 0

    def window_text(self) -> str:
        return self._name

    @property
    def element_info(self) -> FakeInfo:
        return self._info

    def click_input(self) -> None:
        self.clicks += 1


class FakeEdit:
    def __init__(self, automation_id: str, value: str) -> None:
        self._info = FakeInfo("Edit", automation_id)
        self._value = value

    @property
    def element_info(self) -> FakeInfo:
        return self._info

    def get_value(self) -> str:
        return self._value

    def set_edit_text(self, value: str) -> None:
        self._value = value


class Dialog:
    def __init__(self, controls: list[Any]) -> None:
        self._controls = controls

    def descendants(self) -> list[Any]:
        return self._controls


class OrderDialogManager(MT5WindowManager):
    """The order dialog as the accessibility tree exposes it, with no terminal.

    Only the window lookup is missing, so every step from the gate to the click
    is the shipped code rather than a stand-in for it.
    """

    def __init__(self) -> None:
        super().__init__()
        self.buy = FakeButton(BUY_BUTTON_NAME, BUY_BUTTON_ID)
        self.fields = {
            SYMBOL_FIELD_ID: FakeEdit(SYMBOL_FIELD_ID, "EURUSD"),
            VOLUME_FIELD_ID: FakeEdit(VOLUME_FIELD_ID, "0.01"),
            STOP_LOSS_FIELD_ID: FakeEdit(STOP_LOSS_FIELD_ID, "0.00"),
            TAKE_PROFIT_FIELD_ID: FakeEdit(TAKE_PROFIT_FIELD_ID, "0.00"),
        }
        self.dialog = Dialog([self.buy, *self.fields.values()])

    def open_order_dialog(self, timeout_seconds: float = 5.0) -> Any:
        return self.dialog

    def read_field(self, automation_id: str) -> str:
        return self.fields[automation_id].get_value()

    def set_field(self, automation_id: str, value: str) -> None:
        self.fields[automation_id].set_edit_text(value)

    def select_market_execution(self) -> None:
        return

    def close_order_dialog(self, timeout_seconds: float = 5.0) -> None:
        return

    def _is_order_dialog_open(self) -> bool:
        return False


class DemoTerminalAdapter(MT5DesktopAdapter):
    """The shipped adapter with only the process discovery replaced.

    `connect` is the single method that needs a running MT5 process. Everything
    after it, including the gate, the click, and the observation loop, is the
    code that ships.
    """

    def connect(self) -> AccountSnapshot:
        self.connected = True
        return AccountSnapshot(AccountType.DEMO, connected=True)


class SnapshotReader:
    """Serves the baseline, then either the account or the end of the process.

    ``after=None`` kills the process on the first read that follows the click,
    which is the exact point a window is written about elsewhere.

    The account is now read twice before the click as well: once while the order
    is prepared, and once more immediately before the final control, which must
    agree with the first. The first three reads therefore all return the same
    empty baseline, and only a read that follows the click moves on.
    """

    PRE_CLICK_READS = 3

    def __init__(self, after: tuple[PositionSnapshot, ...] | None = None) -> None:
        self.after = after
        self.reads = 0

    def positions(self) -> tuple[PositionSnapshot, ...]:
        self.reads += 1
        if self.reads <= self.PRE_CLICK_READS:
            return ()
        if self.after is None:
            raise ProcessDied("the process was killed before the observation completed")
        return self.after


class LedgerDyingOnResult(JsonExecutionLedger):
    """Dies writing the result, after the outcome had already been proved."""

    def record_result(self, result: ExecutionResult) -> None:
        raise ProcessDied("the process was killed while writing the result")


# -- the run that crashes ----------------------------------------------


def signal() -> TradeSignal:
    data = signal_data(CRASH_SIGNAL_ID) | {"symbol": "EURUSD", "volume": 0.01}
    return TradeSignal.from_dict(data)


def filled() -> PositionSnapshot:
    return PositionSnapshot(FILLED_TICKET, "EURUSD", "BUY", Decimal("0.01"))


def adapter_for(reader: SnapshotReader) -> tuple[DemoTerminalAdapter, OrderDialogManager]:
    manager = OrderDialogManager()
    adapter = DemoTerminalAdapter(
        TerminalProfile("alpari-demo", "terminal64.exe", "data", "Alpari-MT5-Demo"),
        manager,
        position_provider=reader,
        gate=ExecutionGate(enabled=True, dry_run=False, demo_only=True),
    )
    adapter.verification_timeout_seconds = 0.5
    return adapter, manager


def workflow_for(
    adapter: MT5DesktopAdapter, ledger: JsonExecutionLedger, audit: Any
) -> ExecutionWorkflow:
    return ExecutionWorkflow(
        adapter=adapter,
        risk_engine=RiskEngine(RiskLimits(frozenset({"EURUSD"}), Decimal("0.10"), 5, 300)),
        profile=TerminalProfile("alpari-demo", "terminal64.exe", "data", "Alpari-MT5-Demo"),
        policy=ExecutionPolicy(dry_run=False, demo_only=True, execution_enabled=True),
        kill_switch=KillSwitch(),
        audit=audit,
        ledger=ledger,
    )


def crash(
    tmp_path: Path,
    reader: SnapshotReader,
    ledger_class: type[JsonExecutionLedger] = JsonExecutionLedger,
) -> tuple[OrderDialogManager, dict[str, Any], list[AuditEvent]]:
    """Run the guarded path until the process dies, and return what was left.

    The signal is the same one on every run, so a later run against the same
    ledger is a restart rather than a second signal.
    """
    ledger = ledger_class(tmp_path / "idempotency.json")
    events: list[AuditEvent] = []
    adapter, manager = adapter_for(reader)
    workflow = workflow_for(adapter, ledger, events.append)

    with pytest.raises(ProcessDied):
        workflow.execute(signal())

    return manager, json.loads((tmp_path / "idempotency.json").read_text(encoding="utf-8")), events


def test_a_crash_after_the_click_leaves_the_attempt_pending_on_disk(tmp_path: Path) -> None:
    manager, stored, _ = crash(tmp_path, SnapshotReader())

    # The click did land, so the account may have changed: the record on disk is
    # what tells the next process that this is possible.
    assert manager.buy.clicks == 1
    assert stored[CRASH_SIGNAL_ID]["status"] == "REQUESTED"
    assert stored[CRASH_SIGNAL_ID]["state"] == "EXECUTING"
    # Nothing was proved, so nothing may claim to be.
    assert "order_reference" not in stored[CRASH_SIGNAL_ID]


def test_the_audit_trail_stops_at_the_click_and_records_no_result(tmp_path: Path) -> None:
    """The trail ends inside the observation, which is where the process died.

    `VERIFYING` is the last state, and `EXECUTING` is in the trail before it, so
    the log shows a final control was used and then nothing more was established.
    """
    _, _, events = crash(tmp_path, SnapshotReader())

    states = [event.state for event in events if event.event_type == "state"]
    assert states[-1] == ExecutionState.VERIFYING.value
    assert ExecutionState.EXECUTING.value in states
    assert ExecutionState.SUCCESS.value not in states
    assert [event for event in events if event.event_type == "result"] == []


def test_a_proved_fill_is_never_recorded_as_accepted_if_the_process_dies_last(
    tmp_path: Path,
) -> None:
    """The position existed and was observed, but the result never reached disk.

    The alternative would be worse than losing the record: an `ACCEPTED` that was
    written before the crash was finished being written, or inferred from the
    observation afterwards. Neither happened, and neither may.
    """
    manager, stored, _ = crash(tmp_path, SnapshotReader(after=(filled(),)), LedgerDyingOnResult)

    assert manager.buy.clicks == 1
    assert stored[CRASH_SIGNAL_ID]["status"] == "REQUESTED"
    assert "ACCEPTED" not in json.dumps(stored)


def test_a_restarted_process_refuses_to_retry_a_crashed_signal(tmp_path: Path) -> None:
    """A crash must not become a second order on the next run."""
    first, _stored, _ = crash(tmp_path, SnapshotReader())
    assert first.buy.clicks == 1

    # A restart: a new ledger read from the same file, a new adapter, and the
    # same signal arriving again from the same source.
    reader = SnapshotReader(after=(filled(),))
    adapter, second = adapter_for(reader)
    events: list[AuditEvent] = []
    ledger = JsonExecutionLedger(tmp_path / "idempotency.json")

    result = workflow_for(adapter, ledger, events.append).execute(signal())

    assert result.status is ExecutionStatus.REJECTED
    assert result.state == ExecutionState.INVALID_SIGNAL.value
    assert result.message == "duplicate signal id"
    # Refused by the risk engine, before the terminal was ever touched.
    assert second.buy.clicks == 0
    assert first.buy.clicks == 1
    assert reader.reads == 0


def test_the_crashed_record_is_not_overwritten_by_the_refused_retry(tmp_path: Path) -> None:
    """The refused retry has a different execution id and may not replace it.

    If it could, the operator's `recovery` listing would show a clean refusal
    and the pending attempt would vanish, which is the one outcome that must
    never happen to a record nobody has looked at yet.
    """
    crash(tmp_path, SnapshotReader())
    reader = SnapshotReader(after=(filled(),))
    adapter, _ = adapter_for(reader)
    workflow = workflow_for(
        adapter, JsonExecutionLedger(tmp_path / "idempotency.json"), lambda event: None
    )

    workflow.execute(signal())

    recovered = JsonExecutionLedger(tmp_path / "idempotency.json")
    assert [record["signal_id"] for record in recovered.pending()] == [CRASH_SIGNAL_ID]
    assert recovered.pending()[0]["status"] == "REQUESTED"


def test_recovery_lists_a_crashed_attempt_for_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    crash(tmp_path, SnapshotReader())
    monkeypatch.setenv("AUTO_TRADE_LOG_DIR", str(tmp_path))

    assert main(["recovery"]) == 0

    review = json.loads(capsys.readouterr().out)
    assert [record["signal_id"] for record in review["pending"]] == [CRASH_SIGNAL_ID]
    # It is a click that was never proved, not a failure the application observed.
    assert review["unknown"] == []
    assert review["reconciled"] == []


def test_only_the_operator_settles_a_crashed_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A crash is not settled by a retry, and never by the application itself."""
    crash(tmp_path, SnapshotReader())
    monkeypatch.setenv("AUTO_TRADE_LOG_DIR", str(tmp_path))

    code = main(
        [
            "reconcile",
            CRASH_SIGNAL_ID,
            "--observed",
            f"position {FILLED_TICKET} is in the Trade tab, opened before the process died",
        ]
    )

    assert code == 0, capsys.readouterr().err
    record = json.loads(capsys.readouterr().out)
    assert record["status"] == RECONCILED
    assert record["state"] == "RECONCILED_BY_OPERATOR"
    # What the application actually knew is kept beside the operator's word.
    assert record["original_status"] == "REQUESTED"
    assert "not observed by this application" in record["message"]


def test_a_snapshot_from_before_a_terminal_restart_is_refused(tmp_path: Path) -> None:
    """The second half of a restart: the terminal comes back with stale evidence.

    The file the indicator wrote before the crash is a real file with a real
    timestamp, and an operator comparing a pending record against it would be
    reading the account as it was before the restart rather than as it is. It is
    refused instead, and the pending record keeps requiring review.
    """
    directory = tmp_path / "MQL5" / "Files"
    directory.mkdir(parents=True)
    written = datetime(2026, 9, 28, 9, 30, tzinfo=UTC)
    (directory / "auto_trade_positions_a.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "sequence": 41,
                "complete": True,
                "written_at": written.isoformat().replace("+00:00", "Z"),
                "account": 53145727,
                "server": "Alpari-MT5-Demo",
                "positions": [],
            }
        ),
        encoding="utf-8",
    )
    provider = MT5FilePositionSnapshotProvider(
        directory, clock=lambda: written + timedelta(minutes=23)
    )

    with pytest.raises(PositionSnapshotUnavailable, match="stale"):
        provider.positions()

    crashed = tmp_path / "crash"
    crashed.mkdir()
    crash(crashed, SnapshotReader())
    assert JsonExecutionLedger(crashed / "idempotency.json").pending()[0]["status"] == "REQUESTED"
