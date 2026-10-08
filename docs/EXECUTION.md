# Execution

The final execution control is the only code in this project that can place an
order. It is refused by default.

## Gates

`ExecutionGate.refusal()` returns the first reason execution is not permitted,
and `execute_order` returns a `REJECTED` result without touching the terminal.

| Gate | Default | Refusal message |
| --- | --- | --- |
| `AUTO_TRADE_ENABLE_EXECUTION` | `false` | `execution is disabled; set AUTO_TRADE_ENABLE_EXECUTION=true to allow it` |
| kill switch | file-backed, off | `kill switch is active` |
| dry-run | `true` | `dry-run is enforced` |
| demo-only policy | `true` | `demo-only policy is not satisfied` |
| observed baseline | required | `refusing to execute: <reason>` |
| supported action | `BUY`, `SELL` | `action X has no guarded final control` |
| dialog matches approval | required | `dialog <field> ... does not match the approved ...` |
| final control found | exactly one | `final control ... was not found` / `refusing to guess` |

`enabled` is never derived from a configuration default. A fresh checkout cannot
execute.

## Measured control identifiers

Taken by inspecting the real order dialog on Alpari MT5 build 6184, not assumed:

| Control | Name | Automation id |
| --- | --- | --- |
| Buy | `Buy by Market` | `10408` |
| Sell | `Sell by Market` | `10409` |
| Symbol | field | `10325` |
| Volume | field | `10333` |
| Stop loss | field | `10334` |
| Take profit | field | `10336` |
| Comment | field | `1001` |

A button is only clicked when its name **and** its automation id both match, and
only when exactly one element matches. A same-named button with a different id is
not treated as the control.

## Why the dialog is re-read

`confirm_dialog_matches` reads Symbol, Volume, and any Stop Loss or Take Profit
straight back out of the prepared dialog and compares them to the request the
risk engine approved. A dialog that has been repopulated, partially edited, or
left over from an earlier run is refused rather than submitted. Volume comparison
normalises both sides, so `0.010` and `0.01` are equal.

## Pre-submit pause

After the dialog is verified and immediately before the final control is
clicked, `execute_order` can wait a freshly rolled duration. The pause sits at
the narrowest point in `execute_order`: after `confirm_dialog_matches` passes
and before `click_final_control`. It never occurs before the dialog is
prepared, during field entry, after the click, or during `verify_execution`.

```dotenv
AUTO_TRADE_PRE_SUBMIT_DELAY_ENABLED=true
AUTO_TRADE_PRE_SUBMIT_DELAY_MIN_MS=1000
AUTO_TRADE_PRE_SUBMIT_DELAY_MAX_MS=5000
```

Defaults are `false`, `1000`, `5000`, so default behavior is unchanged:
disabled means no sleep and no extra log lines. When enabled, each order rolls
its own duration uniformly from `MIN_MS` to `MAX_MS` inclusive, sleeps that
long, and logs the rolled duration with the signal id. A configured `MIN_MS`
of `0` is legitimate. Bounds are validated loudly at load (integers only, min
`>= 0`, max `>=` min, sanity cap of 3600000 ms), never silently defaulted.

This is UI pacing only. It does not affect the decision, prices, or volume,
and it is not a way to bypass automation detection: there is no randomized
mouse movement, no fake human behavior, and no timing change anywhere else.
Every gate above still applies unchanged, and every refusal path (gate,
baseline, drift, dialog mismatch) returns before the pause is taken. Dry runs
never sleep.

## A click is not a fill

`execute_order` returns `REQUESTED`, never `ACCEPTED`, and its message says
`acceptance not yet observed`. Acceptance is established only by
`verify_execution`, which compares an independently observed snapshot against the
baseline captured at the end of `prepare_order`. Only exactly one new position
matching symbol, side and volume yields `ACCEPTED`; everything else, including an
unreadable snapshot, yields `UNKNOWN`.

That separation is the whole safety argument: a successful click proves nothing
about the broker, and the code never claims it does.

## What `run` is, and what it is not

