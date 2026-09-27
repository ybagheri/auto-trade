from __future__ import annotations

import argparse
import json
import platform
import sys
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ..adapters.terminal import DryRunTerminalAdapter
from ..application.ledger import JsonExecutionLedger
from ..application.risk import RiskEngine
from ..application.workflow import ExecutionWorkflow
from ..domain.exceptions import AutoTradeError
from ..domain.models import AuditEvent, PositionSnapshot, TradeSignal, utc_now
from ..infrastructure.automation import MT5DesktopAdapter
from ..infrastructure.configuration import AppConfig
from ..infrastructure.logging import AuditLogger
from ..infrastructure.terminal import WindowsTerminalDiscovery


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="auto-trade")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="show configured safety status")
    subparsers.add_parser("diagnostics", help="show environment and MT5 diagnostics")
    subparsers.add_parser("recovery", help="review pending and unknown execution records")
    subparsers.add_parser("position-snapshot", help="read MT5 positions for verification")
    commands = (
        ("test-signal", "parse one signal file"),
        ("dry-run", "process one signal without order execution"),
    )
    for name, help_text in commands:
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("signal_file", type=Path)
        if name == "dry-run":
            command.add_argument(
                "--mock",
                action="store_true",
                help="use the fake terminal instead of inspecting MT5",
            )
    make_signal = subparsers.add_parser(
        "make-signal", help="write a signal file with a current timestamp"
    )
    make_signal.add_argument("--symbol", required=True)
    make_signal.add_argument("--action", default="BUY")
    make_signal.add_argument("--volume", type=Decimal, default=Decimal("0.01"))
    make_signal.add_argument("--valid-seconds", type=int, default=300)
    make_signal.add_argument("--comment", default="")
    make_signal.add_argument(
        "--output",
        type=Path,
        default=Path("examples") / "signals" / "example.json",
    )
    evaluate = subparsers.add_parser(
        "evaluate", help="ask the configured strategy for a signal on one symbol"
    )
    evaluate.add_argument("--symbol", required=True)
    evaluate.add_argument(
        "--strategy",
        default=None,
        help="override AUTO_TRADE_STRATEGY, as 'package.module:attribute'",
    )
    evaluate.add_argument(
        "--output",
        type=Path,
        default=None,
        help="where to write the signal; defaults to the configured signal directory",
    )
    subparsers.add_parser("run", help="run the configured signal loop")
    dashboard = subparsers.add_parser(
        "dashboard", help="serve the local read-only status dashboard"
    )
    dashboard.add_argument("--host", default="127.0.0.1")
    dashboard.add_argument("--port", type=int, default=8765)
    dashboard.add_argument(
        "--token",
        default=None,
        help="control token; generated when omitted",
    )
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


