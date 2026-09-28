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
from ..domain.exceptions import AutoTradeError, NoSignalAvailable, SignalSourceError
from ..domain.models import AuditEvent, PositionSnapshot, TradeSignal, utc_now
from ..infrastructure.automation import MT5DesktopAdapter
from ..infrastructure.configuration import AppConfig
from ..infrastructure.logging import AuditLogger
from ..infrastructure.net import safe_url_summary
from ..infrastructure.terminal import WindowsTerminalDiscovery


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="auto-trade")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="show configured safety status")
    subparsers.add_parser("diagnostics", help="show environment and MT5 diagnostics")
    subparsers.add_parser("recovery", help="review pending and unknown execution records")
    subparsers.add_parser("position-snapshot", help="read MT5 positions for verification")
    bundle = subparsers.add_parser(
        "diagnostics-bundle",
        help="export configuration, terminal, position, and log evidence to a zip file",
    )
    bundle.add_argument(
        "--output",
        type=Path,
        default=None,
        help="where to write the bundle; defaults to a timestamped file in the current directory",
    )
    configure = subparsers.add_parser(
        "configure", help="write a reviewed .env configuration for this machine"
    )
    configure.add_argument(
        "--target",
        type=Path,
        default=Path(".env"),
        help="the env file to write; defaults to .env in the current directory",
    )
    configure.add_argument(
        "--overwrite",
        action="store_true",
        help="replace managed keys that already hold a different value",
    )
    configure.add_argument(
        "--dry-run",
        action="store_true",
        help="print the configuration that would be written and change nothing",
    )
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
    fetch = subparsers.add_parser(
        "fetch-signal",
        help="pull one signal from the configured authenticated localhost HTTP source",
    )
    fetch.add_argument(
        "--output",
        type=Path,
        default=None,
        help="where to write the signal; defaults to the configured signal directory",
    )
    execute = subparsers.add_parser(
        "execute", help="execute one explicitly confirmed demo signal"
    )
    execute.add_argument("signal_file", type=Path)
    execute.add_argument(
        "--confirm-demo",
        action="store_true",
        help="required acknowledgement that this may place a demo order",
    )
    close = subparsers.add_parser(
        "close-position",
        help="close one position this application opened, and prove it closed",
    )
    close.add_argument("ticket", help="position ticket as reported by the verifier")
    close.add_argument(
        "--confirm-demo",
        action="store_true",
        help="required acknowledgement that this closes a real demo position",
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
        # The endpoint is summarised without credentials, query, or fragment so
        # diagnostics can never echo the configured token.
        "http_signal_endpoint": safe_url_summary(config.http_signal_url),
        "http_signal_token_configured": bool(config.http_signal_token),
    }


def _evaluate(config: AppConfig, args: argparse.Namespace) -> int:
    """Ask the configured strategy for a signal and record the decision.

    This is the integration point for a market-analysis library: the library only
    has to expose a strategy, and the bridge handles available position context,
    the signal file, and the audit record.
    """
    from ..application.strategy import build_context, load_strategy
    from ..infrastructure.automation.positions_file import MT5FilePositionSnapshotProvider

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
    position_note = "position observation unavailable"
    try:
        provider = MT5FilePositionSnapshotProvider(
            config.data_path / "MQL5" / "Files"
        )
        snapshot = provider.snapshot()
        positions = snapshot.positions
        position_note = snapshot.reference
    except AutoTradeError as exc:
        print(f"WARNING: {exc}", file=sys.stderr)

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


def _diagnostics_bundle(config: AppConfig, args: argparse.Namespace) -> int:
    """Write one archive with everything a support report needs.

    The bundle is read-only: it discovers the terminal and reads local files, and
    it never opens an order dialog or touches an execution control.
    """
    from ..application.diagnostics import (
        DiagnosticsBundle,
        DiagnosticSubject,
        default_bundle_name,
    )
    from ..application.kill_switch import FileKillSwitch
    from ..infrastructure.automation.positions_file import MT5FilePositionSnapshotProvider
    from ..interfaces import kill_switch_path

    subject = DiagnosticSubject(
        profile=config.terminal_profile(),
        signal_directory=config.signal_directory,
        log_directory=config.log_directory,
        policy=config.policy,
        risk=config.risk,
        http_signal_endpoint=safe_url_summary(config.http_signal_url),
        http_signal_token=config.http_signal_token,
        strategy_spec=config.strategy_spec,
    )
    bundle = DiagnosticsBundle(
        subject=subject,
        kill_switch=FileKillSwitch(kill_switch_path(config.log_directory)),
        ledger=JsonExecutionLedger(config.log_directory / "idempotency.json"),
        position_provider=MT5FilePositionSnapshotProvider(
            config.data_path / "MQL5" / "Files"
        ),
        terminal_discovery=WindowsTerminalDiscovery(),
        application_version=_application_version(),
    )
    target = args.output or Path(default_bundle_name())
    try:
        written = bundle.export(Path(target))
    except OSError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "EXPORTED",
                "bundle": str(written),
                "entries": [f"{name}.json" for name in sorted(bundle.sections)],
                "terminal": bundle.sections["terminal"]["status"],
                "positions": bundle.sections["positions"]["status"],
            },
            indent=2,
        )
    )
    return 0


