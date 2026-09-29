from __future__ import annotations

import importlib
import re
import time
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

from ...application.verification import PositionChangeVerifier
from ...domain.enums import AccountType, ExecutionState, ExecutionStatus
from ...domain.exceptions import (
    AutomationError,
    AutomationRejectedError,
    PositionSnapshotUnavailable,
)
from ...domain.models import (
    AccountSnapshot,
    ExecutionResult,
    OrderRequest,
    PositionSnapshot,
    TerminalProfile,
    VerificationEvidence,
)
from ..terminal.discovery import WindowsTerminalDiscovery
from .closing import (
    CLOSE_MENU_ITEM_ID,
    CLOSE_MENU_ITEM_NAME,
    TRADE_LIST_ID,
    CloseGate,
    only_close_entry,
    position_row,
)
from .execution import (
    ExecutionGate,
    assert_action_supported,
    click_final_control,
    confirm_dialog_matches,
    plain_decimal,
    refused_result,
    wait_for_dialog_to_close,
)
from .positions_file import MT5FilePositionSnapshotProvider

MENU_OPEN_SECONDS = 5.0
MENU_SETTLE_SECONDS = 3.0
POPUP_MENU_CLASS = "#32768"

# Matched by prefix, not by equality. Builds differ here: the dialog measured on
# 6184 and 6230 is titled `Order: EURUSD`, while build 6090 titles the same
# dialog plain `Order`. A prefix accepts both without this project having to
# assert that a build's title has not changed again.
ORDER_DIALOG_TITLE = "Order"

_ELEMENT_GONE: tuple[type[BaseException], ...] | None = None


def _require_pywinauto() -> Any:
    try:
        return importlib.import_module("pywinauto")
    except ImportError as exc:
        raise AutomationError("pywinauto is required for real terminal inspection") from exc


def _menu_items(pywinauto: Any, handle: int) -> list[Any]:
    return [
        control
        for control in pywinauto.Desktop(backend="uia")
        .window(handle=handle)
        .descendants()
        if control.element_info.control_type == "MenuItem"
    ]


def _menu_entry_pairs(pywinauto: Any, handle: int) -> list[tuple[str, str]]:
    return [
        (
            str(control.element_info.name or "").strip(),
            str(control.element_info.automation_id or ""),
        )
        for control in _menu_items(pywinauto, handle)
    ]


def _await_menu_entries(pywinauto: Any, handle: int) -> list[tuple[str, str]]:
    """Read a popup menu until it stops changing, or a bound passes.

    A popup window exists before its entries are added, so a single read can see
    a half-built menu and report a missing entry that is about to appear. The
    read is repeated until two consecutive reads agree, and the last list is
    returned either way, so a caller that insists on one exact entry still
    refuses when that entry is genuinely absent.
    """
    deadline = time.monotonic() + MENU_SETTLE_SECONDS
    entries: list[tuple[str, str]] = []
    while time.monotonic() < deadline:
        current = _menu_entry_pairs(pywinauto, handle)
        if current and current == entries:
            return current
        entries = current
        time.sleep(0.15)
    return entries


