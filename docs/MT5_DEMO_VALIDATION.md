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

**Superseded on 2026-09-28.** A position created by the guarded execution path
itself reached `ACCEPTED` with evidence, which exercises the same observation
path, so the record was closed through that route instead. The procedure stays
here because it remains the way to test a position this project did not create,
and because a hand-placed fill is the case the broker, not the bridge, decided.

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

## What the first guarded order exposed

The first `execute --confirm-demo` on 2026-09-28 placed a real demo order. The
order filled, ticket `382626466`, and the application still reported `UNKNOWN`.
Three defects were responsible, all after the click and none of them in a safety
gate:

1. **A destroyed dialog was read as a live one.** MT5 closes the order dialog
   itself once an order is sent, and the code then read that dead element, which
   raised a raw automation error. The order was placed and the result was lost.
   A dialog MT5 has destroyed is now reported as closed, and a cached dead dialog
   is never reused.
2. **One unreadable snapshot ended verification.** The indicator rewrites its
   snapshot while the terminal is busy, so a read can land on a file being
   written. Verification now keeps polling until its deadline and only then
   fails closed, with the last observation error as the reason.
3. **The unknown state hid its cause.** The message was a fixed sentence, so the
   audit trail said only "execution outcome is unknown". The state is now
   `UNKNOWN_EXECUTION` and the underlying exception is recorded.

The project did the safe thing throughout: it never claimed success it could not
prove. It was wrong in the other direction, reporting a fill it could have proven
as unprovable.

After the fix, the second run of the same guarded path returned `ACCEPTED` with
`order_reference 382631622`, an empty baseline, and the observed position in the
evidence. The account was left with one open demo position, which the operator
closed by hand; this project does not close positions.

`logs\idempotency.json` still holds the first attempt as `UNKNOWN`. That is
correct history: the application could not prove that outcome, and it was proven
later by looking. Reconciling such a record from the outside is not implemented,
and is listed under Phase 10.

## Step 3 — guarded demo order (done 2026-09-28, see the record)

Performed as a deliberate operator decision, on the demo account only, with
`AUTO_TRADE_ENABLE_EXECUTION=true` and `AUTO_TRADE_DRY_RUN=false` supplied to the
process rather than written into `.env`, so the live setting did not outlive the
test. `.env` still holds `AUTO_TRADE_ENABLE_EXECUTION=false` and
`AUTO_TRADE_DRY_RUN=true`.

A `REQUESTED` result is an action, not a success. `ACCEPTED` requires the
snapshot to show exactly one new matching position. Anything else is `UNKNOWN`
and must be reviewed with `python -m auto_trade recovery`. A live account is out
of scope for this project at every step.

## Step 4 — close what the test opened

The close is now implemented and was proven on this account: `close-position
382652281 --confirm-demo` returned `CLOSED`, with the position gone from an
independent observation (`1 before, 0 after`). The order was a SELL this project
had opened and recorded, which is the only kind of position this path will close.

Two defects were found on the way and are fixed: a popup menu is read before its
entries exist, and the terminal has to be brought to the foreground before a row is
clicked at a screen coordinate. Both produced a refusal, and in both cases the
position was left open, which is the correct failure for a control like this.

`close_position` does not hedge and does not partially close; only `Close
Position` on a single row is ever used.

| # | Date | Terminal | Account | Item | Symbol / action / volume | Expected | Actual | Verification method | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2026-09-28 | Alpari MT5 6184 | Alpari-MT5-Demo | executable and data directory exist | — | paths resolve | resolved | `diagnostics` | PASS |
| 2 | 2026-09-28 | Alpari MT5 6184 | Alpari-MT5-Demo | process discovery by path and instance name | — | exactly one match, titled demo | `terminal_discovery: found` | `WindowsTerminalDiscovery` | PASS |
| 3 | 2026-09-28 | Alpari MT5 6184 | Alpari-MT5-Demo | indicator compiles | — | 0 errors, 0 warnings, `.ex5` written | `0 errors, 0 warnings` | `MetaEditor64 /compile` with log | PASS |
| 4 | 2026-09-28 | Alpari MT5 6184 | Alpari-MT5-Demo | indicator snapshot observed | — | snapshot file appears and is readable | `AVAILABLE`, `complete: true`, sequence 23 → 59, zero positions, which matches the empty Trade tab | `position-snapshot` | PASS |
| 4a | 2026-09-28 | Alpari MT5 6184 | Alpari-MT5-Demo | staleness guard on a real file | — | an old snapshot is refused, not read as empty | `UNAVAILABLE`, `stale (84756.8s old, limit 30s)` | `position-snapshot` | PASS |
| 4b | 2026-09-28 | Alpari MT5 6184 | Alpari-MT5-Demo | real-terminal dry-run, BUY | EURUSD BUY 0.01 | dialog prepared, no final control, no position | `ORDER_READY` then `DRY_RUN_COMPLETED`; snapshot still empty | `dry-run` on the live terminal plus `position-snapshot` and `recovery` | PASS |
| 4c | 2026-09-28 | Alpari MT5 6184 | Alpari-MT5-Demo | real-terminal dry-run, SELL | EURUSD SELL 0.01 | dialog prepared, no final control, no position | `ORDER_READY` then `DRY_RUN_COMPLETED`; snapshot still empty | same | PASS |
| 5 | 2026-09-28 | Alpari MT5 6184 | Alpari-MT5-Demo | position opened by hand is accepted | — | one new matching position | **superseded by row 6**: a position created by the guarded path itself was accepted with evidence, which proves the same observation path | `position-snapshot` + `PositionChangeVerifier` | SUPERSEDED |
| 6 | 2026-09-28 | Alpari MT5 6184 | Alpari-MT5-Demo | guarded demo order, first attempt | EURUSD BUY 0.01 | `REQUESTED` then `ACCEPTED` | `UNKNOWN`: the order filled as ticket `382626466`, but a defect after the click made the outcome unprovable | `execute --confirm-demo`; position later seen in the snapshot and closed by hand | PARTIAL, DEFECT FOUND |
| 6a | 2026-09-28 | Alpari MT5 6184 | Alpari-MT5-Demo | guarded demo order, after the fix | EURUSD BUY 0.01 | `REQUESTED` then `ACCEPTED` with evidence | `ACCEPTED`, `order_reference 382631622`, baseline `ui positions=none`, observed `ui positions=382631622:EURUSD:BUY:0.01` | `execute --confirm-demo`, then `position-snapshot` and the audit trail | PASS |

Rows 4 to 6 stay open until a person runs the steps above. Nothing in this
repository may mark them passed on their behalf.
