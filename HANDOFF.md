# Handoff prompt — auto-trade

Copy everything below into the next session.

---

You are continuing work on **auto-trade**, a Windows automation bridge that drives
MetaTrader 5 from Python. Read `README.md`, `ROADMAP.md`, and
`docs/SAFETY.md` before changing anything — the safety reasoning is the point of
the project, and several rules below exist because of defects already found.

## Read this first: there are two machines, and they are not interchangeable

The work happens on **two laptops**, and most of the interesting facts in this
project are **per-machine**. A terminal path, data directory, account number,
build number, screen size, and even the repository path differ between them.

An earlier version of this file mixed the two and was wrong in a way that sent
the next session after the wrong terminal. The specific failure was: it named
one machine's terminal, build, and account while the `.env` and the code pointed
at the other machine's. Nothing about that is detectable by reading the
repository, which is why it is called out here.

**So: measure, do not carry over.** Before acting on any terminal fact, confirm
it on the machine you are sitting at, from at least two sources.

| | Machine A | Machine B |
| --- | --- | --- |
| Repository | `E:\auto-trade` | `D:\Projects\auto-trade` |
| Windows | 10, build 19045 | 11, build 26200 |
| Python | **3.13.12** | 3.12.9 |
| Administrator | **no** — the account is not in `Administrators` | yes (`C:\Program Files` installs) |
| Display | single monitor, `VirtualScreen 1366x768`, 96 DPI | single monitor, `VirtualScreen 1536x864` |
| Terminal in use | `Alpari MT5_5` (per-user) | `Alpari MT5_4` (`C:\Program Files`) |
| Build | **6230** | **5430** |
| Data directory | `…\BF4EF096D1140DE6DC1607EA4FC613AB` | `…\1D9617E1A6A4352DBDC25D08FEC12BD2` |
| Account | `53183488` | `53184454` |
| Server | `Alpari-MT5-Demo` | `MT5-Demo.Asia.13` |

Both are `Hedge` demo accounts on `Alpari`. Machine A also runs four other
terminals that **share the window title `Alpari-MT5-Demo`** (accounts 53183409,
53183488, 53183424, 53145727) plus one `AMarkets-Demo`, so the title identifies
nothing — discovery matches on executable path and data directory.

**No admin rights are needed, and Machine A has none.** This was measured rather
than assumed: on 2026-09-30 `terminal-check` read all 13 controls, including both
final controls and the execution-mode button, from a session whose account is not
in `Administrators`. UI Automation sees the terminal because Python and MT5 run at
the same integrity level, and the code asks for elevation nowhere. Recorded as
row 37 in [MT5_DEMO_VALIDATION.md](docs/MT5_DEMO_VALIDATION.md). The per-user
install layout on Machine A is a consequence of the same thing, not a
workaround this project needs.

`mypy` is configured for `python_version = "3.11"` while Machine A runs 3.13.12.
The gate is clean on 3.13; it has not been re-run on Machine B's 3.12.9 since
the lint fixes, so do that before trusting it there.

`.env` is **gitignored**. It did not travel when the checkout moved, and its
absence fails one test. Recreate it before running the suite.

## Where things are

- Branch `main`, clean and in sync with `origin/main`
  (`github.com/ybagheri/auto-trade`). Last commit `ef33d72`.
- Test suite on Machine A: **602 passed, 1 skipped**. Run `python -m pytest -q`
  before and after any change.
- The full gate is `scripts\test.ps1` (`pytest`, `ruff`, `mypy src tests`, and
  it stops on the first failure). Put `typestubs` on `MYPYPATH` first for the
  individual tools:

  ```powershell
  $env:MYPYPATH = ".\typestubs"
  python -m pytest -q
  python -m ruff check .
  python -m mypy src tests
  ```

  **Run all three, not just pytest.** Commit `5dab5df` shipped four `ruff`
  violations and two stale `type: ignore` comments because only the tests had
  been run. They are fixed now, and the gate is clean on Machine A. Whether
  `mypy` is clean on **Machine B's Python 3.12** has not been re-checked since.

## The live terminal (Machine A)

`Alpari MT5_5`, build **6230**, account `53183488` (`Alpari-MT5-Demo`, Hedge,
demo). Pid changes when the terminal restarts — discovery follows it, and that
is expected, not a fault.

```powershell
python -m auto_trade diagnostics
python -m auto_trade position-snapshot
python -m auto_trade terminal-check
python -m auto_trade status
```

The position reader indicator is compiled and attached to a EURUSD chart, so
snapshots are live. The account is **flat: no positions, no orders**.

