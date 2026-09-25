from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from auto_trade.domain.exceptions import InvalidSignalError
from auto_trade.domain.models import TradeSignal
from auto_trade.infrastructure.signals import FileSignalProvider


def signal_data(signal_id: str = "signal-1", now: datetime | None = None) -> dict[str, object]:
    current = now or datetime.now(UTC)
    return {
        "id": signal_id,
        "timestamp": current.isoformat(),
        "source": "test",
        "symbol": "eurusd",
        "action": "BUY",
        "volume": 0.1,
    }


def test_signal_parser_normalizes_and_serializes() -> None:
    signal = TradeSignal.from_dict(signal_data())
    assert signal.symbol == "EURUSD"
    assert signal.action.value == "BUY"
    assert signal.to_dict()["volume"] == "0.1"


@pytest.mark.parametrize(
    "data",
    [
        {"id": "x"},
        signal_data() | {"timestamp": "not-a-time"},
        signal_data() | {"action": "UNKNOWN"},
        signal_data() | {"volume": 0},
    ],
)
def test_signal_parser_rejects_invalid_data(data: dict[str, object]) -> None:
    with pytest.raises(InvalidSignalError):
        TradeSignal.from_dict(data)


def test_file_provider_consumes_valid_signal(tmp_path: Path) -> None:
    path = tmp_path / "signal.json"
    path.write_text(json.dumps(signal_data()), encoding="utf-8")
    provider = FileSignalProvider(tmp_path)
    provider.start()
    received = provider.receive()
    provider.stop()
    assert received.signal_id == "signal-1"
    assert not path.exists()


def test_file_provider_does_not_consume_invalid_signal(tmp_path: Path) -> None:
    path = tmp_path / "signal.json"
    path.write_text("{}", encoding="utf-8")
    provider = FileSignalProvider(tmp_path)
    provider.start()
    with pytest.raises(InvalidSignalError):
        provider.receive()
    assert path.exists()
