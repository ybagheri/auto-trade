# Strategy Integration

How a market-analysis library plugs into the bridge. The library decides *what*
to trade; the bridge decides *whether it is allowed to*.

## The seam

A strategy is any object with a string `name` and an `evaluate` method:

```python
class MyStrategy:
    name = "my-strategy"

    def evaluate(self, context: StrategyContext) -> TradeSignal | None: ...
```

`evaluate` returns a `TradeSignal`, a mapping that `TradeSignal.from_dict`
accepts, or `None` for "no trade right now".

`StrategyContext` is deliberately read-only and deliberately small:

| Field | Meaning |
| --- | --- |
| `symbol` | the symbol being evaluated, uppercased |
| `now` | timezone-aware current time |
| `positions` | every open position the observer reported |
| `account` | account snapshot, when one is available |
| `open_positions_for` | convenience filter for `symbol` |

A strategy cannot reach the terminal, the ledger, the risk engine, or the audit
log. It cannot place an order. That is the point: a third-party library
recommends, and the bridge decides.

## Wiring it up

Put the file in the project's `strategies/` directory and point
`AUTO_TRADE_STRATEGY` at `module:attribute`:

```dotenv
AUTO_TRADE_STRATEGY=my_strategy:build
```

`strategies/example_strategy.py` is a working reference. Copy it and replace the
body.

The `strategies/` directory exists because a hardened interpreter pins
`sys.path` and ignores `PYTHONPATH`, so a module dropped there is importable
without installing anything. A module that is already installed or otherwise
importable is used as-is.

`attribute` may be either:

- a **zero-argument factory** that returns a strategy, or
- a **ready-made instance** that already implements `evaluate`.

A plain function such as `def decide(context)` is not a valid target, because it
would be called with no arguments. The loader detects that and says so. Wrap it
instead:

```python
from auto_trade.application.strategy import CallableStrategy

def build() -> CallableStrategy:
    return CallableStrategy(my_library.decide, name="my-library")
```

## Asking for a decision

```powershell
python -m auto_trade evaluate --symbol BITCOIN
```

This reads the observer snapshot, builds the context, calls the strategy, and:

- writes nothing and exits `0` with `"decision": "NO_SIGNAL"` when it declines;
- writes a signal file and records an audit event when it proposes one;
- exits `1` with the reason if the strategy cannot be loaded or raises;
- exits `2` if no strategy is configured.

The signal lands in `AUTO_TRADE_SIGNAL_DIR` and is then processed exactly like
any other signal. **A library cannot widen its own permissions**: a proposed
`EURUSD` is still rejected when the whitelist contains only `BITCOIN`.

## The order of authority

1. The strategy proposes. It has no ability to act.
2. The risk engine validates: whitelist, volume, expiry, duplicates, rate.
3. The workflow prepares the order dialog and captures an observed baseline.
4. The execution gate decides whether a final control may be clicked at all.
5. The dialog is re-read and must still match what was approved.
6. The control is clicked, which is recorded as an action only.
7. Independent observation decides whether a position actually appeared.

A step that fails stops the sequence. Steps 4 to 7 never consult the strategy.

## Enabling a final control

Execution is refused unless `AUTO_TRADE_ENABLE_EXECUTION=true` is set
explicitly. It has no default-on path. The gate also refuses while dry-run is
active, while the kill switch is engaged, when the demo-only policy is not
satisfied, when no observed baseline exists, and when only `BUY`/`SELL` is not
the requested action.

See [EXECUTION.md](EXECUTION.md) for the full gate list and the measured control
identifiers.
