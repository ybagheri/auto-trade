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

**Confirm the build before you trust a record.** The snapshot carries
`terminal_build`, and this project has measured two of them: build 6184 on
2026-09-28 and build 6230 on 2026-09-29, on different installs. A `PASS` in
[demo validation](MT5_DEMO_VALIDATION.md) is evidence for the build named in
that row and not for another one. In particular, the observation path is
measured on 6230 while the guarded order and close paths are not, so a
successful read here says nothing about whether the order controls are still
where they were on 6184.

**An empty list is only meaningful next to the Trade tab.** A snapshot that
always reports `[]` is indistinguishable from a reader that is looking at the
wrong directory. The position was therefore opened and closed by hand on
2026-09-29 and both ends of that cycle were observed, which is what makes the
empty account above it trustworthy.

## Execution relationship

The indicator only supplies the baseline and post-click observation. The order itself is still performed by the guarded MT5 desktop control, not by the indicator. A click is reported as `REQUESTED`; only an independent matching position observation can produce `ACCEPTED`.

[فارسی](fa/POSITION_READER.md) · [execution](EXECUTION.md) · [recovery](RECOVERY.md)
