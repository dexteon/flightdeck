"""Phase 0 spike: pin the exact shape of every Hermes status transition.

Walks each target status against the scratch board and records the request sent, the
status code, and the response body. The output becomes ``docs/hermes-api-notes.md`` and
is the contract ``hermes/verbs.py`` implements.

Tasks are created with ``triage=true`` and no assignee so the dispatcher never picks one
up mid-spike. Every task created here is deleted before exit.

Run:  PYTHONPATH=server .venv/Scripts/python.exe scripts/spike_verbs.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from flightdeck.hermes.proxy import HermesClient, HermesError  # noqa: E402

BOARD = "flightdeck-test"

# Every status Hermes validates, plus the one it refuses outright.
TARGETS = [
    "todo",
    "ready",
    "scheduled",
    "review",
    "blocked",
    "done",
    "archived",
    "running",  # expected 400: only the dispatcher may claim
    "bogus",    # expected 4xx: not in VALID_STATUSES
]


async def create_task(client: HermesClient, title: str) -> str:
    payload = {
        "title": title,
        "body": "Flightdeck Phase 0 spike. Safe to delete.",
        "triage": True,
        "priority": 0,
    }
    result = await client.post_json("/tasks", payload, board=BOARD)
    return result["task"]["id"]


async def try_patch(client: HermesClient, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        body = await client.request(
            "PATCH", f"/tasks/{task_id}", json=payload, params={"board": BOARD}
        )
    except HermesError as exc:
        return {"ok": False, "status": exc.status_code, "detail": exc.detail}
    try:
        parsed = body.json()
    except ValueError:
        parsed = None
    return {"ok": True, "status": body.status_code, "body": parsed}


async def main() -> None:
    client = HermesClient()
    records: list[dict[str, Any]] = []
    created: list[str] = []
    try:
        # Each target gets a fresh task from a known start state, so results do not
        # depend on the order the spike happens to run in.
        for target in TARGETS:
            task_id = await create_task(client, f"spike-{target}")
            created.append(task_id)
            payload = {"status": target}
            if target == "blocked":
                payload["block_reason"] = "spike: verifying the block verb"
            result = await try_patch(client, task_id, payload)

            after = None
            try:
                detail = await client.get_json(f"/tasks/{task_id}", board=BOARD)
                after = detail["task"]["status"]
            except HermesError:
                pass

            records.append(
                {
                    "from": "triage",
                    "to": target,
                    "request": payload,
                    "result": result,
                    "status_after": after,
                }
            )
            print(
                f"triage -> {target:10} http={result['status']:3} "
                f"after={after} {'' if result['ok'] else result['detail']}"
            )

        # Non-status field patches, which the Hermes drawer cannot do at all.
        task_id = await create_task(client, "spike-fields")
        created.append(task_id)
        for name, payload in [
            ("priority", {"priority": 7}),
            ("title", {"title": "spike-fields renamed"}),
            ("body", {"body": "rewritten by the spike"}),
        ]:
            result = await try_patch(client, task_id, payload)
            records.append({"field": name, "request": payload, "result": result})
            print(f"field  {name:10} http={result['status']:3} ok={result['ok']}")

        # Link add and remove, which exist in the API with no UI attached.
        parent = await create_task(client, "spike-parent")
        child = await create_task(client, "spike-child")
        created += [parent, child]
        # `board` is a query parameter on EVERY endpoint, including the ones that also
        # take a JSON body. Omitting it silently targets the `default` board.
        for verb, method, kwargs in [
            (
                "POST /links",
                "POST",
                {
                    "json": {"parent_id": parent, "child_id": child},
                    "params": {"board": BOARD},
                },
            ),
            (
                "DELETE /links",
                "DELETE",
                {"params": {"parent_id": parent, "child_id": child, "board": BOARD}},
            ),
        ]:
            try:
                resp = await client.request(method, "/links", **kwargs)
                out = {"ok": True, "status": resp.status_code, "body": resp.json()}
            except HermesError as exc:
                out = {"ok": False, "status": exc.status_code, "detail": exc.detail}
            records.append({"verb": verb, "result": out})
            print(f"{verb:14} http={out['status']}")

    finally:
        for task_id in created:
            try:
                await client.delete_json(f"/tasks/{task_id}", board=BOARD)
            except Exception as exc:
                print(f"cleanup failed for {task_id}: {exc}", file=sys.stderr)
        await client.aclose()

    out_path = Path(__file__).resolve().parents[1] / "docs" / "spike-verbs.json"
    out_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
