from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from auto_trade.application.verification import PositionChangeVerifier
from auto_trade.domain.exceptions import PositionSnapshotUnavailable
from auto_trade.domain.models import OrderRequest, PositionSnapshot, TradeSignal
from auto_trade.infrastructure.automation import MT5PositionSnapshotProvider

from ..helpers import signal_data


def request(action: str = "BUY") -> OrderRequest:
    data = signal_data() | {"action": action}
    return OrderRequest(TradeSignal.from_dict(data))


def position(position_id: str, symbol: str = "EURUSD", side: str = "BUY") -> PositionSnapshot:
    return PositionSnapshot(position_id, symbol, side, Decimal("0.1"))


class FakeText:
    def __init__(self, value: str) -> None:
        self.element_info = SimpleNamespace(control_type="Text")
        self._value = value

    def window_text(self) -> str:
        return self._value


class FakeRow:
    def __init__(self, values: list[str]) -> None:
        self._values = values

    def descendants(self) -> list[FakeText]:
        return [FakeText(value) for value in self._values]


def test_mt5_position_provider_parses_accessible_row() -> None:
    row = FakeRow(["XAUUSD", "12345", "12:30", "buy", "0.10"])
    snapshot = MT5PositionSnapshotProvider._parse_row(row)
    assert snapshot.position_id == "12345"
    assert snapshot.side == "BUY"
    assert snapshot.volume == Decimal("0.10")


def test_mt5_position_provider_fails_closed_on_blank_row() -> None:
    with pytest.raises(PositionSnapshotUnavailable):
        MT5PositionSnapshotProvider._parse_row(FakeRow([]))


def test_position_change_verifier_accepts_one_new_match() -> None:
    outcome = PositionChangeVerifier().verify(
        request(),
        [position("old")],
        [position("old"), position("new")],
    )
    assert outcome.verified
    assert outcome.position_id == "new"


def test_position_change_verifier_rejects_ambiguous_changes() -> None:
    outcome = PositionChangeVerifier().verify(
        request(),
        [],
        [position("new-1"), position("new-2")],
    )
    assert not outcome.verified
    assert "multiple" in outcome.message


def test_position_change_verifier_rejects_missing_change() -> None:
    outcome = PositionChangeVerifier().verify(request("SELL"), [], [position("buy")])
    assert not outcome.verified
