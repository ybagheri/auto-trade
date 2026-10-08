"""The intra-dialog pre-submit pause before the final control.

No MT5 required and nothing here ever sleeps: the sleeper is always a fake
that records its argument. These tests prove the pause is taken exactly once
per submission, strictly after dialog verification and before the click, and
never on any refusal or dry-run path.
"""

from __future__ import annotations

import random
from decimal import Decimal

import pytest

from auto_trade.domain.enums import ExecutionStatus
from auto_trade.domain.exceptions import PositionSnapshotUnavailable
from auto_trade.domain.models import OrderRequest, PositionSnapshot, TerminalProfile, TradeSignal
from auto_trade.infrastructure.automation import MT5DesktopAdapter, MT5WindowManager
from auto_trade.infrastructure.automation.execution import (
    BUY_BUTTON_ID,
    BUY_BUTTON_NAME,
    ExecutionGate,
    PreSubmitDelay,
)
from auto_trade.infrastructure.configuration import AppConfig

from ..helpers import signal_data


class FakeInfo:
    control_type = "Button"

    def __init__(self, automation_id: str) -> None:
        self.automation_id = automation_id


class FakeButton:
    def __init__(self, name: str, automation_id: str, events: list[str]) -> None:
        self._name = name
        self._info = FakeInfo(automation_id)
        self._events = events
        self.clicks = 0

    def window_text(self) -> str:
        return self._name

    @property
    def element_info(self) -> FakeInfo:
        return self._info

    def click_input(self) -> None:
        self.clicks += 1
        self._events.append("click")


class FakeDialog:
    def __init__(self, buttons: list[FakeButton]) -> None:
        self._buttons = buttons

    def descendants(self) -> list[FakeButton]:
        return self._buttons


class FakeManager(MT5WindowManager):
    """A field reader that records the call sequence around the pause."""

    def __init__(self, fields: dict[str, str], buttons: list[FakeButton]) -> None:
        super().__init__()
        self.fields = fields
        self.dialog = FakeDialog(buttons)
        self.opened = 0
        self.closed = 0

    def open_order_dialog(self, timeout_seconds: float = 5.0) -> FakeDialog:
        self.opened += 1
        return self.dialog

    def read_field(self, automation_id: str) -> str:
        return self.fields[automation_id]

    def close_order_dialog(self, timeout_seconds: float = 5.0) -> None:
        self.closed += 1


def fields(symbol: str = "BITCOIN, 1 LOT = 1 BITCOIN", volume: str = "0.01") -> dict[str, str]:
    return {"10325": symbol, "10333": volume, "10334": "0.00", "10336": "0.00"}


def profile() -> TerminalProfile:
    return TerminalProfile(
        name="alpari-demo",
        terminal_path="terminal64.exe",
        data_path="data",
        instance_name="Alpari Demo",
    )


class StaticPositions:
    def __init__(self, positions: tuple[PositionSnapshot, ...] = ()) -> None:
        self.positions_value = positions

    def positions(self) -> tuple[PositionSnapshot, ...]:
        return self.positions_value


def request(symbol: str = "BITCOIN", volume: str = "0.01") -> OrderRequest:
    data = signal_data() | {"symbol": symbol, "action": "BUY", "volume": float(volume)}
    return OrderRequest(TradeSignal.from_dict(data))


OPEN_GATE = ExecutionGate(enabled=True, dry_run=False, demo_only=True, kill_switch_active=False)


@pytest.fixture
def clean_delay_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "AUTO_TRADE_PRE_SUBMIT_DELAY_ENABLED",
        "AUTO_TRADE_PRE_SUBMIT_DELAY_MIN_MS",
        "AUTO_TRADE_PRE_SUBMIT_DELAY_MAX_MS",
    ):
        monkeypatch.delenv(name, raising=False)


def enabled_adapter(
    manager: FakeManager,
    delay: PreSubmitDelay,
    sleeps: list[float],
    events: list[str],
    seed: int = 7,
) -> MT5DesktopAdapter:
    def sleeper(seconds: float) -> None:
        sleeps.append(seconds)
        events.append("pause")

    return MT5DesktopAdapter(
        profile(),
        manager,
        position_provider=StaticPositions(()),
        gate=OPEN_GATE,
        pre_submit_delay=delay,
        sleeper=sleeper,
        rng=random.Random(seed),
    )


