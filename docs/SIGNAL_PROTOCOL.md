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

Exactly one source is used per run. If more than one is configured, the
application refuses instead of choosing by precedence: an operator who set two
of them has not decided which one is authoritative, and a signal must never
arrive from a source nobody is watching.

Every source is a client or a reader. None of them listens, none of them exposes
an execution API, and every source's output is an ordinary pending signal that
still has to pass the risk engine, the kill switch, and every other gate.

### Local files

`AUTO_TRADE_SIGNAL_DIR` holds `*.json` files. The provider removes a file only
after it parses, so an invalid or half-written file stays for inspection.

### MT5 bridge files

`MT5BridgeSignalProvider` reads `auto_trade_signal_*.json` from
`<data dir>\MQL5\Files`, which is the only place an MQL5 program can write
without any API of ours. The file format is the same signal object as above; a
file is removed only after it parses, and the position reader's
`auto_trade_positions_*.json` snapshots are never mistaken for signals.

MQL5's `Common` directory is deliberately not used: it is shared by every
terminal on the machine, so a file there cannot be attributed to one instance.

The writer is not part of this repository. An MQL5 program that proposes trades
is the operator's own code, and nothing on the Python side executes it. Trust
extends exactly as far as the payload: it is parsed as data and never evaluated.

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

### Authenticated named pipe

`AUTO_TRADE_PIPE_SIGNAL_NAME` and `AUTO_TRADE_PIPE_SIGNAL_TOKEN` open a local
Windows named pipe and read newline-delimited JSON: the first line is
`{"auth": "<token>"}`, every later line is one signal.

- the name must start with `\\.\pipe\`. A UNC name such as
  `\\host\pipe\name` would carry signals over the network and is refused;
- the first line must authenticate, which is what distinguishes the configured
  writer from a local process that created the pipe first;
- a line that exceeds 64 KiB without a newline is rejected rather than buffered;
- a disconnect is reported as "no signal pending" instead of an OS error.

The boundary is the pipe's own security descriptor, which this application cannot
inspect; the writer's pipe must therefore grant access deliberately rather than
by default. Opening a pipe blocks until a writer connects, so `fetch-signal`
waits by design. Run the pipe source from a process that expects a writer rather
than from an interactive prompt.

### Authenticated localhost WebSocket

`AUTO_TRADE_WS_SIGNAL_URL` and `AUTO_TRADE_WS_SIGNAL_TOKEN` connect to a
loopback WebSocket endpoint and read one signal per text message. The first
message must be `{"auth": "<token>"}`.

The client is a small, strict RFC 6455 implementation written in this project
rather than a dependency, and it refuses:

- anything but `ws://` on a loopback host. `wss://` is refused rather than
  half-implemented, so the source cannot be pointed at a network endpoint;
- a wrong handshake accept key, a refused upgrade, or a server that masked a
  frame;
- a binary message, a continuation that never started, a new message started
  before the previous one finished, a fragmented control frame, a reserved bit,
  and a message beyond the frame or message size limit;
- a peer that cannot present the token, which is the defence against a local
  process that binds the port before the real endpoint does.

A ping is answered, a close is reported as "no signal pending", and a peer that
has the token can still only propose a signal.

### Secret handling

Every token is read from the environment, is never printed by `diagnostics`, is
never written to the audit log, and must not be committed. `diagnostics` reports
only whether a token is configured, plus the endpoint without credentials,
query, or fragment.

## Validation and safety

A signal is normalized before anything else looks at it. The risk engine then checks whitelist, volume, expiration, duplicate IDs, rate, connection, and position limits. A signal is never retried automatically after an unknown execution state.

**The `id` is validated too, because this project uses it as a file name.** It must
start with a letter or digit and contain only letters, digits, dot, dash, and
underscore. A source can therefore never choose a path, only a name; an id of
`../../x` is rejected as an invalid signal rather than written outside the signal
directory. The two places that write a fetched or proposed signal resolve the path
and refuse it unless it is a file directly inside the signal directory, so the
rule holds even if the id rule is ever widened. This was a real finding in the
[security review](SECURITY_REVIEW.md), not a hypothetical.

## Duplicate prevention and expiration

A signal ID is recorded in the durable execution ledger when order preparation reaches `ORDER_READY`, and it is replayed on startup, so a duplicate is rejected across process restarts and not only within one workflow instance. A signal expires at its explicit `expiration`, or at `timestamp + expiration_seconds` when no explicit expiration exists.

## Network exposure

No provider in this project opens a network listener, and no endpoint can place
an order. The HTTP and WebSocket sources are clients: they connect to a loopback
endpoint only, require authentication, and refuse anything that would move the
session elsewhere. The named-pipe source opens a pipe that somebody else created.
Any future provider must keep the same properties and must not weaken them to
gain connectivity; in particular, `wss` and any non-loopback address are out of
scope until they are implemented properly rather than approximated.

## Errors

Malformed JSON, unsupported actions, missing fields, invalid numbers, invalid timestamps, and non-positive volumes are rejected before execution. Errors must be recorded without secrets.

[فارسی](fa/SIGNAL_PROTOCOL.md) · [safety](SAFETY.md) · [recovery](fa/RECOVERY.md)
