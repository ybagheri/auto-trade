"""The audit trail is the record everything else is judged against.

It is a process-wide logger, so the failure this file guards against is a second
instance silently writing into the first one's directory.
"""

from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from auto_trade.domain.models import AuditEvent
from auto_trade.infrastructure.logging.audit import AUDIT_LOGGER_NAME, AuditLogger


def event(message: str) -> AuditEvent:
    return AuditEvent(component="test", event_type="event", message=message)


def read(directory: Path) -> list[str]:
    path = directory / "audit.log"
    if not path.is_file():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_events_are_written_as_json_lines(tmp_path: Path) -> None:
    logger = AuditLogger(tmp_path / "logs")

    logger.record(event("first"))
    logger.record(event("second"))

    lines = read(tmp_path / "logs")
    assert len(lines) == 2
    assert json.loads(lines[0])["message"] == "first"
    assert json.loads(lines[1])["message"] == "second"


def test_a_second_logger_writes_to_its_own_directory(tmp_path: Path) -> None:
    first = tmp_path / "one"
    second = tmp_path / "two"

    AuditLogger(first).record(event("into one"))
    AuditLogger(second).record(event("into two"))
    AuditLogger(second).record(event("again into two"))

    assert [json.loads(line)["message"] for line in read(first)] == ["into one"]
    assert [json.loads(line)["message"] for line in read(second)] == [
        "into two",
        "again into two",
    ]


def test_the_logger_keeps_exactly_one_file_handler(tmp_path: Path) -> None:
    AuditLogger(tmp_path / "one")
    AuditLogger(tmp_path / "two")

    handlers = [
        handler
        for handler in logging.getLogger(AUDIT_LOGGER_NAME).handlers
        if isinstance(handler, RotatingFileHandler)
    ]

    assert len(handlers) == 1
    assert Path(handlers[0].baseFilename).parent == (tmp_path / "two").resolve()


def test_the_trail_does_not_propagate_to_the_root_logger(tmp_path: Path) -> None:
    logger = AuditLogger(tmp_path / "logs")

    assert logger.logger.propagate is False
    assert logger.logger.level == logging.INFO
