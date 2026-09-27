# MT5 Integration

The terminal and data directory are configured per machine through environment variables or a local `.env` file, and the active instance is pinned by window title so an ambiguous or unintended terminal is never driven.

## Current status

The project has verified executable existence, data-directory existence, process path matching, process responsiveness, and a unique visible demo-account window title. UIA discovery finds `New Order` and the Trade grid. The real adapter opens the semantic order dialog, sets Symbol/Volume/SL/TP/Comment by Automation ID, and closes it during dry-run. A real-terminal BITCOIN BUY dry-run completed the full state machine to `DRY_RUN_COMPLETED` without a final execution control. Final execution controls remain blocked.

Position reading through the UI is not possible on this build. The Trade grid is owner-drawn: its column headers resolve through both UIA and Win32, but every row and subitem value is empty through UIA, `LVM_GETITEMTEXT`, and MSAA. Independent observation therefore uses the read-only observer service instead of the grid. See [POSITION_OBSERVER.md](POSITION_OBSERVER.md).

## Required future adapter behavior

1. Match the configured executable path.
2. Match process ID, instance title, and, where possible, data-directory identity.
3. Ensure the window is responsive and foreground.
4. Detect modal dialogs and unexpected state.
5. Select the symbol using semantic/accessibility controls or configurable locators.
6. Prepare volume, SL, and TP without using scattered hard-coded coordinates.
7. Use bounded waits and explicit timeouts rather than sleep-based synchronization.
8. Record the UI action separately from broker acceptance.
9. Verify an independent position/order change.
10. Enter `UNKNOWN_EXECUTION` if the application cannot prove the result.

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
