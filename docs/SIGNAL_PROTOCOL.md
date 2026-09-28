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

## Signal sources

### Local files

`AUTO_TRADE_SIGNAL_DIR` holds `*.json` files. The provider removes a file only
after it parses, so an invalid or half-written file stays for inspection.

### Authenticated localhost HTTP

`AUTO_TRADE_HTTP_SIGNAL_URL` and `AUTO_TRADE_HTTP_SIGNAL_TOKEN` enable
`python -m auto_trade fetch-signal`, which performs one `GET` with
`Authorization: Bearer <token>` and writes the response into the signal
directory. The response body is one signal object, identical to the file format
above.

The provider treats the endpoint as untrusted input and fails closed:

- the URL must use `http` or `https` on a loopback host (`127.0.0.1`, `::1`,
  `localhost`); a lookalike host such as `localhost.example.com` is refused;
- a token is mandatory, and `401` or `403` is reported as a source error rather
  than as an idle source;
- a redirect that would leave loopback is refused instead of being followed, so
  the token is never resent to a host the operator did not configure;
- the response is read with a bounded size and a bounded timeout;
- a body that is not JSON, or JSON that is not a valid signal, is rejected;
- `204`, `404`, and `503` mean "no signal pending", which is not an error.

The token is read from the environment, is never printed by `diagnostics`, is
never written to the audit log, and must not be committed. `diagnostics` reports
only whether a token is configured, plus the endpoint without credentials,
query, or fragment.

This source is read-only. It listens on nothing and it cannot place an order:
the fetched signal is an ordinary pending signal that still has to pass the risk
engine, the kill switch, and every other gate.

## Validation and safety

A signal is normalized before anything else looks at it. The risk engine then checks whitelist, volume, expiration, duplicate IDs, rate, connection, and position limits. A signal is never retried automatically after an unknown execution state.

## Duplicate prevention and expiration

A signal ID is recorded in the durable execution ledger when order preparation reaches `ORDER_READY`, and it is replayed on startup, so a duplicate is rejected across process restarts and not only within one workflow instance. A signal expires at its explicit `expiration`, or at `timestamp + expiration_seconds` when no explicit expiration exists.

## Network exposure

No provider in this project opens a network listener, and no endpoint can place an order. The HTTP source is a client: it connects to a loopback endpoint only, requires authentication, and refuses a redirect that would leave loopback. Any future WebSocket, named-pipe, or MT5 bridge provider must keep the same properties and must not weaken them to gain connectivity.

## Errors

Malformed JSON, unsupported actions, missing fields, invalid numbers, invalid timestamps, and non-positive volumes are rejected before execution. Errors must be recorded without secrets.
