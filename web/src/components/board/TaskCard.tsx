/** One card.
 *
 * Pure and memoized, with no hooks that subscribe to global state: a card that
 * subscribes re-renders with every heartbeat, and heartbeats are the highest-volume
 * event on the fleet by an order of magnitude.
 */

import { memo } from 'react'
import { Link } from 'react-router-dom'
import type { Task } from '../../api/types'
import { duration, statusColor } from '../common/primitives'

interface Props {
  task: Task
  boardSlug: string
  staleThreshold: number
  now: number
  selected: boolean
}

function TaskCard({ task, boardSlug, staleThreshold, now, selected }: Props) {
  const running = task.status === 'running'
  const heartbeatAge =
    task.last_heartbeat_at != null
      ? now - task.last_heartbeat_at
      : task.started_at != null
        ? now - task.started_at
        : null
  const stale = running && heartbeatAge != null && heartbeatAge > staleThreshold

  return (
    <Link
      to={`/b/${boardSlug}/t/${task.id}`}
      className={`mb-1.5 block rounded border-l-2 bg-[var(--color-surface-2)] px-2.5 py-2 transition-colors hover:bg-[var(--color-line)] ${
        selected ? 'ring-1 ring-[var(--color-accent)]' : ''
      }`}
      style={{ borderLeftColor: stale ? 'var(--color-danger)' : statusColor(task.status) }}
    >
      <div className="line-clamp-2 leading-snug" title={task.title}>
        {task.title}
      </div>

      <div className="mt-1.5 flex items-center gap-2 text-[11px] text-[var(--color-faint)]">
        {task.assignee && <span className="text-[var(--color-muted)]">{task.assignee}</span>}
        {!!task.priority && <span className="nums">p{task.priority}</span>}
        {task.block_kind && <span className="text-[var(--color-warn)]">{task.block_kind}</span>}
        {!!task.consecutive_failures && (
          <span className="text-[var(--color-danger)]" title="consecutive failures">
            {task.consecutive_failures}x failed
          </span>
        )}
        {running && (
          <span className={stale ? 'text-[var(--color-danger)]' : 'text-[var(--color-ok)]'}>
            {stale ? `dead ${duration(heartbeatAge)}` : duration(heartbeatAge)}
          </span>
        )}
        <span className="nums ml-auto opacity-60">{task.id.replace(/^t_/, '')}</span>
      </div>
    </Link>
  )
}

export default memo(TaskCard)
