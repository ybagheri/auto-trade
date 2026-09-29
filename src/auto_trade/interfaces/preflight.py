"""The `terminal-check` preflight: is this build still the one the code expects?

A MetaTrader update is the one ordinary event that can silently invalidate this
project, because every control it uses is identified by a value measured on a
specific build. The order path fails closed when a control moves, which is
correct, but it fails at the moment of trading.

This command answers the question earlier and without trading anything. It
resolves the configured terminal, confirms the window is pinned to that process,
opens the order dialog, reads the control tree, closes the dialog, and reports
each expected identifier as present, changed, or absent. **It never uses a final
control.** There is no flag to make it do so, because a probe whose output
depends on a click is not a probe.

The report is filed under the terminal build it was taken on, so a later run on
a different build is a separate record rather than a silent overwrite.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ..domain.exceptions import AutoTradeError
from ..domain.models import AuditEvent
from ..infrastructure.automation.control_probe import (
    MISSING,
    OK,
    ControlReport,
    probe_build,
    probe_main_window,
    probe_order_dialog,
    probe_trade_grid,
    summarise,
)
from ..infrastructure.automation.positions_file import MT5FilePositionSnapshotProvider
from ..infrastructure.automation.window_manager import MT5DesktopAdapter
from ..infrastructure.configuration import AppConfig
from ..infrastructure.logging import AuditLogger
from ..infrastructure.terminal.discovery import WindowsTerminalDiscovery

REPORT_FILENAME = "terminal_check.json"
REPORT_HISTORY = 5


def _snapshot_build(provider: MT5FilePositionSnapshotProvider) -> int | None:
    """Read ``terminal_build`` from the live snapshot, if there is one.

    The build is read from the indicator's own output rather than from the
    executable's version resource, so it describes the terminal that wrote the
    positions rather than a file on disk.
    """
    try:
        snapshot = provider.snapshot()
    except AutoTradeError:
        return None
    value = getattr(snapshot, "terminal_build", None)
    return int(value) if isinstance(value, int) else None


def run_check(config: AppConfig) -> dict[str, Any]:
    """Inspect the configured terminal and return a report. Never trades."""
    profile = config.terminal_profile()
    reports: list[ControlReport] = []

    resolved = WindowsTerminalDiscovery().resolve(profile)
    adapter = MT5DesktopAdapter(
        profile,
        position_provider=MT5FilePositionSnapshotProvider(
            Path(profile.data_path) / "MQL5" / "Files"
        ),
    )
    account = adapter.connect()
    window = adapter.window_manager.root

    build = _snapshot_build(adapter.position_provider)
    reports.extend(probe_build(build))
    reports.append(
        ControlReport(
            "terminal_identity",
            OK,
            f"pid {resolved.process_id}",
            f"pid {resolved.process_id}",
            (
                "the window was selected by process id, not by its title; "
                f"{resolved.candidates_considered} terminal(s) share this executable path"
            ),
        )
    )
    reports.append(
        ControlReport(
            "account_type",
            OK if account.connected else MISSING,
            "demo",
            account.account_type.value,
            "the title must identify a demo account",
        )
    )

    dialog_opened = False
    try:
        reports.extend(probe_main_window(window))
        dialog = adapter.window_manager.open_order_dialog()
        dialog_opened = True
        reports.extend(probe_order_dialog(dialog))
    except AutoTradeError as exc:
        reports.append(
            ControlReport(
                "order_dialog",
                "MISSING",
                "opens and exposes its controls",
                f"could not be inspected: {exc}",
                "the order path would refuse to prepare a request",
            )
        )
    finally:
        if dialog_opened:
            try:
                adapter.window_manager.close_order_dialog(timeout_seconds=2.0)
            except AutoTradeError:
                # Left for the operator. A probe must not leave a dialog open
                # over a trading terminal, and it must not click anything else
                # to tidy up after itself either.
                pass

    reports.extend(probe_trade_grid(window))
    reports.append(
        ControlReport(
            "position_observation",
            "OK" if build else "NOT_PROBED",
            "a snapshot the verifier can read",
            f"terminal_build {build}" if build else "no snapshot available",
            (
                "verification compares positions, so without a snapshot no execution "
                "can be accepted"
            ),
        )
    )

    summary = summarise(reports)
    summary["terminal"] = resolved.to_dict()
    summary["terminal"]["build"] = build
    summary["account"] = account.account_type.value
    summary["observed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    summary["note"] = (
        "Read-only. No final control was used, and no order could be placed by this "
        "command. A DRIFTED or MISSING row means this build no longer presents a "
        "control this project measured; nothing here substitutes a new value for it."
    )
    return summary


def record(config: AppConfig, summary: dict[str, Any]) -> Path:
    """Write the report beside the logs and add an audit event.

    The history is kept rather than overwritten, which is what makes "did the
    update change anything" answerable after the fact instead of from memory.
    """
    target = config.log_directory / REPORT_FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)
    history: list[dict[str, Any]] = []
    if target.is_file():
        try:
            previous = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previous = None
        if isinstance(previous, dict) and isinstance(previous.get("history"), list):
            history = [item for item in previous["history"] if isinstance(item, dict)]
    history.append(summary)
    target.write_text(
        json.dumps({"history": history[-REPORT_HISTORY:]}, indent=2, default=str),
        encoding="utf-8",
    )
    AuditLogger(config.log_directory).record(
        AuditEvent(
            component="terminal-check",
            event_type="control-probe",
            message=(
                f"control probe reported {summary.get('verdict')} on build "
                f"{(summary.get('terminal') or {}).get('build')}"
            ),
            state=str(summary.get("verdict")),
        )
    )
    return target


def compare_builds(config: AppConfig) -> dict[str, Any]:
    """Read the recorded history and report whether the verdict changed.

    This is the part that answers the question an update actually raises: not
    "does it work" but "did it stop working the way it worked".
    """
    target = config.log_directory / REPORT_FILENAME
    if not target.is_file():
        return {
            "status": "NO_HISTORY",
            "detail": f"no previous report in {target}; run terminal-check first",
        }
    try:
        stored = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "UNREADABLE", "detail": f"{target} could not be read"}
    history = [
        item for item in stored.get("history", []) if isinstance(item, dict)
    ]
    if len(history) < 2:
        return {
            "status": "INSUFFICIENT",
            "detail": (
                f"{len(history)} report(s) recorded; at least two are needed, and a "
                "comparison against a single run would say nothing. Run "
                "terminal-check again, or after the next MT5 update."
            ),
            "reports": len(history),
            "verdict_now": history[-1].get("verdict") if history else None,
            "build_now": (history[-1].get("terminal") or {}).get("build")
            if history
            else None,
        }
    first, latest = history[0], history[-1]
    changed = {
        str(before["control"])
        for earlier, later in zip(history, history[1:])
        for before, after in zip(
            earlier.get("controls", []), later.get("controls", [])
        )
        if isinstance(before, dict)
        and isinstance(after, dict)
        and before.get("control") == after.get("control")
        and before.get("found") != after.get("found")
    }
    return {
        "status": "COMPARED",
        "reports": len(history),
        "verdict_before": first.get("verdict"),
        "verdict_now": latest.get("verdict"),
        "verdict_changed": first.get("verdict") != latest.get("verdict"),
        "build_before": (first.get("terminal") or {}).get("build"),
        "build_now": (latest.get("terminal") or {}).get("build"),
        "controls_that_changed": sorted(changed),
    }
