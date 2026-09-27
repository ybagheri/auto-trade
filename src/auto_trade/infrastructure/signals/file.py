from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ...domain.exceptions import InvalidSignalError, NoSignalAvailable
from ...domain.models import TradeSignal


class FileSignalProvider:
    """Consumes one signal per ``receive`` call from a local directory.

    A signal file is deleted only after it parses successfully, so an invalid or
    partially written file is retained for inspection and retried later.
    """

    def __init__(self, directory: Path, pattern: str = "*.json") -> None:
        self.directory = Path(directory)
        self.pattern = pattern
        self._started = False

    def start(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self._started = True

    def stop(self) -> None:
        self._started = False

    def receive(self) -> TradeSignal:
        if not self._started:
            raise NoSignalAvailable("signal provider is not started")
        for path in self._pending():
            signal = self._parse(path)
            path.unlink()
            return signal
        raise NoSignalAvailable("no signal file is pending")

    def _pending(self) -> list[Path]:
        if not self.directory.is_dir():
            return []
        return sorted(self.directory.glob(self.pattern))

    @staticmethod
    def _parse(path: Path) -> TradeSignal:
        try:
            raw: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidSignalError(f"signal file is not readable JSON: {path.name}") from exc
        return TradeSignal.from_dict(raw)
