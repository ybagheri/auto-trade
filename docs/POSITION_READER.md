# Position Reader

The project uses a read-only MQL5 indicator for independent position observation. It is not a service and it does not place, modify, close, or cancel orders. The indicator contains no `OrderSend` or trade request call.

## What it does

Every second, `AutoTradePositionReader` reads the terminal's open positions and writes a JSON snapshot to:

```text
<data dir>\MQL5\Files\auto_trade_positions_a.json
<data dir>\MQL5\Files\auto_trade_positions_b.json
```

The two files alternate so a reader can discard an incomplete or stale file. The reader is fail-closed when the file is missing, old, incomplete, malformed, or has an unknown schema.

The indicator does not call `Print` and does not create a custom log file. MT5 itself may still record that an indicator was loaded or attached in its normal Journal, and the indicator is visible in the Navigator and on the chart. This project does not claim to conceal that platform behaviour.

## Install

```powershell
.\scripts\install-position-reader.ps1 `
    -DataPath "<MT5 data directory>" `
    -MetaEditor "<path to MetaEditor64.exe in the same terminal folder>"
```

The script copies the source into `<data dir>\MQL5\Indicators`, compiles it, and
fails if no `.ex5` is produced. Then in MT5 open a chart, press `Ctrl+I` or use
the indicator button, select `AutoTradePositionReader`, and confirm with `OK`.
The snapshot appears within a second or two.

The last step is a deliberate human action: MT5's grids and context menus are not
exposed to UI Automation, so a chart and its indicator cannot be attached without
a hard-coded screen coordinate. See [demo validation](MT5_DEMO_VALIDATION.md) for
the measured procedure and its record.

## Check

```powershell
python -m auto_trade position-snapshot
```

A successful read reports `AVAILABLE` and a position list. An unavailable, stale, or missing snapshot is never treated as an empty account.

## Execution relationship

The indicator only supplies the baseline and post-click observation. The order itself is still performed by the guarded MT5 desktop control, not by the indicator. A click is reported as `REQUESTED`; only an independent matching position observation can produce `ACCEPTED`.
