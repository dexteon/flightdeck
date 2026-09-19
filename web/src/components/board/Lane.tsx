/** One column, virtualized.
 *
 * `ai-fraud-guide` has 1098 tasks, 997 of them done, so the done lane alone would mount
 * a thousand nodes without this. Because Flightdeck delegates card moves to Hermes and
 * does no drag and drop, virtualization here is free: there is no drop target that has
 * to stay mounted while off screen.
 */

import { useRef } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import type { Task } from '../../api/types'
import { StatusDot, statusColor } from '../common/primitives'
import TaskCard from './TaskCard'

const ROW_HEIGHT = 74

export default function Lane({
  status,
  tasks,
  trueCount,
  boardSlug,
  staleThreshold,
  now,
  selectedId,
}: {
  status: string
  tasks: Task[]
  /** What SQL counted for this status. Differs from `tasks.length` when a filter is
   *  active or the board page was capped, and the header must not pretend otherwise. */
  trueCount: number
  boardSlug: string
  staleThreshold: number
  now: number
  selectedId?: string
}) {
  const parentRef = useRef<HTMLDivElement>(null)

  const virtualizer = useVirtualizer({
    count: tasks.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 8,
  })

  return (
    <div className="flex h-full w-72 shrink-0 flex-col rounded-lg border border-[var(--color-line)] bg-[var(--color-surface)]">
      <header
        className="flex items-center justify-between border-b border-[var(--color-line)] px-2.5 py-2"
        style={{ borderTopColor: statusColor(status) }}
      >
        <span className="flex items-center gap-1.5 text-[11px] font-semibold tracking-wide uppercase">
          <StatusDot status={status} />
          {status}
        </span>
        <span className="nums text-[11px] text-[var(--color-faint)]">
          {tasks.length === trueCount ? (
            trueCount
          ) : (
            <span title={`${tasks.length} shown of ${trueCount} on this board`}>
              {tasks.length}
              <span className="opacity-60">/{trueCount}</span>
            </span>
          )}
        </span>
      </header>

      <div ref={parentRef} className="flex-1 overflow-y-auto p-1.5">
        {tasks.length === 0 ? (
          <div className="px-2 py-4 text-center text-[11px] text-[var(--color-faint)]">empty</div>
        ) : (
          <div style={{ height: virtualizer.getTotalSize(), position: 'relative' }}>
            {virtualizer.getVirtualItems().map((item) => {
              const task = tasks[item.index]
              return (
                <div
                  key={task.id}
                  ref={virtualizer.measureElement}
                  data-index={item.index}
                  style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    width: '100%',
                    transform: `translateY(${item.start}px)`,
                  }}
                >
                  <TaskCard
                    task={task}
                    boardSlug={boardSlug}
                    staleThreshold={staleThreshold}
                    now={now}
                    selected={task.id === selectedId}
                  />
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
