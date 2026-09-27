from __future__ import annotations

import sys
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from auto_trade.application.strategy import (
    CallableStrategy,
    ScriptedStrategy,
    StrategyContext,
    StrategyError,
    build_context,
    load_strategy,
    strategy_directory,
)
from auto_trade.domain.exceptions import InvalidSignalError
from auto_trade.domain.models import AccountSnapshot, TradeSignal

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


def signal_dict(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "id": "strategy-1",
        "timestamp": "2026-09-27T12:00:00Z",
        "source": "unit",
        "symbol": "BITCOIN",
        "action": "BUY",
        "volume": 0.01,
    }
    data.update(overrides)
    return data


def context(*positions: object, symbol: str = "bitcoin") -> StrategyContext:
    return build_context(symbol, positions)  # type: ignore[arg-type]


# -- context -----------------------------------------------------------


def test_context_normalises_the_symbol() -> None:
    assert context().symbol == "BITCOIN"


def test_context_is_timezone_aware() -> None:
    assert build_context("BITCOIN", now=datetime(2026, 1, 1, 12)).now.tzinfo is not None


def test_context_filters_positions_for_the_symbol() -> None:
    from auto_trade.domain.models import PositionSnapshot

    btc = PositionSnapshot("1", "BITCOIN", "BUY", Decimal("0.01"))
    eur = PositionSnapshot("2", "EURUSD", "BUY", Decimal("0.01"))
    ctx = build_context("BITCOIN", (btc, eur))

    assert ctx.open_positions_for == (btc,)
    assert len(ctx.positions) == 2


def test_context_carries_the_account_when_given() -> None:
    from auto_trade.domain.enums import AccountType

    account = AccountSnapshot(AccountType.DEMO, connected=True)
    assert build_context("BITCOIN", (), account).account is account


# -- scripted ----------------------------------------------------------


def test_scripted_strategy_returns_a_signal_once() -> None:
    strategy = ScriptedStrategy(TradeSignal.from_dict(signal_dict()))

    assert strategy.evaluate(context()) is not None
    assert strategy.evaluate(context()) is None
    assert strategy.calls == 2


def test_scripted_strategy_can_start_empty() -> None:
    assert ScriptedStrategy(None).evaluate(context()) is None


# -- callable adapter --------------------------------------------------


def test_callable_strategy_accepts_a_trade_signal() -> None:
    signal = TradeSignal.from_dict(signal_dict())
    strategy = CallableStrategy(lambda ctx: signal)

    assert strategy.evaluate(context()) is signal


def test_callable_strategy_accepts_a_mapping() -> None:
    strategy = CallableStrategy(lambda ctx: signal_dict(id="from-mapping"))

    result = strategy.evaluate(context())

    assert isinstance(result, TradeSignal)
    assert result.signal_id == "from-mapping"


def test_callable_strategy_accepts_none() -> None:
    assert CallableStrategy(lambda ctx: None).evaluate(context()) is None


def test_callable_strategy_rejects_a_bad_return_type() -> None:
    def bad(context: StrategyContext) -> Any:
        return 42

    with pytest.raises(StrategyError, match="expected TradeSignal"):
        CallableStrategy(bad).evaluate(context())


def test_callable_strategy_rejects_an_invalid_mapping() -> None:
    with pytest.raises(InvalidSignalError):
        CallableStrategy(lambda ctx: {"id": "x"}).evaluate(context())


# -- loading -----------------------------------------------------------


def test_reference_strategy_loads_from_the_plugin_directory() -> None:
    assert strategy_directory().name == "strategies"

    strategy = load_strategy("example_strategy:build")

    assert strategy.name == "example-strategy"
    assert strategy.evaluate(build_context("BITCOIN")) is not None


def test_reference_strategy_declines_when_a_position_is_open() -> None:
    from auto_trade.domain.models import PositionSnapshot

    strategy = load_strategy("example_strategy:build")
    held = PositionSnapshot("1", "BITCOIN", "BUY", Decimal("0.01"))

    assert strategy.evaluate(build_context("BITCOIN", (held,))) is None


@pytest.mark.parametrize("spec", ["", "nocolon", ":attr", "module:", "  :  "])
def test_malformed_spec_is_rejected(spec: str) -> None:
    with pytest.raises(StrategyError, match="invalid strategy spec"):
        load_strategy(spec)


def test_missing_module_is_reported_with_the_directory_to_use() -> None:
    with pytest.raises(StrategyError, match="could not be imported") as error:
        load_strategy("definitely_not_a_module_xyz:build")
    assert "strategies" in str(error.value)


def test_missing_attribute_is_reported() -> None:
    with pytest.raises(StrategyError, match="has no attribute"):
        load_strategy("example_strategy:not_there")


def test_attribute_without_evaluate_is_rejected() -> None:
    module = sys.modules[__name__]
    setattr(module, "NOT_A_STRATEGY", object())
    try:
        with pytest.raises(StrategyError, match="no callable evaluate"):
            load_strategy(f"{__name__}:NOT_A_STRATEGY")
    finally:
        delattr(module, "NOT_A_STRATEGY")


def test_instance_attribute_is_accepted_without_calling_it() -> None:
    module = sys.modules[__name__]
    instance = ScriptedStrategy(None)
    setattr(module, "READY_MADE", instance)
    try:
        assert load_strategy(f"{__name__}:READY_MADE") is instance
    finally:
        delattr(module, "READY_MADE")


def test_a_plain_function_attribute_is_rejected_with_guidance() -> None:
    module = sys.modules[__name__]
    setattr(module, "PLAIN_FUNCTION", lambda ctx: None)
    try:
        with pytest.raises(StrategyError, match="CallableStrategy"):
            load_strategy(f"{__name__}:PLAIN_FUNCTION")
    finally:
        delattr(module, "PLAIN_FUNCTION")


def test_a_callable_object_with_evaluate_is_not_invoked() -> None:
    """An instance that implements the protocol must be used as-is, not called."""
    module = sys.modules[__name__]
    instance = ScriptedStrategy(TradeSignal.from_dict(signal_dict()))
    setattr(module, "PROTOCOL_OBJECT", instance)
    try:
        loaded = load_strategy(f"{__name__}:PROTOCOL_OBJECT")
        assert loaded is instance
        assert instance.calls == 0
    finally:
        delattr(module, "PROTOCOL_OBJECT")


def test_plugin_directory_is_the_project_checkout() -> None:
    directory = strategy_directory()
    assert directory.is_dir()
    assert (directory / "example_strategy.py").is_file()
    assert (directory.parent / "pyproject.toml").is_file()
