/** Everything known about one task, assembled from five tables in a single request.
 *
 * Route-driven rather than state-driven, so a task link is shareable. Hermes' drawer is
 * state-only, which means you cannot send someone a link to a task.
 *
 * Edits are delegated: the footer links straight into the Hermes board.
 */

import { useNavigate } from 'react-router-dom'
import { useTask } from '../../api/client'
import type { Run, TaskEvent } from '../../api/types'
import { Age, StatusPill, duration } from '../common/primitives'

const NOISE = new Set(['heartbeat'])

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-2 py-0.5">
      <span className="w-28 shrink-0 text-[11px] text-[var(--color-faint)]">{label}</span>
      <span className="min-w-0 flex-1 break-words">{children}</span>
    </div>
  )
}

function RunRow({ run, now }: { run: Run; now: number }) {
  const bad = ['crashed', 'failed', 'timed_out', 'gave_up'].includes(run.outcome ?? run.status)
  const length =
    run.started_at != null ? (run.ended_at ?? now) - run.started_at : null
  return (
    <li className="border-t border-[var(--color-line)] px-3 py-1.5">
      <div className="flex items-center gap-2">
        <span className={bad ? 'text-[var(--color-danger)]' : 'text-[var(--color-muted)]'}>
          {run.outcome ?? run.status}
        </span>
        <span className="text-[var(--color-faint)]">{run.profile ?? '-'}</span>
        <span className="nums ml-auto text-[11px] text-[var(--color-faint)]">
          {duration(length)}
        </span>
      </div>
      {(run.error || run.summary) && (
        <div className="line-clamp-2 text-[11px] text-[var(--color-faint)]">
          {run.error ?? run.summary}
        </div>
      )}
    </li>
  )
}

function EventRow({ event, now }: { event: TaskEvent; now: number }) {
  const payload =
    event.payload && typeof event.payload === 'object'
      ? JSON.stringify(event.payload).slice(0, 140)
      : null
  return (
    <li className="flex gap-2 px-3 py-1">
      <span className="w-10 shrink-0 text-right text-[11px] text-[var(--color-faint)]">
        {duration(now - event.created_at)}
      </span>
      <span className="shrink-0">{event.kind}</span>
      {payload && (
        <span className="truncate text-[11px] text-[var(--color-faint)]">{payload}</span>
      )}
    </li>
  )
}