The build number **6230** is confirmed by three independent sources: the
executable's version resource (`5.0.0.6230`), the indicator's own
`terminal_build` field, and the terminal journal line
`Alpari MT5 x64 build 6230 started`. Every Alpari executable on Machine A reads
6230; there is no 5430 on it.

Note that the terminal can be closed underneath you. On 2026-09-30 the configured
instance exited cleanly (`exit with code 0`) mid-session, and a second terminal
was started and closed in the same three minutes. If `position-snapshot` starts
reporting `UNAVAILABLE — stale`, check whether the process is still running
before treating it as a defect; the staleness guard refusing a frozen file is
the guard working.

## Rules that are not negotiable

1. **Never enable execution to "test" something.** `AUTO_TRADE_ENABLE_EXECUTION`
   and `AUTO_TRADE_ENABLE_CLOSE` are both `false` and must stay that way unless a
   human explicitly asks for a live demo order in that same message.
2. **Never substitute a control identifier you have not measured.** A control
   found once is a control whose behaviour is not established. If a build
   presents something different, refuse and report it — do not wire it up. The
   same applies to a whole machine: do not carry a measured identifier, or a
   measured build's verdict, from the other laptop.
3. **Never mark a validation row `PASS` on a person's behalf.** Rows in
   `docs/MT5_DEMO_VALIDATION.md` are claims about what was observed, on a named
   build, by a named method.
4. **A build number is a load-bearing fact.** Cross-check it against at least two
   sources (the indicator's `terminal_build` field, the executable's version
   resource, `terminal-check`, the journal's start line) before writing it down.
   This has now gone wrong three times: once from reading `6090` out of a journal
   line, once when a build number was carried between machines, and once when
   Machine B's build was presented as Machine A's live terminal.
5. **Verify a regression test fails against the old code** before trusting it. A
   test that passes against the bug is worse than no test, because it looks like
   coverage. I caught one of my own this way.
6. **Commit only when asked.** Push only when asked.

## What is genuinely open

### 1. Build 5430 cannot be traded through the guarded path — Machine B only

This is the biggest open item and it is **not yours to decide**. Note whose build
it is: **5430 is Machine B's terminal, not Machine A's.** It is not installed on
Machine A at all.

Build 5430's order dialog has **no execution-mode button**. There is a `Type`
combo (`10338`) that already reads `Market Execution` when the dialog opens, but
wiring it up is a judgement about whether a default is a guarantee — a trading
decision, not a lookup.

On Machine B the order path refuses at `select_market_execution`, which is
correct. **Leave it refusing** unless a human says the default is good enough. If
they do, it needs: a measured identifier, a re-run of `terminal-check`, and a
real-terminal validation row. See ROADMAP.md.

Do not "fix" this by editing the 5430 rows in
[MT5_DEMO_VALIDATION.md](docs/MT5_DEMO_VALIDATION.md). Those rows are a valid
measurement of Machine B, taken on that build by that method. They are not
wrong, and rewriting them to match Machine A would destroy the only record of
what that build presents.

### 2. The other open ROADMAP items

- **Recovery after a real terminal restart.** The crash-between-click-and-
  observation case is covered by `tests/integration/test_crash_recovery.py`, and
  the staleness guard now covers both halves. What is untested is the same
  sequence against a *real* terminal restart, which needs a person to kill MT5
  mid-order. Do not fake this. (Machine A did have a real terminal restart on
  2026-09-30, but it was a clean shutdown with no order in flight, so it
  exercises nothing here.)
- **Hedge, partial close, and modify.** Refused today. Each needs its own
  measured control identifiers and its own verification of the resulting state.
  Do not start this speculatively.
- **Reliability across DPI, monitors, focus loss.** The `1536x864` measurement in
  ROADMAP is Machine B's. Machine A is `1366x768` at 96 DPI — still one monitor
  and no scaling fault, so the conclusion that DPI is not the obstacle carries
  across qualitatively, but **the geometry is smaller here and untested**. The
  real variation is which controls a build presents, not DPI.

## Where a defect is most likely to still be

Three patterns produced the defects found so far, and all three are worth
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
- **A fact carried forward instead of measured.** The build number, and now the
  machine it belongs to. Ask: *was this observed here, or remembered from
  somewhere else?*

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

Read `git log --oneline -8` and the last three commit messages in full. They
describe, in detail, four defects found and fixed on the real terminal, one
mis-recorded build number, three defects in the hand-written WebSocket client,
and the reasoning behind each fix. That context is the most useful thing in the
repository right now, and it is not in the code.

Then measure the terminal you are actually on before you trust any terminal fact
in this file.
