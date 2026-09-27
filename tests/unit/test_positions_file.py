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

NOW = datetime(2026, 9, 26, 12, 0, 0, tzinfo=UTC)


def clock() -> datetime:
    return NOW


def document(
    positions: list[dict[str, object]] | None = None,
    sequence: int = 7,
    complete: bool = True,
    written_at: str = "2026-09-26T12:00:00Z",
    schema: object = 1,
) -> dict[str, object]:
    return {
        "schema": schema,
        "sequence": sequence,
        "complete": complete,
        "written_at": written_at,
        "account": 53145727,
        "server": "Alpari-MT5-Demo",
        "positions": [] if positions is None else positions,
    }


def position(ticket: int = 1, symbol: str = "BITCOIN", side: str = "BUY") -> dict[str, object]:
    return {
        "ticket": ticket,
        "symbol": symbol,
        "type": side,
        "volume": 0.01,
        "price_open": 60000.5,
        "sl": 0.0,
        "tp": 0.0,
        "profit": 0.0,
        "magic": 0,
        "opened_at": "2026-09-26T12:00:00Z",
    }


def write(directory: Path, name: str, payload: dict[str, object]) -> Path:
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def provider(
    directory: Path, max_age: timedelta = timedelta(seconds=30)
) -> MT5FilePositionSnapshotProvider:
    return MT5FilePositionSnapshotProvider(directory, max_age=max_age, clock=clock)


def test_reads_open_positions(tmp_path: Path) -> None:
    write(tmp_path, "auto_trade_positions_a.json", document([position(), position(2, side="SELL")]))

    positions = provider(tmp_path).positions()

    assert len(positions) == 2
    assert positions[0].position_id == "1"
    assert positions[0].symbol == "BITCOIN"
    assert positions[0].side == "BUY"
    assert positions[0].volume == Decimal("0.01")
    assert positions[1].side == "SELL"


def test_empty_account_returns_no_positions(tmp_path: Path) -> None:
    write(tmp_path, "auto_trade_positions_a.json", document([]))

    assert provider(tmp_path).positions() == ()


def test_prefers_the_newest_snapshot(tmp_path: Path) -> None:
    write(tmp_path, "auto_trade_positions_a.json", document([position(1)], sequence=4))
    write(tmp_path, "auto_trade_positions_b.json", document([position(2)], sequence=9))

    assert [item.position_id for item in provider(tmp_path).positions()] == ["2"]


def test_missing_snapshot_is_unavailable(tmp_path: Path) -> None:
    with pytest.raises(PositionSnapshotUnavailable, match="no observer snapshot"):
        provider(tmp_path).positions()


def test_incomplete_snapshot_is_rejected(tmp_path: Path) -> None:
    write(tmp_path, "auto_trade_positions_a.json", document([position()], complete=False))

    with pytest.raises(PositionSnapshotUnavailable, match="incomplete"):
        provider(tmp_path).positions()


def test_stale_snapshot_is_rejected(tmp_path: Path) -> None:
    write(
        tmp_path,
        "auto_trade_positions_a.json",
        document([position()], written_at="2026-09-26T11:50:00Z"),
    )

    with pytest.raises(PositionSnapshotUnavailable, match="stale"):
        provider(tmp_path).positions()


def test_unknown_schema_is_rejected(tmp_path: Path) -> None:
    write(tmp_path, "auto_trade_positions_a.json", document([position()], schema=99))

    with pytest.raises(PositionSnapshotUnavailable, match="schema"):
        provider(tmp_path).positions()


def test_truncated_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "auto_trade_positions_a.json"
    path.write_text('{"schema": 1, "complete": tru', encoding="utf-8")

    with pytest.raises(PositionSnapshotUnavailable, match="readable JSON"):
        provider(tmp_path).positions()


@pytest.mark.parametrize(
    "entry",
    [
        {"symbol": "BITCOIN", "type": "BUY", "volume": 0.01},
        {"ticket": 1, "type": "BUY", "volume": 0.01},
        {"ticket": 1, "symbol": "BITCOIN", "volume": 0.01},
        {"ticket": 1, "symbol": "BITCOIN", "type": "HEDGE", "volume": 0.01},
        {"ticket": 1, "symbol": "BITCOIN", "type": "BUY", "volume": -1},
        {"ticket": 1, "symbol": "BITCOIN", "type": "BUY", "volume": "abc"},
        "not-an-object",
    ],
)
def test_malformed_position_entries_are_rejected(tmp_path: Path, entry: object) -> None:
    write(tmp_path, "auto_trade_positions_a.json", document([entry]))  # type: ignore[list-item]

    with pytest.raises(PositionSnapshotUnavailable):
        provider(tmp_path).positions()


def test_timestamp_without_timezone_is_treated_as_utc(tmp_path: Path) -> None:
    write(
        tmp_path,
        "auto_trade_positions_a.json",
        document([position()], written_at="2026-09-26T12:00:00"),
    )

    assert len(provider(tmp_path).positions()) == 1


def test_dotted_mql5_timestamp_is_accepted(tmp_path: Path) -> None:
    """MQL5 writes 2026.09.26T12:00:00Z, which fromisoformat rejects."""
    write(
        tmp_path,
        "auto_trade_positions_a.json",
        document([position()], written_at="2026.09.26T12:00:00Z"),
    )

    assert len(provider(tmp_path).positions()) == 1


def test_dotted_timestamp_is_still_subject_to_the_staleness_check(tmp_path: Path) -> None:
    write(
        tmp_path,
        "auto_trade_positions_a.json",
        document([position()], written_at="2026.09.26T11:50:00Z"),
    )

    with pytest.raises(PositionSnapshotUnavailable, match="stale"):
        provider(tmp_path).positions()


@pytest.mark.parametrize(
    "written_at",
    ["", "not-a-time", "2026-13-45T99:99:99Z", None, 12345],
)
def test_unusable_timestamps_are_rejected(tmp_path: Path, written_at: object) -> None:
    write(tmp_path, "auto_trade_positions_a.json", document([position()], written_at=written_at))  # type: ignore[arg-type]

    with pytest.raises(PositionSnapshotUnavailable):
        provider(tmp_path).positions()
