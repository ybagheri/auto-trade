"""Detecting that an MT5 update moved something this project depends on.

Every control this project uses is matched by a *measured* identifier: an
automation id, or a name that MT5 happens to render in English. Both are
properties of one build of one terminal, and an MT5 update is exactly the event
that can change them. When it does, the failure is loud but late — the order
path simply reports that a control was not found, at the moment somebody is
trying to trade.

This module moves that discovery forward. It opens the order dialog, reads the
control tree, and reports each expected identifier as present, changed, or
absent, without touching a final control. The answer is a report, not a
repair: nothing here guesses a replacement, because a control found under a new
id is a control whose behaviour has not been established, and this project's rule
is that an unmeasured control is a control that is not used.

The expected values live in `execution.py` and `closing.py` next to the code
that uses them, so a probe cannot pass against a stale copy of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .closing import CLOSE_MENU_ITEM_ID, CLOSE_MENU_ITEM_NAME, TRADE_LIST_ID
from .execution import (
    BUY_BUTTON_ID,
    BUY_BUTTON_NAME,
    SELL_BUTTON_ID,
    SELL_BUTTON_NAME,
    STOP_LOSS_FIELD_ID,
    SYMBOL_FIELD_ID,
    TAKE_PROFIT_FIELD_ID,
    VOLUME_FIELD_ID,
)

# The controls the order path needs, as (label, kind, expected value). The kind
# decides how the value is compared, because a field is identified by id alone
# while a final control is matched by name *and* id, and that difference is the
# safety property the order path depends on.
EXPECTED_FIELDS: tuple[tuple[str, str], ...] = (
    ("symbol", SYMBOL_FIELD_ID),
    ("volume", VOLUME_FIELD_ID),
    ("stop_loss", STOP_LOSS_FIELD_ID),
    ("take_profit", TAKE_PROFIT_FIELD_ID),
)

EXPECTED_FINAL_CONTROLS: tuple[tuple[str, str, str], ...] = (
    ("buy", BUY_BUTTON_NAME, BUY_BUTTON_ID),
    ("sell", SELL_BUTTON_NAME, SELL_BUTTON_ID),
)

# Controls matched by visible name only. MT5 localises these, so a terminal set
# to another language is reported as a drift rather than silently failing later.
EXPECTED_NAMED_CONTROLS: tuple[tuple[str, str], ...] = (
    ("new_order_menu_item", "New Order"),
    ("market_execution_button", "Market Execution"),
    ("close_menu_item", CLOSE_MENU_ITEM_NAME),
)

MENU_ITEM = "MenuItem"
BUTTON = "Button"
EDIT = "Edit"
LIST = "List"
WINDOW = "Window"
TAB_ITEM = "TabItem"

# The Toolbox tab whose content is the Trade grid. Named, not identified by an
# automation id, because the tab strip's id is the same for every tab and a
# missing grid is explained by which tab is showing.
TRADE_TAB_NAME = "Trade"

OK = "OK"
DRIFTED = "DRIFTED"
MISSING = "MISSING"
AMBIGUOUS = "AMBIGUOUS"
NOT_PROBED = "NOT_PROBED"


@dataclass(frozen=True)
class ControlReport:
    """What one expected control looked like in the live terminal."""

    label: str
    status: str
    expected: str
    found: str
    detail: str = ""

    @property
    def acceptable(self) -> bool:
        return self.status in {OK, NOT_PROBED}

    def to_dict(self) -> dict[str, Any]:
        return {
            "control": self.label,
            "status": self.status,
            "expected": self.expected,
            "found": self.found,
            "detail": self.detail,
        }


def probe_order_dialog(dialog: Any) -> list[ControlReport]:
    """Read the order dialog and report every control the order path depends on.

    Read-only by construction: the dialog is inspected, never clicked, and the
    caller closes it. A control that is missing produces a report, not an
    exception, because the whole point is to enumerate *what* broke.
    """
    controls = list(_descendants(dialog))
    reports: list[ControlReport] = []
    reports.extend(_probe_edits(controls))
    reports.extend(_probe_final_controls(controls))
    reports.extend(_probe_named(controls, "market_execution_button"))
    return reports


def probe_main_window(window: Any) -> list[ControlReport]:
    """Report the controls that live on the terminal window rather than the dialog.

    ``New Order`` is a menu item on the main window, so probing for it inside the
    order dialog would report a control that is present and working as missing.
    That false positive is worse than no probe at all, because an operator would
    go looking for a break that does not exist.
    """
    controls = list(_descendants(window))
    return _probe_named(controls, "new_order_menu_item")


def probe_trade_grid(window: Any) -> list[ControlReport]:
    """Report the Trade grid, which only exists when the Trade tab is open.

    The close path needs the grid's automation id, and the grid is not in the
    order dialog, so this is a separate probe. This is a read.

    A collapsed Toolbox takes its grid off the accessibility tree, but the other
    panels keep theirs, so a terminal with the Trade tab closed still reports
    several list controls. Counting those as evidence of drift is a false
    positive with a real cost: an operator would go looking for a build change
    that did not happen, having been told the close path is broken. The absent
    grid is therefore reported as *not probed* whenever a Trade tab is visible
    and not the selected one, which is the state that explains it. Drift is
    still reported when the Trade tab is selected and the grid is genuinely
    absent, because that is the case that means the build changed.
    """
    lists = [control for control in _descendants(window) if _kind(control) == LIST]
    matching = [control for control in lists if _identifier(control) == TRADE_LIST_ID]
    if not lists:
        return [
            ControlReport(
                "trade_grid",
                NOT_PROBED,
                TRADE_LIST_ID,
                "",
                "no list control is present; the Trade tab is probably not open",
            )
        ]
    if not matching and _trade_tab_is_open(window) is False:
        return [
            ControlReport(
                "trade_grid",
                NOT_PROBED,
                TRADE_LIST_ID,
                "",
                "the Trade tab is not the selected tab, so the grid is not on screen; "
                "the other lists belong to other panels and say nothing about this id",
            )
        ]
    if not matching:
        return [
            ControlReport(
                "trade_grid",
                DRIFTED,
                TRADE_LIST_ID,
                ", ".join(sorted({_identifier(control) or "(none)" for control in lists})),
                "a list control exists but none carries the expected id",
            )
        ]
    if len(matching) > 1:
        return [
            ControlReport(
                "trade_grid",
                AMBIGUOUS,
                TRADE_LIST_ID,
                f"{len(matching)} matches",
                "more than one list carries the trade grid id; the close path refuses this",
            )
        ]
    return [ControlReport("trade_grid", OK, TRADE_LIST_ID, TRADE_LIST_ID)]


def _trade_tab_is_open(window: Any) -> bool | None:
    """Whether the Trade tab is the one currently showing, or ``None`` if unknown.

    The three states are kept apart on purpose. Only a positively identified
    Trade tab that is *not* selected explains a missing grid, and only a
    positively identified Trade tab that *is* selected turns that missing grid
    into a build change. A tab strip that cannot be read is neither: it returns
    ``None`` so the caller keeps reporting drift, because an unknown UI state is
    not evidence that nothing is wrong with the build.
    """
    for control in _descendants(window):
        if _kind(control) != TAB_ITEM or _name(control) != TRADE_TAB_NAME:
            continue
        try:
            return bool(control.iface_selection_item.CurrentIsSelected)
        except Exception:  # noqa: BLE001
            return None
    return None


def probe_build(build: int | None) -> list[ControlReport]:
    """Record the build the observations were made on.

    This is not a pass or a fail. It is the key every other row is filed under,
    because an identifier measured on one build says nothing about another, and a
    report that does not name its build invites exactly that mistake.
    """
    return [
        ControlReport(
            "terminal_build",
            OK if build else NOT_PROBED,
            "reported by the position snapshot",
            str(build) if build else "unknown",
        )
    ]


def summarise(reports: list[ControlReport]) -> dict[str, Any]:
    """Turn the rows into a verdict an operator can act on.

    The verdict is about the *terminal*, never about a trade: it says whether
    this build still presents the controls this code was written against.
    """
    drifted = [report for report in reports if report.status == DRIFTED]
    missing = [report for report in reports if report.status == MISSING]
    ambiguous = [report for report in reports if report.status == AMBIGUOUS]
    unprobed = [report for report in reports if report.status == NOT_PROBED]
    if ambiguous:
        verdict = "REFUSED"
    elif drifted or missing:
        verdict = "DRIFTED"
    elif unprobed:
        verdict = "PARTIAL"
    else:
        verdict = "OK"
    return {
        "verdict": verdict,
        "checked": len(reports),
        "drifted": [report.label for report in drifted],
        "missing": [report.label for report in missing],
        "ambiguous": [report.label for report in ambiguous],
        "not_probed": [report.label for report in unprobed],
        "controls": [report.to_dict() for report in reports],
    }


def _descendants(element: Any) -> list[Any]:
    try:
        return list(element.descendants())
    except Exception:  # noqa: BLE001
        # pywinauto raises a family of errors once MT5 destroys an element. A
        # probe that cannot read the tree reports nothing rather than guessing.
        return []


def _kind(control: Any) -> str:
    return str(getattr(control.element_info, "control_type", "") or "")


def _identifier(control: Any) -> str:
    return str(getattr(control.element_info, "automation_id", "") or "")


def _name(control: Any) -> str:
    return str(getattr(control.element_info, "name", "") or "").strip()


def _probe_edits(controls: list[Any]) -> list[ControlReport]:
    edits = [control for control in controls if _kind(control) == EDIT]
    known = {_identifier(control) for control in edits}
    reports: list[ControlReport] = []
    for label, expected in EXPECTED_FIELDS:
        if expected in known:
            reports.append(ControlReport(label, OK, expected, expected))
        else:
            reports.append(
                ControlReport(
                    label,
                    MISSING,
                    expected,
                    ", ".join(sorted(item for item in known if item)) or "(no edit fields)",
                    "the dialog no longer exposes this field id; the order path would "
                    "refuse to prepare a request",
                )
            )
    return reports


def _probe_final_controls(controls: list[Any]) -> list[ControlReport]:
    reports: list[ControlReport] = []
    for label, name, control_id in EXPECTED_FINAL_CONTROLS:
        by_name = [
            control
            for control in controls
            if _kind(control) == BUTTON and _name(control) == name
        ]
        if not by_name:
            same_id = [
                control
                for control in controls
                if _kind(control) == BUTTON and _identifier(control) == control_id
            ]
            reports.append(
                ControlReport(
                    f"final_control_{label}",
                    MISSING if not same_id else DRIFTED,
                    f"{name} (id {control_id})",
                    (
                        "present under the same id but a different name: "
                        + ", ".join(sorted(_name(control) for control in same_id))
                        if same_id
                        else "not present"
                    ),
                    (
                        "the id still exists but the name moved. The order path matches on "
                        "both, so it would refuse to click. A renamed button is also a "
                        "button whose behaviour has not been established."
                    )
                    if same_id
                    else "this control is gone; the order path would refuse to click",
                )
            )
            continue
        if len(by_name) > 1:
            reports.append(
                ControlReport(
                    f"final_control_{label}",
                    AMBIGUOUS,
                    f"{name} (id {control_id})",
                    f"{len(by_name)} elements share the name",
                    "the order path refuses to guess between them",
                )
            )
            continue
        actual = _identifier(by_name[0])
        reports.append(
            ControlReport(
                f"final_control_{label}",
                OK if actual == control_id else DRIFTED,
                control_id,
                actual or "(no id)",
                (
                    ""
                    if actual == control_id
                    else "the button is still named the same but its automation id changed; "
                    "the order path matches on both and would refuse to click"
                ),
            )
        )
    return reports


def _probe_named(controls: list[Any], label: str) -> list[ControlReport]:
    expected = dict(EXPECTED_NAMED_CONTROLS)[label]
    matches = [control for control in controls if _name(control) == expected]
    if len(matches) == 1:
        return [ControlReport(label, OK, expected, expected)]
    if not matches:
        return [
            ControlReport(
                label,
                MISSING,
                expected,
                "not present",
                "matched by visible name only, so a localised terminal is reported here "
                "rather than failing later at the click",
            )
        ]
    return [
        ControlReport(
            label,
            AMBIGUOUS,
            expected,
            f"{len(matches)} elements share the name",
            "the first match is never used; ambiguity is refused",
        )
    ]


def report_close_controls(entries: list[tuple[str, str]]) -> ControlReport:
    """Report the row context menu's close entry against the measured identifier.

    Only reachable while a context menu is open, which needs a position this
    project opened. Absent that, the close path is reported as not probed rather
    than as passing.
    """
    candidates = [
        (name, control_id)
        for name, control_id in entries
        if name.split("\t")[0].strip() == CLOSE_MENU_ITEM_NAME
    ]
    if not candidates:
        return ControlReport(
            "final_control_close",
            MISSING,
            f"{CLOSE_MENU_ITEM_NAME} (id {CLOSE_MENU_ITEM_ID})",
            "not present",
            "the close path would refuse rather than use another entry",
        )
    if len(candidates) > 1:
        return ControlReport(
            "final_control_close",
            AMBIGUOUS,
            CLOSE_MENU_ITEM_NAME,
            f"{len(candidates)} entries share the name",
            "the close path refuses to guess between them",
        )
    name, control_id = candidates[0]
    if control_id != CLOSE_MENU_ITEM_ID:
        return ControlReport(
            "final_control_close",
            DRIFTED,
            CLOSE_MENU_ITEM_ID,
            control_id or "(no id)",
            "the entry is named the same but its automation id changed; the close path "
            "refuses rather than clicking an unmeasured control",
        )
    return ControlReport("final_control_close", OK, CLOSE_MENU_ITEM_ID, control_id)
