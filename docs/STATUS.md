# Project Status

One page for whoever opens this repository, human or otherwise: what is built,
what was actually run and observed, what is refused on purpose, and what is
still open with the reason it is open.

Read this first, then [ROADMAP.md](../ROADMAP.md) for the phase plan and
[demo validation](MT5_DEMO_VALIDATION.md) for the measured MT5 record.

For what the 2026-09-29 session changed and what it left open, see
[the session summary](SESSION_2026-09-29.md).

**State as of 2026-09-30.** `main` is green: 602 passed and 1 skipped, `ruff`
clean, `mypy --strict` clean, all on Machine A (see
[HANDOFF.md](../HANDOFF.md) for which machine is which — the terminal facts in
this repository are per-machine). Every claim below was either executed on a
real machine or is labelled as not run.

## What this is

A safety-first Windows bridge that takes a signal, decides whether it may be
acted on, and if it may, uses the MT5 desktop UI to place exactly one guarded
order. The two design commitments that shape everything else:

1. **A signal, a decision, a click, a broker acceptance, and an observed
   position are five different events.** The code never collapses them.
2. **A click proves nothing.** Success is only ever established by an
   independent observation, and a click that cannot be corroborated is reported
   as `UNKNOWN` rather than as a trade.

## Verified on a real terminal

Two terminals are involved in this project's record and they are **not the
same build**, so a row below is evidence only for the build it names. Alpari MT5
build 6184 was measured on 2026-09-28 and is the record for the guarded order
and the guarded close. Alpari MT5 build 6230 (per-user install, account
53183488) was measured on 2026-09-29 and is the record for the read-only
observation path, which was re-measured there from scratch. Details and the full
record table are in [demo validation](MT5_DEMO_VALIDATION.md).

| Capability | Result | How it was established |
| --- | --- | --- |
| Terminal discovery by executable path and instance name | PASS | `diagnostics` reports `found`, on both 6184 and 6230, and with four same-titled terminals running |
| Read-only position indicator | PASS | compiles 0 errors/0 warnings, registered in the Navigator, writes a complete snapshot every second |
| Snapshot read | PASS | `position-snapshot` reports `AVAILABLE`; a fresh snapshot of an empty account and a 23-hour-old one are told apart |
| Staleness guard | PASS | an old snapshot is refused as `stale`, never read as an empty account |
| Position appearing and disappearing | PASS | on 6230, a position opened by hand was observed with its ticket, symbol, side, and volume, and was gone again after being closed by hand |
| Controlled dry-run, BUY and SELL | PASS | reached `ORDER_READY`, closed the dialog, no final control, no position afterwards, on 6184 and again on 6230 |
| Staleness guard on a real old snapshot | PASS | on 6230 it refused four live orders with `refusing to execute: position snapshot is stale`, and the terminal journal records no trade for any of them |
| Control identifiers after an MT5 update | PASS | `terminal-check` reports every measured control present and unchanged on build 6230, including both final controls matched by name and id |
| Correct terminal chosen among five running | PASS | the window is selected by resolved process id; four terminals shared the `Alpari-MT5-Demo` title, and an ambiguous title match is now refused rather than resolved |
| Guarded order | PASS | on 6230 a real order was **rejected by the broker** (no network) and correctly reported `UNKNOWN`; a later attempt returned `ACCEPTED` with `order_reference 383083883` and evidence that the terminal's own journal confirms |
| Close refused for a position this application did not open | PASS | a hand-opened ticket was declined with `not in the execution ledger`, and no `position-close` audit event exists, so it refused before touching the UI |
| Guarded position close | PASS | on 6230, `execute` then `close-position` on the same ticket with no manual step returned `ACCEPTED` then `CLOSED`, each proved by independent observation and each confirmed by the terminal's journal. `position 383098717 is no longer present in the observed snapshot (1 before, 0 after)` |
| Dashboard, diagnostics bundle, configuration wizard | PASS | served and exported from a frozen Windows build |
| Local API server and client | PASS (local, no MT5) | every route refuses without a token, an account-changing route is refused with a reason, the durable stop and its audit record were exercised against a running server |

