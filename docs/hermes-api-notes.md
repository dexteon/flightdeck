# Hermes kanban API: notes from the Phase 0 spike

Everything here was measured against a live `hermes dashboard` on `127.0.0.1:9119`, using
the scratch board `flightdeck-test`. Regenerate with `scripts/spike_verbs.py` and
`scripts/spike_matrix.py` after any Hermes upgrade.

Validated against Hermes commit `69e857425c`.

## Auth

The dashboard mints a session token per process (`hermes_cli/web_server.py:307-311`) and
injects it into the SPA shell as `window.__HERMES_SESSION_TOKEN__`. `GET /` is
unauthenticated, so the token can be read off the page and replayed.

```
X-Hermes-Session-Token: <43-char token>
```

`Authorization: Bearer <token>` is accepted as a legacy fallback. WebSocket upgrades
cannot carry headers, so those take `?token=<token>` on loopback instead.

The token rotates on every dashboard restart. `HERMES_DASHBOARD_SESSION_TOKEN` pins it if
you would rather not scrape.

## `board` is a query parameter on every endpoint

Including the ones that also take a JSON body. There is no board field in any request
body. Omitting the parameter silently targets the `default` board.

This cost real time during the spike: `POST /links` with a correct body but no `board`
returned `400 unknown task(s): t_a6d0052e, t_6e6d4474` for two tasks that plainly
existed, because it was looking for them on the wrong board.

## Status transitions

Full matrix in [`transition-matrix.md`](transition-matrix.md). Three rules matter.

**`running` is unreachable by PATCH.** Every source state returns:

```
400 Cannot set status to 'running' directly; use the dispatcher/claim path
```

Only the dispatcher claims tasks, via `BEGIN IMMEDIATE` plus a compare-and-swap on
`claim_lock`. Flightdeck rejects this client-side before making a request.

**HTTP 200 does not mean the task reached the status you requested.** `review -> todo`
returns 200 with a body whose `task.status` is `ready`, and emits a `review_reopened`
event. Always reconcile from `response["task"]["status"]`.

**409 means the transition was illegal from the task's current state**, with the message
`status transition to '<target>' not valid from current state`. It can also mean the
dispatcher moved the task under you between your read and your write. Either way: surface
it, refetch, never auto-retry.

Reachability from `triage` by PATCH alone: `todo`, `ready`, `archived` directly, and
`scheduled`, `blocked`, `review`, `done` indirectly. `running` never.

`blocked` requires a `block_reason` in the body.

## Field patches

`PATCH /tasks/{id}?board=<slug>` accepts `priority`, `title`, and `body` and returns 200.
All three are things the shipped Hermes drawer cannot edit after creation, so they are
free wins for us.

## Links

```
POST   /links?board=<slug>   body {"parent_id": "...", "child_id": "..."}   -> {"ok": true}
DELETE /links?board=<slug>&parent_id=...&child_id=...                       -> {"ok": bool}
```

`DELETE` returns `{"ok": false}` when there was no such link, not a 404.

## Board creation

```
POST /boards  body {"slug", "name", "description", "switch": false}
```

`switch: false` is honored: the spike confirmed `<kanban>/current` still read `wan2gp`
both before and after creating `flightdeck-test`. The response echoes the resolved
`db_path` and the current board.

## Endpoints with no UI in the shipped dashboard

These are the cheap wins Flightdeck is built on. All verified present.

| Endpoint | What it gives |
|---|---|
| `GET /workers/active` | every running `task_runs` row with a live `worker_pid` |
| `GET /runs/{id}/inspect` | live psutil: cpu, mem, threads, fds, cmdline |
| `POST /runs/{id}/terminate` | SIGTERM then SIGKILL via `reclaim_task` |
| `GET /diagnostics?severity=` | active distress signals across the board |
| `GET /attachments/{id}` | download (upload has a UI, download does not) |
| `DELETE /attachments/{id}` | delete |
| `POST /links`, `DELETE /links` | dependency edges, editable only at creation in the UI |

## Live events

```
WS /api/plugins/kanban/events?board=<slug>&since=<event_id>&token=<token>
```

Frames are `{"events": [...], "cursor": <int>}`; events are
`{id, task_id, run_id, kind, payload, created_at}`. Replay from a cursor works, so a
dropped socket loses nothing. Server-side this is a 0.3s poll of `task_events`.

Flightdeck does not consume this. We tail `task_events` over our own read-only SQLite
connections instead: same freshness, works while Hermes is down, and one stream can cover
all 14 boards where this one pins a single board at handshake.
