"""Latency and counters derived from the audit trail.

The audit log is already structured JSONL, so it is the only place in this
project that holds a record of what happened and when, and it is the only one
that survives a crash. Metrics are therefore *derived* from it rather than
collected in memory: an in-process counter would report an empty, healthy
summary for exactly the run that died between the click and the observation,
which is the one run whose timing matters most.

Nothing here is a health signal on its own. A slow observation is not a
failure, and a fast one is not a success: an execution is only settled by the
independent observation recorded in the ledger, and these numbers describe that
path rather than judging it. See [recovery](RECOVERY.md) for the record a crash
leaves, and docs/METRICS.md for what each figure means.

Every figure is computed over the events that were *read*. A truncated log
produces a partial summary, and the summary says so, because a count that
quietly describes half the history is worse than no count at all.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# The state pairs that bound each phase of a guarded execution, in the order
# they occur. Durations are measured between the two recorded states, so they
# describe the application and not the broker: no event in this project marks
# the moment the broker accepted an order.
PHASES: tuple[tuple[str, str, str], ...] = (
    ("validation", "SIGNAL_RECEIVED", "VALIDATED"),
    ("preparation", "VALIDATED", "ORDER_READY"),
    ("click_to_detection", "EXECUTING", "EXECUTION_DETECTED"),
    ("observation", "EXECUTION_DETECTED", "VERIFYING"),
    ("click_to_outcome", "EXECUTING", "RESULT"),
    ("total", "SIGNAL_RECEIVED", "RESULT"),
)

# States from which a final control has been used. An execution that reached one
# of these and produced no result is an attempt nobody has looked at yet, which
# is the only class of record an operator must review by hand.
_POST_CLICK_STATES = frozenset({"EXECUTING", "EXECUTION_DETECTED", "VERIFYING"})


@dataclass(frozen=True)
class LatencySummary:
    """Count, spread and central tendency of one phase, in milliseconds.

    ``percentiles`` is empty rather than zero-filled when there is nothing to
    measure, so an unmeasured phase can never be read as an instantaneous one.
    """

    count: int = 0
    min_ms: float | None = None
    mean_ms: float | None = None
    p50_ms: float | None = None
    p95_ms: float | None = None
    max_ms: float | None = None

    @property
    def measured(self) -> bool:
        return self.count > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "measured": self.measured,
            "min_ms": _round(self.min_ms),
            "mean_ms": _round(self.mean_ms),
            "p50_ms": _round(self.p50_ms),
            "p95_ms": _round(self.p95_ms),
            "max_ms": _round(self.max_ms),
        }


@dataclass(frozen=True)
class ExecutionMetrics:
    """Counters and phase latency for the audit events that were read."""

    events: int = 0
    executions: int = 0
    results_by_status: Mapping[str, int] = field(default_factory=dict)
    executions_by_final_state: Mapping[str, int] = field(default_factory=dict)
    unresolved: int = 0
    unresolved_execution_ids: tuple[str, ...] = ()
    unparseable_timestamps: int = 0
    non_monotonic_intervals: int = 0
    truncated: bool = False
    latency: Mapping[str, LatencySummary] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": "audit-log",
            "note": (
                "Derived from the audit events that were read. A click is an "
                "action; only the ledger settles an outcome, and no figure here "
                "reports a trade as accepted."
            ),
            "events": self.events,
            "executions": self.executions,
            "truncated": self.truncated,
            "counters": {
                "results_by_status": dict(sorted(self.results_by_status.items())),
                "executions_by_final_state": dict(
                    sorted(self.executions_by_final_state.items())
                ),
                # Attempts that used a final control and recorded no result.
                # Each one requires an operator to look at the account.
                "unresolved_attempts": self.unresolved,
                "unresolved_execution_ids": list(self.unresolved_execution_ids),
            },
            "data_quality": {
                "unparseable_timestamps": self.unparseable_timestamps,
                # A clock that moved backwards between two recorded states. The
                # interval is counted as zero rather than as a negative time.
                "non_monotonic_intervals": self.non_monotonic_intervals,
            },
            "latency_ms": {name: summary.to_dict() for name, summary in self.latency.items()},
        }


def summarize(
    events: Iterable[Mapping[str, Any]],
    *,
    truncated: bool = False,
) -> ExecutionMetrics:
    """Summarize parsed audit events.

    Events are grouped by ``execution_id``. An event that cannot be grouped,
    timed, or interpreted is counted in ``data_quality`` and never silently
    dropped, so a summary that cannot be trusted says why.
    """
    collected = list(events)
    grouped: dict[str, list[tuple[datetime, str, str]]] = {}
    results: dict[str, str] = {}
    unparseable = 0
    total = 0

    for event in collected:
        if not isinstance(event, Mapping):
            total += 1
            unparseable += 1
            continue
        execution_id = str(event.get("execution_id") or "")
        event_type = str(event.get("event_type") or "")
        state = str(event.get("state") or "")
        if not execution_id:
            # A record with no execution id cannot be attributed to a run, so it
            # belongs to no phase and is reported only as an uninterpretable line.
            total += 1
            unparseable += 1
            continue
        moment = _timestamp(event.get("timestamp"))
        total += 1
        if moment is None:
            unparseable += 1
            continue
        if event_type == "result":
            # The result event carries the settled state, which is what an
            # execution's phase durations are measured up to.
            results[execution_id] = state
            grouped.setdefault(execution_id, []).append((moment, "RESULT", state))
            continue
        if state:
            grouped.setdefault(execution_id, []).append((moment, state, state))

    intervals, non_monotonic = _intervals(grouped)
    latency = {
        name: _summarize(intervals.get(name, [])) for name, _, _ in PHASES
    }
    finals: dict[str, int] = {}
    unresolved: list[str] = []
    for execution_id, points in grouped.items():
        final = results.get(execution_id) or points[-1][1]
        finals[final] = finals.get(final, 0) + 1
        if final not in _POST_CLICK_STATES and final != "RESULT":
            continue
        if execution_id in results:
            continue
        unresolved.append(execution_id)

    by_status: dict[str, int] = {}
    for state in results.values():
        by_status[state] = by_status.get(state, 0) + 1

    return ExecutionMetrics(
        events=total,
        executions=len(grouped),
        results_by_status=by_status,
        executions_by_final_state=finals,
        unresolved=len(unresolved),
        unresolved_execution_ids=tuple(sorted(unresolved)),
        unparseable_timestamps=unparseable,
        non_monotonic_intervals=non_monotonic,
        truncated=truncated,
        latency=latency,
    )


def _intervals(
    grouped: Mapping[str, Sequence[tuple[datetime, str, str]]],
) -> tuple[dict[str, list[float]], int]:
    """Measure every phase across every execution.

    The first occurrence of a state wins, because the state machine cannot
    revisit a state within one execution, and the first recorded moment of it is
    when the application entered it.
    """
    collected: dict[str, list[float]] = {name: [] for name, _, _ in PHASES}
    non_monotonic = 0
    for points in grouped.values():
        ordered = sorted(points, key=lambda point: point[0])
        entered: dict[str, datetime] = {}
        for moment, state, _ in ordered:
            entered.setdefault(state, moment)
        for name, start, end in PHASES:
            begin = entered.get(start)
            finish = entered.get(end)
            if begin is None or finish is None:
                continue
            seconds = (finish - begin).total_seconds()
            if seconds < 0:
                # The wall clock moved backwards. Reported rather than smoothed
                # over, and the interval contributes nothing.
                non_monotonic += 1
                continue
            collected[name].append(seconds * 1000.0)
    return collected, non_monotonic


def _summarize(samples: Sequence[float]) -> LatencySummary:
    if not samples:
        return LatencySummary()
    ordered = sorted(samples)
    return LatencySummary(
        count=len(ordered),
        min_ms=ordered[0],
        mean_ms=sum(ordered) / len(ordered),
        p50_ms=_percentile(ordered, 0.50),
        p95_ms=_percentile(ordered, 0.95),
        max_ms=ordered[-1],
    )


def _percentile(ordered: Sequence[float], fraction: float) -> float:
    """Nearest-rank percentile, so a reported value is always a real sample."""
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 1)
