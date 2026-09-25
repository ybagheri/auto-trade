# MT5 Integration

The development fixture is the Alpari terminal at `C:\Program Files\Alpari MT5_2\terminal64.exe` with data directory `C:\Users\BazikadeStore\AppData\Roaming\MetaQuotes\Terminal\AF19ECCF568F855DF9D3196BBF8BF315`.

## Current status

The project has verified executable existence, data-directory existence, process path matching, process responsiveness, a visible demo-account window title, and UIA discovery of `New Order`, `Trade`, and the active `XAUUSD,M5` chart title. The real adapter opens the semantic order dialog, sets Symbol/Volume/SL/TP/Comment by Automation ID, and closes it during dry-run. The Trade position table is detected by Automation ID `10328`, but row values are not exposed through UIA on this build, so verification fails closed. Final execution controls remain blocked.

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

The current CLI performs steps 1–5 as non-order-producing dry-runs against the configured demo terminal when the active chart symbol is visible. It does not click final order controls, switch symbols, or verify a broker position.
