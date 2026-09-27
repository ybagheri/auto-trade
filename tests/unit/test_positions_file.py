from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from auto_trade.domain.exceptions import PositionSnapshotUnavailable
from auto_trade.infrastructure.automation.positions_file import (
    MT5FilePositionSnapshotProvider,
)

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


def write_snapshot(
    directory: Path,
    *,
    written_at: str = NOW.isoformat(),
    complete: bool = True,
    sequence: int = 1,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "auto_trade_positions_a.json"
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "sequence": sequence,
                "complete": complete,
                "written_at": written_at,
                "account": 53145727,
                "server": "Alpari-MT5-Demo",
                "positions": [
                    {
                        "ticket": 12345,
                        "symbol": "BITCOIN",
                        "type": "BUY",
                        "volume": 0.01,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_file_provider_reads_snapshot(tmp_path: Path) -> None:
    write_snapshot(tmp_path)
    provider = MT5FilePositionSnapshotProvider(tmp_path, clock=lambda: NOW)
    snapshot = provider.snapshot()
    assert snapshot.positions[0].position_id == "12345"
    assert snapshot.positions[0].volume == Decimal("0.01")
    assert "file sequence=1" in snapshot.reference


def test_file_provider_fails_closed_when_missing(tmp_path: Path) -> None:
    provider = MT5FilePositionSnapshotProvider(tmp_path, clock=lambda: NOW)
    with pytest.raises(PositionSnapshotUnavailable):
        provider.positions()


def test_file_provider_rejects_incomplete_snapshot(tmp_path: Path) -> None:
    write_snapshot(tmp_path, complete=False)
    provider = MT5FilePositionSnapshotProvider(tmp_path, clock=lambda: NOW)
    with pytest.raises(PositionSnapshotUnavailable, match="incomplete"):
        provider.positions()


def test_file_provider_rejects_stale_snapshot(tmp_path: Path) -> None:
    write_snapshot(
        tmp_path,
        written_at=(NOW - timedelta(seconds=31)).isoformat(),
    )
    provider = MT5FilePositionSnapshotProvider(tmp_path, clock=lambda: NOW)
    with pytest.raises(PositionSnapshotUnavailable, match="stale"):
        provider.positions()