**Not yet measured on build 6230:** nothing about the terminal itself. Both
controls that change an account are proven there, and the account was left with
no position and no order. What remains open is elsewhere: recovering from a stale
snapshot, and the items in the table below.

Both order directions were exercised on the same build that ships the code here.
The order path was exercised twice: the first attempt filled and was reported
`UNKNOWN`, which found three defects; the second returned `ACCEPTED`.

## What is deliberately refused

These are decisions, not gaps. Each one is a place where guessing could cost
money.

| Refused | Why |
| --- | --- |
| The final control without `AUTO_TRADE_ENABLE_EXECUTION=true` | the only code that places an order has no default-on path |
| Closing a position without `AUTO_TRADE_ENABLE_CLOSE=true` | closing is a separate opt-in; allowing an order never allows a close |
| A position this application did not open | the close path requires the ticket in the execution ledger, so a human's position is never touched |
| A close when more than one position is open | the Trade grid exposes row rectangles but no row text, so a ticket cannot be tied to a row without a guess |
| `Close by`, `Close 50%`, `Close All`, `Modify or Delete` | neighbours of the one menu entry this code uses; each would need its own identifiers and its own verification |
| `wss://` and any non-loopback signal endpoint | TLS is not implemented here, and a network source is not approximated |
| A local API read without a token, or a token in a query string | a status feed a program calls on a schedule must not be readable or spoofable by anything else on the machine, and a URL is written to proxy logs |
| An unattended loop placing orders | `run` is a dry-run loop by construction: the same workflow builder as `dry-run`, the gate explicitly disabled, and it stops on an `UNKNOWN` outcome rather than retrying. The final control stays in `execute --confirm-demo`, per signal |
| Two configured signal sources at once | an operator who set two has not decided which is authoritative |
| A snapshot that is missing, stale, incomplete, or unreadable | reported as unavailable; never as an empty account |
| Hedge, partial close, modify | not implemented; see ROADMAP |
| A window chosen by title when several terminals share one | the window is selected by the process id discovery resolved, and an ambiguous title match is refused rather than resolved |
| A control that moved after an MT5 update | `terminal-check` reports it before a trade is attempted, and the order and close paths refuse rather than use an unmeasured control |
| Any live or funded account | out of scope at every step of this project |

## Architecture in one diagram's worth of words

```text
signal source (file | MQL5 bridge | HTTP | pipe | WebSocket)
      -> normalization into a TradeSignal
      -> risk engine (whitelist, volume, expiration, duplicates, rate)
      -> execution state machine (durable ledger, audit log)
      -> MT5 desktop adapter (semantic controls, no coordinates for orders)
      -> independent observation (read-only MQL5 indicator snapshot)
      -> ACCEPTED / CLOSED, or UNKNOWN
```

Layer rules the code keeps: `domain` holds typed models, enums, exceptions and
protocols only; `application` holds the risk engine, the state machine, the
ledger, the diagnostics bundle and the configuration wizard; `infrastructure`
holds providers, configuration, the Windows adapter and logging; `interfaces`
and `cli` call the same application services. The application layer imports no
infrastructure.

## Local state that is not in this repository

- `.env` is ignored and machine-specific. `python -m auto_trade configure` writes
  it; it always writes `AUTO_TRADE_ENABLE_EXECUTION=false`. As of 2026-09-29 it
  points at the per-user install `Alpari MT5_5`, build 6230, data directory
  `BF4EF096D1140DE6DC1607EA4FC613AB`.
- Five terminals run on this machine and four share the window title
  `Alpari-MT5-Demo`. Discovery distinguishes them by executable path and data
  directory, not by the title.
- `logs/`, `signals/` and `dist/` are ignored runtime artifacts.
- Git is installed per user at `%LOCALAPPDATA%\Programs\Git`, not on `PATH`. The
  bundled `ssh` also misreads this shell's `HOME`, which is set to a POSIX path,
  so it finds no `known_hosts` and every push fails with `Host key verification
  failed` even though the GitHub keys are present and correct. Pushing works
  with `HOME=C:\Users\bagheri` and
  `GIT_SSH_COMMAND=C:/Windows/System32/OpenSSH/ssh.exe`, which uses the Windows
  OpenSSH and reads the existing key and `known_hosts`. The host key already in
  `known_hosts` was confirmed to match what GitHub presents, so no new trust was
  needed.