def _evaluate(config: AppConfig, args: argparse.Namespace) -> int:
    """Ask the configured strategy for a signal and record the decision.

    This is the integration point for a market-analysis library: the library only
    has to expose a strategy, and the bridge handles available position context,
    the signal file, and the audit record.
    """
    from ..application.strategy import build_context, load_strategy

    spec = args.strategy or config.strategy_spec
    if not spec:
        print(
            "no strategy configured. Set AUTO_TRADE_STRATEGY=package.module:attribute, "
            "or pass --strategy. See docs/STRATEGY_INTEGRATION.md.",
            file=sys.stderr,
        )
        return 2
    try:
        strategy = load_strategy(spec)
    except AutoTradeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    positions: tuple[PositionSnapshot, ...] = ()
    position_note = "position observation unavailable on this MT5 build"

    context = build_context(args.symbol, positions)
    try:
        signal = strategy.evaluate(context)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: strategy {spec!r} raised {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if signal is None:
        print(
            json.dumps(
                {"decision": "NO_SIGNAL", "strategy": strategy.name, "symbol": args.symbol},
                indent=2,
            )
        )
        return 0

    target = args.output or (config.signal_directory / f"{signal.signal_id}.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(signal.to_dict(), indent=2), encoding="utf-8")
    AuditLogger(config.log_directory).record(
        AuditEvent(
            component="strategy",
            event_type="decision",
            message=f"strategy {strategy.name} proposed a signal",
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            action=signal.action.value,
            volume=signal.volume,
        )
    )
    print(
        json.dumps(
            {
                "decision": "SIGNAL",
                "strategy": strategy.name,
                "written": str(target),
                "position_observation": position_note,
                "signal": signal.to_dict(),
            },
            indent=2,
        )
    )
    return 0


def _dashboard(config: AppConfig, args: argparse.Namespace) -> int:
    from ..application.kill_switch import FileKillSwitch
    from ..interfaces import StatusReporter, build_server, kill_switch_path

    kill_switch = FileKillSwitch(kill_switch_path(config.log_directory))
    reporter = StatusReporter(
        config=config,
        ledger=JsonExecutionLedger(config.log_directory / "idempotency.json"),
        kill_switch=kill_switch,
    )
    try:
        server = build_server(args.host, args.port, reporter, kill_switch, args.token)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"auto-trade dashboard on {server.url}")
    print(f"control token: {server.token}")
    print("The dashboard can activate the kill switch; keep this token private.")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = AppConfig.from_env()
    if args.command in {"status", "diagnostics"}:
        print(json.dumps(_diagnostics(config), indent=2, default=str))
        return 0
    if args.command == "position-snapshot":
        adapter = MT5DesktopAdapter(config.terminal_profile())
        try:
            adapter.connect()
            positions = adapter.capture_positions()
        except AutoTradeError as exc:
            print(json.dumps({"status": "UNAVAILABLE", "error": str(exc)}, indent=2))
            return 1
        print(
            json.dumps(
                {
                    "status": "AVAILABLE",
                    "positions": [
                        {
                            "position_id": position.position_id,
                            "symbol": position.symbol,
                            "side": position.side,
                            "volume": str(position.volume),
                        }
                        for position in positions
                    ],
                },
                indent=2,
            )
        )
        return 0
    if args.command == "recovery":
        records = JsonExecutionLedger(config.log_directory / "idempotency.json").records()
        review = {
            "pending": [record for record in records if record.get("status") == "REQUESTED"],
            "unknown": [record for record in records if record.get("status") == "UNKNOWN"],
        }
        print(json.dumps(review, indent=2, default=str))
        return 0
    if args.command == "make-signal":
        now = utc_now()
        try:
            signal = TradeSignal.from_dict(
                {
                    "id": f"manual-{now.strftime('%Y%m%dT%H%M%SZ')}",
                    "timestamp": now.isoformat().replace("+00:00", "Z"),
                    "expiration": (now + timedelta(seconds=args.valid_seconds))
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "source": "manual-cli",
                    "symbol": args.symbol,
                    "action": args.action,
                    "volume": str(args.volume),
                    "comment": args.comment,
                }
            )
        except (InvalidOperation, AutoTradeError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(signal.to_dict(), indent=2), encoding="utf-8")
        print(json.dumps({"written": str(args.output), "signal": signal.to_dict()}, indent=2))
        return 0
    if args.command == "dashboard":
        return _dashboard(config, args)
    if args.command == "evaluate":
        return _evaluate(config, args)
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
        from ..application.kill_switch import FileKillSwitch
        from ..infrastructure.automation.execution import ExecutionGate
        from ..interfaces import kill_switch_path

        # File backed so an emergency stop raised by the dashboard, another
        # process, or a previous run still blocks execution after a restart.
        kill_switch = FileKillSwitch(kill_switch_path(config.log_directory))
        terminal = (
            DryRunTerminalAdapter()
            if args.mock
            else MT5DesktopAdapter(
                config.terminal_profile(),
                # This path is a dry run, so the final control is unreachable by
                # construction and the opt-in is deliberately not consulted.
                gate=ExecutionGate(
                    enabled=False,
                    dry_run=True,
                    demo_only=config.policy.demo_only,
                    kill_switch_active=kill_switch.active,
                ),
            )
        )
        workflow = ExecutionWorkflow(
            adapter=terminal,
            risk_engine=RiskEngine(config.risk),
            profile=config.terminal_profile(),
            policy=policy,
            kill_switch=kill_switch,
            audit=audit.record,
            ledger=JsonExecutionLedger(config.log_directory / "idempotency.json"),
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
