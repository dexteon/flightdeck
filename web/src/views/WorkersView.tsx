/** Every claimed task across every board, live.
 *
 * `GET /workers/active`, `GET /runs/{id}/inspect` and `POST /runs/{id}/terminate` all
 * exist in the Hermes API with no UI attached to any of them. This is where they land.
 *
 * Rows are read from SQLite rather than from Hermes, so a claim shows here even when the
 * dashboard is down, which matters: a dead dashboard is exactly when claims go stale.
 */

import { Link } from 'react-router-dom'
import { useRunning } from '../api/client'
import type { Worker } from '../api/types'
import {
  Age,
  EmptyState,
  Metric,
  Panel,
  PartialNotice,
  StatusDot,
  duration,
} from '../components/common/primitives'

function WorkerRow({ worker, threshold }: { worker: Worker; threshold: number }) {
  const run = worker.run
  return (
    <tr className="border-t border-[var(--color-line)] hover:bg-[var(--color-surface-2)]">
      <td className="px-3 py-2">
        <StatusDot status={worker.stale ? 'blocked' : 'running'} pulse={!worker.stale} />
      </td>
      <td className="px-3 py-2">
        <Link
          to={`/b/${worker.board}/t/${worker.id}`}
          className="block max-w-[34rem] truncate hover:text-[var(--color-accent)]"
          title={worker.title}
        >
          {worker.title}
        </Link>
        <div className="nums text-[11px] text-[var(--color-faint)]">{worker.id}</div>
      </td>
      <td className="px-3 py-2 text-[var(--color-muted)]">{worker.board}</td>
      <td className="px-3 py-2">{worker.assignee ?? run?.profile ?? '-'}</td>
      <td className="nums px-3 py-2 text-[var(--color-muted)]">{worker.worker_pid ?? '-'}</td>
      <td className="px-3 py-2">
        <Age seconds={worker.heartbeat_age} warnAbove={threshold} />
      </td>
      <td className="nums px-3 py-2 text-[var(--color-muted)]">
        {worker.started_at ? duration(Math.floor(Date.now() / 1000) - worker.started_at) : '-'}
      </td>
      <td className="px-3 py-2">
        {worker.stale ? (
          <span className="text-[var(--color-danger)]">no heartbeat</span>
        ) : (
          <span className="text-[var(--color-ok)]">alive</span>
        )}
      </td>
    </tr>
  )
}

export default function WorkersView() {
  const running = useRunning()

  if (running.isLoading) return <EmptyState>Reading claims...</EmptyState>
  if (!running.data) return <EmptyState>No data.</EmptyState>

  const { workers, count, stale_count, stale_heartbeat_seconds, partial, unavailable } =
    running.data
  const live = count - stale_count

  return (
    <div className="space-y-4 p-4">
      <PartialNotice partial={partial} unavailable={unavailable} />

      <Panel>
        <div className="grid grid-cols-3 gap-4 p-4">
          <Metric label="claimed tasks" value={count} />
          <Metric label="heartbeating" value={live} tone={live ? 'ok' : 'danger'} />
          <Metric label="stale" value={stale_count} tone={stale_count ? 'danger' : undefined} />
        </div>
        {count > 0 && live === 0 && (
          <div className="border-t border-[var(--color-line)] px-4 py-2 text-[12px] text-[var(--color-danger)]">
            All {count} claims are stale. A claimed task with no heartbeat is a row whose
            worker died without releasing it; the dispatcher will not pick these up again
            until the claim TTL expires or something reclaims them.
          </div>
        )}
      </Panel>

      <Panel title="Claims">
        {!workers.length ? (
          <EmptyState>Nothing is claimed anywhere on the fleet.</EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead className="text-[11px] tracking-wide text-[var(--color-faint)] uppercase">
                <tr>
                  <th className="w-6 px-3 py-2" />
                  <th className="px-3 py-2">Task</th>
                  <th className="px-3 py-2">Board</th>
                  <th className="px-3 py-2">Profile</th>
                  <th className="px-3 py-2">PID</th>
                  <th className="px-3 py-2">Heartbeat</th>
                  <th className="px-3 py-2">Claimed</th>
                  <th className="px-3 py-2">State</th>
                </tr>
              </thead>
              <tbody>
                {workers.map((worker) => (
                  <WorkerRow
                    key={`${worker.board}-${worker.id}`}
                    worker={worker}
                    threshold={stale_heartbeat_seconds}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  )
}
