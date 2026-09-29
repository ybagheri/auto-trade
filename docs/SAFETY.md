# Safety

Auto Trade is not financial, broker, or execution advice. It can create orders when a future real adapter is enabled, so safety is part of the execution contract.

## Non-negotiable distinctions

- A signal is not a decision.
- A validated request is not a UI click.
- A UI click is not broker acceptance.
- Broker acceptance is not a verified position.

## Current controls

- Dry-run is enabled by default.
- Demo-only policy is enabled by default.
- The real MT5 adapter is unavailable in this phase.
- Kill switch rejects new execution.
- Symbol whitelist rejects unknown symbols.
- Maximum volume is enforced before order preparation.
- Signal expiration and duplicate IDs are enforced.
- Orders per minute are rate-limited.
- Every state transition and result is audited.
- Unknown execution is never treated as success.
- No network endpoint can place, modify, or close an order. Neither the
  dashboard nor the [local API](API.md) has one, and the local API refuses a
  route that would, with a reason naming the CLI.
- The local API requires a token on every route, reads included, and refuses the
  token in a query string. It binds loopback only.
- A signal `id` is validated before it is used as a file name, and a fetched
  signal is refused if its path would resolve outside the signal directory. See
  [security review](SECURITY_REVIEW.md).
- Live execution is refused when the file that enabled it is not the reviewed
  project checkout's. Setting the variable in the shell still works.
- `diagnostics` reports which env file supplied the settings and whether a person
  chose it.

## Future controls

Before enabling a real action, implement durable idempotency, terminal/account identity checks, confirmation policy enforcement, position verification, restart recovery, and an emergency stop. Never infer demo status from a button click or a title alone.

If any state is ambiguous, stop. Do not retry automatically.

[فارسی](fa/SAFETY.md) · [signal protocol](SIGNAL_PROTOCOL.md) · [traceability](TRACEABILITY.md)
