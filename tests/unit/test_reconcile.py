"""Settling an attempt the application could not prove.

An `UNKNOWN` record is not a bug to be hidden. It is the truth about a click
that could not be corroborated, and only a person looking at the account can
say what happened afterwards. These tests pin what that assertion may and may
not do to the ledger.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from auto_trade.application.ledger import RECONCILED, JsonExecutionLedger, LedgerError
from auto_trade.cli import main


def ledger_with(path: Path, entries: dict[str, dict[str, object]]) -> JsonExecutionLedger:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries), encoding="utf-8")
    return JsonExecutionLedger(path)


def unknown_entry(signal_id: str = "signal-1") -> dict[str, object]:
    return {
        "signal_id": signal_id,
        "execution_id": "exec-1",
        "status": "UNKNOWN",
        "state": "UNKNOWN_STATE",
        "message": "execution outcome is unknown",
        "order_reference": None,
        "evidence": None,
        "timestamp": "2026-09-28T09:04:43.638578+00:00",
    }


def test_reconciling_records_the_operator_assertion(tmp_path: Path) -> None:
    ledger = ledger_with(tmp_path / "idempotency.json", {"signal-1": unknown_entry()})

    record = ledger.reconcile("signal-1", "position 382626466 seen in the Trade tab")

    assert record["status"] == RECONCILED
    assert record["state"] == "RECONCILED_BY_OPERATOR"
    assert "not observed by this application" in str(record["message"])
    assert "382626466" in str(record["message"])
    assert record["original_status"] == "UNKNOWN"
    assert record["original_message"] == "execution outcome is unknown"
    assert record["reconciled_at"]


def test_the_original_record_survives_on_disk(tmp_path: Path) -> None:
    path = tmp_path / "idempotency.json"
    ledger = ledger_with(path, {"signal-1": unknown_entry()})

    ledger.reconcile("signal-1", "filled and closed by hand")

    stored = json.loads(path.read_text(encoding="utf-8"))["signal-1"]
    assert stored["status"] == RECONCILED
    assert stored["original_message"] == "execution outcome is unknown"


def test_a_settled_record_is_refused(tmp_path: Path) -> None:
    entry = unknown_entry()
    entry["status"] = "ACCEPTED"
    ledger = ledger_with(tmp_path / "idempotency.json", {"signal-1": entry})

    with pytest.raises(LedgerError, match="not in doubt"):
        ledger.reconcile("signal-1", "it did fill")


def test_an_unknown_signal_id_is_refused(tmp_path: Path) -> None:
    ledger = ledger_with(tmp_path / "idempotency.json", {})

    with pytest.raises(LedgerError, match="no execution record"):
        ledger.reconcile("signal-404", "something happened")


def test_an_empty_assertion_is_refused(tmp_path: Path) -> None:
    ledger = ledger_with(tmp_path / "idempotency.json", {"signal-1": unknown_entry()})

    with pytest.raises(LedgerError, match="requires what was observed"):
        ledger.reconcile("signal-1", "   ")


def test_a_reconciled_record_can_be_settled_again(tmp_path: Path) -> None:
    """Correcting the operator's own later statement must remain possible."""
    ledger = ledger_with(tmp_path / "idempotency.json", {"signal-1": unknown_entry()})
    ledger.reconcile("signal-1", "first impression")

    record = ledger.reconcile("signal-1", "second impression, after checking history")

    assert "second impression" in str(record["message"])


def test_reconcile_command_writes_through_the_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    logs = tmp_path / "logs"
    ledger_with(logs / "idempotency.json", {"signal-9": unknown_entry("signal-9")})
    monkeypatch.setenv("AUTO_TRADE_LOG_DIR", str(logs))

    code = main(["reconcile", "signal-9", "--observed", "position 555 was filled"])

    printed = capsys.readouterr()
    assert code == 0, printed.err
    assert json.loads(printed.out)["status"] == RECONCILED
    audit = (logs / "audit.log").read_text(encoding="utf-8")
    assert "operator-reconciled" in audit
    assert "signal-9" in audit


def test_reconcile_command_refuses_a_settled_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    logs = tmp_path / "logs"
    entry = unknown_entry("signal-9")
    entry["status"] = "CLOSED"
    ledger_with(logs / "idempotency.json", {"signal-9": entry})
    monkeypatch.setenv("AUTO_TRADE_LOG_DIR", str(logs))

    code = main(["reconcile", "signal-9", "--observed", "already settled"])

    assert code == 1


def test_recovery_separates_reconciled_from_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    logs = tmp_path / "logs"
    ledger_with(
        logs / "idempotency.json",
        {"signal-1": unknown_entry("signal-1"), "signal-2": unknown_entry("signal-2")},
    )
    monkeypatch.setenv("AUTO_TRADE_LOG_DIR", str(logs))
    main(["reconcile", "signal-2", "--observed", "filled"])
    capsys.readouterr()

    assert main(["recovery"]) == 0

    review = json.loads(capsys.readouterr().out)
    assert [record["signal_id"] for record in review["unknown"]] == ["signal-1"]
    assert [record["signal_id"] for record in review["reconciled"]] == ["signal-2"]
