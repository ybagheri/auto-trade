"""MT5 applies order fields asynchronously, and the code did not wait for it.

**The defect, and how it reached production.** `prepare_order` wrote the volume, the
stop loss and the take profit, then read the volume **once**. That read proves the
write reached the control. It says nothing about whether MT5 has applied it.

Measured on Alpari build 6230, EURUSD, with the three fields written in order, the
readings caught up at roughly **250 ms, 500 ms and 800 ms**. For the best part of a
second after the last write, the dialog displays a mixture of the values just typed
and the ones MT5 has not got to.

An order sent in that window carries whatever MT5 had committed at that instant. This
was not hypothetical: a real order went out this way and came back **0.01 lots with no
stop loss and no take profit**, while the dialog read back the approved volume and
`confirm_dialog_matches` compared those same readings and passed. The position was
unprotected, and nothing noticed until verification compared the fill against the
request.

The fix polls every written field until it reads back as written, and refuses if one
never does. These tests drive that with a double that applies fields on a schedule, so
the race is reproduced rather than described.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from auto_trade.domain.exceptions import AutomationError
from auto_trade.domain.models import OrderRequest, TradeSignal
from auto_trade.infrastructure.automation.execution import ExecutionGate
from auto_trade.infrastructure.automation.window_manager import (
    MT5WindowManager,
    _same_number,
)

#: What every field reads once MT5 has applied it. The comment is here because the
#: wait covers every written field, and a field the double cannot answer for is a
#: field the code would -- correctly -- refuse to finish without.
_APPLIED = {
    "10325": "EURUSD",
    "10333": "0.03",
    "10334": "1.12208",
    "10336": "1.12808",
    "1001": "probe",
}


class SettlingManager(MT5WindowManager):
    """A manager whose fields catch up after a delay, the way MT5's do.

    ``pending`` maps a field id to the value it will report once applied. Until then
    it reports the value the terminal would have shown -- the default -- which is
    exactly the state the original code read and accepted.
    """

    def __init__(self, settle_after_reads: dict[str, int]) -> None:
        super().__init__()
        self.settle_after_reads = settle_after_reads
        self.reads = 0
        self.field_reads: dict[str, int] = {}
        self.closed = False
        self.selected = False
        self.written: list[tuple[str, str]] = []
        self.current: dict[str, str] = {
            "10325": "EURUSD",
            "10333": "0.01",
            "10334": "0.00000",
            "10336": "0.00000",
            "1001": "",
        }

    # -- the low-level surface prepare_order drives ---------------------------
    def open_order_dialog(self, timeout_seconds: float = 5.0) -> Any:
        return object()

    def set_field(self, automation_id: str, value: str) -> None:
        self.written.append((automation_id, value))
        # The write is visible to the control immediately -- `set_edit_text` did its
        # job -- but MT5 has not applied it yet.
        self.current[automation_id] = value

    def read_field(self, automation_id: str) -> str:
        # **Per-field read counts, not one shared counter.** The first version shared
        # it, so "settles after 3 reads" meant three reads of *any* field, and the
        # comment -- which the double models as settling immediately -- kept the shared
        # total from reaching the threshold for the volume. The wait correctly refused
        # and the test failed on a field that was never the subject.
        #
        # Per-field is also what MT5 actually does: each field settles on its own
        # schedule, which is why the measurement came back 250/500/800 ms rather than
        # one number.
        self.reads += 1
        self.field_reads[automation_id] = self.field_reads.get(automation_id, 0) + 1
        delay = self.settle_after_reads.get(automation_id)
        if delay is None or self.field_reads[automation_id] >= delay:
            # Settled: MT5 has committed the value, so the control reports it.
            return self.applied.get(automation_id, self.current[automation_id])
        # **Not yet.** The write reached the control, so `current` holds the new text,
        # but MT5 has not applied it -- and what MT5 holds is what an order would be
        # sent with. The terminal's own default is what it shows meanwhile.
        #
        # Returning `current` here instead would make the double say "already
        # applied", the wait would pass on the first pass, and every test in this
        # file would pass on the defective code. It took a failing assertion to notice
        # that the two branches were returning the same thing.
        return self.default_for(automation_id)

    def close_order_dialog(self, timeout_seconds: float = 5.0) -> None:
        self.closed = True

    def select_market_execution(self) -> None:
        self.selected = True

    # -- the two states a field can be in --------------------------------------
    applied: dict[str, str] = {}
    defaults: dict[str, str] = {}

    def default_for(self, automation_id: str) -> str:
        return self.defaults.get(
            automation_id,
            {"10333": "0.01", "10334": "0.00000", "10336": "0.00000"}.get(automation_id, ""),
        )


def _adapter(manager: MT5WindowManager, *, dry_run: bool = False) -> Any:
    from auto_trade.infrastructure.automation import MT5DesktopAdapter

    class _EmptyProvider:
        def positions(self) -> tuple:
            return ()

    adapter = MT5DesktopAdapter.__new__(MT5DesktopAdapter)
    adapter.window_manager = manager
    adapter.gate = ExecutionGate(enabled=True, dry_run=dry_run, demo_only=True)
    adapter.selected_symbol = "EURUSD"
    adapter.prepared = None
    # `_capture_baseline` runs once preparation succeeds, so the adapter needs a
    # position provider by then. An empty one is right: these tests are about the
    # dialog, and a baseline of "no positions" is the ordinary case before an order.
    adapter.position_provider = _EmptyProvider()
    adapter._baseline = ()
    adapter._baseline_error = None
    adapter.connected = True
    return adapter


def _request() -> OrderRequest:
    # The shared helper rather than a hand-built dict. `TradeSignal.from_dict` wants
    # an ISO timestamp string and rejects a `datetime`, which is a small thing to
    # rediscover and has nothing to do with what these tests are about.
    from ..helpers import signal_data

    data = signal_data() | {
        "symbol": "EURUSD",
        "action": "BUY",
        "volume": Decimal("0.03"),
        "price": Decimal("1.12508"),
        "stop_loss": Decimal("1.12208"),
        "take_profit": Decimal("1.12808"),
        "comment": "probe",
    }
    return OrderRequest(TradeSignal.from_dict(data))


class TestPrepareOrderWaitsForMT5ToApplyTheFields:
    def test_it_refuses_while_a_field_is_still_the_default(self) -> None:
        # The regression, stated directly: with a field that never settles, the old
        # code read the volume once, saw its own write, and returned.
        manager = SettlingManager(settle_after_reads={"10334": 10**9, "10336": 10**9})
        manager.applied = {**_APPLIED, "10334": "0.00000", "10336": "0.00000"}
        adapter = _adapter(manager)

        with pytest.raises(AutomationError) as raised:
            adapter.prepare_order(_request())

        assert "did not apply" in str(raised.value)
        assert "1.12208" in str(raised.value)
        assert adapter.prepared is None, (
            "prepare_order returned with a field MT5 had not applied, so the request "
            "was marked prepared and the click would follow it"
        )

    def test_it_succeeds_once_every_field_has_settled(self) -> None:
        manager = SettlingManager(settle_after_reads={"10333": 2, "10334": 3, "10336": 4})
        manager.applied = _APPLIED
        adapter = _adapter(manager)

        adapter.prepare_order(_request())

        assert adapter.prepared is not None
        assert manager.reads >= 4, "it should have polled until the last field settled"

    def test_it_polls_rather_than_sleeping_a_fixed_interval(self) -> None:
        # A fixed wait would make the outcome depend on how fast the machine is
        # today. Polling means a field that settles in 50 ms costs 50 ms and one that
        # settles in 900 ms costs 900 ms.
        fast = SettlingManager(settle_after_reads={"10336": 1})
        fast.applied = _APPLIED
        _adapter(fast).prepare_order(_request())

        slow = SettlingManager(settle_after_reads={"10336": 40})
        slow.applied = _APPLIED
        _adapter(slow).prepare_order(_request())

        assert slow.reads > fast.reads, (
            f"a field that settles after 40 reads cost {slow.reads} reads and one that "
            f"settles immediately cost {fast.reads}; a constant wait would make these "
            f"equal and would be a fixed-interval race with extra steps"
        )
        assert manager_field_reads(fast) <= 4, (
            "sanity: the fast case must not poll many times, or the comparison above "
            "would pass for the wrong reason"
        )

    def test_a_field_that_never_settles_closes_the_dialog(self) -> None:
        # The refusal has to tidy up, because a prepared-looking dialog left open over
        # a live terminal is one click away from a market order.
        manager = SettlingManager(settle_after_reads={"10336": 10**9})
        manager.applied = {**_APPLIED, "10336": "0.00000"}
        adapter = _adapter(manager)

        with pytest.raises(AutomationError):
            adapter.prepare_order(_request())

        assert manager.closed is True


def manager_field_reads(manager: SettlingManager) -> int:
    """Reads of the delayed field, for the sanity assertion below."""
    return manager.field_reads.get("10336", 0)


class TestTheNumericComparison:
    """MT5 reformats what it displays, so a string comparison would refuse good orders."""

    @pytest.mark.parametrize(
        ("shown", "expected"),
        [
            ("0.03", "0.030"),
            ("0.0300", "0.03"),
            ("1.12208", "1.122080"),
            ("1.122080", "1.12208"),
        ],
    )
    def test_equivalent_numbers_are_the_same(self, shown: str, expected: str) -> None:
        assert _same_number(shown, expected) is True

    @pytest.mark.parametrize(
        ("shown", "expected"),
        [("0.03", "0.01"), ("1.12208", "1.12207"), ("0.00000", "1.12208")],
    )
    def test_different_numbers_are_not(self, shown: str, expected: str) -> None:
        assert _same_number(shown, expected) is False

    def test_a_comment_is_compared_as_text(self) -> None:
        # A comment is not a number, and inventing one would be worse than being
        # strict about a string.
        assert _same_number("probe", "probe") is True
        assert _same_number("probe", "other") is False
        assert _same_number("", "") is True
        assert _same_number("", "0.03") is False

    def test_a_numeric_string_that_is_not_a_number_is_text(self) -> None:
        assert _same_number("not-a-number", "not-a-number") is True
        assert _same_number("not-a-number", "other") is False


class TestWhyTheOldCheckWasNotEnough:
    def test_reading_a_field_once_proves_only_that_the_write_landed(self) -> None:
        # The shape of the bug, isolated. `set_field` puts the text in the control, so
        # an immediate read returns it -- while MT5 still holds the old value and will
        # send that instead. A test that only checks "the field reads back what was
        # written" passes on the defective code, which is why every test here drives
        # the settling behaviour rather than the write.
        manager = SettlingManager(settle_after_reads={"10334": 10**9})
        manager.applied = {**_APPLIED, "10334": "0.00000"}
        manager.set_field("10333", "0.03")
        manager.set_field("10334", "1.12208")
        assert manager.current["10334"] == "1.12208", "the write reached the control"
        assert manager.read_field("10334") == manager.default_for("10334"), (
            "and MT5 has not applied it -- which is the whole defect, and it is "
            "invisible to any test that reads a field once"
        )
