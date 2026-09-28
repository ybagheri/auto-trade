from __future__ import annotations

import ctypes
import importlib.util
import json
import platform
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..domain.exceptions import AutoTradeError
from ..domain.models import ExecutionPolicy, RiskLimits, TerminalProfile, utc_now
from ..domain.protocols import KillSwitch, PositionSnapshotProvider, TerminalDiscovery
from .kill_switch import FileKillSwitch
from .ledger import ExecutionLedger
from .metrics import summarize

BUNDLE_VERSION = 1
MAX_SIGNAL_FILES = 50
MAX_AUDIT_EVENTS = 500
OPTIONAL_PACKAGES = ("pywinauto", "comtypes", "win32api", "win32com")

REDACTIONS = (
    "the .env file and every value inside it",
    "the HTTP signal source token; only whether one is configured is reported",
    "credentials, query, and fragment of the configured signal endpoint URL",
)


@dataclass(frozen=True)
class DiagnosticSubject:
    """What a bundle is allowed to describe about this installation.

    ``http_signal_endpoint`` must already be a redacted summary, produced by
    ``infrastructure.net.safe_url_summary``. The token is accepted only so the
    bundle can report that one exists; it is never written to the archive.
    """

    profile: TerminalProfile
    signal_directory: Path
    log_directory: Path
    policy: ExecutionPolicy
    risk: RiskLimits
    http_signal_endpoint: str = ""
    http_signal_token: str = ""
    strategy_spec: str = ""


