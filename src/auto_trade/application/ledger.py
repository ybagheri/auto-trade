from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any, Protocol

from ..domain.exceptions import ExecutionUnknownError
from ..domain.models import ExecutionResult


class ExecutionLedger(Protocol):
    def contains(self, signal_id: str) -> bool: ...

    def record_attempt(self, signal_id: str, execution_id: str) -> None: ...

    def record_result(self, result: ExecutionResult) -> None: ...

    def records(self) -> tuple[dict[str, Any], ...]: ...


class JsonExecutionLedger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = Lock()
        self._entries = self._read()

    def contains(self, signal_id: str) -> bool:
        with self._lock:
            return signal_id in self._entries

    def record_attempt(self, signal_id: str, execution_id: str) -> None:
        with self._lock:
            self._entries[signal_id] = {
                "signal_id": signal_id,
                "execution_id": execution_id,
                "status": "REQUESTED",
                "state": "EXECUTING",
                "timestamp": datetime.now(UTC).isoformat(),
            }
            self._write()

    def record_result(self, result: ExecutionResult) -> None:
        with self._lock:
            existing = self._entries.get(result.signal_id)
            if existing is not None and existing.get("execution_id") != result.execution_id:
                return
            self._entries[result.signal_id] = {
                "signal_id": result.signal_id,
                "execution_id": result.execution_id,
                "status": result.status.value,
                "state": result.state,
                "message": result.message,
                "order_reference": result.order_reference,
                "timestamp": datetime.now(UTC).isoformat(),
            }
            self._write()

    def records(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(dict(entry) for entry in self._entries.values())

    def pending(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(
                dict(entry)
                for entry in self._entries.values()
                if entry.get("status") == "REQUESTED"
            )

    def _read(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ExecutionUnknownError("execution ledger is unreadable") from exc
        if not isinstance(data, dict):
            raise ExecutionUnknownError("execution ledger has an invalid shape")
        return {
            str(key): dict(value)
            for key, value in data.items()
            if isinstance(value, dict)
        }

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self._entries, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)
