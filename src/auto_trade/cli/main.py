from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path

from ..adapters.terminal import DryRunTerminalAdapter
from ..application.risk import RiskEngine
from ..application.workflow import ExecutionWorkflow
from ..domain.exceptions import AutoTradeError
from ..domain.models import TradeSignal
from ..domain.protocols import KillSwitch
from ..infrastructure.configuration import AppConfig
from ..infrastructure.logging import AuditLogger
from ..infrastructure.terminal import WindowsTerminalDiscovery


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="auto-trade")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="show configured safety status")
    subparsers.add_parser("diagnostics", help="show environment and MT5 diagnostics")
    commands = (
        ("test-signal", "parse one signal file"),
        ("dry-run", "process one signal without order execution"),
    )
    for name, help_text in commands:
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("signal_file", type=Path)
    subparsers.add_parser("run", help="run the configured signal loop")
    return parser


def _signal(path: Path) -> TradeSignal:
    return TradeSignal.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _diagnostics(config: AppConfig) -> dict[str, object]:
    terminal = config.terminal_path
    data_path = config.data_path
    discovery_status = "not checked"
    try:
        WindowsTerminalDiscovery().discover(config.terminal_profile())
        discovery_status = "found"
    except AutoTradeError as exc:
        discovery_status = str(exc)
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "application": "auto-trade 0.1.0",
        "terminal_path": str(terminal),
        "terminal_exists": terminal.is_file(),
        "data_path": str(data_path),
        "data_path_exists": data_path.is_dir(),
        "terminal_discovery": discovery_status,
        "dry_run": config.policy.dry_run,
        "demo_only": config.policy.demo_only,
        "allowed_symbols": sorted(config.risk.allowed_symbols),
        "max_volume": str(config.risk.max_volume),
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = AppConfig.from_env()
    if args.command in {"status", "diagnostics"}:
        print(json.dumps(_diagnostics(config), indent=2, default=str))
        return 0
    if args.command == "run":
        print("run is not enabled until a verified MT5 desktop adapter is implemented")
        return 2
    try:
        signal = _signal(args.signal_file)
        if args.command == "test-signal":
            print(json.dumps(signal.to_dict(), indent=2))
            return 0
        audit = AuditLogger(config.log_directory)
        policy = type(config.policy)(
            dry_run=True,
            demo_only=config.policy.demo_only,
            confirmation=config.policy.confirmation,
        )
        workflow = ExecutionWorkflow(
            adapter=DryRunTerminalAdapter(),
            risk_engine=RiskEngine(config.risk),
            profile=config.terminal_profile(),
            policy=policy,
            kill_switch=KillSwitch(),
            audit=audit.record,
        )
        result = workflow.execute(signal)
        output = {
            "status": result.status.value,
            "state": result.state,
            "message": result.message,
            "error": result.error,
        }
        print(json.dumps(output, indent=2))
        return 0 if result.status.value == "DRY_RUN" else 1
    except (OSError, ValueError, AutoTradeError, TimeoutError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