@dataclass
class DiagnosticsBundle:
    """Collect the evidence needed to diagnose an installation into one archive.

    This exists because the remaining validation steps are manual: someone has
    to attach the terminal, the indicator, and a failing run to a report. The
    bundle gathers the read-only view of the same facts the dashboard shows, so a
    report does not depend on the reporter remembering which command to run.

    Nothing here opens the MT5 window, clicks a control, or places an order. The
    terminal is only discovered, and a discovery failure is recorded as text
    rather than raised, because a failure is exactly what a bundle is for.
    """

    subject: DiagnosticSubject
    kill_switch: KillSwitch
    ledger: ExecutionLedger
    position_provider: PositionSnapshotProvider | None = None
    terminal_discovery: TerminalDiscovery | None = None
    audit_tail: int = MAX_AUDIT_EVENTS
    application_version: str = "auto-trade"
    sections: dict[str, Any] = field(default_factory=dict)

    def collect(self) -> dict[str, Any]:
        audit_log = self._audit_log()
        collected: dict[str, Any] = {
            "environment": self._environment(),
            "configuration": self._configuration(),
            "terminal": self._terminal(),
            "kill-switch": self._kill_switch(),
            "positions": self._positions(),
            "executions": self._executions(),
            # Derived from the same events, so a report cannot show a latency
            # summary for a window the log tail does not actually cover.
            "metrics": summarize(
                [event for event in audit_log.get("events", []) if isinstance(event, dict)],
                truncated=bool(audit_log.get("truncated")),
            ).to_dict(),
            "signals": self._signals(),
            "audit-log": audit_log,
        }
        self.sections = collected
        return collected

    def export(self, target: Path) -> Path:
        """Write the bundle to *target* and return the path actually written."""
        if not self.sections:
            self.collect()
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            "bundle_version": BUNDLE_VERSION,
            "created_at": utc_now().isoformat().replace("+00:00", "Z"),
            "application": self.application_version,
            "python": sys.version,
            "platform": platform.platform(),
            "contains_no_credentials": True,
            "excluded": list(REDACTIONS),
            "entries": sorted(f"{name}.json" for name in self.sections),
        }
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "manifest.json", _encode(manifest), compress_type=zipfile.ZIP_DEFLATED
            )
            for name, payload in self.sections.items():
                archive.writestr(f"{name}.json", _encode(payload))
        return path

    # -- sections ---------------------------------------------------------

    def _environment(self) -> dict[str, Any]:
        return {
            "python": sys.version,
            "python_executable": sys.executable,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "working_directory": str(Path.cwd()),
            "optional_packages": {
                name: _module_available(name) for name in OPTIONAL_PACKAGES
            },
            "display": _display_diagnostics(),
        }

    def _configuration(self) -> dict[str, Any]:
        subject = self.subject
        return {
            "terminal": {
                "name": subject.profile.name,
                "terminal_path": subject.profile.terminal_path,
                "data_path": subject.profile.data_path,
                "instance_name": subject.profile.instance_name,
            },
            "paths": {
                "signal_directory": str(subject.signal_directory),
                "log_directory": str(subject.log_directory),
            },
            "safety": {
                "dry_run": subject.policy.dry_run,
                "demo_only": subject.policy.demo_only,
                "confirmation": subject.policy.confirmation.value,
                "execution_enabled": subject.policy.execution_enabled,
            },
            "risk": {
                "allowed_symbols": sorted(subject.risk.allowed_symbols),
                "max_volume": str(subject.risk.max_volume),
                "max_orders_per_minute": subject.risk.max_orders_per_minute,
                "expiration_seconds": subject.risk.expiration_seconds,
            },
            "sources": {
                "file_directory": str(subject.signal_directory),
                "http_endpoint": subject.http_signal_endpoint,
                "http_token_configured": bool(subject.http_signal_token),
            },
            "strategy": subject.strategy_spec,
        }

    def _terminal(self) -> dict[str, Any]:
        if self.terminal_discovery is None:
            return {"status": "NOT CHECKED", "detail": "no discovery service was supplied"}
        try:
            profile = self.terminal_discovery.discover(self.subject.profile)
        except AutoTradeError as exc:
            return {"status": "NOT FOUND", "detail": str(exc)}
        except OSError as exc:
            return {"status": "NOT FOUND", "detail": f"{type(exc).__name__}: {exc}"}
        return {
            "status": "FOUND",
            "detail": "",
            "profile": {
                "name": profile.name,
                "instance_name": profile.instance_name,
                "terminal_path": profile.terminal_path,
                "data_path": profile.data_path,
            },
        }

    def _kill_switch(self) -> dict[str, Any]:
        reason = ""
        if isinstance(self.kill_switch, FileKillSwitch):
            reason = self.kill_switch.reason()
        return {"active": self.kill_switch.active, "reason": reason}

    def _positions(self) -> dict[str, Any]:
        if self.position_provider is None:
            return {"status": "NOT CHECKED", "detail": "no position source was supplied"}
        try:
            positions = self.position_provider.positions()
        except AutoTradeError as exc:
            return {"status": "UNAVAILABLE", "detail": str(exc), "positions": []}
        return {
            "status": "AVAILABLE",
            "detail": "",
            "positions": [
                {
                    "position_id": position.position_id,
                    "symbol": position.symbol,
                    "side": position.side,
                    "volume": str(position.volume),
                }
                for position in positions
            ],
        }

    def _executions(self) -> dict[str, Any]:
        try:
            records = self.ledger.records()
        except AutoTradeError as exc:
            return {"status": "UNAVAILABLE", "detail": str(exc), "records": []}
        return {
            "status": "AVAILABLE",
            "pending": [record for record in records if record.get("status") == "REQUESTED"],
            "unknown": [record for record in records if record.get("status") == "UNKNOWN"],
            "count": len(records),
        }

    def _signals(self) -> dict[str, Any]:
        directory = self.subject.signal_directory
        files: list[dict[str, Any]] = []
        if directory.is_dir():
            for path in sorted(directory.glob("*.json"))[:MAX_SIGNAL_FILES]:
                entry: dict[str, Any] = {"file": path.name, "readable": True, "signal": None}
                try:
                    entry["signal"] = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    entry["readable"] = False
                    entry["detail"] = f"{type(exc).__name__}: {exc}"
                files.append(entry)
        return {
            "directory": str(directory),
            "count": len(files),
            "truncated": directory.is_dir()
            and len(list(directory.glob("*.json"))) > len(files),
            "files": files,
        }

    def _audit_log(self) -> dict[str, Any]:
        path = self.subject.log_directory / "audit.log"
        if not path.is_file():
            return {"path": str(path), "present": False, "events": []}
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            return {"path": str(path), "present": True, "error": str(exc), "events": []}
        limit = max(1, min(int(self.audit_tail), MAX_AUDIT_EVENTS))
        events: list[Any] = []
        for line in lines[-limit:]:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                events.append({"raw": line})
        return {
            "path": str(path),
            "present": True,
            "truncated": len(events) < len(lines),
            "events": events,
        }


def _encode(payload: Any) -> str:
    return json.dumps(payload, indent=2, default=str, ensure_ascii=False)


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _display_diagnostics() -> dict[str, Any]:
    """Report DPI and monitor facts, because UI automation depends on them.

    A bundle must not fail while being written, so an unavailable API is
    recorded as a reason instead of raised.
    """
    if sys.platform != "win32":
        return {"available": False, "reason": f"unsupported platform: {sys.platform}"}
    try:
        user32 = getattr(ctypes, "windll").user32
        get_dpi = getattr(user32, "GetDpiForSystem", None)
        return {
            "available": True,
            "dpi": int(get_dpi()) if callable(get_dpi) else None,
            "monitors": int(user32.GetSystemMetrics(80)),
            "screen": [int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))],
            "virtual_screen": [
                int(user32.GetSystemMetrics(78)),
                int(user32.GetSystemMetrics(79)),
            ],
        }
    except (AttributeError, OSError, ValueError) as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}


def default_bundle_name() -> str:
    return f"auto-trade-diagnostics-{utc_now().strftime('%Y%m%dT%H%M%SZ')}.zip"
