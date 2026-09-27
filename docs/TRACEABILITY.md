# Traceability Inventory

What this project leaves behind, where it lives, and who can see it.

**Scope.** This is an inventory of observable artifacts, written so an operator can
make an informed decision about a broker's terms and their own record keeping. It
is not a concealment guide, and it does not claim that any of these artifacts can
be removed. Where something was measured on this machine, the measurement is
quoted. Where it is general platform behaviour, it is labelled as such. Where it is
unknown, it is left unknown.

---

## Summary

| Artifact | Lives in | Visible to the broker? | Removable by us? |
| --- | --- | --- | --- |
| Observer `.ex5` / `.mq5` on disk | `MQL5\Experts\` | No, but it is on the machine | Yes, by deleting it |
| Observer load/unload entries | MT5 journal, `logs\YYYYMMDD.log` | No, local file | No, written by MT5 |
| Observer in Navigator and on the chart | MT5 UI | No, local | Yes, by detaching it |
| Observer log and snapshot files | `MQL5\Files\` | No, local | Partly, we stop writing them |
| Trade record (symbol, side, volume, time) | Broker and MT5 history | **Yes** | No |
| Magic number on UI-driven trades | Trade record | **Yes** | No |
| Our audit log and ledger | `<repo>\logs\` | No | Yes |
| Timing and behavioural pattern | Correlatable server-side | **Possibly** | No |

---

## A. Traces inside MetaTrader

### A1. The observer program is an MQL5 program, and MT5 says so

The position observer is attached to a chart. Measured on Alpari MT5 build 6184,
the terminal's own journal records it, category `Experts`:

```text
IN  0  08:49:21.066  Experts  expert AutoTradePositionObserver (BITCOIN,H1) loaded successfully
OE  0  09:58:07.146  Experts  expert AutoTradePositionObserver (BITCOIN,H1) removed
```

File: `<data path>\logs\YYYYMMDD.log`.

This is written by MT5, not by us. It is the single most direct piece of evidence
that a program is running in the terminal, and we have no influence over it beyond
not attaching the program.

The journal also carries the account, the server, the terminal build, and the
network endpoint, so it is a complete local record of the session regardless of
this project.

### A2. The compiled program is on disk

```text
<data path>\MQL5\Experts\AutoTradePositionObserver.mq5
<data path>\MQL5\Experts\AutoTradePositionObserver.ex5
```

Both carry filesystem timestamps. The `.ex5` is a compiled binary that any MQL5
decompiler or hex viewer can inspect. This is normal for every EA, script, and
indicator a trader owns, but it means the machine is not "clean" in the sense of
containing no custom programs.

### A3. The Navigator and the chart

The program is listed under `Navigator → Expert Advisors` while it is installed,
and its name is drawn on the chart it is attached to. Both are visible to anyone
looking at the screen. General MT5 behaviour, verified during this work: the item
appears in the Navigator tree, and attaching it names it on the chart.

### A4. Files the observer writes

```text
<data path>\MQL5\Files\auto_trade_positions_a.json
<data path>\MQL5\Files\auto_trade_positions_b.json
<data path>\MQL5\Files\auto_trade_observer.log
```

The two snapshot files are required for verification; without them the bridge
fails closed. `auto_trade_observer.log` is a diagnostic trail we added because
MQL5 program logging can be switched off in terminal options, and its absence
would otherwise be indistinguishable from the program never running. That log is
ours and can be dropped if its presence matters more than its diagnostic value.

These files are local. They are not transmitted anywhere by this project.

### A5. The trade record

This is the part the broker sees, and it is the part we have no influence on.

Measured, from the observer's own reading of the position opened by hand:

```json
{"ticket": 382363348, "symbol": "BITCOIN", "type": "BUY",
 "volume": 0.01000000, "magic": 0}
