"""`run` is a rehearsal, and the tests are about the difference.

The loop walks signals through the whole workflow on a schedule, which is the
shape an unattended trader has. What keeps it a rehearsal is that it builds the
same disabled-gate dry-run workflow `dry-run` uses, so a final control is
unreachable by construction rather than by a flag somebody remembered to set.

These tests would be the last line of defence if that ever changed, which is why
the gate itself is asserted on rather than only the outcome.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from auto_trade.application.kill_switch import FileKillSwitch
from auto_trade.cli.main import _dry_run_workflow, _run, main
from auto_trade.domain.enums import ExecutionStatus
from auto_trade.domain.models import (
    ExecutionPolicy,
    RiskLimits,
    TradeSignal,
)
from auto_trade.infrastructure.configuration import AppConfig
from auto_trade.interfaces.server import kill_switch_path

NOW = datetime(2026, 9, 29, 14, 0, 0, tzinfo=UTC)


def _signal(signal_id: str) -> dict[str, Any]:
    return {
        "id": signal_id,
        "timestamp": "2026-09-29T14:00:00Z",
        "source": "test",
        "symbol": "EURUSD",
        "action": "BUY",
        "volume": 0.01,
    }


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        terminal_path=tmp_path / "terminal64.exe",
        data_path=tmp_path / "data",
        instance_name="Alpari-MT5-Demo",
        signal_directory=tmp_path / "signals",
        log_directory=tmp_path / "logs",
        policy=ExecutionPolicy(dry_run=True, demo_only=True),
        risk=RiskLimits(frozenset({"EURUSD"}), Decimal("1.0"), 5, 300),
    )


def write_signal(directory: Path, signal_id: str, symbol: str = "EURUSD") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{signal_id}.json"
    path.write_text(json.dumps(_signal(signal_id) | {"symbol": symbol}), encoding="utf-8")
    return path


def argv(**overrides: Any) -> argparse.Namespace:
    values: dict[str, Any] = {
        "command": "run",
        "max_signals": 1,
        "timeout": 0.2,
        "interval": 0.0,
        "mock": True,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


# -- the gate is the difference ------------------------------------------


def test_the_loop_workflow_cannot_reach_a_final_control(config: AppConfig) -> None:
    """The refusal is a property of the objects, not of a flag somebody set.

    The real adapter carries a disabled gate; the mock adapter refuses
    unconditionally. Both are asserted, because both are what the loop rests on.
    """
    from auto_trade.adapters.terminal import DryRunTerminalAdapter
    from auto_trade.domain.exceptions import AutomationError
    from auto_trade.domain.models import OrderRequest

    real = _dry_run_workflow(config, mock=False)
    gate = real.adapter.gate  # type: ignore[attr-defined]
    assert gate.enabled is False
    assert gate.dry_run is True
    assert gate.refusal(), "a disabled gate must always produce a refusal"

    mock = _dry_run_workflow(config, mock=True)
    assert isinstance(mock.adapter, DryRunTerminalAdapter)
    request = OrderRequest(TradeSignal.from_dict(_signal("signal-1")))
    with pytest.raises(AutomationError, match="must never execute"):
        mock.adapter.execute_order(request)
    with pytest.raises(AutomationError, match="cannot close"):
        mock.adapter.close_position("1")


def test_the_dry_run_and_the_loop_share_one_workflow(config: AppConfig) -> None:
    """One builder, so the two commands cannot drift apart on safety."""
    first = _dry_run_workflow(config, mock=False)
    second = _dry_run_workflow(config, mock=False)

    assert first.adapter.gate.refusal() == second.adapter.gate.refusal()  # type: ignore[attr-defined]
    assert first.policy.dry_run is True
    assert first.policy.execution_enabled is False


def test_the_loop_policy_can_never_be_configured_to_execute(config: AppConfig) -> None:
    """Even from a config with execution enabled, the loop is a dry run."""
    live = AppConfig(
        terminal_path=config.terminal_path,
        data_path=config.data_path,
        instance_name=config.instance_name,
        signal_directory=config.signal_directory,
        log_directory=config.log_directory,
        policy=ExecutionPolicy(dry_run=False, demo_only=True, execution_enabled=True),
        risk=config.risk,
    )

    workflow = _dry_run_workflow(live, mock=False)

    assert workflow.policy.dry_run is True
    assert workflow.policy.execution_enabled is False
    assert workflow.adapter.gate.refusal()  # type: ignore[attr-defined]


# -- normal operation ----------------------------------------------------


def test_a_pending_signal_is_processed_as_a_dry_run(
    config: AppConfig, capsys: pytest.CaptureFixture[str]
) -> None:
    write_signal(config.signal_directory, "signal-1")

    code = _run(config, argv())

    assert code == 0
    out = capsys.readouterr().out
    assert '"status": "DRY_RUN"' in out
    assert '"processed": 1' in out
    assert "no final control was used" in out


def test_a_signal_the_risk_engine_refuses_is_reported_not_hidden(
    config: AppConfig, capsys: pytest.CaptureFixture[str]
) -> None:
    write_signal(config.signal_directory, "signal-1", symbol="BITCOIN")

    _run(config, argv())

    out = capsys.readouterr().out
    assert '"status": "REJECTED"' in out
    assert "symbol is not allowed" in out


def test_the_loop_stops_at_max_signals(
    config: AppConfig, capsys: pytest.CaptureFixture[str]
) -> None:
    for index in range(3):
        write_signal(config.signal_directory, f"signal-{index}")

    code = _run(config, argv(max_signals=2, timeout=5.0))

    assert code == 0
    out = capsys.readouterr().out
    assert '"processed": 2' in out


def test_an_empty_directory_ends_at_the_timeout_rather_than_spinning(
    config: AppConfig, capsys: pytest.CaptureFixture[str]
) -> None:
    config.signal_directory.mkdir(parents=True, exist_ok=True)

    code = _run(config, argv(max_signals=0, timeout=0.3, interval=0.05))

    assert code == 0
    assert '"processed": 0' in capsys.readouterr().out


# -- the loop must stop, not push on ------------------------------------


def test_the_kill_switch_stops_the_loop(
    config: AppConfig, capsys: pytest.CaptureFixture[str]
) -> None:
    FileKillSwitch(kill_switch_path(config.log_directory)).activate()
    write_signal(config.signal_directory, "signal-1")

    code = _run(config, argv(timeout=5.0))

    assert code == 2
    assert "kill switch is active" in capsys.readouterr().err


def test_an_unprovable_attempt_stops_the_loop(
    config: AppConfig, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """This is the property the loop exists to keep.

    An outcome that could not be proven is a question for a person, not
    something to try again on the next tick.
    """
    from auto_trade.domain.enums import ExecutionState
    from auto_trade.domain.models import ExecutionResult

    write_signal(config.signal_directory, "signal-1")
    write_signal(config.signal_directory, "signal-2")

    def unknown(_config: AppConfig, _args: Any) -> Any:
        class Unprovable:
            def execute(self, signal: Any) -> ExecutionResult:
                return ExecutionResult(
                    execution_id="",
                    signal_id=signal.signal_id,
                    status=ExecutionStatus.UNKNOWN,
                    state=ExecutionState.VERIFICATION_FAILED.value,
                    message="could not be proven",
                )

        return Unprovable()

    # `auto_trade.cli.main` resolves to the re-exported function, so the module
    # has to be imported explicitly for the patch to land on the right object.
    import importlib

    module = importlib.import_module("auto_trade.cli.main")
    monkeypatch.setattr(module, "_dry_run_workflow", unknown)

    code = _run(config, argv(max_signals=2, timeout=5.0))

    assert code == 1
    err = capsys.readouterr().err
    assert "could not be proven" in err
    assert "recovery" in err


def test_an_unreachable_source_is_reported_rather_than_retried_forever(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A source that cannot be reached is an error, not an idle source.

    The distinction matters: an idle source means "no signal yet" and the loop
    should keep waiting, while an unreachable one means something is wrong and
    waiting hides it. Confusing the two would make a broken setup look healthy.
    """
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    config = AppConfig(
        terminal_path=tmp_path / "terminal64.exe",
        data_path=tmp_path / "data",
        instance_name="Alpari-MT5-Demo",
        signal_directory=tmp_path / "signals",
        log_directory=tmp_path / "logs",
        policy=ExecutionPolicy(dry_run=True, demo_only=True),
        risk=RiskLimits(frozenset({"EURUSD"}), Decimal("1.0"), 5, 300),
        http_signal_url=f"http://127.0.0.1:{port}/signals/next",
        http_signal_token="token",
    )

    code = _run(config, argv(max_signals=1, timeout=5.0))

    assert code == 1
    assert "ERROR" in capsys.readouterr().err


