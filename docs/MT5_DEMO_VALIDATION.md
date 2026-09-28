# MT5 Demo Validation

Two roadmap items can only be closed by a person looking at the terminal: the
read-only indicator snapshot has to be confirmed on a real demo terminal, and a
demo position has to be opened by hand and then accepted by the independent
verifier. This file is the runbook for those steps and the record the repository
keeps of what was actually observed.

## Environment, measured on this machine

Measured 2026-09-28 with the project's own `diagnostics`, discovery, and install
script. No value here is assumed.

| Fact | Value |
| --- | --- |
| Terminal | `C:\Users\bagheri\AppData\Roaming\Alpari MT5\terminal64.exe`, build 6184 |
| Data directory | `C:\Users\bagheri\AppData\Roaming\MetaQuotes\Terminal\1BFBA8D123B04AAD5E48746348E9B594` |
| Window title | `… - Alpari-MT5-Demo: Demo Account - Hedge - Alpari` |
| Account type | demo, server `MT5-Demo.Asia.15`, authorized per `<data dir>\logs\20260927.log` |
| Account state | balance and equity equal, free margin equal, **no open positions or orders** |
| Discovery | `python -m auto_trade diagnostics` reports `terminal_discovery: found` |
| Indicator build | `MetaEditor64.exe /compile:` reported `0 errors, 0 warnings`; `AutoTradePositionReader.ex5` written |
| Indicator registered | yes, `AutoTradePositionReader` appears under Navigator → Indicators |
| Indicator attached | yes, to the `EURUSD,M5` chart, after a human attach; the window title now carries the symbol |
| Snapshot file | **observed**: `position-snapshot` reports `AVAILABLE`, sequence advancing 23 → 59, `complete: true` |
| Snapshot contents | `"positions": []` — correct, the account has no open position |
| Stale snapshot guard | a snapshot from 2026-09-27 was refused as `stale (84756.8s old, limit 30s)` before the indicator was attached |
| Last known real position | `BITCOIN` `BUY` `0.01`, ticket `382363348`, in the 2026-09-27 snapshot; the Trade tab is empty today |

A second terminal exists on this machine (`Alpari MT5_2`, build 6230, AMarkets
demo). It is not the configured instance and was not touched.

### What a real snapshot looks like

The snapshot written by the attached indicator today, read for its shape only:

```json
{
  "schema": 1, "sequence": 23, "complete": true,
  "written_at": "2026-09-28T08:53:48Z",
  "account": 53145727, "server": "Alpari-MT5-Demo", "terminal_build": 6184,
  "positions": []
}
```

An earlier snapshot from a session on 2026-09-27, when the account did hold a
position, shows what a populated list looks like on this broker's build:

```json
{"ticket": 382363348, "symbol": "BITCOIN", "type": "BUY", "volume": 0.01,
 "price_open": 84484.0, "sl": 0.0, "tp": 0.0, "profit": 1.64,
 "magic": 0, "opened_at": "2026-09-27T08:52:15Z"}
```

Three things follow. The indicator is live and writing a complete snapshot every
second, and `position-snapshot` reads it. The fields the verifier needs are
`ticket`, `symbol`, `type`, and `volume`, with the side spelled `BUY` or `SELL`,
so a real position is representable in this schema. And the stale guard fired on
a real file before the indicator was attached: the reader reported `UNAVAILABLE`
with the age in seconds instead of reading that old file as an empty account.

The account number, the ticket, and the price are the user's own broker data.
They are recorded here because this is a local validation record; do not copy
them into a public issue.

## Why the last two steps are not automated

MT5's Market Watch and Trade grids are custom-drawn: they expose headers and a
row count through UI Automation but no row names or values, and the chart
context menu does not appear in the accessibility tree at all. Attaching an
indicator therefore needs a chart, and creating a chart needs a menu that this
project cannot identify by name. The alternative is a hard-coded screen
coordinate, which `CONTRIBUTING.md` forbids and which this project will not do to
a trading terminal, least of all next to a visible `New Order` control.

Everything up to the click was done automatically. What remains is three clicks
and one order decision, both of which belong to the operator.

## Step 1 — attach the indicator and confirm the snapshot

1. In the running terminal, open a chart: double-click `EURUSD` in Market Watch
   (or any symbol on the whitelist).
2. Press `Ctrl+I`, or use the indicator button on the chart toolbar.
3. Select `AutoTradePositionReader` and confirm with `OK`.
4. Leave the chart open. The snapshot is written within a second or two.

