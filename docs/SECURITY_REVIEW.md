# Security Review

A review of the whole source tree, performed 2026-09-29 with the project's own
test, lint, and type-check commands green. This file records what was examined,
what was found, what was changed, and what was deliberately left alone.

The scope is the code as it stood, not the documentation of it: 85 source files,
the five signal sources, the two network surfaces, the Windows automation layer,
configuration, the durable ledger, and the diagnostics bundle.

**Two findings were exploitable and both are fixed.** They are described with the
evidence that demonstrated them, because a finding that cannot be reproduced is a
suspicion.

## Summary

| # | Area | Finding | Severity | Status |
| --- | --- | --- | --- | --- |
| 1 | signal ingestion | A signal `id` was used unvalidated as a file name, giving any signal source an arbitrary file write | **high** | fixed, with tests |
| 2 | configuration | A `.env` in the working directory pre-empted the reviewed one and could enable live execution | **high** | fixed, with tests |
| 3 | terminal discovery | A slow or blocked process query escaped as an unhandled exception | medium | fixed, with a test |
| 4 | local API | No rate limit or lockout on repeated bad tokens | low | accepted, documented below |
| 5 | local API | No audit record for a control action refused before it acted | low | fixed, with a test |
| 6 | strategy seam | Loading a strategy executes third-party code by design | low | accepted, by design |
| 7 | signal sources | No filesystem permission check on the signal and log directories | low | accepted, documented below |

## Finding 1 — a signal id was an arbitrary file write (high)

**What it was.** `fetch-signal` and `evaluate` both build the destination of the
signal they are about to write as `signal_directory / f"{signal.signal_id}.json"`.
The id is validated only for being non-empty. A signal from any source —
authenticated HTTP, named pipe, WebSocket, a file, or a strategy — can therefore
name a path.

**Evidence.** This was run, not reasoned about:

```text
parsed signal id: '../../../../pwned'
write target: signals\..\..\..\..\pwned.json
normalised : E:\pwned.json
escapes the signal directory: True
```

**Why it mattered.** The five sources are the project's boundary with everything
outside it. A source is *supposed* to be able to do one thing only: propose a
signal. Being able to choose a filename turned "propose a signal" into "write a
file anywhere this process can write", which on Windows includes startup folders
and anything the operator's account can reach. It also defeated the point of
confining signals to a directory.

**The fix, in two independent locks.**

1. `TradeSignal` now validates the id against `SIGNAL_ID_PATTERN`: it must start
   with a letter or digit and contain only letters, digits, dot, dash, and
   underscore, up to 128 characters. The choke point is the domain model, so all
   five sources and the strategy seam are covered by one rule.
2. The two write sites additionally resolve the path and refuse to write unless
   the result is a file directly inside the signal directory. The check is
   against the *resolved* path, so a symlinked directory does not defeat it.

The second lock is deliberately stricter than the first and the difference is
tested: `sub/../x` and a bare `..` resolve to files *inside* the directory and are
allowed, because refusing them would be a correctness bug rather than a safety
win. Over-blocking is a defect too.

## Finding 2 — an unreviewed `.env` could enable live execution (high)

**What it was.** `load_env_file` resolves, in order: an explicit path,
`$AUTO_TRADE_ENV_FILE`, **`.env` in the current working directory**, then the
project checkout's `.env`. The working directory comes first. Nothing checked
*which* file answered, so a `.env` in whatever directory the process happened to
start in silently pre-empted the reviewed one.

**Evidence.** Also run:

```text
execution_enabled = True
dry_run = False
```

with a `.env` dropped in a temporary directory, while the checkout's `.env` says
`AUTO_TRADE_ENABLE_EXECUTION=false` and `AUTO_TRADE_DRY_RUN=true`.

**Why it mattered.** `AUTO_TRADE_ENABLE_EXECUTION` is the one setting this
project treats as requiring a person's deliberate, reviewed edit. That property
held only for the file a person wrote. A file dropped in a working directory — a
downloaded project, a scheduled task's folder, a share — turned a dry-run
installation into a live one, and then waited for somebody to type
`execute --confirm-demo`. The remaining gates would still have run, but the
premise that execution is off unless a person turned it on was false.

**The fix.** `load_env_file_with_origin` now reports the file and whether it can
be treated as reviewed. Trust is a property of *which file* answered, not of how
it was found — running from the checkout is normal, and flagging it would break
the real installation while fixing nothing. Only a `.env` belonging to some
other directory is untrusted.

`AppConfig.live_execution_refusal()` then refuses `execute --confirm-demo` and
`close-position --confirm-demo` when execution is enabled by an untrusted file,
naming the file and giving the three supported alternatives. `diagnostics` reports
`env_file` and `env_file_trusted`, so an operator can see where the settings came
from before trading.

Setting the variable in the shell still works, because that is a person's
deliberate act for the length of one session. That is tested, so the fix cannot
quietly become a lockout.

## Finding 3 — a slow process query crashed instead of refusing (medium)

**What it was.** `WindowsTerminalDiscovery._query` runs the only subprocess in the
project. A `TimeoutExpired`, a blocked shell, or output that was not the JSON
asked for all escaped as unhandled exceptions, so on a busy machine `diagnostics`
and `status` died with a traceback rather than reporting that the terminal could
not be identified.

