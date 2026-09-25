from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from ...domain.models import AuditEvent


class AuditLogger:
    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger("auto_trade.audit")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        if not self.logger.handlers:
            handler = RotatingFileHandler(
                directory / "audit.log",
                maxBytes=5_000_000,
                backupCount=5,
                encoding="utf-8",
            )
            handler.setFormatter(logging.Formatter("%(message)s"))
            self.logger.addHandler(handler)

    def record(self, event: AuditEvent) -> None:
        self.logger.info(json.dumps(event.to_dict(), separators=(",", ":"), ensure_ascii=False))