Then, in the project:

```powershell
python -m auto_trade position-snapshot
```

**Accepted when** the output is `AVAILABLE`, the list matches what the Trade tab
shows, and `logs\audit.log` is not needed for the read to work. A `UNAVAILABLE`
result here is a failure, not an empty account: the reader is fail-closed.

**Record:** date, terminal build, account type, snapshot file name, position
count, expected result, actual result, verification method, status.

## Step 2 — open a demo position by hand and confirm verification accepts it

1. With the indicator still attached, open one position by hand from the Trade
   tab: pick a whitelisted symbol, `BUY`, the minimum volume, and confirm.
2. Read the position with the project:

```powershell
python -m auto_trade position-snapshot
```

**Accepted when** the new position appears with the same symbol, side, and
volume the operator chose, and `PositionChangeVerifier` reports it as the single
new position. The unit tests already cover the accept, reject, multiple-match, and
unavailable-snapshot branches; this step proves the real snapshot carries the
fields the verifier needs, on this broker's build, in this terminal's data
directory.

3. Close the position by hand afterwards. The account must be left as it was
   found: no open positions, no orders.

**Record:** date, symbol, side, volume, expected result, actual result,
verification method, status.

## Step 3 — guarded demo order (blocked until steps 1 and 2 pass)

Only after both steps are recorded as accepted, and only as a deliberate
operator decision:

1. `AUTO_TRADE_ENABLE_EXECUTION=true` and `AUTO_TRADE_DRY_RUN=false` in `.env`,
   with `AUTO_TRADE_DEMO_ONLY` still `true`.
2. `python -m auto_trade execute --confirm-demo <signal-file>` on a demo account.
3. A `REQUESTED` result is an action, not a success. `ACCEPTED` requires the
   snapshot to show exactly one new matching position. Anything else is
   `UNKNOWN` and must be reviewed with `python -m auto_trade recovery`.

A live account is out of scope for this project at every step.

## Validation record

| # | Date | Terminal | Account | Item | Symbol / action / volume | Expected | Actual | Verification method | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2026-09-28 | Alpari MT5 6184 | Alpari-MT5-Demo | executable and data directory exist | — | paths resolve | resolved | `diagnostics` | PASS |
| 2 | 2026-09-28 | Alpari MT5 6184 | Alpari-MT5-Demo | process discovery by path and instance name | — | exactly one match, titled demo | `terminal_discovery: found` | `WindowsTerminalDiscovery` | PASS |
| 3 | 2026-09-28 | Alpari MT5 6184 | Alpari-MT5-Demo | indicator compiles | — | 0 errors, 0 warnings, `.ex5` written | `0 errors, 0 warnings` | `MetaEditor64 /compile` with log | PASS |
| 4 | 2026-09-28 | Alpari MT5 6184 | Alpari-MT5-Demo | indicator snapshot observed | — | snapshot file appears and is readable | `AVAILABLE`, `complete: true`, sequence 23 → 59, zero positions, which matches the empty Trade tab | `position-snapshot` | PASS |
| 4a | 2026-09-28 | Alpari MT5 6184 | Alpari-MT5-Demo | staleness guard on a real file | — | an old snapshot is refused, not read as empty | `UNAVAILABLE`, `stale (84756.8s old, limit 30s)` | `position-snapshot` | PASS |
| 4b | 2026-09-28 | Alpari MT5 6184 | Alpari-MT5-Demo | real-terminal dry-run, BUY | EURUSD BUY 0.01 | dialog prepared, no final control, no position | `ORDER_READY` then `DRY_RUN_COMPLETED`; snapshot still empty | `dry-run` on the live terminal plus `position-snapshot` and `recovery` | PASS |
| 4c | 2026-09-28 | Alpari MT5 6184 | Alpari-MT5-Demo | real-terminal dry-run, SELL | EURUSD SELL 0.01 | dialog prepared, no final control, no position | `ORDER_READY` then `DRY_RUN_COMPLETED`; snapshot still empty | same | PASS |
| 5 | — | — | — | position opened by hand is accepted | — | one new matching position | — | `position-snapshot` + `PositionChangeVerifier` | AWAITING STEP 2 |
| 6 | — | — | — | guarded demo order | — | `REQUESTED` then `ACCEPTED` | — | `execute --confirm-demo` | BLOCKED BY 5 |

Rows 4 to 6 stay open until a person runs the steps above. Nothing in this
repository may mark them passed on their behalf.
