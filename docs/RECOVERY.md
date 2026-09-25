# Recovery

The application writes `logs/idempotency.json` as a durable execution ledger. Each signal ID maps to one execution attempt and result.

## Rules

- A signal already present in the ledger is never automatically retried.
- A requested attempt left behind by a crash remains `REQUESTED` and requires operator review.
- An unknown result is not overwritten by a later duplicate attempt.
- A different execution ID cannot replace an existing ledger entry.
- A corrupt or unreadable ledger fails closed with `UNKNOWN_EXECUTION`.

The ledger is local operational data and is not a substitute for broker-side position verification. Operators must compare pending records with the MT5 demo account before clearing or resolving them. No automatic recovery action is currently provided.

Use `python -m auto_trade recovery` to review pending and unknown records. The command is read-only.
