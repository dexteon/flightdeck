/** One queue across every board.
 *
 * Hermes has no sort control anywhere and no cross-board view at all, so this is two
 * gaps closed at once. Order is Hermes' own dispatch order by default
 * (`priority DESC, created_at ASC`), which makes it a genuine preview of what the
 * dispatcher will pick up next.
 */

import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQueue } from '../api/client'
import type { Task } from '../api/types'
import {
  Age,
  EmptyState,
  ORDERED_STATUSES,
  Panel,
  PartialNotice,
  StatusPill,
} from '../components/common/primitives'

type SortKey = 'dispatch' | 'newest' | 'oldest' | 'board' | 'title'

const SORTS: { key: SortKey; label: string }[] = [
  { key: 'dispatch', label: 'Dispatch order' },
  { key: 'newest', label: 'Newest' },
  { key: 'oldest', label: 'Oldest' },
  { key: 'board', label: 'Board' },
  { key: 'title', label: 'Title' },
]

const DEFAULT_STATUSES = ['triage', 'todo', 'scheduled', 'ready', 'running', 'blocked', 'review']

function compare(sort: SortKey) {
  return (a: Task & { board: string }, b: Task & { board: string }) => {
    switch (sort) {
      case 'newest':
        return (b.created_at ?? 0) - (a.created_at ?? 0)
      case 'oldest':
        return (a.created_at ?? 0) - (b.created_at ?? 0)
      case 'board':
        return a.board.localeCompare(b.board) || (b.priority ?? 0) - (a.priority ?? 0)
      case 'title':
        return a.title.localeCompare(b.title)
      default:
        return (b.priority ?? 0) - (a.priority ?? 0) || (a.created_at ?? 0) - (b.created_at ?? 0)
    }
  }
}

export default function QueueView() {
  const [statuses, setStatuses] = useState<string[]>(DEFAULT_STATUSES)
  const [sort, setSort] = useState<SortKey>('dispatch')
  const [filter, setFilter] = useState('')
  const queue = useQueue(statuses)

  const rows = useMemo(() => {
    const all = queue.data?.tasks ?? []
    const needle = filter.trim().toLowerCase()
    const matched = needle
      ? all.filter(
          (t) =>
            t.title.toLowerCase().includes(needle) ||
            t.id.toLowerCase().includes(needle) ||
            (t.assignee ?? '').toLowerCase().includes(needle) ||
            t.board.toLowerCase().includes(needle),
        )
      : all
    return [...matched].sort(compare(sort))
  }, [queue.data, filter, sort])

  const toggle = (status: string) =>
    setStatuses((current) =>
      current.includes(status) ? current.filter((s) => s !== status) : [...current, status],
    )

  const now = Math.floor(Date.now() / 1000)

  return (
    <div className="space-y-4 p-4">
      <PartialNotice
        partial={queue.data?.partial ?? false}
        unavailable={queue.data?.unavailable ?? []}
      />

      <div className="flex flex-wrap items-center gap-2">
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter by title, id, assignee or board"
          className="min-w-64 flex-1 rounded border border-[var(--color-line)] bg-[var(--color-surface)] px-2 py-1.5 outline-none focus:border-[var(--color-accent)]"
        />
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as SortKey)}
          className="rounded border border-[var(--color-line)] bg-[var(--color-surface)] px-2 py-1.5 outline-none"
        >
          {SORTS.map((s) => (
            <option key={s.key} value={s.key}>
              {s.label}
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {ORDERED_STATUSES.map((status) => {
          const on = statuses.includes(status)
          return (
            <button
              key={status}
              onClick={() => toggle(status)}
              className={`rounded px-2 py-1 text-[11px] transition-colors ${
                on
                  ? 'bg-[var(--color-surface-2)] text-[var(--color-text)]'
                  : 'text-[var(--color-faint)] hover:text-[var(--color-muted)]'
              }`}
            >
              {status}
            </button>
          )
        })}
      </div>

      <Panel
        title="Fleet queue"
        right={
          <span className="nums text-[11px] text-[var(--color-faint)]">
            {rows.length} of {queue.data?.count ?? 0}
          </span>
        }
      >
        {!rows.length ? (
          <EmptyState>{queue.isLoading ? 'Reading...' : 'Nothing matches.'}</EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead className="text-[11px] tracking-wide text-[var(--color-faint)] uppercase">
                <tr>
                  <th className="px-3 py-2">Status</th>
                  <th className="px-3 py-2">Task</th>
                  <th className="px-3 py-2">Board</th>
                  <th className="px-3 py-2">Assignee</th>
                  <th className="px-3 py-2">Pri</th>
                  <th className="px-3 py-2">Age</th>
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, 300).map((task) => (
                  <tr
                    key={`${task.board}-${task.id}`}
                    className="border-t border-[var(--color-line)] hover:bg-[var(--color-surface-2)]"
                  >
                    <td className="px-3 py-1.5">
                      <StatusPill status={task.status} />
                    </td>
                    <td className="px-3 py-1.5">
                      <Link
                        to={`/b/${task.board}/t/${task.id}`}
                        className="block max-w-[40rem] truncate hover:text-[var(--color-accent)]"
                        title={task.title}
                      >
                        {task.title}
                      </Link>
                    </td>
                    <td className="px-3 py-1.5 text-[var(--color-muted)]">{task.board}</td>
                    <td className="px-3 py-1.5 text-[var(--color-muted)]">
                      {task.assignee ?? '-'}
                    </td>
                    <td className="nums px-3 py-1.5">{task.priority ?? 0}</td>
                    <td className="px-3 py-1.5">
                      <Age seconds={task.created_at ? now - task.created_at : null} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {rows.length > 300 && (
              <div className="px-3 py-2 text-[11px] text-[var(--color-faint)]">
                Showing the first 300 by current sort. Narrow the filter to see more.
              </div>
            )}
          </div>
        )}
      </Panel>
    </div>
  )
}