def _configure(config: AppConfig, args: argparse.Namespace) -> int:
    """Ask for the machine-specific settings and write them to an env file.

    Execution stays disabled in the result. The wizard has no answer that can
    turn it on, so a fresh configuration cannot be the reason an order is sent.
    """
    from ..application.wizard import (
        EXECUTION_KEY,
        ConfigurationError,
        WizardAnswers,
        apply_to_file,
        collect_answers,
        render,
        validate,
    )

    defaults = WizardAnswers(
        terminal_path=str(config.terminal_path),
        data_path=str(config.data_path),
        instance_name=config.instance_name,
        allowed_symbols=",".join(sorted(config.risk.allowed_symbols)),
        max_volume=str(config.risk.max_volume),
        max_orders_per_minute=config.risk.max_orders_per_minute,
        expiration_seconds=config.risk.expiration_seconds,
        signal_directory=str(config.signal_directory),
        log_directory=str(config.log_directory),
        dry_run=config.policy.dry_run,
        demo_only=config.policy.demo_only,
    )
    print("Configure auto-trade. Press Enter to keep the value in brackets.")
    try:
        answers = collect_answers(_ask, defaults)
        validate(answers)
    except (ConfigurationError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    rendered = render(answers)
    if args.dry_run:
        print(rendered)
        print(f"# nothing was written; {args.target} is unchanged")
        return 0
    try:
        written = apply_to_file(answers, args.target, overwrite=args.overwrite)
    except (ConfigurationError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {written}")
    print(rendered)
    print(
        f"{EXECUTION_KEY} stays false. A reviewed manual edit is required before any "
        "final execution control is reachable."
    )
    return 0


def _ask(prompt: str, default: str) -> str:
    try:
        return input(f"{prompt}: ")
    except EOFError:
        # A non-interactive run must not hang waiting for an answer.
        return default


def _application_version() -> str:
    try:
        from importlib.metadata import version

        return f"auto-trade {version('auto-trade')}"
    except Exception:  # noqa: BLE001
        return "auto-trade (version unknown)"


def _fetch_signal(config: AppConfig, args: argparse.Namespace) -> int:
    """Pull one signal from the configured source into the signal directory.

    Fetching is a read: the response is written as a normal pending signal file
    and still has to pass the risk engine, the kill switch, and every other gate
    before anything reaches the terminal. The source is whichever single one is
    configured; two configured sources are refused.
    """
    try:
        provider = config.signal_source()
    except SignalSourceError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if provider is None:
        print(
            "ERROR: no signal source configured. Set exactly one of "
            "AUTO_TRADE_HTTP_SIGNAL_URL, AUTO_TRADE_PIPE_SIGNAL_NAME, or "
            "AUTO_TRADE_WS_SIGNAL_URL, with its matching token. See docs/SIGNAL_PROTOCOL.md.",
            file=sys.stderr,
        )
        return 2
    try:
        provider.start()
    except AutoTradeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    try:
        signal = provider.receive()
    except NoSignalAvailable as exc:
        print(json.dumps({"status": "NO_SIGNAL", "detail": str(exc)}, indent=2))
        return 0
    except (AutoTradeError, OSError, TimeoutError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        provider.stop()

    target = args.output or (config.signal_directory / f"{signal.signal_id}.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(signal.to_dict(), indent=2), encoding="utf-8")
    AuditLogger(config.log_directory).record(
        AuditEvent(
            component="signal-provider",
            event_type="received",
            message="signal received from the configured source",
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            action=signal.action.value,
            volume=signal.volume,
        )
    )
    print(
        json.dumps(
            {
                "status": "RECEIVED",
                "source": type(provider).__name__,
                "written": str(target),
                "signal": signal.to_dict(),
            },
            indent=2,
        )
    )
    return 0


def _close_position(config: AppConfig, args: argparse.Namespace) -> int:
    """Close one position by ticket, if the gates and the ledger allow it.

    The position must be one this application opened. A ticket that is not in
    the execution ledger belongs to somebody else, and this command refuses it
    rather than closing a human's position.
    """
    from ..application.kill_switch import FileKillSwitch
    from ..infrastructure.automation.execution import ExecutionGate
    from ..interfaces import kill_switch_path

    if not args.confirm_demo:
        print("ERROR: --confirm-demo is required", file=sys.stderr)
        return 2
    kill_switch = FileKillSwitch(kill_switch_path(config.log_directory))
    ledger = JsonExecutionLedger(config.log_directory / "idempotency.json")
    known = {str(record.get("order_reference") or "") for record in ledger.records()}
    if args.ticket not in known:
        print(
            f"ERROR: ticket {args.ticket} is not in the execution ledger, so it is not a "
            "position this application opened; close it by hand",
            file=sys.stderr,
        )
        return 2
    if not config.policy.execution_enabled and not _flag_enabled("AUTO_TRADE_ENABLE_CLOSE"):
        print(
            "ERROR: closing is disabled. Set AUTO_TRADE_ENABLE_CLOSE=true in .env, or in "
            "this shell only:\n"
            "  PowerShell  $env:AUTO_TRADE_ENABLE_CLOSE=\"true\"\n"
            "  cmd         set AUTO_TRADE_ENABLE_CLOSE=true",
            file=sys.stderr,
        )
        return 2
    terminal = MT5DesktopAdapter(
        config.terminal_profile(),
        gate=ExecutionGate(
            enabled=config.policy.execution_enabled,
            dry_run=config.policy.dry_run,
            demo_only=config.policy.demo_only,
            kill_switch_active=kill_switch.active,
        ),
        close_gate=config.close_position_gate(kill_switch.active),
    )
    try:
        terminal.connect()
        result = terminal.close_position(args.ticket)
    except (AutoTradeError, OSError, TimeoutError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    AuditLogger(config.log_directory).record(
        AuditEvent(
            component="position-close",
            event_type="result",
            message=result.message,
            state=result.state,
            action=f"CLOSE {args.ticket}",
        )
    )
    print(
        json.dumps(
            {
                "status": result.status.value,
                "state": result.state,
                "message": result.message,
                "position_id": result.order_reference,
            },
            indent=2,
        )
    )
    return 0 if result.status.value == "CLOSED" else 1


def _flag_enabled(name: str) -> bool:
    import os

    return os.getenv(name, "false").strip().lower() in {"1", "true", "yes", "on"}


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


def _execute_live(config: AppConfig, args: argparse.Namespace) -> int:
    if not args.confirm_demo:
        print("ERROR: --confirm-demo is required", file=sys.stderr)
        return 2
    if not config.policy.execution_enabled:
        print(
            "ERROR: execution is disabled; set AUTO_TRADE_ENABLE_EXECUTION=true",
            file=sys.stderr,
        )
        return 2
    if config.policy.dry_run:
        print("ERROR: AUTO_TRADE_DRY_RUN must be false", file=sys.stderr)
        return 2
    if not config.policy.demo_only:
        print("ERROR: demo-only policy must remain enabled", file=sys.stderr)
        return 2

    from ..application.kill_switch import FileKillSwitch
    from ..infrastructure.automation.execution import ExecutionGate
    from ..interfaces import kill_switch_path

    kill_switch = FileKillSwitch(kill_switch_path(config.log_directory))
    gate = ExecutionGate(
        enabled=True,
        dry_run=False,
        demo_only=True,
        kill_switch_active=kill_switch.active,
    )
    terminal = MT5DesktopAdapter(config.terminal_profile(), gate=gate)
    policy = type(config.policy)(
        dry_run=False,
        demo_only=True,
        confirmation=config.policy.confirmation,
        execution_enabled=True,
    )
    workflow = ExecutionWorkflow(
        adapter=terminal,
        risk_engine=RiskEngine(config.risk),
        profile=config.terminal_profile(),
        policy=policy,
        kill_switch=kill_switch,
        audit=AuditLogger(config.log_directory).record,
        ledger=JsonExecutionLedger(config.log_directory / "idempotency.json"),
    )
    try:
        result = workflow.execute(_signal(args.signal_file))
    except (OSError, ValueError, AutoTradeError, TimeoutError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    output = {
        "status": result.status.value,
        "state": result.state,
        "message": result.message,
        "order_reference": result.order_reference,
        "evidence": result.evidence.to_dict() if result.evidence else None,
        "error": result.error,
    }
    print(json.dumps(output, indent=2))
    return 0 if result.status.value == "ACCEPTED" else 1


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = AppConfig.from_env()
    if args.command in {"status", "diagnostics"}:
        print(json.dumps(_diagnostics(config), indent=2, default=str))
        return 0
    if args.command == "diagnostics-bundle":
        return _diagnostics_bundle(config, args)
    if args.command == "configure":
        return _configure(config, args)
    if args.command == "position-snapshot":
        from ..infrastructure.automation.positions_file import MT5FilePositionSnapshotProvider

        try:
            provider = MT5FilePositionSnapshotProvider(
                config.data_path / "MQL5" / "Files"
            )
            positions = provider.positions()
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
    if args.command == "fetch-signal":
        return _fetch_signal(config, args)
    if args.command == "execute":
        return _execute_live(config, args)
    if args.command == "close-position":
        return _close_position(config, args)
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
