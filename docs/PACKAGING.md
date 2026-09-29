# Packaging

Three deliverables: a diagnostics bundle, a configuration wizard, and a Windows
executable with an installer definition. None of them changes what the
application is allowed to do; they change how it is inspected, configured, and
delivered.

## Diagnostics bundle

```powershell
python -m auto_trade diagnostics-bundle
python -m auto_trade diagnostics-bundle --output C:\Temp\report.zip
```

The bundle writes one zip file containing `manifest.json` plus a section per
topic:

| Entry | Content |
| --- | --- |
| `environment.json` | Python, platform, working directory, availability of `pywinauto`/`comtypes`/`pywin32`, and the DPI, monitor, and screen metrics the UI automation depends on |
| `configuration.json` | terminal identity, signal and log directories, safety flags, risk limits, and the signal sources |
| `terminal.json` | the outcome of terminal discovery, or the reason it failed |
| `positions.json` | the position observation, or why it was unavailable |
| `executions.json` | pending and unknown ledger records, and a count |
| `metrics.json` | counters and per-phase latency, derived from the same audit tail, and marked truncated when the tail is short |
| `signals.json` | pending signal files, including the unreadable ones |
| `kill-switch.json` | whether the durable stop is engaged and why |
| `audit-log.json` | the tail of `logs\audit.log` |

It is read-only. It discovers the terminal and reads local files; it does not
open an order dialog and it does not touch an execution control. A discovery
failure is recorded as text rather than raised, because a failure is exactly the
reason the bundle exists.

The bundle contains no credentials. `.env` is never included, the HTTP signal
token is never written (only whether one is configured), and the endpoint URL is
reported without credentials, query, or fragment. `manifest.json` repeats that
guarantee as `contains_no_credentials` and lists what was excluded.

This exists because the remaining validation steps are manual. Attaching the
bundle to a report is more reliable than asking someone to remember which of
`diagnostics`, `position-snapshot`, and `recovery` to run.

## Configuration wizard

```powershell
python -m auto_trade configure
python -m auto_trade configure --dry-run
python -m auto_trade configure --target C:\auto-trade\.env --overwrite
```

The wizard asks for the machine-specific settings, shows the current value as the
default of every question, and refuses answers that do not exist on disk: a
terminal executable that is missing or a data directory that is absent is an
error, not a written value. An empty answer keeps the current value.

Two properties are deliberate:

- it writes `AUTO_TRADE_ENABLE_EXECUTION=false` and has no answer that can change
  it, so a fresh configuration is never the reason a final control is reachable;
- it does not replace an env file wholesale. Keys the wizard never asks about,
  such as `AUTO_TRADE_STRATEGY` and `AUTO_TRADE_HTTP_SIGNAL_TOKEN`, are
  preserved, and a managed key that already holds a different value is refused
  unless `--overwrite` is given.

## Windows executable

```powershell
.\scripts\build-exe.ps1
.\scripts\build-exe.ps1 -SkipTests
```

The script runs the test suite first, creates a throwaway virtual environment in
`.build`, installs the build requirements, runs PyInstaller against
`packaging\auto-trade.spec`, and copies the operator-facing files (the MT5
indicator, `install-position-reader.ps1`, the documentation, the licence) next to
the executable. It then checks that the expected files exist and fails loudly
otherwise, because an incomplete build does not report itself at start-up.

`auto-trade.spec` freezes `packaging\launcher.py` rather than
`auto_trade\__main__.py`: a frozen build runs the entry script as a top-level
file with no parent package, so the relative import in `__main__` cannot work.
The dashboard page is declared as package data, and the MT5 automation stack
(`pywinauto`, `comtypes`, `pywin32`) is named explicitly because it is imported
lazily and is not discovered by analysis.

Smoke test a build before trusting it:

```powershell
.\dist\auto-trade\auto-trade.exe diagnostics
.\dist\auto-trade\auto-trade.exe diagnostics-bundle
.\dist\auto-trade\auto-trade.exe dashboard
.\dist\auto-trade\auto-trade.exe api --print-token
```

A build that cannot pass those commands is not a working build. The last one
proves the `api` command is in the frozen build without starting a listener:
`--print-token` prints a token and exits, and starting the server needs
`AUTO_TRADE_API_TOKEN` set or `--token` passed.

## Installer

```powershell
.\scripts\build-installer.ps1
.\scripts\build-installer.ps1 -Iscc "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
```

`packaging\installer.iss` is an Inno Setup 6 definition. It installs into
`{autopf}\auto-trade` without administrator rights, registers no service, adds no
firewall rule, and runs exactly one thing after installation: `diagnostics`. The
post-install step is a read.

`scripts\build-installer.ps1` refuses to run when `dist\auto-trade` is missing,
so an installer cannot be produced around an empty program folder.

## Verified state of this build

Recorded honestly, because a build claim without a run is not a claim:

- **PASS:** the executable was built on Windows with PyInstaller 6.22 and runs.
- **PASS (executable):** `diagnostics`, `diagnostics-bundle`, `make-signal`,
  `dry-run --mock`, and `configure` all produce the expected output or the
  expected refusal.
- **PASS (executable):** `dashboard` serves the real page and `/api/status` from
  the frozen build, which proves the package data was collected.
- **PASS (executable):** `configure` refuses to write when the configured
  terminal path does not exist, which is the fail-closed path.
- **NOT RUN — installer:** Inno Setup 6 is not installed on this machine, so
  `installer.iss` was never compiled. The definition is unverified.
- **NOT RUN — MT5 automation from the executable:** the `pywinauto` and
  `comtypes` imports are declared, but no MT5 terminal exists on this machine, so
  UI automation was never exercised from the frozen build.
- **DEVIATION:** the build used the only interpreter available here, Python
  3.13.12 embeddable, while the documented development baseline is Python 3.12.
  Rebuild on 3.12 before treating a release artifact as validated.
