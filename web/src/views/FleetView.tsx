/** Every board at once.
 *
 * This is the view Hermes structurally cannot offer: its switcher shows one board at a
 * time, so the 15 boards and 1279 tasks have never been visible together.
 */

import { Link } from 'react-router-dom'
import { useAlerts, useFleet } from '../api/client'
import type { Board } from '../api/types'
import {
  Age,
  EmptyState,
  Metric,
  ORDERED_STATUSES,
  Panel,
  PartialNotice,
  StatusDot,
  duration,
  statusColor,
} from '../components/common/primitives'

function StatusBar({ counts, total }: { counts: Record<string, number>; total: number }) {
  if (!total) return <div className="h-1.5 rounded bg-[var(--color-line)]" />
  return (
    <div className="flex h-1.5 overflow-hidden rounded" title={JSON.stringify(counts)}>
      {ORDERED_STATUSES.filter((s) => counts[s]).map((s) => (
        <div
          key={s}
          style={{ background: statusColor(s), width: `${(counts[s] / total) * 100}%` }}
        />
      ))}
    </div>
  )
}

function BoardTile({ board }: { board: Board }) {
  const stats = board.stats
  const unavailable = board.state !== 'available'

  return (
    <Link
      to={`/b/${board.slug}`}
      className="block rounded-lg border border-[var(--color-line)] bg-[var(--color-surface)] p-3 transition-colors hover:border-[var(--color-line-strong)]"
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <span className="truncate font-medium">{board.slug}</span>
            {board.is_current && (
              <span
                className="rounded bg-[var(--color-accent)]/15 px-1 text-[10px] text-[var(--color-accent)]"
                title="the board the Hermes CLI acts on"
              >
                current
              </span>
            )}
          </div>
          {board.name !== board.slug && (
            <div className="truncate text-[11px] text-[var(--color-faint)]">{board.name}</div>
          )}
        </div>
        <span className="nums shrink-0 text-lg leading-none font-semibold">
          {stats?.total ?? '-'}
        </span>
      </div>

      {unavailable ? (
        <div className="text-[11px] text-[var(--color-danger)]">{board.reason}</div>
      ) : (
        <>
          <StatusBar counts={stats?.counts ?? {}} total={stats?.total ?? 0} />
          <div className="mt-2 flex items-center gap-3 text-[11px] text-[var(--color-muted)]">
            {stats?.running ? (
              <span className="flex items-center gap-1">
                <StatusDot status="running" pulse={stats.stale < stats.running} />
                {stats.running} running
              </span>
            ) : (
              <span className="text-[var(--color-faint)]">idle</span>
            )}
            {!!stats?.stale && (
              <span className="text-[var(--color-danger)]">{stats.stale} stale</span>
            )}
            {stats?.oldest_ready_age != null && (
              <span title="oldest ready task has been queued this long">
                queued <Age seconds={stats.oldest_ready_age} warnAbove={86400} />
              </span>
            )}
          </div>
        </>
      )}
    </Link>
  )
}

export default function FleetView() {
  const fleet = useFleet()
  const alerts = useAlerts()

  if (fleet.isLoading) return <EmptyState>Reading boards...</EmptyState>
  if (fleet.error) return <EmptyState>Could not read the fleet: {String(fleet.error)}</EmptyState>
  if (!fleet.data) return null

  const { boards, rollup, unavailable, partial, stale_heartbeat_seconds } = fleet.data
  const live = rollup.running - rollup.stale

  return (
    <div className="space-y-4 p-4">
      <PartialNotice partial={partial} unavailable={unavailable} />

      <Panel>
        <div className="grid grid-cols-2 gap-4 p-4 md:grid-cols-6">
          <Metric label="boards" value={`${boards.filter((b) => b.state === 'available').length}/${boards.length}`} />
          <Metric label="tasks" value={rollup.total} />
          <Metric label="claimed" value={rollup.running} />
          <Metric
            label="live workers"
            value={live}
            tone={live === 0 && rollup.running > 0 ? 'danger' : 'ok'}
          />
          <Metric
            label="stale claims"
            value={rollup.stale}
            tone={rollup.stale ? 'danger' : undefined}
          />
          <Metric
            label="blocked"
            value={rollup.counts.blocked ?? 0}
            tone={rollup.counts.blocked ? 'warn' : undefined}
          />
        </div>
        {rollup.stale > 0 && rollup.stale === rollup.running && (
          <div className="border-t border-[var(--color-line)] px-4 py-2 text-[12px] text-[var(--color-danger)]">
            Every claimed task is stale: no worker has sent a heartbeat in the last{' '}
            {duration(stale_heartbeat_seconds)}. These are almost certainly dead claims that
            nothing has reclaimed.
          </div>
        )}
      </Panel>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {boards.map((board) => (
          <BoardTile key={board.slug} board={board} />
        ))}
      </div>

      <Panel
        title="Needs attention"
        right={
          <span className="nums text-[11px] text-[var(--color-faint)]">
            {alerts.data?.count ?? 0}
          </span>
        }
      >
        {!alerts.data?.alerts.length ? (
          <EmptyState>Nothing is wedged. Unusual.</EmptyState>
        ) : (
          <ul className="divide-y divide-[var(--color-line)]">
            {alerts.data.alerts.slice(0, 40).map((alert, i) => (
              <li key={`${alert.board}-${alert.task_id ?? i}`} className="flex gap-3 px-3 py-2">
                <span
                  className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full"
                  style={{
                    background:
                      alert.severity === 'error'
                        ? 'var(--color-danger)'
                        : 'var(--color-warn)',
                  }}
                />
                <div className="min-w-0 flex-1">
                  <div className="truncate">
                    {alert.task_id ? (
                      <Link
                        to={`/b/${alert.board}/t/${alert.task_id}`}
                        className="hover:text-[var(--color-accent)]"
                      >
                        {alert.title}
                      </Link>
                    ) : (
                      alert.title
                    )}
                  </div>
                  <div className="text-[11px] text-[var(--color-faint)]">
                    <span className="text-[var(--color-muted)]">{alert.board}</span> ·{' '}
                    {alert.kind.replace('_', ' ')} · {alert.detail}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  )
}