**How it was found.** Not by reading. The full suite was run while five MT5
terminals were active, and two tests failed with `subprocess.TimeoutExpired`
raised through `AppConfig.from_env`. It is a real failure mode, and the machine
that produced it is the kind of machine this runs on.

**The fix.** Every failure mode of that subprocess is now a
`TerminalNotFoundError` with the reason. A discovery failure is a refusal, and a
refusal is reported rather than thrown. The timeout duration is unchanged at 15
seconds; what changed is what happens when it is reached.

## Finding 5 — a refused control action left no record (low)

The dashboard audits its own control actions, but the CLI's close path did not:
a ticket that is not in the ledger, or a close that is disabled, printed to
stderr and returned non-zero with nothing in `audit.log`. A refusal to close a
position is exactly the sort of event an operator later wants to find, and it was
invisible in the trail. Both refusals are now audited as `position-close`
`event_type: refused`.

## Accepted, not fixed

These are decisions, and each is stated here so a reader does not have to guess
whether they were overlooked.

**No rate limit or lockout on the local API (4).** The API is loopback-only and
token-authenticated on every route. A lockout would be a new denial-of-service
surface against a control — the emergency stop — that must always be reachable.
Every refusal is constant-time compared, and the address space is one machine.
Adding a counter is a decision with a cost, not an omission.

**Loading a strategy executes third-party code (6).** `AUTO_TRADE_STRATEGY` names
a module to import, and a module that is not already importable is looked for in
`strategies/`, which is added to `sys.path`. That is arbitrary code execution, and
it is the documented purpose of the seam. It is bounded in the way that matters
here: what a strategy receives is a read-only `StrategyContext`, and it can
propose a signal but cannot reach the terminal, the risk engine, or the ledger.
A test asserts the context's field set, so adding a capability to it is a visible
change rather than a quiet one. The file is operator-supplied and the operator
knows they configured it.

**No permission check on the signal and log directories (7).** On Windows these
sit under the working directory and inherit its ACL. Any process running as the
same user can read them and can drop a file into the signal directory. That
process can already do far more, and the risk engine treats a dropped signal as
untrusted input. Tightening this would mean inventing an ACL scheme; the honest
statement is what it is.

## What was examined and found sound

Recording these matters as much as the findings: the review would be worthless if
it only listed problems.

- **The five signal sources.** No `pickle`, no `eval`, no `exec`, and no
  `yaml.load` anywhere in the tree — the only deserialisation is `json.loads`,
  which does not construct objects. Payloads are treated as data throughout; a
  test writes a signal whose comment is `__import__('os').system('whoami')` and
  asserts it comes back as an inert string.
- **Command injection.** The only subprocess is the discovery query, which takes
  a module constant rather than anything operator- or network-supplied, and is
  passed as a list with no shell.
- **Secret handling.** No token is written to the audit log, printed by
  `diagnostics`, or included in the diagnostics bundle. Endpoint URLs are reduced
  by `safe_url_summary`, which strips credentials, query, and fragment. A test
  asserts the env-file origin description — which diagnostics prints — carries no
  token, since the file it names may contain one.
- **Path traversal beyond the signal id.** The diagnostics bundle writes a zip
  with literal entry names and never extracts one, so there is no zip-slip
  surface. Position snapshots are read from a configured directory and are parsed
  as JSON with a schema check, a staleness check, and a completeness check.
- **The network surfaces.** Both refuse a non-loopback bind and a non-loopback
  client URL, comparing the literal host so `localhost.example.com` and
  `127.0.0.1.nip.io` are rejected. The redirect refusal that stops a bearer token
  being resent off loopback was moved into `infrastructure/net.py` during this
  work precisely so the signal provider and the API client cannot disagree about
  it. Every read is size-bounded and every read is a bounded wait.
- **The local API.** Authenticated before routing, so an unauthenticated caller
  cannot enumerate routes. The token is refused in a query string. No route
  places, modifies, or closes an order, and the client has no method that could.
- **Idempotency.** `record_attempt` is written to the durable ledger *before* the
  final control is used, so a click by this application cannot exist without a
  record. This was confirmed against the real terminal journal on 2026-09-29,
  where seven trade lines appeared and only two belonged to a signal this
  application processed.
- **The MT5 bridge.** `MQL5\Common` is deliberately unused because it is shared
  between terminals, so a signal cannot be attributed to one instance. The
  position reader's snapshots are never mistaken for signals.

## How to re-run this

```powershell
.\scripts\test.ps1
```

`tests/unit/test_security_review.py` reproduces both exploitable findings against
the code as it was, and asserts the properties in the "examined and found sound"
section so that removing one is a visible test failure.

One test is **skipped** on this machine: the symlinked-directory containment check
needs permission to create a symlink, which this account does not have. The code
path it covers is the same one the string-based cases exercise; what the skipped
test adds is a path that only resolves correctly. It is skipped rather than
deleted so the gap stays visible.

## Reviewing the review

This document is one person's reading of one day's work, and the hand-written
WebSocket client still has not had a second pair of eyes — that remains open in
[ROADMAP.md](../ROADMAP.md) and is not something a review by the same author
settles. The two findings fixed here were found by running the code, not only by
reading it, which is the argument for doing the same rather than for this review
being complete.

[فارسی](fa/SECURITY_REVIEW.md) · [safety](SAFETY.md) · [signal protocol](SIGNAL_PROTOCOL.md)
