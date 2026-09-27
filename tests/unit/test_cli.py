from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from auto_trade.cli import main
from auto_trade.domain.models import ExecutionPolicy

REPO_ROOT = Path(__file__).resolve().parents[2]


def run_module(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment.setdefault("PYTHONPATH", str(REPO_ROOT / "src"))
    if env:
        environment.update(env)
    return subprocess.run(
        [sys.executable, "-m", "auto_trade", *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=environment,
        timeout=120,
    )


def generate_bitcoin_signal(target: Path) -> int:
    return main(
        [
            "make-signal",
            "--symbol",
            "BITCOIN",
            "--volume",
            "0.01",
            "--output",
            str(target),
        ]
    )


def test_status_command_succeeds() -> None:
    assert main(["status"]) == 0


def test_unknown_command_is_rejected() -> None:
    with pytest.raises(SystemExit):
        main(["not-a-command"])


def test_make_signal_writes_a_parseable_signal(tmp_path: Path) -> None:
    target = tmp_path / "signals" / "example.json"
    code = main(
        [
            "make-signal",
            "--symbol",
            "BITCOIN",
            "--action",
            "BUY",
            "--volume",
            "0.01",
            "--output",
            str(target),
        ]
    )

    assert code == 0
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["symbol"] == "BITCOIN"
    assert payload["action"] == "BUY"
    assert payload["expiration"]


def test_make_signal_rejects_an_unsupported_action(tmp_path: Path) -> None:
    target = tmp_path / "signals" / "bad.json"
    code = main(
        ["make-signal", "--symbol", "BITCOIN", "--action", "TELEPORT", "--output", str(target)]
    )

    assert code == 1
    assert not target.exists()


def test_module_entry_point_propagates_the_exit_code(tmp_path: Path) -> None:
    """A non-dry-run outcome must be visible to a shell, scheduler, or CI job."""
    completed = run_module(
        "dry-run",
        "--mock",
        "does-not-exist.json",
        env={"AUTO_TRADE_LOG_DIR": str(tmp_path / "logs")},
    )

    assert completed.returncode == 1


def test_module_entry_point_succeeds_on_a_mock_dry_run(tmp_path: Path) -> None:
    signal = tmp_path / "signal.json"
    assert (
        main(
            [
                "make-signal",
                "--symbol",
                "BITCOIN",
                "--volume",
                "0.01",
                "--output",
                str(signal),
            ]
        )
        == 0
    )

    completed = run_module(
        "dry-run",
        "--mock",
        str(signal),
        env={
            "AUTO_TRADE_LOG_DIR": str(tmp_path / "logs"),
            "AUTO_TRADE_ALLOWED_SYMBOLS": "BITCOIN",
        },
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["status"] == "DRY_RUN"


def test_dry_run_is_refused_while_the_kill_switch_is_active(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "KILL_SWITCH").write_text("activated by test\n", encoding="utf-8")
    signal = tmp_path / "signal.json"
    assert generate_bitcoin_signal(signal) == 0

    completed = run_module(
        "dry-run",
        "--mock",
        str(signal),
        env={
            "AUTO_TRADE_LOG_DIR": str(logs),
            "AUTO_TRADE_ALLOWED_SYMBOLS": "BITCOIN",
        },
    )

    assert completed.returncode == 1
    assert json.loads(completed.stdout)["message"] == "kill switch is active"


def test_dashboard_refuses_a_non_loopback_host() -> None:
    assert main(["dashboard", "--host", "0.0.0.0"]) == 2


def test_dry_run_forces_dry_run_even_when_configured_live(tmp_path: Path) -> None:
    """The CLI must never be able to reach a live execution path."""
    assert ExecutionPolicy(dry_run=False, demo_only=True).dry_run is False
    signal = tmp_path / "signal.json"
    assert generate_bitcoin_signal(signal) == 0


    completed = run_module(
        "dry-run",
        "--mock",
        str(signal),
        env={
            "AUTO_TRADE_LOG_DIR": str(tmp_path / "logs"),
            "AUTO_TRADE_ALLOWED_SYMBOLS": "BITCOIN",
            "AUTO_TRADE_DRY_RUN": "false",
        },
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout)["status"] == "DRY_RUN"


def test_execute_requires_explicit_demo_confirmation(tmp_path: Path) -> None:
    signal = tmp_path / "signal.json"
    assert generate_bitcoin_signal(signal) == 0

    code = main(["execute", str(signal)])

    assert code == 2


def test_execute_refuses_when_execution_is_not_explicitly_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    signal = tmp_path / "signal.json"
    assert generate_bitcoin_signal(signal) == 0
    monkeypatch.setenv("AUTO_TRADE_ENABLE_EXECUTION", "false")
    monkeypatch.setenv("AUTO_TRADE_DRY_RUN", "false")
    monkeypatch.setenv("AUTO_TRADE_LOG_DIR", str(tmp_path / "logs"))

    code = main(["execute", "--confirm-demo", str(signal)])

    assert code == 2
