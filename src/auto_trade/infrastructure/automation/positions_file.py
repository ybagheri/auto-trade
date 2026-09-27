from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from ...domain.exceptions import PositionSnapshotUnavailable
from ...domain.models import PositionSnapshot, utc_now

SCHEMA_VERSION = 1
SNAPSHOT_FILENAMES = ("auto_trade_positions_a.json", "auto_trade_positions_b.json")


class MT5FilePositionSnapshotProvider:
    """Reads the read-only snapshot written by the MT5 position observer service.

    This is the approved independent observation path. The service never sends
    orders, so a snapshot can be trusted as evidence of terminal state without
    being circular with the desktop UI that produced the request.

    Every failure mode is closed: a missing, stale, truncated, unreadable or
    schema-mismatched snapshot raises ``PositionSnapshotUnavailable`` rather than
    returning a partial or guessed result.
    """

    def __init__(
        self,
        directory: Path,
        max_age: timedelta = timedelta(seconds=30),
        clock: Any = utc_now,
    ) -> None:
        self.directory = Path(directory)
        self.max_age = max_age
        self.clock = clock

    def positions(self) -> tuple[PositionSnapshot, ...]:
        path, document = self._load()
        written_at = self._written_at(document, path)
        if written_at is None:
            raise PositionSnapshotUnavailable(
                f"observer snapshot has no usable written_at timestamp: {path.name}"
            )
        age = self.clock() - written_at
        if age > self.max_age:
            raise PositionSnapshotUnavailable(
                f"observer snapshot is stale ({age.total_seconds():.1f}s old, "
                f"limit {self.max_age.total_seconds():.0f}s); the MT5 observer service "
                "is probably not running"
            )
        raw_positions = document.get("positions")
        if not isinstance(raw_positions, list):
            raise PositionSnapshotUnavailable("observer snapshot has no positions list")
        return tuple(
            self._parse_position(entry) for entry in raw_positions
        )

    def _load(self) -> tuple[Path, dict[str, Any]]:
        candidates = [self.directory / name for name in SNAPSHOT_FILENAMES]
        existing = [path for path in candidates if path.is_file()]
        if not existing:
            raise PositionSnapshotUnavailable(
                f"no observer snapshot found in {self.directory}; install and start the "
                "MT5 AutoTradePositionObserver service"
            )
        newest: tuple[Path, dict[str, Any]] | None = None
        for path in existing:
            document = self._parse(path)
            if newest is None or _sequence(document) > _sequence(newest[1]):
                newest = (path, document)
        if newest is None:
            raise PositionSnapshotUnavailable("no readable observer snapshot was found")
        return newest

    @staticmethod
    def _parse(path: Path) -> dict[str, Any]:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PositionSnapshotUnavailable(
                f"observer snapshot is not readable JSON: {path.name}"
            ) from exc
        if not isinstance(document, dict):
            raise PositionSnapshotUnavailable(
                f"observer snapshot is not a JSON object: {path.name}"
            )
        if document.get("schema") != SCHEMA_VERSION:
            raise PositionSnapshotUnavailable(
                f"observer snapshot schema {document.get('schema')!r} is not supported"
            )
        if document.get("complete") is not True:
            raise PositionSnapshotUnavailable(
                f"observer snapshot is incomplete, discarding: {path.name}"
            )
        return document

    @staticmethod
    def _written_at(document: dict[str, Any], path: Path) -> datetime | None:
        raw = document.get("written_at")
        if not isinstance(raw, str) or not raw:
            return None
        text = raw.strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        # MQL5 conventionally writes dotted dates (2026.09.27T05:19:27Z). Accept
        # that form too, because the observer is a separate component whose exact
        # build we do not control at runtime.
        if re.match(r"^\d{4}\.\d{2}\.\d{2}", text):
            text = text.replace(".", "-", 2)
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    @staticmethod
    def _parse_position(entry: Any) -> PositionSnapshot:
        if not isinstance(entry, dict):
            raise PositionSnapshotUnavailable("observer position entry is not an object")
        ticket = entry.get("ticket")
        symbol = entry.get("symbol")
        side = entry.get("type")
        if ticket is None or not isinstance(symbol, str) or not isinstance(side, str):
            raise PositionSnapshotUnavailable(
                "observer position entry is missing ticket, symbol or type"
            )
        try:
            volume = Decimal(str(entry.get("volume")))
        except (InvalidOperation, TypeError) as exc:
            raise PositionSnapshotUnavailable(
                "observer position entry has an invalid volume"
            ) from exc
        try:
            return PositionSnapshot(str(ticket), symbol, side, volume)
        except ValueError as exc:
            raise PositionSnapshotUnavailable(
                f"observer position entry failed domain validation: {exc}"
            ) from exc


def _sequence(document: dict[str, Any]) -> int:
    value = document.get("sequence")
    return value if isinstance(value, int) else -1