# -- configuration ----------------------------------------------------


def test_delay_is_disabled_by_default(clean_delay_env: None) -> None:
    assert PreSubmitDelay.from_env() == PreSubmitDelay(enabled=False, min_ms=1000, max_ms=5000)


def test_custom_bounds_load_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, clean_delay_env: None
) -> None:
    monkeypatch.setenv("AUTO_TRADE_PRE_SUBMIT_DELAY_ENABLED", "true")
    monkeypatch.setenv("AUTO_TRADE_PRE_SUBMIT_DELAY_MIN_MS", "200")
    monkeypatch.setenv("AUTO_TRADE_PRE_SUBMIT_DELAY_MAX_MS", "800")

    loaded = PreSubmitDelay.from_env()

    assert loaded == PreSubmitDelay(enabled=True, min_ms=200, max_ms=800)


def test_a_configured_min_of_zero_survives_loading(
    monkeypatch: pytest.MonkeyPatch, clean_delay_env: None
) -> None:
    """Zero is legitimate and falsy, so an `or`-default would swallow it."""
    monkeypatch.setenv("AUTO_TRADE_PRE_SUBMIT_DELAY_ENABLED", "true")
    monkeypatch.setenv("AUTO_TRADE_PRE_SUBMIT_DELAY_MIN_MS", "0")
    monkeypatch.setenv("AUTO_TRADE_PRE_SUBMIT_DELAY_MAX_MS", "5000")

    loaded = PreSubmitDelay.from_env()

    assert loaded.min_ms == 0
    assert loaded.max_ms == 5000


def test_app_config_carries_the_delay_disabled_by_default(clean_delay_env: None) -> None:
    config = AppConfig.from_env()

    assert config.pre_submit_delay.enabled is False


def test_app_config_loads_custom_bounds(
    monkeypatch: pytest.MonkeyPatch, clean_delay_env: None
) -> None:
    monkeypatch.setenv("AUTO_TRADE_PRE_SUBMIT_DELAY_ENABLED", "true")
    monkeypatch.setenv("AUTO_TRADE_PRE_SUBMIT_DELAY_MIN_MS", "0")
    monkeypatch.setenv("AUTO_TRADE_PRE_SUBMIT_DELAY_MAX_MS", "250")

    assert AppConfig.from_env().pre_submit_delay == PreSubmitDelay(True, 0, 250)


@pytest.mark.parametrize(
    ("minimum", "maximum"),
    [(-1, 5000), (6000, 5000), (0, 3_600_001), (3_600_001, 3_600_001)],
)
def test_out_of_range_bounds_are_rejected(minimum: int, maximum: int) -> None:
    with pytest.raises(ValueError):
        PreSubmitDelay(enabled=True, min_ms=minimum, max_ms=maximum)


@pytest.mark.parametrize("raw", ["1.5", "true", "", "1e3", "abc"])
def test_non_integer_bounds_are_rejected_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, clean_delay_env: None, raw: str
) -> None:
    monkeypatch.setenv("AUTO_TRADE_PRE_SUBMIT_DELAY_ENABLED", "true")
    monkeypatch.setenv("AUTO_TRADE_PRE_SUBMIT_DELAY_MIN_MS", raw)
    monkeypatch.setenv("AUTO_TRADE_PRE_SUBMIT_DELAY_MAX_MS", "5000")

    with pytest.raises(ValueError):
        PreSubmitDelay.from_env()


@pytest.mark.parametrize("value", [True, False, 1.5, "1000", None])
def test_non_integer_bounds_are_rejected_at_construction(value: object) -> None:
    """Bools are ints in Python, so the check must be by exact type."""
    with pytest.raises(ValueError):
        PreSubmitDelay(enabled=True, min_ms=value, max_ms=5000)  # type: ignore[arg-type]


