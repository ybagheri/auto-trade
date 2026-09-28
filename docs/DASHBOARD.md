# Dashboard

A local, read-only status dashboard with an emergency stop. It is served by the
Python standard library only, so the project keeps its zero-runtime-dependency
design and the page has no external assets.

```powershell
python -m auto_trade dashboard --port 8765
```

The control token is printed on startup and generated when `--token` is omitted.

## Why not a desktop GUI toolkit

The project targets a plain `python -m auto_trade` install with no third-party
runtime dependencies, and a native toolkit would either break that or force a
weighted dependency for a status view. Serving a single local page keeps the
installation unchanged and works over the tooling that is already present.

## Safety properties

**Loopback only.** `build_server` refuses any bind address that is not
`127.0.0.1`, `::1`, or `localhost`, because the dashboard can activate the kill
switch. There is no flag to override this; expose the dashboard through an SSH
tunnel or a proxy with its own authentication if remote access is genuinely
required.

**Token-guarded mutations.** Every `POST` endpoint requires `X-Auto-Trade-Token`,
or a `token` query parameter, compared with `hmac.compare_digest`. Missing or
wrong tokens get `403` and change nothing. `GET` endpoints are read-only and need
no token, but they do expose the configured terminal paths, so the server should
still be treated as sensitive.

**No trading capability.** The dashboard has no endpoint that places, modifies,
or closes an order. The only mutating routes are `/api/emergency-stop` and
`/api/resume`. Execution stays in the CLI and the workflow.

**Response hardening.** JSON replies set `Cache-Control: no-store` and
`X-Content-Type-Options: nosniff`. The page sets a `Content-Security-Policy` of
`default-src 'none'` with only inline style and script, so it cannot load a
remote asset even if the HTML were tampered with. Request bodies are capped at
64 KiB and parsed defensively.

## The emergency stop is durable

`KillSwitch` in `domain/protocols.py` is in-memory and therefore only protects
the workflow instance that owns it, which makes it useless as an emergency stop:
a second session or a restarted process would not see it. `FileKillSwitch`
records the stop in a sentinel file, by default `logs/KILL_SWITCH`, so it is
shared by every process using the same log directory and survives a crash.

`ExecutionWorkflow` is now constructed with a `FileKillSwitch`, so a stop raised
from the dashboard blocks a `dry-run` started from a separate shell. The CLI also
drains `main()`'s return value, so a blocked run exits non-zero instead of
looking successful to a scheduler.

## Timing is a description, not a verdict

The Timing section renders a dash, never `0 ms`, for a phase that was not
measured. A dry run never uses a final control, so its click phases have no
measurement; showing zero there would read as an instantaneous trade.

The figures are derived from the audit log rather than held in the server's
memory, so a run that crashed between the click and the observation is still
counted, and the page says so when the underlying log tail is truncated. No
figure on this page reports a trade as accepted, because nothing in this
application observes broker acceptance; the ledger settles an outcome. See
[metrics](METRICS.md).

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/` | dashboard page |
| GET | `/api/health` | liveness and kill switch state |
| GET | `/api/status` | terminal paths, safety flags, counts |
| GET | `/api/risk` | whitelist and risk limits |
| GET | `/api/positions` | position observation status, or a reason it is unavailable |
| GET | `/api/signals` | pending signal files |
| GET | `/api/executions` | ledger records, newest first |
| GET | `/api/metrics?tail=N` | counters and per-phase latency, N capped at 5000 |
| GET | `/api/logs?tail=N` | audit log tail, N capped at 5000 |
| POST | `/api/emergency-stop` | activate the durable stop (token) |
| POST | `/api/resume` | clear the stop (token) |

## Position data

Position values come from the read-only indicator snapshot, not from the owner-drawn
MT5 Trade grid. The endpoint returns `UNAVAILABLE` with the reason when the
snapshot is missing or stale, so “no positions” and “cannot see positions” stay
distinguishable. The dashboard never opens or drives the MT5 window.

## Tests

`tests/unit/test_dashboard.py` covers loopback enforcement, token rejection,
durability of the stop across instances, and the read-only endpoints. It binds
port 0 on loopback only, so it needs no MT5 and no fixed port.

[فارسی](fa/DASHBOARD.md) · [metrics](METRICS.md) · [recovery](RECOVERY.md)
