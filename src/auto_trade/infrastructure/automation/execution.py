"""The guarded final execution control.

This is the only module in the project that can place an order, and it is
refused by default. Every gate below must pass before a single control is
clicked, and a click is reported as an action only: broker acceptance and a
resulting position are established separately by independent observation.
"""

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from ...domain.enums import ExecutionStatus, OrderAction
from ...domain.exceptions import AutomationError, AutomationRejectedError
from ...domain.models import ExecutionResult, OrderRequest

# Measured on Alpari MT5 build 6184 by inspecting the order dialog.
BUY_BUTTON_ID = "10408"
BUY_BUTTON_NAME = "Buy by Market"
SELL_BUTTON_ID = "10409"
SELL_BUTTON_NAME = "Sell by Market"

# A final control is only clicked if the dialog still shows exactly what the risk
# engine approved, so a stale or repopulated dialog cannot be submitted.
SYMBOL_FIELD_ID = "10325"
VOLUME_FIELD_ID = "10333"
STOP_LOSS_FIELD_ID = "10334"
TAKE_PROFIT_FIELD_ID = "10336"

ALLOWED_ACTIONS = {OrderAction.BUY, OrderAction.SELL}

# Upper bound for the intra-dialog pre-submit pause. A value above this is
# almost certainly a seconds-vs-milliseconds mistake (e.g. 5000 seconds where
# 5000 ms was meant), so it is rejected loudly at load rather than waited out.
PRE_SUBMIT_DELAY_MAX_MS_CAP = 3_600_000
PRE_SUBMIT_DELAY_DEFAULT_MIN_MS = 1000
PRE_SUBMIT_DELAY_DEFAULT_MAX_MS = 5000


def _parse_delay_ms(raw: str, name: str) -> int:
    """Parse an ``AUTO_TRADE_PRE_SUBMIT_DELAY_*_MS`` value strictly as an integer.

    ``int()`` alone would accept surrounding whitespace (handled by stripping
    first) but also strings like ``"1_000"``; the explicit digit check keeps the
    accepted shape to an optional sign followed by digits, so ``"1.5"``,
    ``"true"``, ``""``, and ``"1e3"`` are all rejected loudly rather than
    truncated or defaulted.
    """
    text = raw.strip()
    if not text or not text.lstrip("+-").isdigit():
        raise ValueError(
            f"{name} must be an integer number of milliseconds, got {raw!r}"
        )
    return int(text)


@dataclass(frozen=True)
class PreSubmitDelay:
    """Randomized UI-pacing pause taken inside the order dialog before the click.

    This is pacing only: it changes when the final control is used, never
    whether it is used, nor the prices or volume it carries. It is rolled fresh
    per order with a plain PRNG (``random.Random``), which is appropriate
    because the value is UI pacing rather than anything security-sensitive.
    No randomized mouse movement, fake human behaviour, or timing manipulation
    anywhere else is involved.
    """

    enabled: bool = False
    min_ms: int = PRE_SUBMIT_DELAY_DEFAULT_MIN_MS
    max_ms: int = PRE_SUBMIT_DELAY_DEFAULT_MAX_MS

    def __post_init__(self) -> None:
        for label, value in (("min_ms", self.min_ms), ("max_ms", self.max_ms)):
            if type(value) is not int:
                raise ValueError(
                    f"pre-submit delay {label} must be an integer number of "
                    f"milliseconds, got {value!r}"
                )
        if self.min_ms < 0:
            raise ValueError(
                f"pre-submit delay min_ms must be >= 0, got {self.min_ms}"
            )
        if self.max_ms < self.min_ms:
            raise ValueError(
                f"pre-submit delay max_ms ({self.max_ms}) must be >= min_ms "
                f"({self.min_ms})"
            )
        if self.max_ms > PRE_SUBMIT_DELAY_MAX_MS_CAP:
            raise ValueError(
                f"pre-submit delay max_ms ({self.max_ms}) exceeds the sanity cap "
                f"of {PRE_SUBMIT_DELAY_MAX_MS_CAP} ms (1h); check for a "
                "seconds-vs-milliseconds mistake"
            )
        if self.min_ms > PRE_SUBMIT_DELAY_MAX_MS_CAP:
            raise ValueError(
                f"pre-submit delay min_ms ({self.min_ms}) exceeds the sanity cap "
                f"of {PRE_SUBMIT_DELAY_MAX_MS_CAP} ms (1h); check for a "
                "seconds-vs-milliseconds mistake"
            )

    def roll(self, rng: random.Random) -> int:
        """Roll one fresh duration, inclusive on both ends."""
        return rng.randint(self.min_ms, self.max_ms)

    @classmethod
    def from_env(cls) -> PreSubmitDelay:
        enabled = (
            os.getenv("AUTO_TRADE_PRE_SUBMIT_DELAY_ENABLED", "false")
            .strip()
            .lower()
            in {"1", "true", "yes", "on"}
        )
        min_raw = os.getenv(
            "AUTO_TRADE_PRE_SUBMIT_DELAY_MIN_MS", str(PRE_SUBMIT_DELAY_DEFAULT_MIN_MS)
        )
        max_raw = os.getenv(
            "AUTO_TRADE_PRE_SUBMIT_DELAY_MAX_MS", str(PRE_SUBMIT_DELAY_DEFAULT_MAX_MS)
        )
        # NOTE: no `or`-default idiom here: a configured MIN_MS of 0 is
        # legitimate and falsy, and must survive loading.
        min_ms = _parse_delay_ms(min_raw, "AUTO_TRADE_PRE_SUBMIT_DELAY_MIN_MS")
        max_ms = _parse_delay_ms(max_raw, "AUTO_TRADE_PRE_SUBMIT_DELAY_MAX_MS")
        return cls(enabled=enabled, min_ms=min_ms, max_ms=max_ms)