def test_over_cap_max_is_rejected_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, clean_delay_env: None
) -> None:
    monkeypatch.setenv("AUTO_TRADE_PRE_SUBMIT_DELAY_ENABLED", "true")
    monkeypatch.setenv("AUTO_TRADE_PRE_SUBMIT_DELAY_MIN_MS", "1000")
    monkeypatch.setenv("AUTO_TRADE_PRE_SUBMIT_DELAY_MAX_MS", "3600001")

    with pytest.raises(ValueError, match="[Cc]ap|seconds"):
        PreSubmitDelay.from_env()


# -- placement and ordering -------------------------------------------


def test_disabled_delay_takes_no_pause_and_clicks() -> None:
    events: list[str] = []
    sleeps: list[float] = []
    button = FakeButton(BUY_BUTTON_NAME, BUY_BUTTON_ID, events)
    manager = FakeManager(fields(), [button])
    adapter = enabled_adapter(
        manager, PreSubmitDelay(enabled=False, min_ms=100, max_ms=200), sleeps, events
    )
    adapter.connected = True
    adapter._baseline = ()

    result = adapter.execute_order(request())

    assert result.status is ExecutionStatus.REQUESTED
    assert button.clicks == 1
    assert sleeps == []
    assert events == ["click"]


def test_pause_happens_exactly_once_strictly_before_the_click() -> None:
    events: list[str] = []
    sleeps: list[float] = []
    button = FakeButton(BUY_BUTTON_NAME, BUY_BUTTON_ID, events)
    manager = FakeManager(fields(), [button])
    adapter = enabled_adapter(
        manager, PreSubmitDelay(enabled=True, min_ms=100, max_ms=200), sleeps, events
    )
    adapter.connected = True
    adapter._baseline = ()

    result = adapter.execute_order(request())

    assert result.status is ExecutionStatus.REQUESTED
    assert button.clicks == 1
    assert len(sleeps) == 1
    assert events == ["pause", "click"]
    assert 0.1 <= sleeps[0] <= 0.2


def test_rolled_values_stay_within_bounds_with_a_seeded_rng() -> None:
    rng = random.Random(1234)
    delay = PreSubmitDelay(enabled=True, min_ms=1000, max_ms=5000)

    rolled = {delay.roll(rng) for _ in range(200)}

    assert rolled
    assert min(rolled) >= 1000
    assert max(rolled) <= 5000


def test_equal_bounds_always_roll_that_value() -> None:
    rng = random.Random(0)
    delay = PreSubmitDelay(enabled=True, min_ms=250, max_ms=250)

    assert {delay.roll(rng) for _ in range(10)} == {250}


def test_zero_min_is_a_legitimate_bound() -> None:
    delay = PreSubmitDelay(enabled=True, min_ms=0, max_ms=10)
    rng = random.Random(99)

    assert all(0 <= delay.roll(rng) <= 10 for _ in range(50))


# -- refusals and dry runs never sleep ---------------------------------


def test_gate_refusal_takes_no_pause() -> None:
    events: list[str] = []
    sleeps: list[float] = []
    button = FakeButton(BUY_BUTTON_NAME, BUY_BUTTON_ID, events)
    manager = FakeManager(fields(), [button])
    adapter = MT5DesktopAdapter(
        profile(),
        manager,
        position_provider=StaticPositions(()),
        gate=ExecutionGate(),
        pre_submit_delay=PreSubmitDelay(enabled=True, min_ms=100, max_ms=200),
        sleeper=lambda seconds: sleeps.append(seconds),
        rng=random.Random(1),
    )
    adapter.connected = True
    adapter._baseline = ()

    result = adapter.execute_order(request())

    assert result.status is ExecutionStatus.REJECTED
    assert button.clicks == 0
    assert sleeps == []


def test_baseline_drift_takes_no_pause() -> None:
    events: list[str] = []
    sleeps: list[float] = []
    button = FakeButton(BUY_BUTTON_NAME, BUY_BUTTON_ID, events)
    manager = FakeManager(fields(), [button])

    class Changing:
        def positions(self) -> tuple[PositionSnapshot, ...]:
            return (PositionSnapshot("999", "EURUSD", "BUY", Decimal("0.01")),)

    adapter = MT5DesktopAdapter(
        profile(),
        manager,
        position_provider=Changing(),
        gate=OPEN_GATE,
        pre_submit_delay=PreSubmitDelay(enabled=True, min_ms=100, max_ms=200),
        sleeper=lambda seconds: sleeps.append(seconds),
        rng=random.Random(1),
    )
    adapter.connected = True
    adapter._baseline = ()

    result = adapter.execute_order(request())

    assert result.status is ExecutionStatus.REJECTED
    assert "changed between preparing" in result.message
    assert button.clicks == 0
    assert sleeps == []


