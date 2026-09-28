# Recovery

The application writes `logs/idempotency.json` as a durable execution ledger. Each signal ID maps to one execution attempt and result.

## Rules

- A signal already present in the ledger is never automatically retried.
- A requested attempt left behind by a crash remains `REQUESTED` and requires operator review.
- An unknown result is not overwritten by a later duplicate attempt.
- A different execution ID cannot replace an existing ledger entry.
- A corrupt or unreadable ledger fails closed with `UNKNOWN_EXECUTION`.

The ledger is local operational data and is not a substitute for broker-side position verification. Operators must compare pending records with the MT5 demo account before clearing or resolving them.

## Reviewing

```powershell
python -m auto_trade recovery
```

The command is read-only. It lists `pending`, `unknown`, and `reconciled` records.

## Settling an attempt the application could not prove

A click that could not be corroborated is recorded as `UNKNOWN`, and the
application cannot prove it later on its own. A person can: they look at the
account. `reconcile` records that assertion.

```powershell
python -m auto_trade reconcile <signal-id> --observed "what you saw on the account"
```

What it does and deliberately does not do:

- it requires the observation text, so a record cannot be settled silently;
- it refuses a signal with no record, and refuses any record that is already
  `ACCEPTED`, `REJECTED`, `CLOSED`, or `DRY_RUN`, because such a record is not in
  doubt and rewriting it would erase a settled outcome;
- it keeps `original_status` and `original_message` beside the new ones, so the
  history of what the application actually knew is not lost;
- it writes `RECONCILED` / `RECONCILED_BY_OPERATOR` and a message that says
  `operator-reconciled, not observed by this application`, because nobody should
  read the record later as if this software had verified the outcome;
- it appends an audit event with the operator's text;
- it may be run again on the same record, so a correction is possible.

`recovery` then lists the record under `reconciled` rather than `unknown`.

No automatic recovery action is provided, and none is planned: every path that
changes an account in this project is operator-initiated and independently
observed.
