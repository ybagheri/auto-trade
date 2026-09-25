# Signal Protocol

The first protocol is newline-free JSON documents supplied through a local directory. Each file must use the `.json` suffix and contain one signal object.

## Required fields

- `id`: non-empty stable string used for idempotency.
- `timestamp`: ISO-8601 timestamp with an explicit timezone.
- `source`: non-empty provider identifier.
- `symbol`: broker symbol, normalized to uppercase by the application.
- `action`: one of `BUY`, `SELL`, `BUY_LIMIT`, `SELL_LIMIT`, `BUY_STOP`, `SELL_STOP`, `CLOSE`, `MODIFY`, or `CANCEL`.
- `volume`: finite positive decimal number.

## Optional fields

`order_type`, `price`, `stop_loss`, `take_profit`, `comment`, `strategy`, `confidence` from 0 to 1, `expiration`, and `metadata`.

## Example

```json
{
  "id": "signal-123456",
  "timestamp": "2026-09-25T10:30:00Z",
  "source": "price_action_indicator",
  "symbol": "EURUSD",
  "action": "BUY",
  "volume": 0.10,
  "stop_loss": 1.16500,
  "take_profit": 1.17000,
  "comment": "PA reversal",
  "strategy": "price_action",
  "metadata": {}
}
```

## Validation and safety

The provider removes a file only after JSON parsing and signal normalization succeed. The risk engine then checks whitelist, volume, expiration, duplicate IDs, rate, connection, and position limits. A signal is never retried automatically after an unknown execution state.

## Duplicate prevention and expiration

A signal ID is recorded in the workflow after order preparation reaches `ORDER_READY`. A later occurrence is rejected in the same workflow instance. Durable storage across application restarts is a planned feature. A signal expires at its explicit `expiration`, or at `timestamp + expiration_seconds` when no explicit expiration exists.

## Authentication and network exposure

The current file provider has no network listener. Any future HTTP or WebSocket provider must bind to localhost by default, authenticate non-local access, rate-limit requests, and reject unauthenticated public exposure.

## Errors

Malformed JSON, unsupported actions, missing fields, invalid numbers, invalid timestamps, and non-positive volumes are rejected before execution. Errors must be recorded without secrets.