def test_dialog_mismatch_takes_no_pause() -> None:
    events: list[str] = []
    sleeps: list[float] = []
    button = FakeButton(BUY_BUTTON_NAME, BUY_BUTTON_ID, events)
    manager = FakeManager(fields(volume="0.50"), [button])
    adapter = enabled_adapter(
        manager, PreSubmitDelay(enabled=True, min_ms=100, max_ms=200), sleeps, events
    )
    adapter.connected = True
    adapter._baseline = ()

    result = adapter.execute_order(request())

    assert result.status is ExecutionStatus.REJECTED
    assert "volume" in result.message
    assert button.clicks == 0
    assert sleeps == []


def test_unobservable_account_takes_no_pause() -> None:
    sleeps: list[float] = []

    class Gone:
        def positions(self) -> tuple[PositionSnapshot, ...]:
            raise PositionSnapshotUnavailable("stale")

    button = FakeButton(BUY_BUTTON_NAME, BUY_BUTTON_ID, [])
    manager = FakeManager(fields(), [button])
    adapter = MT5DesktopAdapter(
        profile(),
        manager,
        position_provider=Gone(),
        gate=OPEN_GATE,
        pre_submit_delay=PreSubmitDelay(enabled=True, min_ms=100, max_ms=200),
        sleeper=lambda seconds: sleeps.append(seconds),
        rng=random.Random(1),
    )
    adapter.connected = True
    adapter._baseline = ()

    result = adapter.execute_order(request())

    assert result.status is ExecutionStatus.REJECTED
    assert button.clicks == 0
    assert sleeps == []


def test_dry_run_gate_takes_no_pause_even_when_enabled() -> None:
    """A dry run records nothing about a pause it would not take."""
    sleeps: list[float] = []
    button = FakeButton(BUY_BUTTON_NAME, BUY_BUTTON_ID, [])
    manager = FakeManager(fields(), [button])
    adapter = MT5DesktopAdapter(
        profile(),
        manager,
        position_provider=StaticPositions(()),
        gate=ExecutionGate(enabled=True, dry_run=True, demo_only=True),
        pre_submit_delay=PreSubmitDelay(enabled=True, min_ms=100, max_ms=200),
        sleeper=lambda seconds: sleeps.append(seconds),
        rng=random.Random(1),
    )
    adapter.connected = True
    adapter._baseline = ()

    result = adapter.execute_order(request())

    assert result.status is ExecutionStatus.REJECTED
    assert "dry-run" in result.message
    assert button.clicks == 0
    assert sleeps == []


def test_missing_final_control_takes_the_pause_but_clicks_nothing() -> None:
    """The pause sits before the click, so a dialog verified but missing its
    control still waited; the refusal is about the control, not the pause."""
    sleeps: list[float] = []
    events: list[str] = []
    manager = FakeManager(fields(), [FakeButton("Something Else", "99999", events)])
    adapter = enabled_adapter(
        manager, PreSubmitDelay(enabled=True, min_ms=100, max_ms=100), sleeps, events
    )
    adapter.connected = True
    adapter._baseline = ()

    result = adapter.execute_order(request())

    assert result.status is ExecutionStatus.REJECTED
    assert "was not found" in result.message
    assert len(sleeps) == 1


def test_adapters_do_not_share_rng_state() -> None:
    """Each adapter owns its PRNG so two instances cannot draw from one stream."""
    first = MT5DesktopAdapter(
        profile(),
        FakeManager(fields(), []),
        position_provider=StaticPositions(()),
        gate=OPEN_GATE,
    )
    second = MT5DesktopAdapter(
        profile(),
        FakeManager(fields(), []),
        position_provider=StaticPositions(()),
        gate=OPEN_GATE,
    )
    assert first._rng is not second._rng
