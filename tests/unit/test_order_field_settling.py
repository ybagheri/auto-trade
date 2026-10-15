"""MT5 commits order fields on keystroke input, and the code wrote them another way.

**The defect, and how it reached production.** `prepare_order` wrote the volume, the
stop loss and the take profit with `set_edit_text`, which sets the control's text
through the accessibility ValuePattern and bypasses the keystroke messages MT5
commits on. Measured on Alpari build 6230 with read-only probes: the control then
displays the typed value indefinitely while MT5's committed order state keeps the
defaults -- no waiting would ever change that, because there is nothing to wait
for. A real order went out this way and came back **0.01 lots with no stop loss
and no take profit**, while the dialog read back the approved volume and
`confirm_dialog_matches` compared those same readings and passed. The position was
unprotected, and nothing noticed until verification compared the fill against the
request.

The fix writes every field with real keystrokes and waits on MT5's own rendering
of its committed state -- the volume label and the stop/target distance labels --
rather than on the fields it typed into. These tests drive that with a double
that models the two surfaces separately (display text vs committed state), so a
write that never commits is reproduced rather than described.
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

#: What the commit-witness labels render once MT5 has committed each level. The
#: volume label renders the committed volume in base-currency units; the
#: stop/target labels stay empty until a level commits, then render MT5's own
#: computed distance. Measured on Alpari build 6230 with read-only probes.
_APPLIED_LABELS = {
    "10881": "3 000 EUR",
    "11138": "300 points, ~15 USD",
    "11139": "300 points, ~15 USD",
}

_DEFAULT_LABELS = {
    "10881": "1 000 EUR",
    "11138": "",
    "11139": "",
}

#: Which commit label witnesses which field. Mirrors the production mapping so
#: the double and the code cannot disagree about it silently.
_FIELD_FOR_LABEL = {
    "10881": "10333",
    "11138": "10334",
    "11139": "10336",
}


class SettlingManager(MT5WindowManager):
    """A manager with separate display and commit surfaces, the way MT5 has.

    ``settle_after_reads`` maps a field id to the number of display reads
    before MT5 commits it; ``commit_settle_after_reads`` maps a *label* id to
    the number of witness reads before the commit becomes visible there. A
    label with no explicit schedule mirrors its field's, because one MT5
    commit moves both surfaces together.

    The two surfaces are independent on purpose: the incident this file is
    about is a write that updated the display immediately and never committed,
    which is exactly ``settle_after_reads={}`` with an infinite commit
    schedule. A double with one shared surface could not express that state,
    and every test in this file would pass on the defective code.
    """

    def __init__(
        self,
        settle_after_reads: dict[str, int],
        commit_settle_after_reads: dict[str, int] | None = None,
    ) -> None:
        super().__init__()
        self.settle_after_reads = settle_after_reads
        self.commit_settle_after_reads = commit_settle_after_reads or {}
        self.reads = 0
        self.field_reads: dict[str, int] = {}
        self.commit_reads: dict[str, int] = {}
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
        # The write is visible to the control immediately -- keystrokes land in
        # the edit -- but MT5 commits it on its own schedule.
        self.current[automation_id] = value

    def read_field(self, automation_id: str) -> str:
        # **Per-field read counts, not one shared counter.** The first version shared
        # it, so "settles after 3 reads" meant three reads of *any* field, and the
        # comment -- which the double models as settling immediately -- kept the shared
        # total from reaching the threshold for the volume. The wait correctly refused
        # and the test failed on a field that was never the subject.
        #
        # Per-field is also what MT5 actually does: each field settles on its own
        # schedule.
        self.reads += 1
        self.field_reads[automation_id] = self.field_reads.get(automation_id, 0) + 1
        delay = self.settle_after_reads.get(automation_id)
        if delay is None or self.field_reads[automation_id] >= delay:
            # Settled -- but only a *written* field reports its applied value.
            # Before anything is written the dialog shows MT5's committed
            # defaults however many times it is read, which is what the
            # pre-write snapshot in prepare_order observes.
            if any(field == automation_id for field, _ in self.written):
                return self.applied.get(automation_id, self.current[automation_id])
            return self.default_for(automation_id)
        # **Not yet.** The write reached the control, so `current` holds the new text,
        # but MT5 has not committed it -- and what MT5 holds is what an order would be
        # sent with. The terminal's own default is what the control reports meanwhile.
        #
        # Returning `current` here instead would make the double say "already
        # applied", the wait would pass on the first pass, and every test in this
        # file would pass on the defective code. It took a failing assertion to notice
        # that the two branches were returning the same thing.
        return self.default_for(automation_id)

    def read_commit_label(self, automation_id: str) -> str:
        field = _FIELD_FOR_LABEL[automation_id]
        if not any(written_field == field for written_field, _ in self.written):
            # Nothing written: MT5 holds its committed defaults, whatever the
            # display was asked to show.
            return self.default_label_for(automation_id)
        self.commit_reads[automation_id] = self.commit_reads.get(automation_id, 0) + 1
        delay = self.commit_settle_after_reads.get(
            automation_id, self.settle_after_reads.get(field, 1)
        )
        if self.commit_reads[automation_id] >= delay:
            return self.applied_labels.get(automation_id, self.default_label_for(automation_id))
        return self.default_label_for(automation_id)

    def close_order_dialog(self, timeout_seconds: float = 5.0) -> None:
        self.closed = True

    def select_market_execution(self) -> None:
        self.selected = True

    # -- the two states a field can be in --------------------------------------
    applied: dict[str, str] = {}
    defaults: dict[str, str] = {}
    applied_labels: dict[str, str] = {}

    def default_for(self, automation_id: str) -> str:
        return self.defaults.get(
            automation_id,
            {"10333": "0.01", "10334": "0.00000", "10336": "0.00000"}.get(automation_id, ""),
        )

    def default_label_for(self, automation_id: str) -> str:
        return _DEFAULT_LABELS.get(automation_id, "")


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


def _request(volume: Decimal = Decimal("0.03")) -> OrderRequest:
    # The shared helper rather than a hand-built dict. `TradeSignal.from_dict` wants
    # an ISO timestamp string and rejects a `datetime`, which is a small thing to
    # rediscover and has nothing to do with what these tests are about.
    from ..helpers import signal_data

    data = signal_data() | {
        "symbol": "EURUSD",
        "action": "BUY",
        "volume": volume,
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
        manager.applied_labels = _APPLIED_LABELS
        adapter = _adapter(manager)

        with pytest.raises(AutomationError) as raised:
            adapter.prepare_order(_request())

        assert "did not commit" in str(raised.value)
        assert "1.12208" in str(raised.value)
        assert adapter.prepared is None, (
            "prepare_order returned with a field MT5 had not applied, so the request "
            "was marked prepared and the click would follow it"
        )

    def test_it_succeeds_once_every_field_has_settled(self) -> None:
        manager = SettlingManager(settle_after_reads={"10333": 2, "10334": 3, "10336": 4})
        manager.applied = _APPLIED
        manager.applied_labels = _APPLIED_LABELS
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
        fast.applied_labels = _APPLIED_LABELS
        _adapter(fast).prepare_order(_request())

        slow = SettlingManager(settle_after_reads={"10336": 40})
        slow.applied = _APPLIED
        slow.applied_labels = _APPLIED_LABELS
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


class TestAWriteThatNeverCommitsIsRefused:
    def test_display_correct_but_commit_absent_refuses(self) -> None:
        # The incident, stated exactly: the write reached the control at once
        # (every field reads back as written on the first read, the way
        # `set_edit_text` leaves it) but MT5 never committed anything, so the
        # commit witnesses still render the defaults. The old display-only wait
        # passed this state and the click followed it; the commit-aware wait
        # must refuse it.
        manager = SettlingManager(
            settle_after_reads={},
            commit_settle_after_reads={
                "10881": 10**9,
                "11138": 10**9,
                "11139": 10**9,
            },
        )
        manager.applied = _APPLIED
        manager.applied_labels = _DEFAULT_LABELS
        adapter = _adapter(manager)

        with pytest.raises(AutomationError, match="did not commit") as raised:
            adapter.prepare_order(_request())

        assert "0.03" in str(raised.value)
        assert adapter.prepared is None, (
            "prepare_order returned with MT5 holding the defaults behind a "
            "correct-looking dialog, so the request was marked prepared and "
            "the click would follow it at the wrong volume with no protection"
        )
        assert manager.closed is True

    def test_requested_equals_default_needs_no_commit(self) -> None:
        # The boundary the witness rule must respect: when the requested value
        # already matches what the dialog showed before writing, MT5's
        # committed state already holds it (a fresh dialog shows committed
        # defaults), so an unchanged witness is agreement, not a stall.
        manager = SettlingManager(settle_after_reads={})
        manager.applied = {**_APPLIED, "10333": "0.01"}
        manager.applied_labels = _APPLIED_LABELS
        adapter = _adapter(manager)

        adapter.prepare_order(_request(volume=Decimal("0.01")))

        assert adapter.prepared is not None


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
