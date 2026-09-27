# Traceability Inventory

This project leaves local artifacts and creates ordinary broker-visible trade records. It does not claim to conceal automation and does not use an MQL5 program or `OrderSend` to place orders.

## Local artifacts

| Artifact | Location | Purpose |
| --- | --- | --- |
| Signal files | `signals\*.json` | pending local requests |
| Audit log | `logs\audit.log` | state transitions, refusals, results |
| Execution ledger | `logs\idempotency.json` | restart-safe duplicate prevention |
| Kill-switch sentinel | `logs\KILL_SWITCH` | durable emergency stop |
| Local configuration | `.env` | machine-specific paths and safety flags |

These files are local. They are not transmitted by this project.

## Broker-visible records

A UI-placed order creates the normal MT5 trade record: symbol, side, volume, time, price, and account history. The application does not set an MQL5 magic number because it does not place the order through an MQL5 program.

## Behavioural traces

Timing, regularity, latency, and repeated symbol/volume choices can be correlated by a provider independently of local files. Removing local logs does not change those properties.

## Unknowns

Whether a broker or account provider distinguishes terminal-placed orders, and whether a particular account's terms permit this use, cannot be determined from the client. Users must confirm permissions with the broker, prop firm, or account provider before trading.

## Compliance position

Automated trading and desktop automation may be restricted. This project does not claim that UI automation is “manual trading” and does not claim that any provider permits or forbids this architecture.
