# Position Observer

Independent position observation is the gate on live execution. The observer is a
read-only MT5 Service that publishes the terminal's own open positions to a file
that the bridge reads.

## Why an observer service instead of the UI

The Trade grid in MT5 is owner-drawn. Measured on the Alpari MT5 demo build, its
cell text is not reachable by any of the three Windows accessibility paths:

| Path | Result |
| --- | --- |
| UI Automation (`List` AutomationId `10328`) | structure, column count and headers resolve; every cell `Name` is empty |
| Win32 `LVM_GETITEMTEXT` on `SysListView32` | headers resolve; every row and subitem returns an empty string |
| MSAA / `IAccessible` | the list exposes rows but no cell names |

This is a property of how MT5 draws the grid, not a defect in this project. The
column headers are readable and are `Symbol, Ticket, Time, Type, Volume, Price,
S / L, T / P, Price, Profit`, but the values are not. OCR was rejected because it
would require guessing, and guessing is exactly what this project must not do.

The observer therefore uses the alternative the design already called for: a
separate observation path that is not the desktop UI being driven.

## Safety properties

`mql5/Services/AutoTradePositionObserver.mq5` contains no `OrderSend`, no trade
request, and no position modification call. It only calls `PositionsTotal`,
`PositionGetTicket` and `PositionGetDouble`/`PositionGetString`. A snapshot is
therefore evidence of terminal state that is independent of the request path, so
verification is not circular.

## Install

```powershell
.\scripts\install-observer.ps1 -DataPath "<terminal data dir>"
```

This copies the source into `<data dir>\MQL5\Services` and compiles it with
`MetaEditor64.exe`. The script fails if compilation does not produce an `.ex5`.

## Start it: attach it to a chart

In the terminal: **Navigator → Services → AutoTradePositionObserver → right click →
Attach to Chart**, then confirm with `OK` in the dialog that appears.

### Why a chart, and not `Add Service`

The MQL5 Service route does not work on this terminal build, and the reason is
worth recording so it is not retried blindly.

- With `#property service` in the source, MetaEditor compiles a **script**
  (`warning 51: no OnStart function defined in the script`). The Navigator then
  offers the service menu (`Add Service`, `Start All`, `Stop All`), the entry is
  written to `config\services.ini` with `enabled=1`, and the terminal log reports
  `service 'AutoTradePositionObserver' started` immediately followed by
  `service 'AutoTradePositionObserver' stopped` about 10 ms later. `OnInit` never
  runs and no snapshot is produced.
- Without the property, MetaEditor compiles a clean Expert Advisor
  (`0 errors, 0 warnings`) and the Navigator offers `Attach to Chart`. Attaching
  it runs `OnInit`, `EventSetTimer` succeeds, and snapshots appear within a
  second.

So the observer is shipped as an Expert Advisor that lives in the `Services`
folder and is attached to a chart. Do not add `#property service` back: it turns
the program into a script, which is the configuration that fails to initialise.

### Consequences

The observer only runs while the chart it is attached to is open, and it must be
re-attached after a terminal restart. This is acceptable because the reader fails
closed on staleness: a snapshot older than the limit is treated as
`UNAVAILABLE`, never as "no positions". A stopped observer can therefore never be
mistaken for an empty account.

Leave the chart open on a quiet symbol; the program only reads positions.

## Snapshot format

Written to `<data dir>\MQL5\Files`, alternating between
`auto_trade_positions_a.json` and `auto_trade_positions_b.json`:

```json
{
  "schema": 1,
  "sequence": 412,
  "complete": true,
  "written_at": "2026-09-26T12:00:00Z",
  "account": 53145727,
  "server": "Alpari-MT5-Demo",
  "terminal_build": 6184,
  "positions": [
    {
      "ticket": 1234567,
      "symbol": "BITCOIN",
      "type": "BUY",
      "volume": 0.01000000,
      "price_open": 60000.5,
      "sl": 0.0,
      "tp": 0.0,
      "profit": 0.0,
      "magic": 0,
      "opened_at": "2026-09-26T11:58:03Z"
    }
  ]
}
```

Timestamps are ISO 8601. MQL5's usual dotted date form (`2026.09.26T12:00:00Z`) is
also accepted by the reader, because the observer is a separate component whose
exact build is not controlled at runtime.

A reader can never observe a half-written document: the new file is written in
full and only then is the previous one deleted, so at most one file exists, and
`complete` is present in every finished write.

## Diagnostics

The observer also appends to `<data dir>\MQL5\Files\auto_trade_observer.log`,
because MQL5 program logging can be switched off in terminal options and its
absence would otherwise be indistinguishable from the program never running.

## Fail-closed behaviour

`MT5FilePositionSnapshotProvider` raises `PositionSnapshotUnavailable` rather than
returning a partial or inferred result when the snapshot is missing, unreadable,
truncated, of an unknown schema, missing `complete`, older than the staleness
limit (30s by default, which also detects a stopped service), or containing a
position entry that fails domain validation.

`MT5DesktopAdapter` captures a position baseline at the end of `prepare_order`,
which is the last moment before a final execution control. A baseline that cannot
be observed is recorded as an error, never as an empty account, so verification
can never succeed by comparing against positions that were not actually seen.

`verify_execution` returns `ACCEPTED` only when exactly one new position matches
the requested symbol, side and volume. No match, several matches, a missing
baseline, or an unreadable snapshot all return `UNKNOWN`.

## Checking it

```powershell
python -m auto_trade position-snapshot
```

`AVAILABLE` with a position list means the observer is running and the bridge can
read it. `UNAVAILABLE` with a reason means it is not, and the message says which
condition failed.
