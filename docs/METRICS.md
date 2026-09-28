# Metrics

Execution counters and phase latency, derived from `logs/audit.log`.

```powershell
python -m auto_trade metrics
python -m auto_trade metrics --tail 5000
```

The same summary is served read-only at `GET /api/metrics` on the dashboard and
is written as `metrics.json` inside the diagnostics bundle.

## Why these are derived, not collected

An in-process counter would report a clean, empty, healthy-looking summary for
exactly the run that died between the click and the observation. That is the run
whose timing an operator needs, and it is the one an in-memory counter loses.

The audit log is the only record in this project that survives a crash, so the
summary is computed from it on demand. Two consequences follow, and both are
reported rather than hidden:

- the figures describe the events that were **read**, not the whole history. A
  truncated log sets `truncated: true`.
- a run whose events are no longer in the tail is not in the summary at all.
  `recovery` and the bundle's `executions` section remain the record of record.

## What the numbers mean

| Phase | From | To |
| --- | --- | --- |
| `validation` | `SIGNAL_RECEIVED` | `VALIDATED` |
| `preparation` | `VALIDATED` | `ORDER_READY` |
| `click_to_detection` | `EXECUTING` | `EXECUTION_DETECTED` |
| `observation` | `EXECUTION_DETECTED` | `VERIFYING` |
| `click_to_outcome` | `EXECUTING` | the result record |
| `total` | `SIGNAL_RECEIVED` | the result record |

`click_to_outcome` is the one an operator usually wants: how long the
application took to report anything after the final control was used.

Every duration is measured between two states this application recorded. **No
event in this project marks the moment the broker accepted an order**, so none of
these figures is a measure of fill time. They describe the application, not the
broker.

An unmeasured phase reports `null` for every figure and `"measured": false`. It
never reports zero: a dry run never clicked, and a zero there would read as an
instantaneous trade. The dashboard renders those as a dash for the same reason.

## Counters

- `results_by_status` — the state each execution settled in, counted.
- `executions_by_final_state` — including executions that recorded no result.
- `unresolved_attempts` — **the figure worth acting on.** These are executions
  that used a final control and recorded no result. Each one may have changed an
  account and needs a person to look, through `python -m auto_trade recovery`.
- `unresolved_execution_ids` — which ones, so they can be looked up.

An execution that ended in a refusal (`INVALID_SIGNAL`, `TERMINAL_NOT_FOUND`, …)
is not unresolved: nothing was clicked, so there is no account state to inspect.
An execution that recorded `UNKNOWN` *is* counted as settled, because the
application wrote that record itself; it still needs review, which is what
`recovery` is for.

## Data quality

| Figure | Meaning |
| --- | --- |
| `unparseable_timestamps` | lines with no timestamp, no `execution_id`, or not an object |
| `non_monotonic_intervals` | the wall clock moved backwards between two recorded states |

Neither is smoothed over. An uninterpretable line is counted rather than dropped,
so a summary that cannot be fully trusted says how much of the log it could not
read. A backwards clock produces no interval at all, rather than a negative
duration.

## What these figures are not

They are not a health signal. A slow observation is not a failure and a fast one
is not a success. An execution is settled only by the independent observation
recorded in the ledger, and the summary deliberately reports no figure that
could be read as a trade:

- `results_by_status` counts the *state* an execution ended in, not a fill.
- nothing here reports broker acceptance, because nothing here observes it.
- a click that could not be corroborated is counted as unresolved, which is the
  opposite of a success.

See [recovery](RECOVERY.md) for what a crash leaves behind and how an operator
settles it, and [verification](VERIFICATION.md) for what counts as proof.