`python -m auto_trade run` processes pending signals in a loop, and every one of
them is a **dry run**. It walks the whole workflow against the real terminal and
stops at `DRY_RUN_COMPLETED`, so it exercises the signal source, the risk engine,
the state machine, and the order dialog together, on a schedule, without an
account changing.

```powershell
python -m auto_trade run --max-signals 5 --timeout 120
python -m auto_trade run --mock          # no terminal needed
```

**It cannot place an order, by construction.** It builds the same workflow
`dry-run` uses, from the same function, with the gate explicitly disabled, and
the mock adapter refuses unconditionally. Placing an order stays in
`execute --confirm-demo`, which a person runs per signal.

A loop that confirmed once and then traded for hours would turn one deliberate
act into an unbounded one, and `--confirm-demo` would stop meaning what it says.
That is why the loop is a rehearsal and not a trader.

**It stops rather than pushing on** in three cases: when the kill switch is
active, when a signal's outcome is `UNKNOWN` because an attempt that could not be
proven is a question for a person and never something to retry, and when the
timeout or `--max-signals` is reached.

With no signal source configured it reads the local signal directory, so a file
run needs nothing set up. See [signal protocol](SIGNAL_PROTOCOL.md).

## Turning it on

```dotenv
AUTO_TRADE_ENABLE_EXECUTION=true
AUTO_TRADE_DRY_RUN=false
```

Both are required. The CLI `execute` command additionally requires `--confirm-demo`:

```powershell
python -m auto_trade execute --confirm-demo <signal-file>
```

The CLI `dry-run` path constructs its adapter with `enabled=False` regardless of configuration, so the documented dry-run workflow can never reach a final control.

Enabling this on a live account is outside what this project has been tested for.
The supported target is a demo account, and the first run should be watched:

1. Confirm `position-snapshot` reports `AVAILABLE` from the read-only indicator.
2. Confirm `AUTO_TRADE_MAX_VOLUME` is set deliberately.
3. Use the smallest broker-allowed volume.
4. Keep the kill switch one HTTP call away: `python -m auto_trade dashboard`.
5. Watch the audit log. Every gate refusal and every verification outcome is
   recorded with its evidence.

## Closing a position

Closing is the second control that changes an account, and it has its own opt-in
so that it is never reachable because an order was allowed.

```dotenv
AUTO_TRADE_ENABLE_CLOSE=true
AUTO_TRADE_DRY_RUN=false
```

```powershell
python -m auto_trade close-position 382652281 --confirm-demo
```

| Gate | Default | Refusal message |
| --- | --- | --- |
| `AUTO_TRADE_ENABLE_CLOSE` | `false` | `closing is disabled; set AUTO_TRADE_ENABLE_CLOSE=true to allow it` |
| kill switch | file-backed, off | `kill switch is active` |
| dry-run | `true` | `dry-run is enforced` |
| demo-only policy | `true` | `demo-only policy is not satisfied` |
| ticket in the execution ledger | required | `ticket ... is not in the execution ledger, so it is not a position this application opened` |
| ticket observed now | required | `position ... is not in the observed snapshot` |
| one open position only | required | `N positions are open and the trade grid exposes no row text` |
| unambiguous row | one row, plus the summary row | `the trade grid exposes N rows; refusing to guess` |
| menu entry | `Close Position` / `33033`, exactly one | `context menu has no 'Close Position' entry` / `automation id` |

The ledger rule is the important one: only a position this application opened can
be closed by this path, so a position a person opened is never touched by it.

The row rule exists because the Trade grid on this build exposes a row's rectangle
but not its text, so a ticket cannot be read out of the grid. With exactly one
open position the first row is provably the intended one; with more, this code
refuses and asks for a human.

`CLOSED` is returned only when the ticket that was open when the call started is
absent from a later observation. A position that merely changed is not mistaken
for a closed one, and a snapshot that cannot be read yields `UNKNOWN` rather than
a close. `close_position` does not modify, partially close, or hedge: the menu
entries `Close by`, `Close 50%` and `Close All` are neighbours of the entry this
code uses and are named in `closing.py` so the reason for the exact match is on
record.

[فارسی](fa/EXECUTION.md) · [recovery](RECOVERY.md) · [metrics](METRICS.md)
