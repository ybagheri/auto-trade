from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any, Protocol

from ..domain.exceptions import AutoTradeError, ExecutionUnknownError
from ..domain.models import ExecutionResult

RECONCILED = "RECONCILED"


class LedgerError(AutoTradeError):
    """Raised when an execution record cannot be changed as requested."""


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
                "evidence": result.evidence.to_dict() if result.evidence else None,
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

    def reconcile(self, signal_id: str, observation: str) -> dict[str, Any]:
        """Settle an attempt the application could not prove, on an operator's word.

        A click that could not be corroborated is recorded as ``UNKNOWN``, and the
        application has no way to prove it later on its own. A person can: they
        look at the account. This records that assertion, attributed to the
        operator, and never presents it as an observation the application made.

        Only an attempt that is still unknown or pending can be settled. A
        recorded ``ACCEPTED``, ``REJECTED``, ``CLOSED``, or already reconciled
        entry is refused, because the record is not in doubt.
        """
        text = observation.strip()
        if not text:
            raise LedgerError("reconciling an attempt requires what was observed")
        with self._lock:
            entry = self._entries.get(signal_id)
            if entry is None:
                raise LedgerError(f"no execution record for signal {signal_id}")
            status = str(entry.get("status", ""))
            if status not in {"UNKNOWN", "REQUESTED", RECONCILED}:
                raise LedgerError(
                    f"signal {signal_id} is recorded as {status or 'unknown state'}, which "
                    "is not in doubt; reconciling it would rewrite a settled record"
                )
            settled = dict(entry)
            settled["original_status"] = status or None
            settled["original_message"] = entry.get("message")
            settled["status"] = RECONCILED
            settled["state"] = "RECONCILED_BY_OPERATOR"
            settled["message"] = f"operator-reconciled, not observed by this application: {text}"
            settled["reconciled_at"] = datetime.now(UTC).isoformat()
            self._entries[signal_id] = settled
            self._write()
            return dict(settled)

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
