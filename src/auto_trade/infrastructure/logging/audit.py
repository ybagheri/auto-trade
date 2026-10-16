from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from ...domain.models import AuditEvent

AUDIT_LOGGER_NAME = "auto_trade.audit"


class AuditLogger:
    """Append-only JSONL audit trail, rotating by size.

    The logger is a process-wide singleton, so a second instance pointed at a
    different directory would keep writing into the first one. That is invisible
    in normal use, where a process has one log directory, and wrong the moment a
    process has two: the trail would not be where the operator expects it. The
    handler is therefore moved when the directory changes, instead of being
    installed once and forgotten.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(AUDIT_LOGGER_NAME)
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        self._install(self.directory / "audit.log")

    def _install(self, path: Path) -> None:
        target = path.resolve()
        for handler in list(self.logger.handlers):
            existing = getattr(handler, "baseFilename", None)
            if existing is None or Path(existing).resolve() == target:
                continue
            self.logger.removeHandler(handler)
            handler.close()
        if any(
            Path(getattr(handler, "baseFilename", "")).resolve() == target
            for handler in self.logger.handlers
        ):
            return
        handler = RotatingFileHandler(
            path,
            maxBytes=5_000_000,
            backupCount=5,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        self.logger.addHandler(handler)

    def record(self, event: AuditEvent) -> None:
        self.logger.info(json.dumps(event.to_dict(), separators=(",", ":"), ensure_ascii=False))

    def close(self) -> None:
        """Release the audit file handle.

        The handler stays open for the life of the process unless it is
        closed, which on Windows blocks log rotation, deletion, and the
        directory cleanup a long-running command would otherwise do on
        shutdown. A one-shot command never needs this -- the process exit
        releases the handle -- but a server that never exits (`api`,
        `dashboard`) must call it when it stops. Only the file handlers this
        class installed are touched; anything else on the logger is left
        alone. Idempotent: closing twice removes nothing the second time.
        """
        for handler in list(self.logger.handlers):
            if getattr(handler, "baseFilename", None) is None:
                continue
            self.logger.removeHandler(handler)
            handler.close()
