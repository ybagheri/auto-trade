from __future__ import annotations

import json
from typing import Any

from ..application.kill_switch import FileKillSwitch
from ..application.ledger import JsonExecutionLedger
from ..application.metrics import summarize
from ..domain.exceptions import AutoTradeError
from ..domain.models import utc_now
from ..infrastructure.automation.positions_file import MT5FilePositionSnapshotProvider
from ..infrastructure.configuration import AppConfig

AUDIT_FILENAME = "audit.log"
SIGNAL_SUFFIXES = (".json",)


class StatusReporter:
    """Read-only view of the running configuration for the local dashboard.

    Nothing here opens the MT5 window or changes state. The MT5 Trade grid on this
    build does not expose position values, so the dashboard reports position
    observation as unavailable rather than guessing.
    """

    def __init__(
        self,
        config: AppConfig,
        ledger: JsonExecutionLedger,
        kill_switch: FileKillSwitch,
    ) -> None:
        self.config = config
        self.ledger = ledger
        self.kill_switch = kill_switch

    def status(self) -> dict[str, Any]:
        return {
            "checked_at": utc_now().isoformat().replace("+00:00", "Z"),
            "terminal": {
                "terminal_path": str(self.config.terminal_path),
                "terminal_exists": self.config.terminal_path.is_file(),
                "data_path": str(self.config.data_path),
                "data_path_exists": self.config.data_path.is_dir(),
                "instance_name": self.config.instance_name,
            },
            "safety": {
                "dry_run": self.config.policy.dry_run,
                "demo_only": self.config.policy.demo_only,
                "confirmation": self.config.policy.confirmation.value,
                "kill_switch_active": self.kill_switch.active,
                "kill_switch_reason": self.kill_switch.reason(),
            },
            "counts": {
                "executions": len(self.ledger.records()),
                "pending": len(self.ledger.pending()),
            },
        }

    def risk(self) -> dict[str, Any]:
        return {
            "allowed_symbols": sorted(self.config.risk.allowed_symbols),
            "max_volume": str(self.config.risk.max_volume),
            "max_orders_per_minute": self.config.risk.max_orders_per_minute,
            "expiration_seconds": self.config.risk.expiration_seconds,
        }

    def positions(self) -> dict[str, Any]:
        provider = MT5FilePositionSnapshotProvider(
            self.config.data_path / "MQL5" / "Files"
        )
        try:
            positions = provider.positions()
        except AutoTradeError as exc:
            return {"status": "UNAVAILABLE", "error": str(exc), "positions": []}
        return {
            "status": "AVAILABLE",
            "error": None,
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

    def executions(self) -> dict[str, Any]:
        records = sorted(
            self.ledger.records(), key=lambda item: str(item.get("timestamp", "")), reverse=True
        )
        return {"executions": list(records)}

    def metrics(self, tail: int = 2000) -> dict[str, Any]:
        """Latency and counters for the executions the audit tail covers.

        Read-only, and derived from the same log the dashboard already shows. The
        unresolved count is the figure an operator acts on: it is the number of
        attempts that used a final control and recorded no result, each of which
        needs the account looked at by hand.
        """
        parsed = self.logs(tail)
        return summarize(
            [event for event in parsed.get("events", []) if isinstance(event, dict)],
            truncated=bool(parsed.get("truncated")),
        ).to_dict()

    def signals(self) -> dict[str, Any]:
        directory = self.config.signal_directory
        pending: list[dict[str, Any]] = []
        if directory.is_dir():
            for path in sorted(directory.glob("*")):
                if path.suffix.lower() not in SIGNAL_SUFFIXES or not path.is_file():
                    continue
                entry: dict[str, Any] = {
                    "file": path.name,
                    "modified": path.stat().st_mtime,
                    "readable": True,
                    "error": None,
                }
                try:
                    entry["signal"] = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    entry["readable"] = False
                    entry["error"] = str(exc)
                pending.append(entry)
        return {"directory": str(directory), "count": len(pending), "signals": pending}

    def logs(self, tail: int = 200) -> dict[str, Any]:
        path = self.config.log_directory / AUDIT_FILENAME
        if not path.is_file():
            return {"events": [], "truncated": False}
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        limit = max(1, min(int(tail), 5000))
        selected = lines[-limit:]
        events: list[Any] = []
        for line in selected:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                events.append({"raw": line})
        return {"events": events, "truncated": len(selected) < len(lines)}
