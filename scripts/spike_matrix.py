"""Phase 0 spike: the complete status transition matrix.

For every ordered pair of statuses, put a fresh task into the source state and attempt
the move, recording success or the exact 4xx. Source states are reached by breadth-first
search from ``triage`` using only transitions already proven legal, so the matrix is
self-bootstrapping and does not depend on guesses about reachability.

Writes ``docs/transition-matrix.md``. That file is simultaneously the verification and
the documentation of ``hermes/verbs.py``.

Every task created here is deleted before exit.

Run:  PYTHONPATH=server .venv/Scripts/python.exe scripts/spike_matrix.py
"""

from __future__ import annotations

import asyncio
import sys
from collections import deque
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from flightdeck.hermes.proxy import HermesClient, HermesError  # noqa: E402

BOARD = "flightdeck-test"

STATUSES = (
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

created: list[str] = []


async def fresh_task(client: HermesClient, title: str) -> str:
    result = await client.post_json(
        "/tasks",
        {"title": title, "body": "matrix spike", "triage": True, "priority": 0},
        board=BOARD,
    )
    task_id = result["task"]["id"]
    created.append(task_id)
    return task_id


async def attempt(client: HermesClient, task_id: str, target: str) -> dict[str, Any]:
    payload: dict[str, Any] = {"status": target}
    if target == "blocked":
        payload["block_reason"] = "matrix spike"
    try:
        response = await client.request(
            "PATCH", f"/tasks/{task_id}", json=payload, params={"board": BOARD}
        )
        return {"ok": True, "status": response.status_code, "detail": None}
    except HermesError as exc:
        return {"ok": False, "status": exc.status_code, "detail": str(exc.detail)}


async def current_status(client: HermesClient, task_id: str) -> str | None:
    try:
        detail = await client.get_json(f"/tasks/{task_id}", board=BOARD)
    except HermesError:
        return None
    return detail["task"]["status"]


async def discover_paths(client: HermesClient) -> dict[str, list[str]]:
    """BFS from triage. Returns status -> the transition sequence that reaches it."""
    paths: dict[str, list[str]] = {"triage": []}
    frontier: deque[str] = deque(["triage"])
    while frontier:
        source = frontier.popleft()
        for target in STATUSES:
            if target in paths:
                continue
            task_id = await fresh_task(client, f"probe-{source}-{target}")
            replayed = True
            for step in paths[source]:
                if not (await attempt(client, task_id, step))["ok"]:
                    replayed = False
                    break
            if not replayed:
                continue
            if (await attempt(client, task_id, target))["ok"]:
                if await current_status(client, task_id) == target:
                    paths[target] = paths[source] + [target]
                    frontier.append(target)
    return paths


async def main() -> None:
    client = HermesClient()
    rows: list[dict[str, Any]] = []
    try:
        paths = await discover_paths(client)
        reachable = sorted(paths, key=STATUSES.index)
        print(f"reachable from triage by PATCH: {', '.join(reachable)}")
        unreachable = [s for s in STATUSES if s not in paths]
        if unreachable:
            print(f"not reachable by PATCH at all: {', '.join(unreachable)}")

        for source in reachable:
            for target in STATUSES:
                if source == target:
                    continue
                task_id = await fresh_task(client, f"m-{source}-{target}")
                ok = True
                for step in paths[source]:
                    if not (await attempt(client, task_id, step))["ok"]:
                        ok = False
                        break
                if not ok:
                    continue
                result = await attempt(client, task_id, target)
                after = await current_status(client, task_id)
                rows.append(
                    {
                        "from": source,
                        "to": target,
                        "http": result["status"],
                        "ok": result["ok"] and after == target,
                        "detail": result["detail"],
                        "after": after,
                    }
                )
            print(f"  {source:10} done")
    finally:
        for task_id in created:
            try:
                await client.delete_json(f"/tasks/{task_id}", board=BOARD)
            except Exception:
                pass
        await client.aclose()

    render(rows)


def render(rows: list[dict[str, Any]]) -> None:
    sources = sorted({r["from"] for r in rows}, key=STATUSES.index)
    index = {(r["from"], r["to"]): r for r in rows}

    lines = [
        "# Hermes status transition matrix",
        "",
        "Generated by `scripts/spike_matrix.py` against the `flightdeck-test` board.",
        "Rows are the current status, columns the requested one, via",
        "`PATCH /api/plugins/kanban/tasks/{id}?board=<slug>` with `{\"status\": <column>}`.",
        "",
        "`ok` means Hermes accepted it *and* a follow-up read confirmed the new status.",
        "",
        "| from \\ to | " + " | ".join(STATUSES) + " |",
        "|---" * (len(STATUSES) + 1) + "|",
    ]
    for source in sources:
        cells = []
        for target in STATUSES:
            if source == target:
                cells.append("-")
                continue
            row = index.get((source, target))
            if row is None:
                cells.append("?")
            elif row["ok"]:
                cells.append("ok")
            else:
                cells.append(str(row["http"]))
        lines += [f"| **{source}** | " + " | ".join(cells) + " |"]

    lines += ["", "## Refusal messages", ""]
    seen: dict[str, str] = {}
    for row in rows:
        if not row["ok"] and row["detail"]:
            seen.setdefault(f"{row['http']} {row['detail']}", f"{row['from']} -> {row['to']}")
    for message, example in sorted(seen.items()):
        lines.append(f"- `{message}`  (e.g. {example})")

    out = Path(__file__).resolve().parents[1] / "docs" / "transition-matrix.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    asyncio.run(main())
