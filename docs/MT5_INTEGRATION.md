# MT5 Integration

The terminal and data directory are configured per machine through environment variables or a local `.env` file. The active instance is pinned by its **executable path and data directory**, and its window is then selected by the process id that discovery resolved. A window title is never the identity.

## Which terminal gets driven

A machine routinely runs several MT5 instances, and several of them share a window
title, because the title shows the account and a broker names its demo accounts
alike. On this machine, four of five running terminals were titled
`Alpari-MT5-Demo` at once.

That is why identity is resolved in this order, and why each step fails closed:

1. the configured **executable path** must match a running `terminal64.exe`;
2. the configured **data directory** must exist;
3. the **instance name** may only *narrow* the set the path already selected, and
   never select on its own;
4. the window is then found by **process id**, so a shared title cannot make the
   wrong account look like the right one.

### The defect this found

`MT5WindowManager.find()` used to match windows by title and take `matches[0]`.
With four identically-titled demo terminals open, that selected an account by
enumeration order. The demo check that follows would have passed for all of them,
because every one of them is a demo — so the guard meant to prevent driving the
wrong account did not prevent it.

The window is now selected by process id, and a title match that finds more than
one window is **refused** rather than resolved. There is no flag to pick the first
one. `tests/unit/test_terminal_check.py` pins this: four same-titled windows, and
choosing between them is an error.

## After a MetaTrader update

Every control this project uses is identified by a value measured on one build:
an automation id like `10408`, or a name MT5 happens to render in English. An
MT5 update is the one ordinary event that can move them. When one does, the order
path refuses — which is correct, but it refuses at the moment of trading.

`python -m auto_trade terminal-check` answers the question earlier and without
trading anything. It resolves the terminal, opens the order dialog, reads the
control tree, closes the dialog, and reports each expected identifier as present,
drifted, absent, or ambiguous. **It has no code path that uses a final control**,
so it cannot place an order even with every gate open.

```powershell
python -m auto_trade terminal-check
python -m auto_trade terminal-check --compare
```

`--compare` diffs this run against the recorded history and names any control
whose value changed. Reports are kept in `logs\terminal_check.json` and appended,
not overwritten, so "did the update change anything" stays answerable after the
fact rather than from memory.

The report is filed under the terminal build it was taken on, read from the
indicator's own snapshot. A `PASS` is evidence for that build and not for
another. Nothing in the probe substitutes a new identifier for a moved control: a
button found under a different id is a button whose behaviour has not been
established, and this project does not use unmeasured controls.

## Current status

The project has verified executable existence, data-directory existence, process
path matching, process responsiveness, and unambiguous window selection by process
id. UIA discovery finds `New Order` and the Trade grid. The real adapter opens
the semantic order dialog, sets Symbol/Volume/SL/TP/Comment by Automation ID, and
closes it during dry-run. Real-terminal EURUSD BUY and SELL dry-runs have
completed the full state machine to `DRY_RUN_COMPLETED` without a final execution
control, on build 6184 and again on build 6230.

Position reading through the UI is not possible on this build. The Trade grid is owner-drawn: its column headers resolve through both UIA and Win32, but every row and subitem value is empty through UIA, `LVM_GETITEMTEXT`, and MSAA. The project therefore uses a separate read-only MQL5 indicator snapshot for verification. The indicator contains no `OrderSend` or trade request call. See [POSITION_READER.md](POSITION_READER.md).

## Required future adapter behavior

1. Match the configured executable path.
2. Match process ID, instance title, and, where possible, data-directory identity.
3. Select the window by process id, and refuse an ambiguous title.
4. Ensure the window is responsive and foreground.
5. Detect modal dialogs and unexpected state.
6. Select the symbol using semantic/accessibility controls or configurable locators.
7. Prepare volume, SL, and TP without using scattered hard-coded coordinates.
8. Use bounded waits and explicit timeouts rather than sleep-based synchronization.
9. Record the UI action separately from broker acceptance.
10. Verify an independent position/order change.
11. Enter `UNKNOWN_EXECUTION` if the application cannot prove the result.
12. Re-measure the control identifiers after an MT5 update, deliberately.

## DPI and display

The current machine reports one logical screen at 1536x864, physical adapter output at 1920x1080, registry DPI 120, and system DPI 96. This mismatch requires controlled UI validation. Coordinates are not a stable interface.

## Demo validation sequence

The only permitted automated validation target is the specified demo terminal:

1. Connection only.
2. Window detection.
3. Symbol detection.
4. Dry-run BUY.
5. Dry-run SELL.
6. Explicitly review account, symbol, volume, risk limits, and kill switch before any real demo order.

The current CLI performs steps 1–5 as non-order-producing dry-runs against the configured demo terminal. It does not click final order controls or switch symbols.
