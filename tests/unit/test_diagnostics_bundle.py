from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from auto_trade.application.diagnostics import DiagnosticsBundle, DiagnosticSubject
from auto_trade.application.kill_switch import FileKillSwitch
from auto_trade.application.ledger import JsonExecutionLedger
from auto_trade.domain.exceptions import PositionSnapshotUnavailable, TerminalNotFoundError
from auto_trade.domain.models import (
    ExecutionPolicy,
    PositionSnapshot,
    RiskLimits,
    TerminalProfile,
)

NOW = datetime(2026, 9, 28, 9, 0, 0, tzinfo=UTC)


class StubDiscovery:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def discover(self, profile: TerminalProfile) -> TerminalProfile:
        if self.error is not None:
            raise self.error
        return profile


class StubPositions:
    def __init__(
        self,
        positions: tuple[PositionSnapshot, ...] = (),
        error: Exception | None = None,
    ) -> None:
        self._positions = positions
        self.error = error

    def positions(self) -> tuple[PositionSnapshot, ...]:
        if self.error is not None:
            raise self.error
        return self._positions


def subject(tmp_path: Path) -> DiagnosticSubject:
    return DiagnosticSubject(
        profile=TerminalProfile(
            name="alpari-demo",
            terminal_path=r"C:\Program Files\Alpari MT5_2\terminal64.exe",
            data_path=str(tmp_path / "data"),
            instance_name="Alpari-MT5-Demo",
        ),
        signal_directory=tmp_path / "signals",
        log_directory=tmp_path / "logs",
        policy=ExecutionPolicy(dry_run=True, demo_only=True),
        risk=RiskLimits(frozenset({"EURUSD"}), Decimal("1.0"), 5, 10),
        http_signal_endpoint="http://127.0.0.1:8787/signals/next",
        http_signal_token="super-secret-token",
    )


def bundle_for(tmp_path: Path, **overrides: Any) -> DiagnosticsBundle:
    subject_value = overrides.pop("subject", subject(tmp_path))
    return DiagnosticsBundle(
        subject=subject_value,
        kill_switch=overrides.pop(
            "kill_switch", FileKillSwitch(tmp_path / "logs" / "KILL_SWITCH", clock=lambda: NOW)
        ),
        ledger=overrides.pop("ledger", JsonExecutionLedger(tmp_path / "logs" / "idempotency.json")),
        position_provider=overrides.pop("position_provider", StubPositions()),
        terminal_discovery=overrides.pop("terminal_discovery", StubDiscovery()),
        **overrides,
    )


