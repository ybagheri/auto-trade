# Local API

A token-authenticated, loopback-only, read-only HTTP API for programs on this
machine. It is served by the Python standard library only, so the project keeps
its zero-runtime-dependency design.

```powershell
$env:AUTO_TRADE_API_TOKEN = "<token>"
python -m auto_trade api --port 8766
```

`python -m auto_trade api --print-token` prints a freshly generated token for an
operator who has not configured one yet.

## Why this exists and what it is not

The [dashboard](DASHBOARD.md) serves a person who opened a page. This serves
another process: a monitoring script, a status line in another application, a
second operator tool. That difference decides everything below.

**It is not an execution API.** No route here places, modifies, or closes an
order, and none can be made to. An operator who wants an order placed runs the
CLI, which re-runs every gate and requires `--confirm-demo` by hand. See
[execution](EXECUTION.md).

**It is not reachable from the network.** The server refuses any bind address
that is not `127.0.0.1`, `::1`, or `localhost`, and the client refuses any
endpoint that is not an explicit loopback `http`/`https` URL. A lookalike host
such as `localhost.example.com` is refused by literal comparison, not by
suffix. There is no flag to override the bind check; use an SSH tunnel or a
proxy with its own authentication if remote access is genuinely required.

**It is the only local surface where a read needs a token.** The dashboard's
`GET` endpoints are open on loopback, which is acceptable for a page somebody
opened deliberately but not for a program that calls on a schedule. A monitoring
agent reporting "kill switch inactive" or "one unresolved attempt" is a status
feed, and an unauthenticated one can be read, or spoofed, by anything else
running as any user on the machine.

## Safety properties

**Every route requires the token, reads included.** A missing or wrong token
gets `401` and the request changes nothing. Authentication is checked *before*
routing, so an unauthenticated caller cannot learn which routes exist by reading
the difference between a `401` and a `404`.

**The token is refused in a query string.** `?token=...` gets `400`. A URL is
written to proxy logs, browser history, and `Referer` headers. The dashboard
tolerates the query form because a hand-written fetch from a browser cannot
always set a header; a program can, so this surface has no such excuse. The
client sends it in the `X-Auto-Trade-Token` header and nowhere else.

**The token is compared without an early exit**, using the same
`constant_time_equals` the WebSocket and named-pipe sources use, so a caller
cannot learn a prefix by timing.

**A token is mandatory.** `build_api_server` refuses to start without one,
rather than generating a random token nobody can read, which would be a service
that quietly answers `401` forever. An empty `AUTO_TRADE_API_TOKEN` does not
mean "no authentication"; it means the command exits with an error.

**An account-changing route is refused with a reason, not a bare `404`.** A
caller that guesses `/execute` gets `403` naming the CLI as the route that still
exists. The point is that a caller learns the boundary instead of trying another
verb until something answers.

**A refused request leaves the connection usable.** Request bodies are drained
before any reply, including refusals and unknown routes, because an unread body
stays in the socket buffer and desynchronises the next keep-alive request on the
same connection.

**Control actions are audited.** Both directions write a `local-api` audit
record, and neither contains the token. The dashboard does not audit its own
control actions; this surface does, because the *reset* is the action worth
watching — it is the one that removes a stop.

## Endpoints

All routes are under `/api/v1/` and all of them require the header.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/v1/health` | liveness and kill switch state |
| GET | `/api/v1/status` | terminal paths, safety flags, counts |
| GET | `/api/v1/risk` | whitelist and risk limits |
| GET | `/api/v1/positions` | position observation status, or a reason it is unavailable |
| GET | `/api/v1/signals` | pending signal files |
| GET | `/api/v1/executions` | ledger records, newest first |
| GET | `/api/v1/metrics?tail=N` | counters and per-phase latency, N capped at 5000 |
| GET | `/api/v1/logs?tail=N` | audit log tail, N capped at 5000 |
| POST | `/api/v1/emergency-stop` | activate the durable stop |
| POST | `/api/v1/resume` | clear the stop |

There is deliberately no `POST /api/v1/signals`. A read route answers `405` to
a `POST` rather than writing anything, so a monitoring client cannot become a
signal source by changing one method.

Every read is served by the same `StatusReporter` the dashboard uses, so the two
surfaces cannot disagree about what they report. Nothing here opens the MT5
window or drives it.

## The client

`LocalApiClient` in `infrastructure/api_client.py` exists so a caller does not
re-implement the three rules that make the call safe.

```python
from auto_trade.infrastructure.api_client import LocalApiClient

with LocalApiClient("http://127.0.0.1:8766/api/v1", token) as client:
    print(client.status()["safety"]["kill_switch_active"])
    print(client.metrics(tail=500)["counters"]["unresolved_attempts"])
```

It is a *reader*. It has no method that places, modifies, or closes an order,
and the server refuses those routes regardless. A `401` or `403` is reported as
"the token was rejected" rather than as an outage, so a caller is not taught to
retry. Redirects that would leave loopback are refused rather than followed,
which is the same shared policy the signal provider uses, so the two cannot
disagree about it.

## What these responses are not

A `200` from `/api/v1/status` means the request was authorised and the state was
read. It does not mean the terminal was reachable, that the account is a demo,
or that anything is healthy. `/api/v1/positions` returns `UNAVAILABLE` with a
reason when the snapshot is missing or stale, so "no positions" and "cannot see
positions" stay distinguishable. `/api/v1/metrics` reports an unmeasured phase
as `null` with `measured: false`, never as zero. No figure on this API reports a
trade as accepted: nothing in this application observes broker acceptance, and
the ledger settles an outcome. See [metrics](METRICS.md) and
[recovery](RECOVERY.md).

## Tests

`tests/unit/test_api.py` covers the refusals rather than the happy path alone:
that no route in the read table answers without a token (parametrised over the
table, so a new route cannot be added unauthenticated), that the token is
refused in a query string, that the bind check and the mandatory token hold,
that every account-changing route is refused with a reason, that both control
directions are audited without the token, and that a refused request does not
corrupt a keep-alive connection. It binds port `0` on loopback only, so it needs
no MT5 and no fixed port.

## See also

[فارسی](fa/API.md) · [dashboard](DASHBOARD.md) · [safety](SAFETY.md) ·
[execution](EXECUTION.md) · [configuration](CONFIGURATION.md)