export default function TaskDrawer({
  boardSlug,
  taskId,
}: {
  boardSlug: string
  taskId: string
}) {
  const navigate = useNavigate()
  const detail = useTask(boardSlug, taskId)

  const close = () => navigate(`/b/${boardSlug}`)

  return (
    <aside className="absolute top-0 right-0 bottom-0 z-20 flex w-[34rem] flex-col border-l border-[var(--color-line)] bg-[var(--color-surface)] shadow-2xl">
      <header className="flex items-center gap-2 border-b border-[var(--color-line)] px-3 py-2">
        {detail.data && <StatusPill status={detail.data.task.status} />}
        <span className="nums text-[11px] text-[var(--color-faint)]">{taskId}</span>
        <button
          onClick={close}
          className="ml-auto rounded px-2 py-0.5 text-[var(--color-muted)] hover:bg-[var(--color-surface-2)]"
        >
          close
        </button>
      </header>

      {detail.isLoading && <div className="p-4 text-[var(--color-faint)]">Reading...</div>}
      {detail.error && (
        <div className="p-4 text-[var(--color-danger)]">{String(detail.error)}</div>
      )}

      {detail.data && (
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="border-b border-[var(--color-line)] p-3">
            <h2 className="mb-2 leading-snug font-medium">{detail.data.task.title}</h2>
            <Field label="board">{boardSlug}</Field>
            <Field label="assignee">{detail.data.task.assignee ?? 'unassigned'}</Field>
            <Field label="priority">{detail.data.task.priority ?? 0}</Field>
            {detail.data.task.worker_pid != null && (
              <Field label="worker pid">{detail.data.task.worker_pid}</Field>
            )}
            {detail.data.task.last_heartbeat_at != null && (
              <Field label="heartbeat">
                <Age seconds={detail.data.now - detail.data.task.last_heartbeat_at} warnAbove={120} />{' '}
                ago
              </Field>
            )}
            {detail.data.task.block_kind && (
              <Field label="blocked by">{detail.data.task.block_kind}</Field>
            )}
            {!!detail.data.task.consecutive_failures && (
              <Field label="failures">
                <span className="text-[var(--color-danger)]">
                  {detail.data.task.consecutive_failures} consecutive
                </span>
              </Field>
            )}
            {detail.data.task.last_failure_error && (
              <Field label="last error">
                <span className="text-[var(--color-danger)]">
                  {detail.data.task.last_failure_error}
                </span>
              </Field>
            )}
            {detail.data.task.model_override && (
              <Field label="model">{detail.data.task.model_override}</Field>
            )}
            {detail.data.task.workspace_path && (
              <Field label="workspace">
                <span className="text-[11px]">{detail.data.task.workspace_path}</span>
              </Field>
            )}
          </div>

          {detail.data.task.body && (
            <div className="border-b border-[var(--color-line)] p-3">
              <div className="mb-1 text-[11px] tracking-wide text-[var(--color-faint)] uppercase">
                Description
              </div>
              <pre className="font-sans text-[12px] whitespace-pre-wrap text-[var(--color-muted)]">
                {detail.data.task.body}
              </pre>
            </div>
          )}

          {(detail.data.links.parents.length > 0 || detail.data.links.children.length > 0) && (
            <div className="border-b border-[var(--color-line)] p-3">
              <div className="mb-1 text-[11px] tracking-wide text-[var(--color-faint)] uppercase">
                Dependencies
              </div>
              {detail.data.links.parents.length > 0 && (
                <Field label="blocked by">
                  {detail.data.links.parents.map((id) => (
                    <button
                      key={id}
                      onClick={() => navigate(`/b/${boardSlug}/t/${id}`)}
                      className="nums mr-1.5 rounded bg-[var(--color-surface-2)] px-1.5 py-0.5 text-[11px] hover:text-[var(--color-accent)]"
                    >
                      {id.replace(/^t_/, '')}
                    </button>
                  ))}
                </Field>
              )}
              {detail.data.links.children.length > 0 && (
                <Field label="blocks">
                  {detail.data.links.children.map((id) => (
                    <button
                      key={id}
                      onClick={() => navigate(`/b/${boardSlug}/t/${id}`)}
                      className="nums mr-1.5 rounded bg-[var(--color-surface-2)] px-1.5 py-0.5 text-[11px] hover:text-[var(--color-accent)]"
                    >
                      {id.replace(/^t_/, '')}
                    </button>
                  ))}
                </Field>
              )}
            </div>
          )}

          {detail.data.runs.length > 0 && (
            <div className="border-b border-[var(--color-line)]">
              <div className="px-3 pt-3 pb-1 text-[11px] tracking-wide text-[var(--color-faint)] uppercase">
                Runs ({detail.data.runs.length})
              </div>
              <ul>
                {detail.data.runs.slice(0, 12).map((run) => (
                  <RunRow key={run.id} run={run} now={detail.data.now} />
                ))}
              </ul>
            </div>
          )}

          {detail.data.events.length > 0 && (
            <div className="border-b border-[var(--color-line)]">
              <div className="px-3 pt-3 pb-1 text-[11px] tracking-wide text-[var(--color-faint)] uppercase">
                Activity
              </div>
              <ul>
                {detail.data.events
                  .filter((e) => !NOISE.has(e.kind))
                  .slice(0, 30)
                  .map((event) => (
                    <EventRow key={event.id} event={event} now={detail.data.now} />
                  ))}
              </ul>
            </div>
          )}

          <div className="p-3">
            <a
              href={detail.data.hermes_url}
              target="_blank"
              rel="noreferrer"
              className="text-[var(--color-accent)] hover:underline"
            >
              Edit in Hermes
            </a>
            <span className="ml-2 text-[11px] text-[var(--color-faint)]">
              Flightdeck delegates card editing rather than duplicating it.
            </span>
          </div>
        </div>
      )}
    </aside>
  )
}
