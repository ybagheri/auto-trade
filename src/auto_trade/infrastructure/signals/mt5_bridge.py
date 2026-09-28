from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ...domain.exceptions import InvalidSignalError, NoSignalAvailable
from ...domain.models import TradeSignal

SIGNAL_PREFIX = "auto_trade_signal_"
DEFAULT_PATTERN = f"{SIGNAL_PREFIX}*.json"


class MT5BridgeSignalProvider:
    """Consumes signals written as files by an MQL5 program.

    ``MQL5\\Files`` inside the terminal data directory is the only place an MQL5
    program can write without any API of ours, so it is the bridge channel. The
    program's ``Common`` directory is deliberately not used: it is shared by
    every terminal on the machine, so a file there cannot be attributed to one
    instance and two terminals could read each other's signals.

    The writer is trusted only as far as the payload: a file is deleted after it
    parses, anything unparsable is left for inspection, and the signal still has
    to pass the risk engine, the kill switch, and every other gate. Nothing in
    this path executes MQL5 code, and no file naming an executable can be
    reached through it.
    """

    def __init__(
        self,
        files_directory: Path,
        pattern: str = DEFAULT_PATTERN,
        delete_after_read: bool = True,
    ) -> None:
        self.directory = Path(files_directory)
        self.pattern = pattern
        self.delete_after_read = delete_after_read
        self._started = False

    def start(self) -> None:
        self._started = True

    def stop(self) -> None:
        self._started = False

    def receive(self) -> TradeSignal:
        if not self._started:
            raise NoSignalAvailable("signal provider is not started")
        for path in self._pending():
            signal = self._parse(path)
            if self.delete_after_read:
                path.unlink()
            return signal
        raise NoSignalAvailable("no bridge signal is pending")

    def _pending(self) -> list[Path]:
        if not self.directory.is_dir():
            return []
        return sorted(self.directory.glob(self.pattern))

    @staticmethod
    def _parse(path: Path) -> TradeSignal:
        try:
            raw: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidSignalError(f"bridge signal is not readable JSON: {path.name}") from exc
        return TradeSignal.from_dict(raw)
