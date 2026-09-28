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

_ELEMENT_GONE: tuple[type[BaseException], ...] | None = None


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



class MT5WindowManager:
    def __init__(self) -> None:
        self._window: Any | None = None
        self._order_dialog: Any | None = None

    def find(self, profile: TerminalProfile) -> Any:
        try:
            pywinauto = importlib.import_module("pywinauto")
        except ImportError as exc:
            raise AutomationError("pywinauto is required for real terminal inspection") from exc
        windows = pywinauto.Desktop(backend="uia").windows()
        matches = [window for window in windows if self._matches(window.window_text(), profile)]
        if not matches:
            raise AutomationError("configured MT5 window was not found")
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
                and control.window_text().startswith("Order:")
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

    def _is_order_dialog_open(self) -> bool:
        if self._window is None:
            return False
        try:
            return any(
                control.element_info.control_type == "Window"
                and control.window_text().startswith("Order:")
                for control in self._window.descendants()
            )
        except _element_gone():
            return False


class MT5DesktopAdapter:
    def __init__(
        self,
        profile: TerminalProfile,
        window_manager: MT5WindowManager | None = None,
        position_provider: Any | None = None,
        gate: ExecutionGate | None = None,
    ) -> None:
        self.profile = profile
        self.window_manager = window_manager or MT5WindowManager()
        self.gate = gate if gate is not None else ExecutionGate()
        if position_provider is None:
            position_provider = MT5FilePositionSnapshotProvider(
                Path(profile.data_path) / "MQL5" / "Files"
            )
        self.position_provider = position_provider
        self.connected = False
        self.verification_timeout_seconds = 5.0
        self.selected_symbol: str | None = None
        self.prepared: OrderRequest | None = None
        self._baseline: tuple[PositionSnapshot, ...] | None = None
        self._baseline_error: str | None = None

    def connect(self) -> AccountSnapshot:
        WindowsTerminalDiscovery().discover(self.profile)
        self.window_manager.find(self.profile)
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
        raise AutomationError("real MT5 position closing is not implemented")