```

`magic: 0` is the value MT5 uses when no magic number is set, which is the case
for a terminal-placed order. An EA that calls `OrderSend` normally sets a non-zero
magic number, and that number is stored on the trade and is visible to the broker
and in the History tab.

So a trade placed by clicking the terminal UI carries the same magic number as a
trade placed by a person clicking the same button. There is no MT5 field that
records "a human did this" or "a program did this"; the closest thing is the
magic number, and UI-driven orders do not set one.

**What this does not mean.** It does not mean the trade is indistinguishable from
manual. It means the trade record contains no field that says so. Sections C and
D cover why that distinction matters.

### A6. MT5 program logging

MT5 writes program `Print` output to `<data path>\MQL5\Logs\YYYYMMDD.log`. This is
a terminal setting (`Tools → Options → Expert Advisors → Log`) and it applies to
all MQL5 programs, not only this one. The observer writes its own log file rather
than relying on it, so disabling MT5 logging does not break verification.

---

## B. Traces outside MetaTrader

These live entirely on the local filesystem and are not sent to the broker. They
exist for the operator's own record keeping and recovery.

| Path | Contents |
| --- | --- |
| `<repo>\logs\audit.log` | every state transition, gate refusal, verification outcome, and snapshot evidence |
| `<repo>\logs\idempotency.json` | per-signal execution ledger, survives restart |
| `<repo>\logs\KILL_SWITCH` | emergency-stop sentinel, when active |
| `<repo>\signals\*.json` | signals awaiting processing |
| `<repo>\strategies\*.py` | the market-analysis library that proposes trades |

The audit log is deliberately thorough. It is the reason a refused execution can be
investigated after the fact rather than merely counted, and it is the reason
verification evidence exists at all. Nothing in it reaches the broker.

---

## C. Behavioural patterns

These are not files. They are properties of *when* things happen, and they are the
part that cannot be removed by changing any code in this repository.

- **Regularity.** The observer writes on a fixed one-second interval. Snapshot
  sequence numbers advance with clock regularity.
- **Latency.** A dry-run reaches `ORDER_READY` in roughly seven seconds, almost
  entirely spent in `PREPARING_UI` driving the dialog. A person is not that
  consistent.
- **No idle time.** In a strategy-driven run there is no gap between a signal
  appearing and an order being submitted.
- **Coverage.** An unattended process runs through sessions, weekends, and
  rollover without the pauses a human has.
- **Selection.** Repeatedly identical volume, symbol, and timing choices.

Any one of these is weak evidence. Together, and correlated against a session
record, they are not. This is the reason the project never claims that UI
automation is "manual trading": the absence of a label is not the absence of a
pattern.

---

## D. What is not known

Stated plainly rather than guessed:

- Whether or how the broker's servers distinguish terminal-placed orders from
  other sources is **not known** to this project and cannot be determined from the
  client.
- Which fields the broker retains, for how long, and who can inspect them is
  **not known**.
- Whether a given account's terms permit this is a **contractual** question. It
  cannot be answered by inspecting code, and no amount of engineering changes the
  answer.
- What a prop firm or account provider does with correlated timing data is
  **not known**.

`docs/COMPLIANCE.md` already states the position this project takes: users are
responsible for confirming with their broker, prop firm, and account provider that
this use is permitted, and this project does not claim that desktop automation is
manual trading.

---

## E. What can legitimately be reduced

Some artifacts are noise rather than substance, and reducing noise is ordinary
hygiene rather than concealment.

| Action | Effect | Cost |
| --- | --- | --- |
| Detach the observer when not verifying | removes A1, A2, A3 | verification becomes `UNAVAILABLE` |
| Stop writing `auto_trade_observer.log` | removes one file in A4 | a failed start is harder to diagnose |
| Turn off MT5 program logging in Options | removes MQL5 log files | affects all programs, not only this one |
| Lower the audit log level | shrinks B | weakens your own record keeping |

None of these change C. Timing patterns are unaffected by any of them.

---

## F. The question that is not technical

If the purpose is that a broker or prop firm should not learn that an account is
automated, that is a decision about a contractual relationship, and the right
place to raise it is with the provider in writing, before trading. A provider that
permits disclosed automation is in a very different position from one that
discovers it later.

The alternative supported by this project is the opposite of concealment: every
order can be tagged as automated, so the account is self-declaring. That is a
one-line change to the comment or magic number the bridge sends, and it makes
permitted automation unambiguously permitted.

---

## G. How to reproduce the measurements in this document

```powershell
# A1: the terminal's own record of the program
Select-String -Path "<data path>\logs\$(Get-Date -Format yyyyMMdd).log" -Pattern "Experts"

# A4: files the observer writes
Get-ChildItem "<data path>\MQL5\Files"

# A5: the magic number on an open position
python -m auto_trade position-snapshot
Get-Content "<data path>\MQL5\Files\auto_trade_positions_a.json"
```