## Open work, and what blocks each item

| Item | Blocked by |
| --- | --- |
| Recovery after terminal restart | partly done: a crash between the click and the observation is covered end to end, including the durable `REQUESTED` record, the refusal of the same signal after a restart, and settlement only by the operator. Still open: the same sequence against a real terminal that is killed mid-order |
| Reliability across DPI, monitors, focus loss, dialogs | needs a second machine, or an MT5 build on this one that can be resized and moved; the focus-loss defect found on 2026-09-28 is now covered by the window manager bringing the terminal forward |
| Independent review of the hand-written WebSocket client | needs a second pair of eyes, or a decision to accept a runtime dependency |
| Complete bilingual documentation synchronization | done for the pages that state a refusal, a recovery, or an observation. Ten developer- and operator-facing reference pages are English-only and named as deliberate in `tests/unit/test_documentation.py`, which fails when a pair drifts |
| Security review and dependency review | **done.** Two exploitable findings were found and fixed — a signal `id` that was an arbitrary file write, and a `.env` in the working directory that could enable live execution past the reviewed one. A third, an unhandled exception from a slow process query, was found by the suite failing under load. See [security review](SECURITY_REVIEW.md) |
| Hedge, partial close, modify | needs measured control identifiers and verification of the resulting state |
| Staleness guard on a real old snapshot, build 6230 | **done.** Four live orders were refused on a stale snapshot and the terminal journal shows no trade for any of them |
| Recovery from a stale snapshot | needs only this terminal. The guard is proven to refuse; that a later fresh snapshot lets the order proceed is the untested half |

Three items are no longer open. Settling an execution record an operator later
proved is described in [recovery](RECOVERY.md). Structured metrics and latency
observability are described in [metrics](METRICS.md): they are derived from the
audit log rather than collected in memory, so a run that crashed between the
click and the observation is still measured, and a phase with no measurement
reports nothing rather than a zero. The security review is in
[security review](SECURITY_REVIEW.md): two exploitable findings were fixed, both
found by running the code rather than only by reading it. Hedge, partial close,
and modify are deliberately not planned in this phase.

## How to reproduce the verification

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,windows]"
.\scripts\test.ps1
```

On a machine with the demo terminal running, the indicator attached to a chart,
and the flags in the process environment only:

```powershell
$env:AUTO_TRADE_ENABLE_EXECUTION = "true"
$env:AUTO_TRADE_ENABLE_CLOSE = "true"
$env:AUTO_TRADE_DRY_RUN = "false"
python -m auto_trade diagnostics
python -m auto_trade position-snapshot
python -m auto_trade dry-run <signal-file>
python -m auto_trade execute --confirm-demo <signal-file>
python -m auto_trade close-position <ticket> --confirm-demo
python -m auto_trade diagnostics-bundle
python -m auto_trade api
python -m auto_trade run --mock --max-signals 1
```

`api` needs a token, from `AUTO_TRADE_API_TOKEN` or `--token`; without one it
exits rather than serving an endpoint nobody can authenticate to. `run` is a
**dry-run loop**: it walks pending signals through the whole workflow and stops
at `DRY_RUN_COMPLETED`, and it cannot place an order by construction. See
[execution](EXECUTION.md).

## Reading order for a new reader

1. This page, for where the project stands.
2. [README.md](../README.md), for what it is and how to run it.
3. [demo validation](MT5_DEMO_VALIDATION.md), for the measured MT5 record and
   the manual steps that remain.
4. [execution](EXECUTION.md), for the two controls that change an account and
   every gate in front of them.
5. [signal protocol](SIGNAL_PROTOCOL.md), for the five signal sources and their
   refusals.
6. [local API](API.md), for the one local surface a program, rather than a
   person, is meant to call.
7. [ROADMAP.md](../ROADMAP.md), for the phase plan and the open items.