def test_an_idle_source_waits_rather_than_failing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A source with nothing pending is normal, and the loop waits for its timeout."""
    config = AppConfig(
        terminal_path=tmp_path / "terminal64.exe",
        data_path=tmp_path / "data",
        instance_name="Alpari-MT5-Demo",
        signal_directory=tmp_path / "signals",
        log_directory=tmp_path / "logs",
        policy=ExecutionPolicy(dry_run=True, demo_only=True),
        risk=RiskLimits(frozenset({"EURUSD"}), Decimal("1.0"), 5, 300),
    )
    config.signal_directory.mkdir(parents=True, exist_ok=True)

    code = _run(config, argv(max_signals=0, timeout=0.3, interval=0.05))

    assert code == 0
    assert '"processed": 0' in capsys.readouterr().out


# -- through the CLI -----------------------------------------------------


def test_the_run_command_is_reachable_and_not_stubbed(
    config: AppConfig, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """It used to answer "not enabled until a verified adapter is implemented".

    That statement became false when the adapter was verified, and a command
    whose refusal reasons out of date is worse than no command.
    """
    write_signal(config.signal_directory, "signal-1")
    monkeypatch.setattr(AppConfig, "from_env", classmethod(lambda cls: config))

    code = main(["run", "--mock", "--max-signals", "1", "--timeout", "0.2"])

    assert code == 0
    assert "not enabled" not in capsys.readouterr().out


def test_the_parser_offers_the_loop_and_documents_it_as_dry_runs(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--help` says "dry runs", so the nature of the command is visible before use."""
    from auto_trade.cli.main import _parser

    with pytest.raises(SystemExit) as exit_info:
        _parser().parse_args(["run", "--help"])

    assert exit_info.value.code == 0
    captured = capsys.readouterr().out
    assert "dry runs" in captured
    assert "--max-signals" in captured
