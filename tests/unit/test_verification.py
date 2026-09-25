from __future__ import annotations

from decimal import Decimal

from auto_trade.application.verification import PositionChangeVerifier
from auto_trade.domain.models import OrderRequest, PositionSnapshot, TradeSignal

from ..helpers import signal_data


def request(action: str = "BUY") -> OrderRequest:
    data = signal_data() | {"action": action}
    return OrderRequest(TradeSignal.from_dict(data))


def position(position_id: str, symbol: str = "EURUSD", side: str = "BUY") -> PositionSnapshot:
    return PositionSnapshot(position_id, symbol, side, Decimal("0.1"))


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
