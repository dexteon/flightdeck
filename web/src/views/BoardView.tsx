/** One board, read-oriented.
 *
 * Flightdeck does not reimplement card editing: Hermes already does that well, and
 * duplicating drag and drop would mean reimplementing its claim-aware transition rules.
 * Cards deep-link to the drawer; the drawer links out to Hermes for edits.
 */

import { useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useBoardTasks } from '../api/client'
import type { Task } from '../api/types'
import Lane from '../components/board/Lane'
import { EmptyState, ORDERED_STATUSES } from '../components/common/primitives'
import TaskDrawer from '../components/drawer/TaskDrawer'

type SortKey = 'dispatch' | 'newest' | 'oldest' | 'title'

function sorter(sort: SortKey) {
  return (a: Task, b: Task) => {
    switch (sort) {
      case 'newest':
        return (b.created_at ?? 0) - (a.created_at ?? 0)
      case 'oldest':
        return (a.created_at ?? 0) - (b.created_at ?? 0)
      case 'title':
        return a.title.localeCompare(b.title)
      default:
        return (b.priority ?? 0) - (a.priority ?? 0) || (a.created_at ?? 0) - (b.created_at ?? 0)
    }
  }
}

export default function BoardView() {
  const { slug, taskId } = useParams<{ slug: string; taskId?: string }>()
  const board = useBoardTasks(slug)
  const [filter, setFilter] = useState('')
  const [sort, setSort] = useState<SortKey>('dispatch')
  const [showArchived, setShowArchived] = useState(false)

  const lanes = useMemo(() => {
    const tasks = board.data?.tasks ?? []
    const needle = filter.trim().toLowerCase()
    const matched = needle
      ? tasks.filter(
          (t) =>
            t.title.toLowerCase().includes(needle) ||
            t.id.toLowerCase().includes(needle) ||
            (t.body ?? '').toLowerCase().includes(needle) ||
            (t.assignee ?? '').toLowerCase().includes(needle),
        )
      : tasks

    const columns = ORDERED_STATUSES.filter((s) => showArchived || s !== 'archived')
    const grouped = new Map<string, Task[]>(columns.map((s) => [s, []]))
    for (const task of matched) {
      const bucket = grouped.get(task.status)
      if (bucket) bucket.push(task)
    }
    for (const bucket of grouped.values()) bucket.sort(sorter(sort))
    return [...grouped.entries()]
  }, [board.data, filter, sort, showArchived])

  if (board.isLoading) return <EmptyState>Reading {slug}...</EmptyState>
  if (board.error) return <EmptyState>Cannot read {slug}: {String(board.error)}</EmptyState>
  if (!board.data || !slug) return null

  const now = Math.floor(Date.now() / 1000)
  const shown = lanes.reduce((n, [, tasks]) => n + tasks.length, 0)

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-[var(--color-line)] px-4 py-2">
        <h1 className="font-medium">{slug}</h1>
        <span className="nums text-[11px] text-[var(--color-faint)]">
          {shown} of {board.data.total}
        </span>
        {board.data.truncated && (
          <span
            className="rounded bg-[var(--color-warn)]/15 px-1.5 py-0.5 text-[10px] text-[var(--color-warn)]"
            title={`This board holds ${board.data.total} tasks; ${board.data.returned} were fetched. Lane counts show shown/total.`}
          >
            capped at {board.data.limit}
          </span>
        )}
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter this board"
          className="ml-auto min-w-56 rounded border border-[var(--color-line)] bg-[var(--color-surface)] px-2 py-1 outline-none focus:border-[var(--color-accent)]"
        />
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as SortKey)}
          className="rounded border border-[var(--color-line)] bg-[var(--color-surface)] px-2 py-1 outline-none"
          title="Hermes has no sort control at all"
        >
          <option value="dispatch">Dispatch order</option>
          <option value="newest">Newest</option>
          <option value="oldest">Oldest</option>
          <option value="title">Title</option>
        </select>
        <label className="flex items-center gap-1.5 text-[11px] text-[var(--color-muted)]">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(e) => setShowArchived(e.target.checked)}
          />
          archived
        </label>
      </div>

      <div className="flex min-h-0 flex-1 gap-2 overflow-x-auto p-2">
        {lanes.map(([status, tasks]) => (
          <Lane
            key={status}
            status={status}
            tasks={tasks}
            trueCount={board.data.counts[status] ?? tasks.length}
            boardSlug={slug}
            staleThreshold={board.data.stale_heartbeat_seconds}
            now={now}
            selectedId={taskId}
          />
        ))}
      </div>

      {taskId && <TaskDrawer boardSlug={slug} taskId={taskId} />}
    </div>
  )
}
