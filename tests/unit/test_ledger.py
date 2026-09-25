from __future__ import annotations

import json
from pathlib import Path

from auto_trade.application.ledger import JsonExecutionLedger
from auto_trade.domain.enums import ExecutionStatus
from auto_trade.domain.models import ExecutionResult


def test_ledger_persists_attempt_and_result(tmp_path: Path) -> None:
    path = tmp_path / "idempotency.json"
    first = JsonExecutionLedger(path)
    first.record_attempt("signal-1", "execution-1")
    assert first.pending()[0]["execution_id"] == "execution-1"
    first.record_result(
        ExecutionResult(
            "execution-1",
            "signal-1",
            ExecutionStatus.ACCEPTED,
            "SUCCESS",
            "verified",
        )
    )
    second = JsonExecutionLedger(path)
    assert second.contains("signal-1")
    assert second.pending() == ()


def test_ledger_keeps_requested_attempt_after_restart(tmp_path: Path) -> None:
    path = tmp_path / "idempotency.json"
    JsonExecutionLedger(path).record_attempt("signal-unknown", "execution-unknown")
    recovered = JsonExecutionLedger(path)
    assert recovered.contains("signal-unknown")
    assert recovered.pending()[0]["status"] == "REQUESTED"


def test_ledger_does_not_overwrite_unknown_execution(tmp_path: Path) -> None:
    path = tmp_path / "idempotency.json"
    ledger = JsonExecutionLedger(path)
    ledger.record_result(
        ExecutionResult(
            "execution-unknown",
            "signal-unknown",
            ExecutionStatus.UNKNOWN,
            "UNKNOWN_EXECUTION",
            "verification unavailable",
        )
    )
    ledger.record_result(
        ExecutionResult(
            "execution-retry",
            "signal-unknown",
            ExecutionStatus.REJECTED,
            "INVALID_SIGNAL",
            "duplicate",
        )
    )
    entry = json.loads(path.read_text(encoding="utf-8"))["signal-unknown"]
    assert entry["execution_id"] == "execution-unknown"
    assert entry["status"] == "UNKNOWN"
