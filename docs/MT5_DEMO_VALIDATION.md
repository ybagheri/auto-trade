# MT5 Demo Validation

Two roadmap items can only be closed by a person looking at the terminal: the
read-only indicator snapshot has to be confirmed on a real demo terminal, and a
demo position has to be opened by hand and then accepted by the independent
verifier. This file is the runbook for those steps and the record the repository
keeps of what was actually observed.

**Both were performed, on two different terminals.** The 2026-09-28 session
measured Alpari MT5 build 6184 and is the record for the guarded order and the
guarded close. The 2026-09-29 session re-pointed `.env` at a per-user install
of **build 6230** and re-measured the observation path there from scratch; see
[The 2026-09-29 session](#the-2026-09-29-session--a-different-install-re-verified-from-scratch).
The two sections are deliberately not merged, because a result on one build is
not a result on the other.

## Environment, measured on 2026-09-28

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

## The 2026-09-29 session — a different install, re-verified from scratch

The configured instance was changed to a per-user install, so **every row above
describes a different terminal from the one now in `.env`**. Nothing in the
2026-09-28 record transfers automatically, and this section re-measured what
matters rather than assuming it.

| Fact | Value |
| --- | --- |
| Terminal | `C:\Users\bagheri\AppData\Roaming\Alpari MT5_5\terminal64.exe`, **build 6230** |
| Data directory | `C:\Users\bagheri\AppData\Roaming\MetaQuotes\Terminal\BF4EF096D1140DE6DC1607EA4FC613AB` |
| Account | `53183488`, server `Alpari-MT5-Demo` |
| Indicator build | `MetaEditor64.exe /compile:` reported `0 errors, 0 warnings` |
| Indicator attached | yes, to a chart, after a human attach |
| Snapshot at rest | `AVAILABLE`, `complete: true`, `terminal_build: 6230`, sequence advancing 138 → 273 |
| Account state at the end | `positions: []`, no pending or unknown execution record, kill switch not engaged |

**The build is 6230, not the 6184 recorded above.** This is a different
terminal build on a different install, so the control identifiers, the window
title, and the data directory are all different values. The rows above remain
the record of what was measured on 6184 and are not restated here.

Four terminals on this machine share the window title `Alpari-MT5-Demo`
(accounts 53183409, 53183488, 53183424, 53145727) and a fifth is
`AMarkets-Demo`. Discovery still reported `terminal_discovery: found` for the
configured instance, because it matches the configured executable path and data
directory rather than the title. **A shared title is therefore not ambiguous
here, and the project did not have to guess** — but that is a property of
matching on path and data identity, not of the title matching.

A snapshot from this session, read for its shape:

```json
{
  "schema": 1, "sequence": 138, "complete": true,
  "written_at": "2026-09-29T05:20:14Z",
  "account": 53183488, "server": "Alpari-MT5-Demo", "terminal_build": 6230,
  "positions": []
}
```

## Step 1 and Step 2 re-measured on 2026-09-29

Both were performed by the operator on build 6230, and both passed. Step 1
confirmed the snapshot; Step 2 confirmed that a position the operator opened by
hand is observable, which is the case the 2026-09-28 record had marked
`SUPERSEDED` rather than performed.

The full open-close cycle was observed, which is the part that matters: an
empty account, a position appearing with the fields the verifier needs, and the
account empty again. A snapshot that only ever reported `[]` would have proved
nothing, and neither would one that reported a position it could not later lose.

| # | Date | Terminal | Account | Item | Symbol / action / volume | Expected | Actual | Verification method | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 7 | 2026-09-29 | Alpari MT5_5 6230 | 53183488 | configured paths exist and discovery resolves this instance | — | paths resolve, one match | `terminal_discovery: found`; `terminal_exists` and `data_path_exists` true | `diagnostics`, `diagnostics-bundle` | PASS |
| 8 | 2026-09-29 | Alpari MT5_5 6230 | 53183488 | indicator compiles on this build | — | 0 errors, 0 warnings, `.ex5` written | `0 errors, 0 warnings` | `MetaEditor64 /compile` with log | PASS |
| 9 | 2026-09-29 | Alpari MT5_5 6230 | 53183488 | indicator snapshot observed | — | `AVAILABLE`, `complete: true`, sequence advancing | `AVAILABLE`, sequence 138 → 273, `positions: []` matching an empty Trade tab | `position-snapshot` | PASS |
| 10 | 2026-09-29 | Alpari MT5_5 6230 | 53183488 | snapshot reports `UNAVAILABLE` before the indicator was attached | — | missing snapshot is never read as an empty account | `UNAVAILABLE`, `no position snapshot found in …\MQL5\Files` | `position-snapshot` | PASS |
| 11 | 2026-09-29 | Alpari MT5_5 6230 | 53183488 | position opened by hand is observed | EURUSD BUY 0.01 | one position with the chosen symbol, side, and volume | `AVAILABLE`, `position_id 383037521`, `EURUSD`, `BUY`, `0.01` | `position-snapshot` | PASS |
| 12 | 2026-09-29 | Alpari MT5_5 6230 | 53183488 | position closed by hand disappears from the observation | EURUSD BUY 0.01 | the account returns to empty | `AVAILABLE`, `positions: []` | `position-snapshot` | PASS |
| 13 | 2026-09-29 | Alpari MT5_5 6230 | 53183488 | account left as found | — | no open position, no pending record, no stop | `positions: []`; `recovery` empty; `logs\KILL_SWITCH` absent | `position-snapshot`, `recovery` | PASS |
| 14 | 2026-09-29 | Alpari MT5_5 6230 | 53183488 | real-terminal dry-run, BUY | EURUSD BUY 0.01 | dialog prepared, no final control, no position | `ORDER_READY` then `DRY_RUN_COMPLETED`, `final execution control not used` | `dry-run` on the live terminal, then `position-snapshot` and `recovery` | PASS |
| 15 | 2026-09-29 | Alpari MT5_5 6230 | 53183488 | real-terminal dry-run, SELL | EURUSD SELL 0.01 | dialog prepared, no final control, no position | `ORDER_READY` then `DRY_RUN_COMPLETED`, `final execution control not used` | same | PASS |
| 16 | 2026-09-29 | Alpari MT5_5 6230 | 53183488 | control identifiers unchanged after the update to build 6230 | — | every measured control still present with the measured value | `verdict OK`, 13 controls, none drifted and none missing; `10408`, `10409`, `10325`, `10333`, `10334`, `10336`, `10328` all as measured on 6184 | `terminal-check`, read-only | PASS |
| 17 | 2026-09-29 | Alpari MT5_5 6230 | 53183488 | the right terminal is driven among five running ones | — | the window is pinned to the resolved process, not chosen by title | window selected by pid 5680 while four other terminals shared the `Alpari-MT5-Demo` title | `terminal-check`, `WindowsTerminalDiscovery.resolve` | PASS, DEFECT FOUND AND FIXED |
| 18 | 2026-09-29 | Alpari MT5_5 6230 | 53183488 | guarded demo order, broker rejected it | EURUSD BUY 0.01 | `REQUESTED` then `ACCEPTED` | `UNKNOWN`, `VERIFICATION_FAILED`, `no new matching position detected`. The click did reach MT5, which logged `market buy 0.01 EURUSD` and then `failed market buy 0.01 EURUSD [Request rejected due to absence of network connection]`. The account held no order and no position, and the terminal resynchronised reporting `0 positions, 0 orders` | `execute --confirm-demo`; the terminal journal `<data dir>\logs\20260929.log`; live snapshot; `recovery` | PASS, CORRECTLY REFUSED, DEFECT FOUND AND FIXED |
| 19 | 2026-09-29 | Alpari MT5_5 6230 | 53183488 | staleness guard on a real old snapshot | EURUSD BUY 0.01 | a stale snapshot is refused before the order dialog is used, never read as an empty account | four attempts refused with `refusing to execute: position snapshot is stale (129.4s old, limit 30s)`, `(369.8s…)`, `(406.1s…)`, `(485.9s…)`; the terminal journal records **no** trade for any of them | `execute --confirm-demo` with the indicator detached; `logs\idempotency.json` shows all four as `REJECTED` / `ORDER_REJECTED` | PASS |
| 20 | 2026-09-29 | Alpari MT5_5 6230 | 53183488 | guarded demo order, accepted | EURUSD BUY 0.01 | `REQUESTED` then `ACCEPTED` with evidence | `ACCEPTED`, `order_reference 383083883`, baseline `ui positions=none`, observed `ui positions=383083883:EURUSD:BUY:0.01`. The journal agrees: `accepted market buy 0.01 EURUSD`, `deal #339578159 buy 0.01 EURUSD at 1.13456 done (based on order #383083883)` | `execute --confirm-demo`, then the live snapshot and the terminal journal | PASS |
| 21 | 2026-09-29 | Alpari MT5_5 6230 | 53183488 | the close path refuses a position this application did not open | EURUSD BUY 0.01, ticket `383094933`, opened by hand | refused, nothing clicked | exit code 2, `ticket 383094933 is not in the execution ledger, so it is not a position this application opened; close it by hand`. No `position-close` audit event exists, so the refusal happened before any UI work | `close-position --confirm-demo` | PASS |
| 22 | 2026-09-29 | Alpari MT5_5 6230 | 53183488 | guarded order and guarded close, back to back | EURUSD BUY 0.01, ticket `383098717` | `ACCEPTED` then `CLOSED`, each proved by independent observation | `ACCEPTED`, `order_reference 383098717`, baseline `ui positions=none`, observed `ui positions=383098717:EURUSD:BUY:0.01`; then `CLOSED`, `position 383098717 is no longer present in the observed snapshot (1 before, 0 after)`. The journal agrees with both: `deal #339591761 buy 0.01 EURUSD at 1.13495 done (based on order #383098717)` and `accepted market sell 0.01 EURUSD, close #383098717` | `execute --confirm-demo` then `close-position --confirm-demo` on the same ticket, with no manual step in between | PASS |


**Row 18 is a broker rejection, which was one of the two rows this file listed
as unfilled.** It arrived by accident rather than by plan, and it is the most
useful result in the table, because it exercises the case the whole design
exists for: a click that lands, an outcome that cannot be proven, and an
application that says `UNKNOWN` rather than claiming a trade.

The click reached MT5, so **the control identifiers are correct on build 6230** —
row 16 said they were unchanged, and this confirms it end to end. The order was
then rejected for lack of a network connection, which is a broker-side event no
gate in this project can prevent, and the correct response is exactly what
happened: no position, no `order_reference`, and an `UNKNOWN` record for a person
to look at.

**A defect came out of it.** The `UNKNOWN` result carried no evidence, because
the workflow discarded the readings the adapter had already taken. Those readings
were the entire basis for "no new matching position", and they existed. Evidence
is now carried on the failed path as well as the accepted one, with three
regression tests. The ledger record for this attempt still predates the fix and
shows `evidence: null`; that is correct history, not an error to correct by hand.

## The 2026-09-29 evening session — a third build, 5430, and three defects

Worked on a different machine from the two sections above, so nothing here
transfers from them either. This build presents a **different order dialog**, and
checking it produced two defects in this project's own code.

| Fact | Value |
| --- | --- |
| Terminal | `C:\Program Files\Alpari MT5_4\terminal64.exe`, **build 5430** |
| Data directory | `C:\Users\BazikadeStore\AppData\Roaming\MetaQuotes\Terminal\1D9617E1A6A4352DBDC25D08FEC12BD2` |
| Account | `53184454`, server `MT5-Demo.Asia.13`, `Hedge` |
| Windows | `Windows-11-10.0.26200-SP0`, single monitor, `VirtualScreen 1536x864` |
| Python | 3.12.9 — the executable builds and runs on the target interpreter |
| Order dialog title | **`Order`**, not the `Order: EURUSD` of builds 6184 and 6230 |
| Order dialog shape | one-click: `Buy by Market` (10408) and `Sell by Market` (10409), no OK button |
| Execution mode | **absent** — this build's dialog has no `Market Execution` control at all |
| Order fields | `10325` symbol, `10333` volume, `10334` stop loss, `10336` take profit — all as measured on 6184 |
| Trade grid | `10328`, unchanged |
| Indicator | compiled with `MetaEditor64 /compile`, `0 errors, 0 warnings`, `.ex5` written |
| Account state throughout | `0 positions, 0 orders` for the read-only checks; one position opened by hand afterwards, for row 30 |

**The build number was first recorded wrongly, which is itself worth recording.**
This session initially read the build as `6090` from a line in the terminal
journal and wrote that down. The indicator's own `terminal_build` field, the
executable's version resource (`5.0.0.5430`), and `terminal-check` all say
**5430**. The journal line was the outlier and the mistake was not caught at the
time, because the journal was read once and never cross-checked. It is recorded
here rather than quietly corrected, since a build number is exactly the value this
file exists to keep trustworthy.

### Defect 1 — a collapsed Trade tab was reported as a build change

`terminal-check` reported `trade_grid: DRIFTED`, naming `10128` and `10144`. Both
belong to other panels (Mailbox and Market Watch). The real cause was that the
Toolbox was collapsed, so the grid was not on the accessibility tree at all while
its neighbours were. Opening the Trade tab showed `10328` present and correct.

The probe reported a break that had not happened, which is worse than silence: an
operator would have re-measured a sound build. It is now `NOT_PROBED` whenever a
Trade tab is positively identified and not selected, and still `DRIFTED` when that
tab *is* selected and the grid is genuinely absent. A tab strip that cannot be read
stays `DRIFTED`, because an unknown UI state is not evidence that nothing is wrong.

### Defect 2 — the probe left an order dialog open on the terminal

`open_order_dialog` only records the dialog once it recognises it, and it matched
on the title `Order:`. On build 5430 it therefore raised *after* MT5 had already put
a dialog on screen, and the cleanup path trusted only the recorded handle. The
probe returned with a live one-click order dialog sitting over the terminal, where
a single click is a market order — on the one build where that is most true.

The dialog is now matched by the prefix `Order`, and the cleanup runs on every
path, including the one where recognition failed. Both were verified against this
terminal: the report is unchanged, and no dialog is left behind.

### What is still refused, and why that is correct

- `market_execution_button` is `MISSING` and stays that way. This build's dialog
  has no execution-mode *button*. `select_market_execution` raises, and the order
  path refuses. Substituting a different control would be exactly the guessing
  this project forbids.

  What the build does have is the `Type` combo (`10338`), which already reads
  **`Market Execution`** when the dialog opens. That is a plausible equivalent and
  it is deliberately **not** wired up: a control that has been found once is not a
  control whose behaviour has been established, and on this build the guarded
  order path has never reached a final control. Deciding that a default is
  sufficient is a judgement about trading, not a lookup.
- The terminal also restarted during this session, so the process id moved from
  10808 to 14004 while the data directory stayed the same. Discovery followed it
  correctly, which is the behaviour the process-id pinning exists for.

### Defect 3 — a control that was never found was recorded as an unknown outcome

The indicator was attached and a EURUSD SELL opened by hand, and the first
real-terminal dry-run on this build produced the interesting result of the whole
session. It refused at `select_market_execution` — correctly — and was recorded as:

    status UNKNOWN / UNKNOWN_EXECUTION, "Market Execution control was not found"

**Nothing had been clicked.** The run stopped while preparing the dialog. But
`UNKNOWN` is this project's word for "a final control was used and the outcome
could not be proven", and it is what tells an operator to go and check their
account. Recording a pre-click refusal that way invents an incident: the first
record written on this build sent an operator looking for a trade that had never
been placed.

The cause was in the exception handler, which lumped `PREPARING_UI` in with
`EXECUTING` when deciding on `UNKNOWN`. A failure in `PREPARING_UI` is now
`REJECTED` / `ORDER_REJECTED`, and it is still audited with its reason, so nothing
is lost. Failures at or after `EXECUTING` remain `UNKNOWN`, which is the case that
earns the word. Three tests cover both directions.

| # | Date | Terminal | Account | Item | Expected | Actual | Verification method | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 23 | 2026-09-29 | Alpari MT5_4 5430 | 53184454 | paths resolve and the process is found | exactly one match, titled demo | `terminal_discovery: found`, pid 10808 of four running terminals | `diagnostics` | PASS |
| 24 | 2026-09-29 | Alpari MT5_4 5430 | 53184454 | indicator compiles and installs | `0 errors, 0 warnings`, `.ex5` written | exactly that | `scripts/install-position-reader.ps1` with the log | PASS |
| 25 | 2026-09-29 | Alpari MT5_4 5430 | 53184454 | order dialog is found and read | the dialog opens and exposes its controls | found once the title is matched by prefix; all four order fields and both final controls `OK` with the values measured on 6184 | `terminal-check`, read-only | PASS, DEFECT FOUND AND FIXED |
| 26 | 2026-09-29 | Alpari MT5_4 5430 | 53184454 | trade grid identifier | `10328` when the Trade tab is showing | `10328`, unchanged | `terminal-check`, read-only | PASS, DEFECT FOUND AND FIXED |
| 27 | 2026-09-29 | Alpari MT5_4 5430 | 53184454 | execution mode control | present | **absent as a button**; the `Type` combo (`10338`) reads `Market Execution` but is not substituted. The order path refuses | `terminal-check`, read-only | CORRECTLY REFUSED |
| 28 | 2026-09-29 | Alpari MT5_4 5430 | 53184454 | no dialog is left open by a probe | the terminal is as it was found | no `#32770` or `#32768` dialog remains after `terminal-check` or after a failed `dry-run` | live check with `pywinauto` after each command | PASS, DEFECT FOUND AND FIXED |
| 29 | 2026-09-29 | Alpari MT5_4 5430 | 53184454 | executable builds and runs on Python 3.12 | the build completes and both smoke tests pass | built with `scripts/build-exe.ps1`; `diagnostics` and `diagnostics-bundle` both pass; `status` reports `dry_run` and `demo_only` | `dist\auto-trade\auto-trade.exe` | PASS, DEFECT FOUND AND FIXED |
| 30 | 2026-09-29 | Alpari MT5_4 5430 | 53184454 | the indicator is attached and the snapshot is live | `AVAILABLE`, `complete: true`, build reported | `AVAILABLE`, sequence advancing, `terminal_build 5430`, and the hand-opened EURUSD SELL `0.01` ticket `383284296` is visible in it | `position-snapshot` | PASS |
| 31 | 2026-09-29 | Alpari MT5_4 5430 | 53184454 | the close path refuses a position this application did not open | refused before any UI work | exit code 2, `ticket 383284296 is not in the execution ledger, so it is not a position this application opened; close it by hand`. No `position-close` audit event exists, so it refused before touching the UI, and the position is still open | `close-position 383284296 --confirm-demo`; `position-snapshot` afterwards | PASS |
| 32 | 2026-09-29 | Alpari MT5_4 5430 | 53184454 | real-terminal dry-run refuses before any final control | `REJECTED`, no control clicked, no trade | `REJECTED` / `ORDER_REJECTED`, `Market Execution control was not found`; the journal records no trade and the snapshot still shows exactly one position | `dry-run` on the live terminal; `position-snapshot`; the terminal journal | CORRECTLY REFUSED, DEFECT FOUND AND FIXED |
| 33 | 2026-09-29 | Alpari MT5_4 5430 | 53184454 | discovery survives a terminal restart | the new process is found, not a fallback | the terminal restarted mid-session; discovery resolved pid 14004 for the same data directory and `terminal-check` reported `terminal_identity OK` | `diagnostics`, `terminal-check` | PASS |
| 34 | 2026-09-29 | Alpari MT5_4 5430 | 53184454 | a guarded order and a guarded close on this build | `ACCEPTED` then `CLOSED`, each proved by observation | **not run, and not runnable**: the execution-mode control this code requires does not exist on this build, so the order path refuses before any final control. Row 30 shows the observation path is live; it does not show an order can be placed | not run | NOT RUN |

Row 34 is the one thing this build cannot demonstrate, and it is not a defect in
this project: build 5430 presents a dialog without the control that the guarded
order path needs. Whether to treat the `Type` combo's `Market Execution` default
as sufficient is a decision about how this build should be traded, and it is not
one this project may make on its own. Until somebody makes it, row 34 stays
`NOT RUN` and this build cannot trade through the guarded path at all.

The account was left exactly as found: one hand-opened EURUSD SELL `0.01`
(`383284296`), no orders, and no `UNKNOWN` record other than the one written by
the pre-fix run, which is correct history and is left in place.

### The rows that remain

**Both controls that change an account are now measured on build 6230.** Row 22
is the one that matters: an `execute` and then a `close-position` on the same
ticket, with no manual step between them, each proved by an observation and each
independently confirmed by the terminal's own journal. The account was left with
no position and no order.

Taken with rows 16 to 21, the whole surface is exercised on this build: the
control identifiers, the window selection among five terminals, the staleness
guard, a broker rejection, an accepted fill, a refused foreign ticket, and a
guarded close.

**Still open, and not about the terminal:** a stale snapshot that later becomes
fresh and the order then proceeding, which is the recovery half of row 19. And
the operator has one `UNKNOWN` record left to settle, which is a judgement about
what they saw rather than anything the code can measure.

**And, on build 5430, the guarded order and close paths are unproven.** Row 25
shows the identifiers are right, but the execution-mode button that build presents
does not exist, so the order path refuses before reaching a final control — as row
32 confirms, by refusing on the real terminal. A build whose dialog has no
execution-mode button is a build this code cannot trade on at all, and that is a
decision for the operator rather than something a substituted identifier can
settle. Row 34 is the open item, and the `Type` combo that already reads
`Market Execution` is the thing somebody has to make that decision about.


## Clicks that left no record in this application

Between 10:52 and 10:55 local the terminal journal records six `market buy` and
one `market sell` lines, and only two of them correspond to a signal this
application processed. The others produced **no ledger record and no audit
event**, which is the signature of a human clicking in the terminal rather than
of this project: the workflow writes `record_attempt` to the durable ledger
*before* the final control is used, so a click by this application cannot exist
without a record. That ordering is what makes the absence meaningful rather than
merely unobserved.

The account was left with no position and no order.



**What rows 9 to 12 do and do not prove.** They prove the read-only observation
path on this build: the snapshot is live, complete, advancing, and it reflects a
real open and a real close. They do **not** prove that the guarded *order* path
works on build 6230. That path is untested here, and its control identifiers
were measured on 6184, so it is not a given that they carry over. Rows 6 and 6a
remain the only evidence for the guarded order, and they are evidence about a
different build.

Row 10 is a row that records a **failure being reported correctly**: before the
indicator was attached, the reader said `UNAVAILABLE` with a reason rather than
`AVAILABLE` with an empty list. That distinction is the whole point of the
fail-closed reader, and it was observed rather than assumed.

**Not repeated on 2026-09-29:** the staleness guard on a real old file, the
real-terminal BUY and SELL dry-runs, the guarded order, and the guarded close.
The first three need only this terminal and are the next thing worth running;
the last two change the account and remain an operator decision.

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

**Done 2026-09-28 on build 6184 (row 4) and again on 2026-09-29 on build 6230
(row 9).** The procedure is kept because a future install needs it again.

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

**Performed 2026-09-29 on build 6230 (rows 9 to 12).** On 2026-09-28 this step
had been marked `SUPERSEDED` because a position created by the guarded execution
path itself reached `ACCEPTED` with evidence. It has now been done directly, so
the hand-placed case is measured rather than inferred. The 2026-09-28
observation is kept because it remains the only evidence for the guarded order
path.

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
later by looking. It was settled with `reconcile`, which records the operator's
assertion and never presents it as an observation this application made; see
[recovery](RECOVERY.md).

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

Rows 1 to 6 were measured on 2026-09-28 on **build 6184**; rows 7 to 17 were
measured on 2026-09-29 on **build 6230**. A row is marked `PASS` only for the
build named in that row. Nothing in this repository may mark a row passed on an
operator's behalf, and a result on one build is not a result on the other.

**Row 16 is the answer to "did the MetaTrader update break anything": no.** Every
identifier measured on build 6184 is still correct on build 6230 — both final
controls, all four order fields, and the trade grid. The final controls are
matched by name *and* id, so this says both survived. It does not by itself prove
the guarded order path works on 6230; it proves nothing it depends on has moved.

**Row 17 records a defect found while checking.** `MT5WindowManager.find()`
selected a window by title and took the first match. With four demo terminals
sharing one title, that chose an account by enumeration order, and the demo check
that follows would have passed for all of them. The window is now selected by
process id, and an ambiguous title match is refused. See
[MT5 integration](MT5_INTEGRATION.md).
