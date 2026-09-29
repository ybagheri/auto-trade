# Traceability Inventory

This project leaves local artifacts and creates ordinary broker-visible trade records. It does not claim to conceal automation and does not use `OrderSend` to place orders.

## Local artifacts

| Artifact | Location | Purpose |
| --- | --- | --- |
| Signal files | `signals\*.json` | pending local requests |
| Audit log | `logs\audit.log` | state transitions, refusals, results |
| Execution ledger | `logs\idempotency.json` | restart-safe duplicate prevention |
| Kill-switch sentinel | `logs\KILL_SWITCH` | durable emergency stop |
| Position snapshots | `<data dir>\MQL5\Files\auto_trade_positions_*.json` | read-only position evidence |
| Local configuration | `.env` | machine-specific paths and safety flags |
| Diagnostics bundle | a path the operator chooses | a copy of the evidence above, for a report |

The position reader writes snapshots but does not write a custom log and does not send anything over the network. The files are local.

The [local API](API.md) is a loopback listener, which is a network surface even
though it never leaves the machine. Every request to it is recorded in the same
local audit log as everything else, with the route and the outcome and without
the token. A caller on this machine is a local process, not a broker-visible
trace, and nothing it can ask for changes an account.

A diagnostics bundle is a copy of these artifacts, written wherever the operator
points it and therefore shareable. It contains no credential: `.env` is excluded,
the HTTP signal token is reported only as configured or not, and the endpoint URL
is stripped of credentials, query, and fragment. Handing the bundle to someone
else is still a disclosure of terminal paths, symbols, volumes, and timing, so
it should be shared deliberately.

## MT5-visible traces

The read-only indicator is an MQL5 program. Once compiled and attached, MT5 can show it in the Navigator and chart, and the terminal's normal Journal can record its load or attachment. Those are platform behaviours, not a custom log created by this project.

## Broker-visible records

A UI-placed order creates the normal MT5 trade record: symbol, side, volume, time, price, and account history. The position reader does not place or modify that order.

## Behavioural traces

Timing, regularity, latency, and repeated symbol/volume choices can be correlated by a provider independently of local files. Removing local logs does not change those properties.

## Compliance position

Automated trading and desktop automation may be restricted. This project does not claim that UI automation is “manual trading” and does not claim that any provider permits or forbids this architecture. Users must confirm permissions with the broker, prop firm, or account provider.

[فارسی](fa/TRACEABILITY.md) · [safety](SAFETY.md) · [signal protocol](SIGNAL_PROTOCOL.md)