def read(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        return {name: json.loads(archive.read(name)) for name in archive.namelist()}


def test_bundle_contains_every_expected_section(tmp_path: Path) -> None:
    target = bundle_for(tmp_path).export(tmp_path / "bundle.zip")

    entries = read(target)
    assert set(entries) == {
        "manifest.json",
        "environment.json",
        "configuration.json",
        "terminal.json",
        "kill-switch.json",
        "positions.json",
        "executions.json",
        "metrics.json",
        "signals.json",
        "audit-log.json",
    }
    assert entries["manifest.json"]["contains_no_credentials"] is True
    assert entries["environment.json"]["working_directory"] == str(Path.cwd())


def test_bundle_metrics_describe_only_the_events_in_the_log_tail(tmp_path: Path) -> None:
    """The summary is derived from the tail, and says so when the tail is short.

    A latency figure computed from a truncated log would otherwise look exactly
    like one computed from the whole history.
    """
    logs = tmp_path / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    events = [
        {
            "timestamp": f"2026-09-28T09:00:0{index}Z",
            "component": "execution",
            "event_type": "state",
            "signal_id": "signal-1",
            "execution_id": "exec-1",
            "state": name,
            "message": name,
        }
        for index, name in enumerate(
            ["SIGNAL_RECEIVED", "VALIDATING", "VALIDATED", "ORDER_READY"]
        )
    ]
    (logs / "audit.log").write_text(
        "\n".join(json.dumps(event) for event in events), encoding="utf-8"
    )
    target = bundle_for(tmp_path, audit_tail=2).export(tmp_path / "bundle.zip")

    metrics = read(target)["metrics.json"]
    # Only the two trailing events were read, so only one execution is counted.
    assert metrics["truncated"] is True
    assert metrics["events"] == 2
    assert metrics["executions"] == 1
    # VALIDATED and ORDER_READY are the two events read, so the preparation phase
    # between them is genuinely measured.
    assert metrics["latency_ms"]["preparation"]["measured"] is True
    assert metrics["latency_ms"]["preparation"]["max_ms"] == 1000.0
    # Nothing about a final control is in the tail, so no click phase is claimed.
    assert metrics["latency_ms"]["click_to_outcome"]["measured"] is False
    assert metrics["latency_ms"]["total"]["measured"] is False
    assert metrics["counters"]["unresolved_attempts"] == 0


def test_bundle_never_writes_the_configured_token(tmp_path: Path) -> None:
    target = bundle_for(tmp_path).export(tmp_path / "bundle.zip")

    assert b"super-secret-token" not in target.read_bytes()
    sources = read(target)["configuration.json"]["sources"]
    assert sources["http_token_configured"] is True
    assert sources["http_endpoint"] == "http://127.0.0.1:8787/signals/next"


def test_bundle_records_a_terminal_that_cannot_be_found(tmp_path: Path) -> None:
    """A discovery failure is the reason a bundle exists, so it is data, not a crash."""
    bundle = bundle_for(
        tmp_path,
        terminal_discovery=StubDiscovery(TerminalNotFoundError("MT5 process is not running")),
    )

    target = bundle.export(tmp_path / "bundle.zip")

    terminal = read(target)["terminal.json"]
    assert terminal["status"] == "NOT FOUND"
    assert "not running" in terminal["detail"]


def test_bundle_records_unavailable_positions_instead_of_guessing(tmp_path: Path) -> None:
    bundle = bundle_for(
        tmp_path,
        position_provider=StubPositions(
            error=PositionSnapshotUnavailable("no indicator snapshot was written")
        ),
    )

    target = bundle.export(tmp_path / "bundle.zip")

    positions = read(target)["positions.json"]
    assert positions["status"] == "UNAVAILABLE"
    assert positions["positions"] == []


def test_bundle_reports_observed_positions(tmp_path: Path) -> None:
    position = PositionSnapshot(
        position_id="42",
        symbol="EURUSD",
        side="BUY",
        volume=Decimal("0.10"),
    )
    bundle = bundle_for(tmp_path, position_provider=StubPositions((position,)))

    target = bundle.export(tmp_path / "bundle.zip")

    positions = read(target)["positions.json"]
    assert positions["status"] == "AVAILABLE"
    assert positions["positions"] == [
        {"position_id": "42", "symbol": "EURUSD", "side": "BUY", "volume": "0.10"}
    ]


def test_bundle_includes_the_kill_switch_state(tmp_path: Path) -> None:
    kill_switch = FileKillSwitch(tmp_path / "logs" / "KILL_SWITCH", clock=lambda: NOW)
    kill_switch.activate()
    bundle = bundle_for(tmp_path, kill_switch=kill_switch)

    target = bundle.export(tmp_path / "bundle.zip")

    recorded = read(target)["kill-switch.json"]
    assert recorded["active"] is True
    assert "2026-09-28T09:00:00" in recorded["reason"]


def test_bundle_includes_pending_signals_and_reports_unreadable_ones(tmp_path: Path) -> None:
    signals = tmp_path / "signals"
    signals.mkdir(parents=True)
    (signals / "valid.json").write_text(
        json.dumps({"id": "signal-1", "symbol": "EURUSD"}), encoding="utf-8"
    )
    (signals / "broken.json").write_text("{", encoding="utf-8")

    target = bundle_for(tmp_path).export(tmp_path / "bundle.zip")

    section = read(target)["signals.json"]
    by_name = {entry["file"]: entry for entry in section["files"]}
    assert by_name["valid.json"]["readable"] is True
    assert by_name["broken.json"]["readable"] is False
    assert section["count"] == 2


def test_bundle_tails_the_audit_log(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "audit.log").write_text(
        "\n".join(json.dumps({"n": index}) for index in range(10)) + "\nnot json\n",
        encoding="utf-8",
    )
    bundle = bundle_for(tmp_path, audit_tail=3)

    target = bundle.export(tmp_path / "bundle.zip")

    section = read(target)["audit-log.json"]
    # The tail keeps the last three lines, including the unparsable one.
    assert [event.get("n") for event in section["events"]] == [8, 9, None]
    assert section["events"][-1] == {"raw": "not json"}
    assert section["truncated"] is True


def test_bundle_survives_a_missing_ledger_and_log_directory(tmp_path: Path) -> None:
    bundle = bundle_for(
        tmp_path,
        position_provider=None,
        terminal_discovery=None,
    )

    target = bundle.export(tmp_path / "nested" / "bundle.zip")

    entries = read(target)
    assert entries["positions.json"] == {
        "status": "NOT CHECKED",
        "detail": "no position source was supplied",
    }
    assert entries["terminal.json"]["status"] == "NOT CHECKED"
    assert entries["audit-log.json"]["present"] is False
    assert entries["signals.json"]["count"] == 0


def test_bundle_default_name_is_timestamped() -> None:
    from auto_trade.application.diagnostics import default_bundle_name

    name = default_bundle_name()

    assert name.startswith("auto-trade-diagnostics-")
    assert name.endswith(".zip")


def test_bundle_overwrites_an_existing_archive(tmp_path: Path) -> None:
    target = tmp_path / "bundle.zip"
    bundle_for(tmp_path).export(target)

    bundle_for(tmp_path).export(target)

    assert read(target)["manifest.json"]["bundle_version"] == 1


@pytest.mark.parametrize("section", ["configuration", "environment"])
def test_bundle_sections_are_serialisable(tmp_path: Path, section: str) -> None:
    bundle = bundle_for(tmp_path)

    bundle.collect()

    assert json.loads(json.dumps(bundle.sections[section], default=str))
