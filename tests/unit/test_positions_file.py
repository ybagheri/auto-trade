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
    positions: list[dict] | None = None,
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
                "positions": positions
                if positions is not None
                else [
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
    assert snapshot.positions[0].stop_loss is None
    assert snapshot.positions[0].take_profit is None
    assert "file sequence=1" in snapshot.reference


def test_file_provider_reads_protection_levels(tmp_path: Path) -> None:
    write_snapshot(
        tmp_path,
        positions=[
            {
                "ticket": 12345,
                "symbol": "EURUSD",
                "type": "BUY",
                "volume": 0.99,
                "sl": 1.11786,
                "tp": 1.12386,
            }
        ],
    )
    provider = MT5FilePositionSnapshotProvider(tmp_path, clock=lambda: NOW)
    snapshot = provider.snapshot()
    assert snapshot.positions[0].stop_loss == Decimal("1.11786")
    assert snapshot.positions[0].take_profit == Decimal("1.12386")


def test_file_provider_reads_zero_levels_as_absent(tmp_path: Path) -> None:
    # The indicator writes 0.0 for a level the position does not carry. That
    # is absence, not a stop at zero -- comparing it against an approval must
    # mismatch rather than compare equal to nothing.
    write_snapshot(
        tmp_path,
        positions=[
            {
                "ticket": 12345,
                "symbol": "EURUSD",
                "type": "BUY",
                "volume": 0.01,
                "sl": 0.0,
                "tp": 0.0,
            }
        ],
    )
    provider = MT5FilePositionSnapshotProvider(tmp_path, clock=lambda: NOW)
    snapshot = provider.snapshot()
    assert snapshot.positions[0].stop_loss is None
    assert snapshot.positions[0].take_profit is None


def test_file_provider_refuses_a_position_with_an_unreadable_level(
    tmp_path: Path,
) -> None:
    # A level that is present but not a number refuses the whole snapshot,
    # the same way a bad volume does: skipping the entry would under-count
    # the book, and an under-count admits a trade the concurrency gate
    # should have refused.
    write_snapshot(
        tmp_path,
        positions=[
            {
                "ticket": 12345,
                "symbol": "EURUSD",
                "type": "BUY",
                "volume": 0.01,
                "sl": "far away",
                "tp": 1.12386,
            }
        ],
    )
    provider = MT5FilePositionSnapshotProvider(tmp_path, clock=lambda: NOW)
    with pytest.raises(PositionSnapshotUnavailable, match="invalid sl"):
        provider.positions()


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
