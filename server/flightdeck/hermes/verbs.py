"""Status transitions: the single source of truth for every write Flightdeck makes.

The matrix below was measured, not inferred. ``scripts/spike_matrix.py`` walks every
ordered pair of statuses against the scratch board and regenerates
``docs/transition-matrix.md``; this module encodes what it found.

Three rules came out of that spike, and all three are easy to get wrong:

1. **``running`` is unreachable.** Hermes answers 400 from every source state:
   "Cannot set status to 'running' directly; use the dispatcher/claim path". Only the
   dispatcher may claim a task, via ``BEGIN IMMEDIATE`` plus a compare-and-swap on
   ``claim_lock``. We reject it client-side before any network call.

2. **A 200 does not mean the task reached the status you asked for.** ``review -> todo``
   returns 200 and lands the task in ``ready``, emitting ``review_reopened``. Always
   reconcile from ``response["task"]["status"]``, never from the value you sent. This is
   what :func:`resulting_status` exists for.

3. **``board`` is a query parameter on every endpoint**, including the ones that also
   take a JSON body. Omitting it silently targets the ``default`` board, which during the
   spike produced a baffling "unknown task(s)" 400 on a task that plainly existed.

A 409 means the claim moved under us. Surface it verbatim, refetch, and never auto-retry:
retrying a lost compare-and-swap is fighting the claim protocol rather than observing it.
"""

from __future__ import annotations

from typing import Any, Final

STATUSES: Final[tuple[str, ...]] = (
    "triage",
    "todo",
    "scheduled",
    "ready",
    "running",
    "blocked",
    "review",
    "done",
    "archived",
)

#: Only the dispatcher may put a task here.
DISPATCHER_ONLY: Final[frozenset[str]] = frozenset({"running"})

#: Measured legal transitions, source -> set of targets Hermes accepts.
#: Regenerate with scripts/spike_matrix.py after any Hermes upgrade.
ALLOWED: Final[dict[str, frozenset[str]]] = {
    "triage": frozenset({"todo", "ready", "archived"}),
    "todo": frozenset({"triage", "scheduled", "ready", "archived"}),
    "scheduled": frozenset({"triage", "todo", "ready", "archived"}),
    "ready": frozenset({"triage", "todo", "scheduled", "blocked", "review", "done", "archived"}),
    "blocked": frozenset({"triage", "todo", "scheduled", "ready", "done", "archived"}),
    "review": frozenset({"triage", "todo", "ready", "done", "archived"}),
    "done": frozenset({"triage", "todo", "ready", "archived"}),
    "archived": frozenset({"triage", "todo", "ready"}),
}

#: Transitions Hermes accepts but redirects. Requested target -> where it actually lands.
#: Keyed by (source, requested).
REDIRECTS: Final[dict[tuple[str, str], str]] = {
    # Reopening a review does not drop the task back to the backlog; it re-queues it.
    ("review", "todo"): "ready",
}

#: Targets needing an extra field in the PATCH body.
REQUIRED_FIELDS: Final[dict[str, tuple[str, ...]]] = {
    "blocked": ("block_reason",),
}


class TransitionRejected(ValueError):
    """Refused before any network call, with the reason Hermes would have given."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def validate(source: str | None, target: str) -> None:
    """Raise :class:`TransitionRejected` for a move we know Hermes will refuse.

    ``source`` may be ``None`` when the caller has not read the task first. We then
    check only the rules that hold from every source state, and let Hermes arbitrate
    the rest; its 409 is authoritative anyway, because our SQLite read can lag the
    dispatcher by up to a tick.
    """
    if target not in STATUSES:
        raise TransitionRejected(f"unknown status: {target}")
    if target in DISPATCHER_ONLY:
        raise TransitionRejected(
            f"Cannot set status to {target!r} directly; use the dispatcher/claim path"
        )
    if source is None:
        return
    if source == target:
        raise TransitionRejected(f"task is already {target!r}")
    if source not in ALLOWED:
        return
    if target not in ALLOWED[source]:
        raise TransitionRejected(
            f"status transition to {target!r} not valid from {source!r}",
            status_code=409,
        )


def expected_status(source: str | None, target: str) -> str:
    """Where the task will actually end up, accounting for Hermes' redirects."""
    if source is None:
        return target
    return REDIRECTS.get((source, target), target)


def build_payload(target: str, **extra: Any) -> dict[str, Any]:
    """The PATCH body for a transition, validating any target-specific requirements."""
    payload: dict[str, Any] = {"status": target}
    for field in REQUIRED_FIELDS.get(target, ()):
        value = extra.get(field)
        if not value:
            raise TransitionRejected(f"{target!r} requires a non-empty {field!r}")
        payload[field] = value
    for key, value in extra.items():
        if value is not None and key not in payload:
            payload[key] = value
    return payload


def resulting_status(response_body: Any, requested: str) -> str:
    """Read the true post-write status out of Hermes' response.

    Never trust ``requested``: see rule 2 in the module docstring.
    """
    if isinstance(response_body, dict):
        task = response_body.get("task")
        if isinstance(task, dict) and isinstance(task.get("status"), str):
            return task["status"]
    return requested


def allowed_targets(source: str) -> list[str]:
    """Targets the UI should offer for a task in ``source``, in board-column order."""
    allowed = ALLOWED.get(source, frozenset())
    return [s for s in STATUSES if s in allowed]
