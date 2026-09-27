from __future__ import annotations

import importlib
import inspect
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

from ..domain.exceptions import AutoTradeError
from ..domain.models import AccountSnapshot, PositionSnapshot, TradeSignal, utc_now


class StrategyError(AutoTradeError):
    """Raised when a strategy cannot be loaded or fails to produce a decision."""


@dataclass(frozen=True)
class StrategyContext:
    """What a strategy is allowed to see.

    Deliberately read-only and deliberately limited: a strategy observes the
    account and proposes a signal. It cannot reach the terminal, the ledger or
    the risk engine, so no third-party library can place an order by itself.
    """

    symbol: str
    now: datetime
    positions: tuple[PositionSnapshot, ...] = ()
    account: AccountSnapshot | None = None

    @property
    def open_positions_for(self) -> tuple[PositionSnapshot, ...]:
        target = self.symbol.upper()
        return tuple(p for p in self.positions if p.symbol == target)


class SignalStrategy(Protocol):
    """The seam a market-analysis library plugs into.

    Implement ``name`` and ``evaluate`` and point ``AUTO_TRADE_STRATEGY`` at a
    factory that returns an instance. Nothing else in the project needs to change.
    """

    name: str

    def evaluate(self, context: StrategyContext) -> TradeSignal | None: ...


class ScriptedStrategy:
    """Returns a fixed signal once, then nothing. Used by tests and dry runs."""

    name = "scripted"

    def __init__(self, signal: TradeSignal | None) -> None:
        self._signal = signal
        self.calls = 0

    def evaluate(self, context: StrategyContext) -> TradeSignal | None:
        self.calls += 1
        signal, self._signal = self._signal, None
        return signal


class CallableStrategy:
    """Adapts any plain callable into a strategy.

    This is the lowest-effort integration: wrap a function from your library that
    returns a signal, a dict, or None.
    """

    def __init__(
        self,
        function: Callable[[StrategyContext], TradeSignal | dict[str, Any] | None],
        name: str = "callable",
    ) -> None:
        self._function = function
        self.name = name

    def evaluate(self, context: StrategyContext) -> TradeSignal | None:
        outcome = self._function(context)
        if outcome is None:
            return None
        if isinstance(outcome, TradeSignal):
            return outcome
        if isinstance(outcome, dict):
            return TradeSignal.from_dict(outcome)
        raise StrategyError(
            f"strategy {self.name!r} returned {type(outcome).__name__}; expected "
            "TradeSignal, a mapping, or None"
        )


STRATEGY_DIRECTORY = "strategies"


def strategy_directory() -> Path:
    """The project's plugin directory, where a strategy library can simply be dropped in."""
    return _project_root() / STRATEGY_DIRECTORY


def _project_root() -> Path:
    """The checkout root when running from source, else the current directory.

    ``application/strategy.py`` sits at ``<root>/src/auto_trade/application/``, so
    the root is three levels up. An installed copy has no checkout above it, in
    which case the current directory is the sensible place to look.
    """
    candidate = Path(__file__).resolve().parents[3]
    if (candidate / "pyproject.toml").is_file():
        return candidate
    return Path.cwd()


def load_strategy(spec: str) -> SignalStrategy:
    """Load ``module:attribute`` and call it if it is a factory.

    The attribute may be a ready instance or a zero-argument factory. The result
    must satisfy the SignalStrategy protocol.

    A module that is not already importable is looked for in the project's
    ``strategies`` directory. That directory is used because the interpreter's
    ``sys.path`` cannot be extended with ``PYTHONPATH`` on a hardened
    distribution, so a library dropped there is importable without installing it.
    """
    module_name, separator, attribute = spec.partition(":")
    if not separator or not module_name.strip() or not attribute.strip():
        raise StrategyError(
            f"invalid strategy spec {spec!r}; expected 'package.module:attribute'"
        )
    module = _import_strategy_module(module_name.strip(), spec)
    try:
        candidate = getattr(module, attribute.strip())
    except AttributeError as exc:
        raise StrategyError(
            f"module {module_name!r} has no attribute {attribute.strip()!r}"
        ) from exc
    strategy: Any = candidate
    if not hasattr(candidate, "evaluate") and callable(candidate):
        strategy = _call_factory(candidate, spec)
    _validate(strategy, spec)
    return cast(SignalStrategy, strategy)


def _call_factory(candidate: Any, spec: str) -> Any:
    """Call a zero-argument factory, and say so clearly when it is not one.

    A plain ``def decide(context)`` is not a valid target: it would be invoked with
    no arguments. Wrapping it in ``CallableStrategy`` is the supported route.
    """
    try:
        required = [
            parameter
            for parameter in inspect.signature(candidate).parameters.values()
            if parameter.default is inspect.Parameter.empty
            and parameter.kind
            in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
    except (TypeError, ValueError):
        required = []
    if required:
        raise StrategyError(
            f"{spec!r} points at a function that needs {len(required)} argument(s). "
            "Expose a zero-argument factory that returns a strategy, or wrap the "
            "function in CallableStrategy and point at that."
        )
    return candidate()


def _import_strategy_module(module_name: str, spec: str) -> Any:
    try:
        return importlib.import_module(module_name)
    except ImportError:
        directory = strategy_directory()
        if directory.is_dir() and str(directory) not in sys.path:
            sys.path.insert(0, str(directory))
        try:
            return importlib.import_module(module_name)
        except ImportError as exc:
            raise StrategyError(
                f"strategy module {module_name!r} could not be imported ({exc}). Place it "
                f"in {directory}, install it, or make it importable. Tried PYTHONPATH too."
            ) from exc


def _validate(strategy: Any, spec: str) -> None:
    if not hasattr(strategy, "evaluate") or not callable(strategy.evaluate):
        raise StrategyError(
            f"strategy from {spec!r} has no callable evaluate(context); it cannot be used"
        )
    if not isinstance(getattr(strategy, "name", None), str):
        raise StrategyError(f"strategy from {spec!r} must expose a string 'name'")


def build_context(
    symbol: str,
    positions: tuple[PositionSnapshot, ...] = (),
    account: AccountSnapshot | None = None,
    now: datetime | None = None,
) -> StrategyContext:
    moment = now or utc_now()
    return StrategyContext(
        symbol=symbol.upper(),
        now=moment if moment.tzinfo else moment.replace(tzinfo=UTC),
        positions=tuple(positions),
        account=account,
    )