def _await_menu_entry(
    pywinauto: Any, handle: int, name: str, control_id: str
) -> Any | None:
    """Wait for exactly one entry matching *name* and *control_id*, else ``None``."""
    deadline = time.monotonic() + MENU_SETTLE_SECONDS
    while time.monotonic() < deadline:
        matches = [
            control
            for control in _menu_items(pywinauto, handle)
            if str(control.element_info.name or "").split("\t")[0].strip() == name
            and str(control.element_info.automation_id or "") == control_id
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise AutomationError(
                f"menu entry {name!r} (id {control_id}) matched {len(matches)} elements; "
                "nothing was clicked"
            )
        time.sleep(0.15)
    return None


def _element_gone() -> tuple[type[BaseException], ...]:
    """The errors pywinauto raises once an element has been destroyed.

    MT5 destroys the order dialog itself the moment an order is sent, so every
    read of that dialog after the click can hit one of these. Resolved at
    runtime, like pywinauto itself, so this module still imports on a machine
    without the automation extras.
    """
    global _ELEMENT_GONE
    if _ELEMENT_GONE is None:
        names = ("ElementNotAvailable", "InvalidElementHandle", "ElementNotVisible")
        try:
            library: Any = importlib.import_module("pywinauto")
        except ImportError:
            _ELEMENT_GONE = ()
        else:
            _ELEMENT_GONE = tuple(
                error
                for error in (getattr(library, name, None) for name in names)
                if isinstance(error, type) and issubclass(error, BaseException)
            )
    return _ELEMENT_GONE



def _owner_pid(window: Any) -> int:
    """The process that owns *window*, or ``-1`` when the tree does not say.

    pywinauto raises rather than returning ``None`` on some builds when the
    element is gone mid-read, so a terminal closing during discovery must
    produce a miss here and not an exception that looks like a different fault.
    """
    try:
        return int(window.element_info.process_id)
    except (AttributeError, TypeError, ValueError, AutomationError):
        return -1


class MT5WindowManager:
    def __init__(self) -> None:
        self._window: Any | None = None
        self._order_dialog: Any | None = None

    def find(self, profile: TerminalProfile, process_id: int | None = None) -> Any:
        """Select the one window belonging to the connected terminal.

        When *process_id* is known, that is the only thing that identifies the
        window. Several MT5 instances on one machine routinely carry the *same*
        window title, because the title shows the account name and the broker
        names its demo accounts alike. Matching on the title and then taking the
        first hit is therefore how this project could drive somebody else's
        account: the demo check that follows would pass, because every one of
        them is a demo. An ambiguous set is refused instead.
        """
        try:
            pywinauto = importlib.import_module("pywinauto")
        except ImportError as exc:
            raise AutomationError("pywinauto is required for real terminal inspection") from exc
        windows = pywinauto.Desktop(backend="uia").windows()
        if process_id is not None:
            matches = [window for window in windows if _owner_pid(window) == process_id]
            if not matches:
                raise AutomationError(
                    f"no window belongs to the connected terminal (pid {process_id}); "
                    "the terminal may have been restarted"
                )
            if len(matches) > 1:
                raise AutomationError(
                    f"{len(matches)} windows belong to the connected terminal "
                    f"(pid {process_id}); refusing to guess which one to drive"
                )
        else:
            matches = [
                window
                for window in windows
                if self._matches(str(window.window_text() or ""), profile)
            ]
            if not matches:
                raise AutomationError("configured MT5 window was not found")
            if len(matches) > 1:
                titles = sorted(
                    {f"{_owner_pid(window)}: {window.window_text()}" for window in matches}
                )
                raise AutomationError(
                    f"{len(matches)} MT5 windows match the instance name and their titles "
                    f"are not unique ({'; '.join(titles)}); refusing to choose one. "
                    "This happens when several terminals are open at once, and the fix "
                    "is to drive it through discovery so the window is pinned by process id."
                )
        self._window = matches[0]
        return self._window

    @staticmethod
    def _matches(title: str, profile: TerminalProfile) -> bool:
        normalized = title.lower()
        words = [word for word in re.split(r"[^a-z0-9]+", profile.instance_name.lower()) if word]
        return "terminal64" not in normalized and all(word in normalized for word in words)

    @property
    def root(self) -> Any:
        if self._window is None:
            raise AutomationError("MT5 window is not connected")
        return self._window

    @property
    def title(self) -> str:
        window = self._window
        if window is None:
            raise AutomationError("MT5 window is not connected")
        return str(self._guard("MT5 window", lambda: window.window_text()))

    def contains_symbol(self, symbol: str) -> bool:
        match = re.search(r"\[([A-Za-z0-9._#]+),", self.title)
        return match is not None and match.group(1).upper() == symbol.upper()

    def open_order_dialog(self, timeout_seconds: float = 5.0) -> Any:
        if self._order_dialog is not None and self._is_alive(self._order_dialog):
            return self._order_dialog
        self._order_dialog = None
        if self._window is None:
            raise AutomationError("MT5 window is not connected")
        menu_items = [
            control
            for control in self._window.descendants()
            if control.element_info.control_type == "MenuItem"
            and control.window_text() == "New Order"
        ]
        if not menu_items:
            raise AutomationError("New Order control was not found")
        menu_item = menu_items[0]
        invoke = getattr(menu_item, "invoke", None)
        if callable(invoke):
            invoke()
        else:
            menu_item.click_input()
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            dialogs = [
                control
                for control in self._window.descendants()
                if control.element_info.control_type == "Window"
                and control.window_text().startswith(ORDER_DIALOG_TITLE)
            ]
            if dialogs:
                self._order_dialog = dialogs[0]
                return self._order_dialog
            time.sleep(0.1)
        raise AutomationError("MT5 order dialog did not become ready")

    def close_order_dialog(self, timeout_seconds: float = 5.0) -> None:
        dialog = self._order_dialog
        if dialog is None:
            return
        if not self._is_alive(dialog):
            # MT5 destroyed it, which is the outcome this method waits for.
            self._order_dialog = None
            return
        close_buttons = [
            control
            for control in dialog.descendants()
            if control.element_info.control_type == "Button"
            and control.window_text() == "Close"
        ]
        if not close_buttons:
            raise AutomationError("order dialog close control was not found")
        close_buttons[-1].click_input()
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if not self._is_order_dialog_open():
                self._order_dialog = None
                return
            time.sleep(0.1)
        raise AutomationError("order dialog did not close")

    def select_market_execution(self) -> None:
        dialog = self.open_order_dialog()
        buttons = self._guard(
            "order dialog",
            lambda: [
                control
                for control in dialog.descendants()
                if control.element_info.control_type == "Button"
                and control.window_text() == "Market Execution"
            ],
        )
        if not buttons:
            raise AutomationError("Market Execution control was not found")
        buttons[0].click_input()

    def set_field(self, automation_id: str, value: str) -> None:
        dialog = self.open_order_dialog()
        control = self._find_edit(dialog, automation_id)
        try:
            control.set_edit_text(value)
        except AttributeError as exc:
            raise AutomationError(f"field {automation_id} is not editable") from exc

    def read_field(self, automation_id: str) -> str:
        dialog = self.open_order_dialog()
        control = self._find_edit(dialog, automation_id)
        try:
            return str(control.get_value()).strip()
        except AttributeError as exc:
            raise AutomationError(f"field {automation_id} cannot be read") from exc

    @staticmethod
    def _is_alive(element: Any) -> bool:
        """Whether an element can still be read, i.e. MT5 has not destroyed it."""
        exists = getattr(element, "exists", None)
        try:
            if callable(exists) and not exists():
                return False
            element.descendants()
        except _element_gone():
            return False
        except AutomationError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise AutomationError(f"the MT5 element could not be read: {exc}") from exc
        return True

    def _guard(self, description: str, call: Callable[[], Any]) -> Any:
        try:
            return call()
        except _element_gone() as exc:
            raise AutomationError(f"{description} no longer exists") from exc

    @staticmethod
    def _find_edit(dialog: Any, automation_id: str) -> Any:
        for control in dialog.descendants():
            if (
                control.element_info.control_type == "Edit"
                and control.element_info.automation_id == automation_id
            ):
                return control
        raise AutomationError(f"order field {automation_id} was not found")

    def close_any_order_dialog(self, timeout_seconds: float = 2.0) -> bool:
        """Close an order dialog this manager did not successfully open.

        ``open_order_dialog`` only records a dialog once it recognises it, so a
        build whose dialog is titled differently raises *after* MT5 has already
        put one on screen. A caller that trusts only the recorded handle then
        leaves that dialog open over a live terminal, where on this build a
        single click is a market order. Finding the dialog again and closing it
        with its own Close control is the only way to guarantee tidying up on
        every path, including the path where recognition failed.
        """
        for control in self._guarded_descendants(self._window):
            if control.element_info.control_type != "Window":
                continue
            if not str(control.window_text() or "").startswith(ORDER_DIALOG_TITLE):
                continue
            close_buttons = [
                candidate
                for candidate in self._guarded_descendants(control)
                if candidate.element_info.control_type == "Button"
                and candidate.window_text() == "Close"
            ]
            if not close_buttons:
                return False
            close_buttons[-1].click_input()
            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                if not self._order_dialog_is_present():
                    self._order_dialog = None
                    return True
                time.sleep(0.1)
            return False
        return False

    def _order_dialog_is_present(self) -> bool:
        return any(
            control.element_info.control_type == "Window"
            and str(control.window_text() or "").startswith(ORDER_DIALOG_TITLE)
            for control in self._guarded_descendants(self._window)
        )

    @staticmethod
    def _guarded_descendants(element: Any) -> list[Any]:
        """Read an element's children, treating a destroyed one as no children.

        Used on the tidying-up paths, where raising would leave the terminal
        exactly as it was found, which is the one outcome they exist to prevent.
        """
        if element is None:
            return []
        try:
            return list(element.descendants())
        except _element_gone():
            return []
        except AutomationError:
            return []

    def _is_order_dialog_open(self) -> bool:
        if self._window is None:
            return False
        return self._order_dialog_is_present()

    # -- the trade grid, for closing a position ---------------------------

    def trade_rows(self) -> list[Any]:
        """The rows the Trade tab currently shows, in display order.

        The grid is a real list view, so rows and their rectangles are visible
        through the accessibility tree, but its cell text is not. A row is
        therefore identified by its position in the list and only when the list
        is unambiguous, never by guessing from a pixel.
        """
        window = self._window
        if window is None:
            raise AutomationError("MT5 window is not connected")
        lists = [
            control
            for control in window.descendants()
            if control.element_info.control_type == "List"
            and control.element_info.automation_id == TRADE_LIST_ID
        ]
        if len(lists) != 1:
            raise AutomationError(
                f"the Trade grid was not uniquely identifiable ({len(lists)} lists)"
            )
        rows: list[Any] = self._guard(
            "trade grid",
            lambda: [
                control
                for control in lists[0].descendants()
                if control.element_info.control_type == "ListItem"
            ],
        )
        return rows

    def row_context_menu(self, row: Any) -> RowContextMenu:
        """Open *row*'s context menu once and return a handle for reading and using it.

        The terminal is brought to the foreground first: the row is clicked at a
        screen coordinate taken from the accessibility tree, so a click that
        lands on whatever is in front of the terminal would open a different
        program's menu. The returned object dismisses the menu when its context
        exits, on every path.
        """
        pywinauto = _require_pywinauto()
        self._focus_window()
        if not self._point_inside_window(row):
            raise AutomationError(
                "the trade row is not inside the connected window; refusing to click"
            )
        before = {
            candidate.handle
            for candidate in pywinauto.Desktop(backend="win32").windows()
            if candidate.class_name() == POPUP_MENU_CLASS
        }
        row.click_input(button="right")
        popup = self._await_popup(pywinauto, before)
        return RowContextMenu(pywinauto, popup.handle)

    def _focus_window(self) -> None:
        window = self._window
        if window is None:
            raise AutomationError("MT5 window is not connected")
        self._guard("MT5 window", lambda: window.set_focus())
        time.sleep(0.3)

    def _point_inside_window(self, row: Any) -> bool:
        window = self._window
        if window is None:
            return False
        area = row.rectangle()
        bounds: Any = window.rectangle()
        point = ((area.left + area.right) // 2, (area.top + area.bottom) // 2)
        return bool(
            bounds.left <= point[0] <= bounds.right and bounds.top <= point[1] <= bounds.bottom
        )

    def _await_popup(self, pywinauto: Any, before: set[int]) -> Any:
        deadline = time.monotonic() + MENU_OPEN_SECONDS
        while time.monotonic() < deadline:
            appeared = [
                candidate
                for candidate in pywinauto.Desktop(backend="win32").windows()
                if candidate.class_name() == POPUP_MENU_CLASS
                and candidate.handle not in before
            ]
            if len(appeared) == 1:
                return appeared[0]
            if len(appeared) > 1:
                raise AutomationError("more than one context menu appeared; refusing to guess")
            time.sleep(0.2)
        raise AutomationError("the row context menu did not appear")

    @staticmethod
    def _dismiss_menu(pywinauto: Any) -> None:
        pywinauto.keyboard.send_keys("{ESC}")
        time.sleep(0.2)
        pywinauto.keyboard.send_keys("{ESC}")


class RowContextMenu:
    """An open row menu: read its entries, or click exactly one of them."""

    def __init__(self, pywinauto: Any, handle: int) -> None:
        self._pywinauto = pywinauto
        self._handle = handle
        self._closed = False

    def __enter__(self) -> RowContextMenu:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def entries(self) -> list[tuple[str, str]]:
        return _await_menu_entries(self._pywinauto, self._handle)

    def click(self, name: str, control_id: str) -> None:
        entry = _await_menu_entry(self._pywinauto, self._handle, name, control_id)
        if entry is None:
            raise AutomationError(
                f"menu entry {name!r} (id {control_id}) is not present; nothing was clicked"
            )
        entry.click_input()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        MT5WindowManager._dismiss_menu(self._pywinauto)


class MT5DesktopAdapter:
    def __init__(
        self,
        profile: TerminalProfile,
        window_manager: MT5WindowManager | None = None,
        position_provider: Any | None = None,
        gate: ExecutionGate | None = None,
        close_gate: CloseGate | None = None,
    ) -> None:
        self.profile = profile
        self.window_manager = window_manager or MT5WindowManager()
        self.gate = gate if gate is not None else ExecutionGate()
        self.close_gate = close_gate if close_gate is not None else CloseGate()
        if position_provider is None:
            position_provider = MT5FilePositionSnapshotProvider(
                Path(profile.data_path) / "MQL5" / "Files"
            )
        self.position_provider = position_provider
        self.connected = False
        self.verification_timeout_seconds = 5.0
        self.close_timeout_seconds = 10.0
        self.selected_symbol: str | None = None
        self.prepared: OrderRequest | None = None
        self.resolved_terminal: Any | None = None
        self._baseline: tuple[PositionSnapshot, ...] | None = None
        self._baseline_error: str | None = None

    def connect(self) -> AccountSnapshot:
        # Discovery resolves the process; the window is then selected by that
        # process id rather than by a title several instances may share.
        resolved = WindowsTerminalDiscovery().resolve(self.profile)
        self.resolved_terminal = resolved
        self.window_manager.find(self.profile, resolved.process_id)
        title = self.window_manager.title
        if "demo" not in title.lower():
            raise AutomationError("configured MT5 window is not identified as a demo account")
        self.connected = True
        return AccountSnapshot(AccountType.DEMO, connected=True)

    def get_terminal_state(self) -> str:
        return "CONNECTED_DEMO" if self.connected else "DISCONNECTED"

    def select_symbol(self, symbol: str) -> None:
        if not self.connected:
            raise AutomationError("MT5 terminal is not connected")
        self.window_manager.open_order_dialog()
        self.window_manager.set_field("10325", symbol.upper())
        if not self.window_manager.read_field("10325").upper().startswith(symbol.upper()):
            raise AutomationError(f"symbol field did not accept {symbol}")
        self.selected_symbol = symbol.upper()

    def prepare_order(self, request: OrderRequest) -> None:
        if self.selected_symbol != request.symbol:
            raise AutomationError("symbol was not selected")
        try:
            self.window_manager.select_market_execution()
            self.window_manager.set_field("10333", self._format_decimal(request.volume))
            if request.stop_loss is not None:
                self.window_manager.set_field("10334", self._format_decimal(request.stop_loss))
            if request.take_profit is not None:
                self.window_manager.set_field("10336", self._format_decimal(request.take_profit))
            if request.signal.comment:
                self.window_manager.set_field("1001", request.signal.comment)
            if self.window_manager.read_field("10333") != self._format_decimal(request.volume):
                raise AutomationError("volume field did not accept the request")
            self.prepared = request
            self._capture_baseline()
        except Exception:
            self.window_manager.close_order_dialog()
            raise
        if self.gate.dry_run:
            self.window_manager.close_order_dialog()

    def _capture_baseline(self) -> None:
        """Record the observed account state immediately before a final control.

        A baseline that cannot be observed is recorded as an error rather than
        silently treated as "no positions", so verification can never succeed by
        comparing against an empty account it did not actually observe.
        """
        try:
            self._baseline = self.capture_positions()
            self._baseline_error = None
        except PositionSnapshotUnavailable as exc:
            self._baseline = None
            self._baseline_error = str(exc)

    @staticmethod
    def _format_decimal(value: Decimal) -> str:
        return format(value, "f")

    def capture_positions(self) -> tuple[PositionSnapshot, ...]:
        if not self.connected:
            raise AutomationError("MT5 terminal is not connected")
        return self.position_provider.positions()

    def execute_order(self, request: OrderRequest) -> ExecutionResult:
        """Use the final execution control, only if every gate allows it.

        Refusal is the default. A control click is reported as REQUESTED, never
        as success: acceptance is established afterwards by independent
        observation in ``verify_execution``.
        """
        gate = self.gate
        reason = gate.refusal()
        if reason:
            return refused_result(request, reason)
        try:
            assert_action_supported(request)
        except AutomationRejectedError as exc:
            return refused_result(request, str(exc))
        if self._baseline is None:
            detail = self._baseline_error or "no position baseline was captured"
            return refused_result(request, f"refusing to execute: {detail}")
        try:
            dialog_manager = self.window_manager
            confirm_dialog_matches(dialog_manager, request)
            click_final_control(dialog_manager, request.action)
        except (AutomationError, AutomationRejectedError) as exc:
            return refused_result(request, f"refusing to execute: {exc}")
        wait_for_dialog_to_close(dialog_manager)
        return ExecutionResult(
            execution_id="",
            signal_id=request.signal.signal_id,
            status=ExecutionStatus.REQUESTED,
            state=ExecutionState.EXECUTING.value,
            message=(
                f"final control used for {request.action.value} {request.symbol} "
                f"{plain_decimal(request.volume)}; acceptance not yet observed"
            ),
        )

    def verify_execution(self, request: OrderRequest) -> ExecutionResult:
        """Confirm the outcome against an independently observed position list.

        A snapshot that cannot be read, or a missing baseline, produces UNKNOWN.
        Only exactly one new position matching symbol, side and volume is accepted.
        The baseline and observed references travel with the result so a verified
        outcome can be traced back to the exact readings that produced it.

        A single unreadable snapshot is not a failure. MT5 writes the snapshot
        while it is busy submitting an order, so a read can land on a file being
        rewritten. The loop keeps polling until its deadline and only then fails
        closed, with the last observation error as the reason.
        """
        if self._baseline is None:
            detail = self._baseline_error or "no position baseline was captured"
            return self._unknown(request, f"verification baseline unavailable: {detail}")
        deadline = time.monotonic() + self.verification_timeout_seconds
        last_evidence: VerificationEvidence | None = None
        last_message = "no position observation completed"
        last_error = ""
        while True:
            try:
                after = self.capture_positions()
            except PositionSnapshotUnavailable as exc:
                last_error = f"position observation unavailable: {exc}"
                if time.monotonic() >= deadline:
                    return self._unknown(request, last_error, last_evidence)
                time.sleep(0.25)
                continue
            last_error = ""
            outcome = PositionChangeVerifier().verify(request, self._baseline, after)
            last_message = outcome.message
            last_evidence = VerificationEvidence(
                baseline=self._position_reference(self._baseline),
                observed=self._position_reference(after),
                position_id=outcome.position_id,
            )
            if outcome.verified:
                return ExecutionResult(
                    execution_id="",
                    signal_id=request.signal.signal_id,
                    status=ExecutionStatus.ACCEPTED,
                    state=ExecutionState.SUCCESS.value,
                    message=outcome.message,
                    order_reference=outcome.position_id,
                    evidence=last_evidence,
                )
            if time.monotonic() >= deadline:
                return self._unknown(request, last_message, last_evidence)
            time.sleep(0.25)

    @staticmethod
    def _position_reference(positions: tuple[PositionSnapshot, ...]) -> str:
        values = ",".join(
            f"{position.position_id}:{position.symbol}:{position.side}:{position.volume}"
            for position in positions
        )
        return f"ui positions={values or 'none'}"

    def _unknown(
        self,
        request: OrderRequest,
        message: str,
        evidence: VerificationEvidence | None = None,
    ) -> ExecutionResult:
        return ExecutionResult(
            execution_id="",
            signal_id=request.signal.signal_id,
            status=ExecutionStatus.UNKNOWN,
            state=ExecutionState.VERIFICATION_FAILED.value,
            message=message,
            evidence=evidence,
        )

    def close_position(self, position_id: str) -> ExecutionResult:
        """Close one position and prove it with an independent observation.

        The click is an action; the closed position is observed. The account
        carries no `closed` state in the snapshot, so a close is accepted only
        when the ticket that was open at the start of this call is gone from a
        later reading, and a position that merely changed would not be mistaken
        for a closed one.
        """
        ticket = str(position_id).strip()
        refusal = self.close_gate.refusal()
        if refusal:
            return self._close_refused(refusal)
        if not self.connected:
            return self._close_refused("MT5 terminal is not connected")
        try:
            observed = self.capture_positions()
        except PositionSnapshotUnavailable as exc:
            return self._close_unknown(
                f"position observation unavailable before closing: {exc}"
            )
        before = [position for position in observed if position.position_id == ticket]
        if not before:
            return self._close_refused(
                f"position {ticket} is not in the observed snapshot; refusing to close "
                "something this application cannot see"
            )
        if len(observed) != 1:
            return self._close_refused(
                f"{len(observed)} positions are open and the trade grid exposes no row "
                "text, so the intended one cannot be identified; close it by hand"
            )
        try:
            rows = self.window_manager.trade_rows()
            row = position_row(rows)
            with self.window_manager.row_context_menu(row) as menu:
                only_close_entry(menu.entries())
                menu.click(CLOSE_MENU_ITEM_NAME, CLOSE_MENU_ITEM_ID)
        except LookupError as exc:
            return self._close_refused(f"refusing to close: {exc}")
        except AutomationError as exc:
            return self._close_unknown(f"the close control could not be used: {exc}")

        deadline = time.monotonic() + self.close_timeout_seconds
        while True:
            try:
                after = self.capture_positions()
            except PositionSnapshotUnavailable as exc:
                if time.monotonic() >= deadline:
                    return self._close_unknown(
                        f"the close was used and the position could not be observed: {exc}",
                        ticket,
                    )
                time.sleep(0.25)
                continue
            if all(position.position_id != ticket for position in after):
                return ExecutionResult(
                    execution_id="",
                    signal_id="",
                    status=ExecutionStatus.CLOSED,
                    state=ExecutionState.POSITION_CLOSED.value,
                    message=(
                        f"position {ticket} is no longer present in the observed "
                        f"snapshot ({len(before)} before, {len(after)} after)"
                    ),
                    order_reference=ticket,
                )
            if time.monotonic() >= deadline:
                return self._close_unknown(
                    f"position {ticket} is still present after the close control was used",
                    ticket,
                )
            time.sleep(0.25)

    def _close_refused(self, reason: str) -> ExecutionResult:
        return ExecutionResult(
            execution_id="",
            signal_id="",
            status=ExecutionStatus.REJECTED,
            state=ExecutionState.POSITION_CLOSE_REFUSED.value,
            message=reason,
        )

    def _close_unknown(self, reason: str, ticket: str = "") -> ExecutionResult:
        return ExecutionResult(
            execution_id="",
            signal_id="",
            status=ExecutionStatus.UNKNOWN,
            state=ExecutionState.UNKNOWN_EXECUTION.value,
            message=reason,
            order_reference=ticket or None,
        )
