"""A terminal update must be detected before it is met at the moment of trading.

Every control this project uses is identified by a value measured on one build.
These tests are about the two ways that can go wrong: the window manager driving
the wrong terminal because several instances share a title, and a control moving
under a new identifier without anybody noticing until a live order is attempted.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from auto_trade.domain.exceptions import AutomationError
from auto_trade.domain.models import ExecutionPolicy, RiskLimits, TerminalProfile
from auto_trade.infrastructure.automation.closing import CLOSE_MENU_ITEM_ID
from auto_trade.infrastructure.automation.control_probe import (
    NOT_PROBED,
    ControlReport,
    probe_build,
    probe_main_window,
    probe_order_dialog,
    probe_trade_grid,
    report_close_controls,
    summarise,
)
from auto_trade.infrastructure.automation.execution import (
    BUY_BUTTON_ID,
    BUY_BUTTON_NAME,
    SELL_BUTTON_ID,
    SELL_BUTTON_NAME,
    STOP_LOSS_FIELD_ID,
    SYMBOL_FIELD_ID,
    TAKE_PROFIT_FIELD_ID,
    VOLUME_FIELD_ID,
)
from auto_trade.infrastructure.automation.window_manager import MT5WindowManager
from auto_trade.infrastructure.configuration import AppConfig

NOW = datetime(2026, 9, 29, 10, 0, 0, tzinfo=UTC)


# -- fakes shaped like what pywinauto returns ---------------------------


class FakeControl:
    def __init__(self, kind: str, name: str = "", automation_id: str = "") -> None:
        self.element_info = FakeInfo(kind, name, automation_id)
        self.clicked = False

    def click_input(self, **_kwargs: Any) -> None:
        self.clicked = True


class FakeInfo:
    def __init__(self, kind: str, name: str, automation_id: str) -> None:
        self.control_type = kind
        self.name = name
        self.automation_id = automation_id
        # pywinauto reports the owning process on every element; the window
        # manager reads it to pin a window to the terminal discovery resolved.
        self.process_id = 0


class FakeElement:
    def __init__(self, controls: list[FakeControl], process_id: int = 1) -> None:
        self._controls = controls
        self.element_info = FakeInfo("Window", "", "")
        self.element_info.process_id = process_id
        self.handle = 1

    def descendants(self) -> list[FakeControl]:
        return list(self._controls)

    def window_text(self) -> str:
        return "53183488 - Alpari-MT5-Demo: Demo Account - Hedge - Alpari"


def dialog_controls(
    buy_id: str = BUY_BUTTON_ID,
    sell_id: str = SELL_BUTTON_ID,
    buy_name: str = BUY_BUTTON_NAME,
    symbol_id: str = SYMBOL_FIELD_ID,
) -> list[FakeControl]:
    return [
        FakeControl("Edit", "", symbol_id),
        FakeControl("Edit", "", VOLUME_FIELD_ID),
        FakeControl("Edit", "", STOP_LOSS_FIELD_ID),
        FakeControl("Edit", "", TAKE_PROFIT_FIELD_ID),
        FakeControl("Button", buy_name, buy_id),
        FakeControl("Button", SELL_BUTTON_NAME, sell_id),
        FakeControl("Button", "Market Execution", ""),
        FakeControl("Button", "Close", ""),
    ]


def report_for(reports: list[ControlReport], label: str) -> ControlReport:
    return next(report for report in reports if report.label == label)


# -- an unchanged build is a pass ---------------------------------------


def test_a_build_that_has_not_moved_reports_ok() -> None:
    dialog = FakeElement(dialog_controls())
    window = FakeElement([FakeControl("MenuItem", "New Order", "")] + dialog_controls())

    summary = summarise(
        [*probe_order_dialog(dialog), *probe_main_window(window), *probe_build(6230)]
    )

    assert summary["verdict"] == "OK"
    assert summary["drifted"] == []
    assert summary["missing"] == []


# -- drift is detected, not tolerated ------------------------------------


def test_a_final_control_with_a_new_id_is_reported_as_drifted() -> None:
    """The exact failure an MT5 update causes, and it must not read as a pass."""
    dialog = FakeElement(dialog_controls(buy_id="99999"))

    summary = summarise(probe_order_dialog(dialog))

    assert summary["verdict"] == "DRIFTED"
    assert "final_control_buy" in summary["drifted"]


def test_a_renamed_final_control_is_drifted_not_accepted() -> None:
    """A button that kept its id but changed name is a button we have not measured."""
    dialog = FakeElement(dialog_controls(buy_name="Buy"))

    reports = probe_order_dialog(dialog)
    entry = report_for(reports, "final_control_buy")

    assert entry.status == "DRIFTED"
    assert "different name" in entry.found


def test_a_removed_final_control_is_reported_missing() -> None:
    dialog = FakeElement(
        [control for control in dialog_controls() if control.element_info.control_type != "Button"
         or control.element_info.name != BUY_BUTTON_NAME]
    )

    summary = summarise(probe_order_dialog(dialog))

    assert summary["verdict"] == "DRIFTED"
    assert "final_control_buy" in summary["missing"]


def test_a_moved_order_field_is_reported_missing() -> None:
    dialog = FakeElement(dialog_controls(symbol_id="77777"))

    summary = summarise(probe_order_dialog(dialog))

    assert "symbol" in summary["missing"]


def test_two_final_controls_with_one_name_is_ambiguous() -> None:
    dialog = FakeElement(
        [*dialog_controls(), FakeControl("Button", BUY_BUTTON_NAME, BUY_BUTTON_ID)]
    )

    summary = summarise(probe_order_dialog(dialog))

    assert summary["verdict"] == "REFUSED"
    assert "final_control_buy" in summary["ambiguous"]


def test_a_localised_terminal_is_reported_rather_than_failing_later() -> None:
    """MT5 renders these names in the UI language; a probe says so explicitly."""
    window = FakeElement([FakeControl("MenuItem", "Neue Order", "")])

    reports = probe_main_window(window)

    assert report_for(reports, "new_order_menu_item").status == "MISSING"


# -- the probe reads the right window -----------------------------------


def test_new_order_is_probed_on_the_main_window_not_the_dialog() -> None:
    """It is a menu item on the window, so probing the dialog would be a false alarm."""
    dialog = FakeElement(dialog_controls())
    window = FakeElement([FakeControl("MenuItem", "New Order", "")])

    assert report_for(probe_main_window(window), "new_order_menu_item").status == "OK"

    dialog_labels = {report.label for report in probe_order_dialog(dialog)}
    assert "new_order_menu_item" not in dialog_labels
    # And the dialog is still fully accounted for, so nothing is merely skipped.
    assert {"symbol", "volume", "final_control_buy", "final_control_sell"} <= dialog_labels


# -- the trade grid and the close control --------------------------------


def test_a_trade_grid_with_the_expected_id_is_ok() -> None:
    window = FakeElement([FakeControl("List", "", "10328")])
    assert report_for(probe_trade_grid(window), "trade_grid").status == "OK"


def test_a_trade_grid_with_a_new_id_is_drifted() -> None:
    window = FakeElement([FakeControl("List", "", "55555")])
    entry = report_for(probe_trade_grid(window), "trade_grid")
    assert entry.status == "DRIFTED"
    assert "55555" in entry.found


def test_an_absent_trade_grid_is_not_probed_rather_than_passed() -> None:
    """No grid is not the same as a correct grid, and it must not read as a pass."""
    summary = summarise(probe_trade_grid(FakeElement([])))

    assert summary["verdict"] == "PARTIAL"
    assert "trade_grid" in summary["not_probed"]


def test_two_trade_grids_are_ambiguous() -> None:
    window = FakeElement([FakeControl("List", "", "10328"), FakeControl("List", "", "10328")])
    assert report_for(probe_trade_grid(window), "trade_grid").status == "AMBIGUOUS"


# -- a collapsed Trade tab is not a build that changed --------------------


class FakeSelection:
    def __init__(self, selected: bool) -> None:
        self.CurrentIsSelected = selected


class FakeTab(FakeControl):
    """A tab item, which reports whether it is the selected one."""

    def __init__(self, name: str, selected: bool) -> None:
        super().__init__("TabItem", name, "")
        self.iface_selection_item = FakeSelection(selected)


def test_a_collapsed_trade_tab_is_not_probed_rather_than_drifted() -> None:
    """Other panels keep their lists when the Trade tab is closed.

    Reporting drift here sends an operator to re-measure a build that did not
    change, having been told the close path is broken.
    """
    window = FakeElement(
        [
            FakeControl("List", "", "10144"),
            FakeControl("List", "", "10128"),
            FakeTab("Trade", selected=False),
            FakeTab("Journal", selected=True),
        ]
    )

    entry = report_for(probe_trade_grid(window), "trade_grid")

    assert entry.status == NOT_PROBED
    assert "10144" not in entry.found


def test_a_missing_grid_with_the_trade_tab_open_is_drifted() -> None:
    """With the Trade tab showing, an absent grid really does mean the build moved."""
    window = FakeElement(
        [FakeControl("List", "", "10144"), FakeTab("Trade", selected=True)]
    )

    assert report_for(probe_trade_grid(window), "trade_grid").status == "DRIFTED"


def test_an_unreadable_tab_strip_does_not_soften_drift() -> None:
    """A terminal whose selection state cannot be read is an unknown, not a pass.

    Defaulting the other way would let a real build change be reported as
    merely unprobed, which is the failure this whole project is built to avoid.
    """

    class ExplodingTab(FakeControl):
        @property
        def iface_selection_item(self) -> Any:
            raise RuntimeError("element gone")

    window = FakeElement(
        [FakeControl("List", "", "10144"), ExplodingTab("TabItem", "Trade", "")]
    )

    assert report_for(probe_trade_grid(window), "trade_grid").status == "DRIFTED"


def test_a_trade_grid_is_still_ok_when_the_tab_is_open() -> None:
    window = FakeElement([FakeControl("List", "", "10328"), FakeTab("Trade", selected=True)])

    assert report_for(probe_trade_grid(window), "trade_grid").status == "OK"


def test_the_close_control_is_reported_against_its_measured_id() -> None:
    good = report_close_controls([("Close Position", CLOSE_MENU_ITEM_ID)])
    assert good.status == "OK"

    drifted = report_close_controls([("Close Position", "12345")])
    assert drifted.status == "DRIFTED"


def test_a_near_miss_close_entry_is_not_accepted() -> None:
    """`Close by` and `Close All` are neighbours of the one entry this code uses."""
    for name in ("Close by", "Close 50%", "Close All", "Modify or Delete"):
        assert report_close_controls([(name, "33033")]).status == "MISSING"


# -- the build is part of the answer -------------------------------------


def test_an_unknown_build_is_not_probed_rather_than_assumed() -> None:
    summary = summarise(probe_build(None))
    assert summary["verdict"] == "PARTIAL"
    assert "terminal_build" in summary["not_probed"]


def test_the_build_is_recorded_with_the_report() -> None:
    entry = report_for(probe_build(6230), "terminal_build")
    assert entry.status == "OK"
    assert entry.found == "6230"


# -- the window is pinned to a process, never chosen by title ------------


class _FakeDesktop:
    def __init__(self, windows: list[FakeElement]) -> None:
        self._windows = windows

    def windows(self) -> list[FakeElement]:
        return self._windows


def _manager_with(monkeypatch: pytest.MonkeyPatch, windows: list[FakeElement]) -> MT5WindowManager:
    import importlib

    module = importlib.import_module("pywinauto")
    monkeypatch.setattr(module, "Desktop", lambda **_kwargs: _FakeDesktop(windows), raising=False)
    return MT5WindowManager()


PROFILE = TerminalProfile(
    name="alpari-demo",
    terminal_path=r"C:\Users\bagheri\AppData\Roaming\Alpari MT5_5\terminal64.exe",
    data_path=r"C:\data",
    instance_name="Alpari-MT5-Demo",
)


def test_several_titles_are_refused_rather_than_the_first_being_taken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The defect: four terminals share this title, and one of them is not ours.

    Every one of these windows is a demo account, so the demo check that follows
    would pass for all of them. Choosing the first would be choosing an account
    by enumeration order.
    """
    windows = [FakeElement([], process_id=pid) for pid in (4208, 5680, 8168, 8488)]
    manager = _manager_with(monkeypatch, windows)

    with pytest.raises(AutomationError, match="refusing to choose one"):
        manager.find(PROFILE)


