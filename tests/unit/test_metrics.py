"""Counters and latency derived from the audit trail.

Metrics are read back out of `audit.log` rather than collected while a run is in
progress. That choice is the point of this file: an in-process counter would
report a clean, empty summary for exactly the run that died between the click
and the observation, which is the run whose timing an operator needs.

Every test below builds audit events in the shape `AuditLogger` writes, so a
change to that record breaks these tests rather than silently invalidating the
numbers.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from auto_trade.application.metrics import ExecutionMetrics, summarize

BASE = "2026-09-28T09:00:00Z"


def at(seconds: float) -> str:
    """An ISO timestamp *seconds* after the start of a run."""
    start = datetime.fromisoformat(BASE.replace("Z", "+00:00"))
    return (start + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def state(
    name: str,
    *,
    seconds: float,
    execution_id: str = "exec-1",
    component: str = "execution",
) -> dict[str, Any]:
    return {
        "timestamp": at(seconds),
        "component": component,
        "event_type": "state",
        "signal_id": "signal-1",
        "execution_id": execution_id,
        "symbol": "EURUSD",
        "action": "BUY",
        "volume": "0.01",
        "state": name,
        "message": name,
        "error": None,
        "evidence": None,
    }


def result(
    settled: str,
    *,
    seconds: float,
    execution_id: str = "exec-1",
    component: str = "execution",
) -> dict[str, Any]:
    return {
        **state(settled, seconds=seconds, execution_id=execution_id, component=component),
        "event_type": "result",
    }


def full_run(seconds: float = 0.0, execution_id: str = "exec-1") -> list[dict[str, Any]]:
    """One guarded execution that reached an independently proved outcome."""
    return [
        state("SIGNAL_RECEIVED", seconds=seconds, execution_id=execution_id),
        state("VALIDATING", seconds=seconds + 0.01, execution_id=execution_id),
        state("VALIDATED", seconds=seconds + 0.02, execution_id=execution_id),
        state("LOCATING_TERMINAL", seconds=seconds + 0.03, execution_id=execution_id),
        state("PREPARING_UI", seconds=seconds + 0.04, execution_id=execution_id),
        state("ORDER_READY", seconds=seconds + 0.30, execution_id=execution_id),
        state("EXECUTING", seconds=seconds + 0.31, execution_id=execution_id),
        state("EXECUTION_DETECTED", seconds=seconds + 0.36, execution_id=execution_id),
        state("VERIFYING", seconds=seconds + 0.37, execution_id=execution_id),
        state("SUCCESS", seconds=seconds + 0.42, execution_id=execution_id),
        result("SUCCESS", seconds=seconds + 0.43, execution_id=execution_id),
    ]


# -- the phase boundary that matters ------------------------------------


def test_the_click_to_outcome_phase_is_measured() -> None:
    """The interval an operator asks about: the click, and when it was settled.

    No event in this project marks broker acceptance, so this measures the
    application returning an outcome, not the broker filling an order.
    """
    metrics = summarize(full_run())

    click = metrics.latency["click_to_outcome"]
    assert click.measured
    # EXECUTING at 0.31 to the result at 0.43.
    assert click.max_ms == pytest.approx(120.0, abs=1.0)
    assert click.min_ms == click.p50_ms == click.max_ms


def test_each_phase_is_measured_between_its_two_recorded_states() -> None:
    latency = summarize(full_run()).latency

    assert latency["validation"].max_ms == pytest.approx(20.0, abs=1.0)
    # VALIDATED to ORDER_READY is the symbol and dialog preparation.
    assert latency["preparation"].max_ms == pytest.approx(280.0, abs=1.0)
    # EXECUTING to EXECUTION_DETECTED is the click and the dialog closing.
    assert latency["click_to_detection"].max_ms == pytest.approx(50.0, abs=1.0)
    # EXECUTION_DETECTED to VERIFYING is the handoff into observation.
    assert latency["observation"].max_ms == pytest.approx(10.0, abs=1.0)
    assert latency["total"].max_ms == pytest.approx(430.0, abs=1.0)


def test_an_unmeasured_phase_is_empty_rather_than_zero() -> None:
    """A dry run never clicks, so it has no click latency to report.

    Reporting zero there would be a claim that the click was instantaneous.
    """
    latency = summarize(
        [
            state("SIGNAL_RECEIVED", seconds=0.0),
            state("VALIDATED", seconds=0.02),
            state("ORDER_READY", seconds=0.30),
            result("DRY_RUN_COMPLETED", seconds=0.31),
        ]
    ).latency

    assert latency["click_to_outcome"].measured is False
    assert latency["click_to_outcome"].count == 0
    assert latency["click_to_outcome"].mean_ms is None
    assert latency["click_to_outcome"].p95_ms is None
    # The phases that did happen are still reported.
    assert latency["total"].measured is True


# -- counters -----------------------------------------------------------


def test_results_are_counted_by_the_state_they_settled_in() -> None:
    metrics = summarize(
        full_run(0.0, "exec-1")
        + full_run(10.0, "exec-2")[:-1]
        + [result("VERIFICATION_FAILED", seconds=12.0, execution_id="exec-2")]
    )

    assert metrics.results_by_status == {"SUCCESS": 1, "VERIFICATION_FAILED": 1}
    assert metrics.executions == 2


def test_an_attempt_that_never_recorded_a_result_is_counted_as_unresolved() -> None:
    """A crash between the click and the observation leaves this shape.

    It is the one figure an operator acts on, and it is derived rather than
    remembered, so a process that died cannot take it with it.
    """
    metrics = summarize(
        full_run()[:8]  # stopped at EXECUTION_DETECTED, no result event
    )

    assert metrics.unresolved == 1
    assert metrics.unresolved_execution_ids == ("exec-1",)
    assert metrics.results_by_status == {}
    # The attempt is not reported as a failure it never established either.
    assert metrics.executions_by_final_state == {"EXECUTION_DETECTED": 1}


def test_a_run_that_reached_a_refusal_is_not_unresolved() -> None:
    """Nothing was clicked, so there is no account state to look at by hand."""
    metrics = summarize(
        [
            state("SIGNAL_RECEIVED", seconds=0.0),
            state("VALIDATING", seconds=0.01),
            result("INVALID_SIGNAL", seconds=0.02),
        ]
    )

    assert metrics.unresolved == 0
    assert metrics.results_by_status == {"INVALID_SIGNAL": 1}


def test_an_unknown_outcome_is_a_settled_record_and_not_unresolved() -> None:
    """UNKNOWN is a result this application wrote: it is pending review, but counted."""
    metrics = summarize(full_run()[:-1] + [result("UNKNOWN_EXECUTION", seconds=0.44)])

    assert metrics.unresolved == 0
    assert metrics.results_by_status == {"UNKNOWN_EXECUTION": 1}


# -- honesty about the data ---------------------------------------------


def test_a_truncated_log_says_so() -> None:
    """A summary of half the history must not read as the whole history."""
    metrics = summarize(full_run(), truncated=True)

    assert metrics.truncated is True
    assert metrics.to_dict()["truncated"] is True


def test_an_empty_log_reports_nothing_measured_instead_of_nothing_wrong() -> None:
    payload = summarize([]).to_dict()

    assert payload["events"] == 0
    assert payload["executions"] == 0
    assert payload["counters"]["unresolved_attempts"] == 0
    assert all(not entry["measured"] for entry in payload["latency_ms"].values())


def test_an_unreadable_line_is_counted_rather_than_dropped() -> None:
    """A line that cannot be interpreted must not quietly become a shorter count."""
    events: list[Any] = full_run()
    events.append({"timestamp": "not a timestamp", "execution_id": "exec-9", "state": "X"})
    events.append({"timestamp": at(1.0), "execution_id": "", "state": "SIGNAL_RECEIVED"})
    events.append("not even an object")

    metrics = summarize(events)

    assert metrics.unparseable_timestamps == 3
    assert metrics.to_dict()["data_quality"]["unparseable_timestamps"] == 3
    # The readable run is still measured.
    assert metrics.latency["click_to_outcome"].measured is True


def test_a_clock_that_moved_backwards_is_reported_not_smoothed() -> None:
    """An NTP correction mid-run would otherwise produce negative durations."""
    events = [
        state("SIGNAL_RECEIVED", seconds=10.0),
        state("VALIDATED", seconds=9.0),
        result("SUCCESS", seconds=11.0),
    ]

    metrics = summarize(events)

    assert metrics.non_monotonic_intervals == 1
    assert metrics.to_dict()["data_quality"]["non_monotonic_intervals"] == 1
    assert metrics.latency["validation"].measured is False


def test_the_summary_never_reports_a_trade_as_accepted() -> None:
    """Metrics describe the path. Only the ledger settles an outcome."""
    payload = summarize(full_run()).to_dict()

    assert payload["source"] == "audit-log"
    assert "no figure here reports a trade as accepted" in payload["note"]


# -- spread across runs -------------------------------------------------


def test_percentiles_are_real_samples_from_the_distribution() -> None:
    events: list[dict[str, Any]] = []
    for index in range(1, 101):
        events.extend(full_run(seconds=index * 10.0, execution_id=f"exec-{index}"))

    click = summarize(events).latency["click_to_outcome"]

    assert click.count == 100
    assert click.min_ms == pytest.approx(120.0, abs=1.0)
    assert click.max_ms == pytest.approx(120.0, abs=1.0)
    assert click.p50_ms in (click.min_ms, click.max_ms)


def test_a_slower_run_shows_up_in_the_spread() -> None:
    events = full_run() + [
        state("EXECUTING", seconds=5.0, execution_id="exec-2"),
        state("EXECUTION_DETECTED", seconds=5.1, execution_id="exec-2"),
        result("SUCCESS", seconds=12.0, execution_id="exec-2"),
    ]

    click = summarize(events).latency["click_to_outcome"]

    assert click.count == 2
    assert click.measured
    # Narrowed by the assertion above: an unmeasured phase has no figures at all.
    assert click.min_ms is not None
    assert click.max_ms is not None
    assert click.min_ms < 1000.0
    assert click.max_ms > 6000.0
    assert click.mean_ms == pytest.approx((click.min_ms + click.max_ms) / 2, abs=1.0)


# -- the real reader ----------------------------------------------------


def test_the_summary_is_json_serializable(tmp_path: Path) -> None:
    payload = summarize(full_run()).to_dict()

    written = tmp_path / "metrics.json"
    written.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    assert json.loads(written.read_text(encoding="utf-8")) == payload


def test_summarize_returns_the_domain_type() -> None:
    assert isinstance(summarize([]), ExecutionMetrics)


def test_the_cli_reads_a_real_audit_log_written_by_a_real_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """End to end through the shipped audit logger, the shipped CLI, and the parser.

    Everything above feeds hand-written dictionaries. This one runs the real
    workflow so the record `AuditLogger` actually writes is what gets parsed,
    which is the only way to know the two agree.
    """
    from decimal import Decimal

    from auto_trade.application.ledger import JsonExecutionLedger
    from auto_trade.application.risk import RiskEngine
    from auto_trade.application.workflow import ExecutionWorkflow
    from auto_trade.cli import main
    from auto_trade.domain.enums import AccountType
    from auto_trade.domain.models import (
        AccountSnapshot,
        ExecutionPolicy,
        OrderRequest,
        RiskLimits,
        TerminalProfile,
        TradeSignal,
        utc_now,
    )
    from auto_trade.domain.protocols import KillSwitch
    from auto_trade.infrastructure.logging import AuditLogger

    logs = tmp_path / "logs"
    audit = AuditLogger(logs)

    class DryAdapter:
        """Stops after the order is ready, so no final control is used."""

        def connect(self) -> Any:
            return AccountSnapshot(AccountType.DEMO, connected=True)

        def get_terminal_state(self) -> str:
            return "CONNECTED_DEMO"

        def select_symbol(self, symbol: str) -> None:
            return

        def prepare_order(self, order: OrderRequest) -> None:
            return

        def execute_order(self, order: OrderRequest) -> Any:
            raise AssertionError("dry-run must not reach the final control")

        def verify_execution(self, order: OrderRequest) -> Any:
            raise AssertionError("not used")

        def close_position(self, position_id: str) -> Any:
            raise AssertionError("not used")

    # A current timestamp: the risk engine refuses a signal that has expired, and
    # a hard-coded one from the record date would be refused on any later day.
    signal = TradeSignal.from_dict(
        {
            "id": "signal-metrics-1",
            "timestamp": utc_now().isoformat().replace("+00:00", "Z"),
            "source": "test",
            "symbol": "EURUSD",
            "action": "BUY",
            "volume": 0.01,
        }
    )
    workflow = ExecutionWorkflow(
        adapter=DryAdapter(),
        risk_engine=RiskEngine(RiskLimits(frozenset({"EURUSD"}), Decimal("0.10"), 5, 300)),
        profile=TerminalProfile("alpari-demo", "terminal64.exe", "data", "Alpari-MT5-Demo"),
        policy=ExecutionPolicy(dry_run=True, demo_only=True),
        kill_switch=KillSwitch(),
        audit=audit.record,
        ledger=JsonExecutionLedger(logs / "idempotency.json"),
    )
    workflow.execute(signal)

    monkeypatch.setenv("AUTO_TRADE_LOG_DIR", str(logs))
    assert main(["metrics"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["events"] > 0
    assert payload["executions"] == 1
    assert payload["counters"]["results_by_status"] == {"DRY_RUN_COMPLETED": 1}
    # A dry run never clicked, so the click phases must claim no measurement.
    assert payload["latency_ms"]["click_to_outcome"]["measured"] is False
    assert payload["latency_ms"]["total"]["measured"] is True
    assert payload["counters"]["unresolved_attempts"] == 0
