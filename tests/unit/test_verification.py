from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from auto_trade.application.verification import PositionChangeVerifier
from auto_trade.domain.exceptions import PositionSnapshotUnavailable
from auto_trade.domain.models import OrderRequest, PositionSnapshot, TradeSignal
from auto_trade.infrastructure.automation import MT5PositionSnapshotProvider

from ..helpers import signal_data


def request(
    action: str = "BUY",
    stop_loss: Decimal | None = None,
    take_profit: Decimal | None = None,
) -> OrderRequest:
    data = signal_data() | {"action": action}
    if stop_loss is not None:
        data |= {"stop_loss": stop_loss}
    if take_profit is not None:
        data |= {"take_profit": take_profit}
    return OrderRequest(TradeSignal.from_dict(data))


def position(
    position_id: str,
    symbol: str = "EURUSD",
    side: str = "BUY",
    stop_loss: Decimal | None = None,
    take_profit: Decimal | None = None,
) -> PositionSnapshot:
    return PositionSnapshot(position_id, symbol, side, Decimal("0.1"), stop_loss, take_profit)


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


class TestVerificationChecksTheProtection:
    """A fill with the right volume but no stop must not verify clean.

    This is the hole the October order exposed from the other side: the dialog
    showed the approved levels while MT5 committed its defaults, and the
    verifier -- matching on symbol, side and volume only -- could not see the
    missing stop. The snapshot carries the levels MT5 reports, so the verifier
    compares them against the approval.
    """

    def test_matching_protection_verifies(self) -> None:
        outcome = PositionChangeVerifier().verify(
            request(stop_loss=Decimal("1.11786"), take_profit=Decimal("1.12386")),
            [position("old")],
            [
                position("old"),
                position(
                    "new",
                    stop_loss=Decimal("1.11786"),
                    take_profit=Decimal("1.12386"),
                ),
            ],
        )
        assert outcome.verified
        assert outcome.position_id == "new"

    def test_wrong_stop_loss_does_not_verify(self) -> None:
        outcome = PositionChangeVerifier().verify(
            request(stop_loss=Decimal("1.11786")),
            [position("old")],
            [position("old"), position("new", stop_loss=Decimal("1.11800"))],
        )
        assert not outcome.verified
        assert "stop loss" in outcome.message
        assert "1.11786" in outcome.message

    def test_missing_stop_loss_does_not_verify(self) -> None:
        # The snapshot reports no level at all: the October fill, which MT5
        # opened with sl 0.0. An unobserved level is a mismatch, not an
        # absence of evidence, because "nothing to compare" would verify the
        # exact position this check exists to catch.
        outcome = PositionChangeVerifier().verify(
            request(stop_loss=Decimal("1.11786")),
            [position("old")],
            [position("old"), position("new", stop_loss=None)],
        )
        assert not outcome.verified
        assert "stop loss" in outcome.message

    def test_wrong_take_profit_does_not_verify(self) -> None:
        outcome = PositionChangeVerifier().verify(
            request(stop_loss=Decimal("1.11786"), take_profit=Decimal("1.12386")),
            [position("old")],
            [
                position("old"),
                position(
                    "new",
                    stop_loss=Decimal("1.11786"),
                    take_profit=Decimal("1.12000"),
                ),
            ],
        )
        assert not outcome.verified
        assert "take profit" in outcome.message

    def test_no_approved_levels_asks_nothing(self) -> None:
        # A request without protection verifies on symbol, side and volume
        # alone, even against a position that happens to carry levels: there
        # is no approved protection to contradict.
        outcome = PositionChangeVerifier().verify(
            request(),
            [position("old")],
            [
                position("old"),
                position(
                    "new",
                    stop_loss=Decimal("1.11786"),
                    take_profit=Decimal("1.12386"),
                ),
            ],
        )
        assert outcome.verified
