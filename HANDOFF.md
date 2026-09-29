# Handoff prompt — auto-trade

Copy everything below into the next session.

---

You are continuing work on **auto-trade**, a Windows automation bridge that drives
MetaTrader 5 from Python. Read `README.md`, `ROADMAP.md`, and
`docs/SAFETY.md` before changing anything — the safety reasoning is the point of
the project, and several rules below exist because of defects already found.

## Where things are

- Repo: `D:\Projects\auto-trade`, branch `main`, clean and in sync with
  `origin/main` (`github.com/ybagheri/auto-trade`). Last commit `5dab5df`.
- Python 3.12.9 is installed. The executable builds:
  `scripts\build-exe.ps1 -SkipTests` (it runs the test suite first otherwise).
- Test suite: **602 passed, 1 skipped**. Run `python -m pytest -q` before and
  after any change.
- `.env` exists, is gitignored, and points at the terminal below.

## The live terminal

`Alpari MT5_4`, build **5430**, account `53184454` (`Alpari-MT5-Demo`, Hedge,
demo account). Pid changes when the terminal restarts — discovery follows it, and
that is expected, not a fault.

```powershell
python -m auto_trade diagnostics
python -m auto_trade position-snapshot
python -m auto_trade terminal-check
python -m auto_trade status
```

The position reader indicator is **compiled and attached** to a EURUSD chart, so
snapshots are live. The account is currently **flat: no positions, no orders**.

## Rules that are not negotiable

1. **Never enable execution to "test" something.** `AUTO_TRADE_ENABLE_EXECUTION`
   and `AUTO_TRADE_ENABLE_CLOSE` are both `false` and must stay that way unless a
   human explicitly asks for a live demo order in that same message.
2. **Never substitute a control identifier you have not measured.** A control
   found once is a control whose behaviour is not established. If a build
   presents something different, refuse and report it — do not wire it up.
3. **Never mark a validation row `PASS` on a person's behalf.** Rows in
   `docs/MT5_DEMO_VALIDATION.md` are claims about what was observed, on a named
   build, by a named method.
4. **A build number is a load-bearing fact.** Cross-check it against at least two
   sources (the indicator's `terminal_build` field, the executable's version
   resource, `terminal-check`) before writing it down. I got this wrong once
   already this session and had to correct the record.
5. **Verify a regression test fails against the old code** before trusting it. A
   test that passes against the bug is worse than no test, because it looks like
   coverage. I caught one of my own this way.
6. **Commit only when asked.** Push only when asked.

## What is genuinely open

### 1. Build 5430 cannot be traded through the guarded path — needs a human decision

This is the biggest open item and it is **not yours to decide**.

Build 5430's order dialog has **no execution-mode button**. There is a `Type`
combo (`10338`) that already reads `Market Execution` when the dialog opens, but
wiring it up is a judgement about whether a default is a guarantee — a trading
decision, not a lookup.

Today the order path refuses at `select_market_execution`, which is correct.
**Leave it refusing** unless a human says the default is good enough. If they do,
it needs: a measured identifier, a re-run of `terminal-check`, and a real-terminal
validation row. See ROADMAP.md.

### 2. The other open ROADMAP items

- **Recovery after a real terminal restart.** The crash-between-click-and-
  observation case is covered by `tests/integration/test_crash_recovery.py`, and
  the staleness guard now covers both halves. What is untested is the same
  sequence against a *real* terminal restart, which needs a person to kill MT5
  mid-order. Do not fake this.
- **Hedge, partial close, and modify.** Refused today. Each needs its own
  measured control identifiers and its own verification of the resulting state.
  Do not start this speculatively.
- **Reliability across DPI, monitors, focus loss.** Measured and ruled out as the
  obstacle on this machine (single monitor, 1536x864, no scaling fault). The real
  variation is which controls a build presents, not DPI.

## Where a defect is most likely to still be

Two patterns produced most of the defects found this session, and both are worth
checking first in any new code:

- **A safety property enforced at one moment rather than at the point of use.**
  This is how the WebSocket loopback check passed `start()` and then connected
  somewhere unchecked, and how the position baseline was captured during order
  preparation and reused at click time. Ask: *is this checked where the action
  happens, or only earlier?*
- **A refusal recorded as something stronger than it is.** A missing control
  reported as `UNKNOWN` told an operator to check their account for a trade that
  was never placed. Ask: *does this status word commit me to something I did not
  actually do?*

## Useful commands

```powershell
python -m pytest -q                                   # full suite
python -m pytest tests/unit/test_terminal_check.py -q # the probe
python -m auto_trade terminal-check --no-record       # read-only, no history write
python -m auto_trade dry-run <signal.json>            # never reaches a final control
python -m auto_trade recovery                         # pending / unknown / reconciled
scripts\build-exe.ps1 -SkipTests                      # build the executable
```

`terminal-check` is read-only and never uses a final control. It opens the order
dialog on the real terminal, so the terminal will flicker and briefly take focus.

## First thing to do

Read `git log --oneline -8` and the last two commit messages in full. They
describe, in detail, four defects found and fixed on the real terminal, one
mis-recorded build number, and the reasoning behind each fix. That context is the
most useful thing in the repository right now, and it is not in the code.