@dataclass(frozen=True)
class ExecutionGate:
    """Whether a final execution control may be used at all.

    ``enabled`` is the explicit opt-in. It is never derived from configuration
    defaults, so a fresh checkout cannot execute.
    """

    enabled: bool = False
    dry_run: bool = True
    demo_only: bool = True
    kill_switch_active: bool = False

    def refusal(self) -> str:
        if not self.enabled:
            return "execution is disabled; set AUTO_TRADE_ENABLE_EXECUTION=true to allow it"
        if self.kill_switch_active:
            return "kill switch is active"
        if self.dry_run:
            return "dry-run is enforced"
        if self.demo_only is False:
            return "demo-only policy is not satisfied"
        return ""


def refused_result(request: OrderRequest, reason: str) -> ExecutionResult:
    return ExecutionResult(
        execution_id="",
        signal_id=request.signal.signal_id,
        status=ExecutionStatus.REJECTED,
        state="GATE_REFUSED",
        message=reason,
    )


def assert_action_supported(request: OrderRequest) -> None:
    if request.action not in ALLOWED_ACTIONS:
        raise AutomationRejectedError(
            f"action {request.action.value} has no guarded final control; "
            "only BUY and SELL are implemented"
        )


def target_control(action: OrderAction) -> tuple[str, str]:
    if action is OrderAction.BUY:
        return BUY_BUTTON_ID, BUY_BUTTON_NAME
    if action is OrderAction.SELL:
        return SELL_BUTTON_ID, SELL_BUTTON_NAME
    raise AutomationRejectedError(f"action {action.value} has no final control")


def confirm_dialog_matches(dialog: Any, request: OrderRequest) -> None:
    """Re-read the prepared dialog and refuse anything the risk engine did not approve."""
    manager = dialog  # kept opaque; the caller supplies a field reader

    symbol_field = manager.read_field(SYMBOL_FIELD_ID)
    if not symbol_field.upper().startswith(request.symbol.upper()):
        raise AutomationRejectedError(
            f"dialog symbol {symbol_field.strip()!r} does not match the approved "
            f"{request.symbol!r}; refusing to submit"
        )

    approved = plain_decimal(request.volume)
    shown = plain_decimal(_number(manager.read_field(VOLUME_FIELD_ID)))
    if shown != approved:
        raise AutomationRejectedError(
            f"dialog volume {shown} does not match the approved {approved}; "
            "refusing to submit"
        )

    for field_id, expected, label in (
        (STOP_LOSS_FIELD_ID, request.stop_loss, "stop loss"),
        (TAKE_PROFIT_FIELD_ID, request.take_profit, "take profit"),
    ):
        if expected is None:
            continue
        shown_optional = plain_decimal(_number(manager.read_field(field_id)))
        if shown_optional != plain_decimal(expected):
            raise AutomationRejectedError(
                f"dialog {label} {shown_optional} does not match the approved "
                f"{plain_decimal(expected)}; refusing to submit"
            )


def click_final_control(manager: Any, action: OrderAction) -> None:
    """Click the single matching button, matched by name and by automation id."""
    control_id, control_name = target_control(action)
    matches = [
        control
        for control in manager.open_order_dialog().descendants()
        if control.element_info.control_type == "Button"
        and str(control.window_text() or "").strip() == control_name
        and str(control.element_info.automation_id or "") == control_id
    ]
    if not matches:
        raise AutomationError(
            f"final control {control_name!r} (id {control_id}) was not found; "
            "nothing was clicked"
        )
    if len(matches) > 1:
        raise AutomationError(
            f"final control {control_name!r} matched {len(matches)} elements; "
            "refusing to guess"
        )
    matches[0].click_input()


def wait_for_dialog_to_close(manager: Any, timeout_seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            manager.close_order_dialog(timeout_seconds=0.5)
            return True
        except AutomationError:
            time.sleep(0.3)
    return False


def _number(text: str) -> Decimal:
    cleaned = str(text).replace(",", ".").strip()
    try:
        return Decimal(cleaned)
    except Exception as exc:  # noqa: BLE001
        raise AutomationRejectedError(f"dialog field {text.strip()!r} is not a number") from exc


def plain_decimal(value: Decimal | str) -> str:
    """Normalise a number for comparison: no exponent, no trailing zeros.

    Accepting a string keeps a value read from a dialog field comparable with a
    Decimal the risk engine already approved.
    """
    number = value if isinstance(value, Decimal) else _number(value)
    return format(number.normalize(), "f")