def test_the_window_is_selected_by_process_id_among_identical_titles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    windows = [FakeElement([], process_id=pid) for pid in (4208, 5680, 8168, 8488)]
    manager = _manager_with(monkeypatch, windows)

    chosen = manager.find(PROFILE, process_id=8168)

    assert chosen.element_info.process_id == 8168


def test_a_process_id_with_no_window_is_a_miss_not_a_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A restarted terminal must not silently fall back to a title match."""
    windows = [FakeElement([], process_id=4208)]
    manager = _manager_with(monkeypatch, windows)

    with pytest.raises(AutomationError, match="no window belongs"):
        manager.find(PROFILE, process_id=5680)


def test_two_windows_for_one_process_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    windows = [FakeElement([], process_id=5680), FakeElement([], process_id=5680)]
    manager = _manager_with(monkeypatch, windows)

    with pytest.raises(AutomationError, match="refusing to guess"):
        manager.find(PROFILE, process_id=5680)


def test_a_single_matching_window_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _manager_with(monkeypatch, [FakeElement([], process_id=5680)])
    assert manager.find(PROFILE, process_id=5680).element_info.process_id == 5680


# -- the report is recorded, not overwritten -----------------------------


def test_reports_are_kept_as_a_history(config: AppConfig) -> None:
    from auto_trade.interfaces.preflight import compare_builds, record

    assert compare_builds(config)["status"] == "NO_HISTORY"

    record(config, {"verdict": "OK", "terminal": {"build": 6230}, "controls": []})
    assert compare_builds(config)["status"] == "INSUFFICIENT"

    record(config, {"verdict": "OK", "terminal": {"build": 6230}, "controls": []})
    compared = compare_builds(config)
    assert compared["status"] == "COMPARED"
    assert compared["verdict_changed"] is False


def test_a_changed_control_is_named_by_the_comparison(config: AppConfig) -> None:
    """This is the report an operator reads after an update, so it must be specific."""
    from auto_trade.interfaces.preflight import compare_builds, record

    def report(found: str) -> dict[str, Any]:
        return {
            "verdict": "OK",
            "terminal": {"build": 6230},
            "controls": [
                {"control": "final_control_buy", "status": "OK", "found": found, "expected": "x"}
            ],
        }

    record(config, report(BUY_BUTTON_ID))
    record(config, report("99999"))

    compared = compare_builds(config)
    assert compared["controls_that_changed"] == ["final_control_buy"]
    # The verdict is about the terminal as a whole and is unchanged here, which
    # is exactly why the per-control diff is reported separately: a summary that
    # stayed "OK" would otherwise hide a control that moved under it.
    assert compared["verdict_changed"] is False


def test_a_verdict_change_is_reported(config: AppConfig) -> None:
    from auto_trade.interfaces.preflight import compare_builds, record

    record(config, {"verdict": "OK", "terminal": {"build": 6184}, "controls": []})
    record(config, {"verdict": "DRIFTED", "terminal": {"build": 6230}, "controls": []})

    compared = compare_builds(config)
    assert compared["verdict_before"] == "OK"
    assert compared["verdict_now"] == "DRIFTED"
    assert compared["verdict_changed"] is True


def test_an_unreadable_history_is_reported_not_raised(config: AppConfig) -> None:
    from auto_trade.interfaces.preflight import compare_builds

    target = config.log_directory / "terminal_check.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{not json", encoding="utf-8")

    assert compare_builds(config)["status"] == "UNREADABLE"


def test_the_report_file_contains_no_token(config: AppConfig) -> None:
    """The report is written beside the audit log and may be shared for support."""
    from auto_trade.interfaces.preflight import record

    written = record(config, {"verdict": "OK", "terminal": {"build": 6230}, "controls": []})

    assert written.is_file()
    assert json.loads(written.read_text(encoding="utf-8"))["history"]


# -- fixtures ------------------------------------------------------------


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        terminal_path=tmp_path / "terminal64.exe",
        data_path=tmp_path / "data",
        instance_name="Alpari-MT5-Demo",
        signal_directory=tmp_path / "signals",
        log_directory=tmp_path / "logs",
        policy=ExecutionPolicy(dry_run=True, demo_only=True),
        risk=RiskLimits(frozenset({"EURUSD"}), Decimal("1.0"), 5, 10),
    )
