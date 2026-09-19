/** Small shared pieces. Kept together because none of them is big enough to own a file. */

import type { ReactNode } from 'react'
import type { Status } from '../../api/types'

const STATUS_COLOR: Record<string, string> = {
  triage: 'var(--color-triage)',
  todo: 'var(--color-todo)',
  scheduled: 'var(--color-scheduled)',
  ready: 'var(--color-ready)',
  running: 'var(--color-running)',
  blocked: 'var(--color-blocked)',
  review: 'var(--color-review)',
  done: 'var(--color-done)',
  archived: 'var(--color-archived)',
}

export function statusColor(status: string): string {
  return STATUS_COLOR[status] ?? 'var(--color-faint)'
}

export function StatusDot({ status, pulse }: { status: string; pulse?: boolean }) {
  return (
    <span
      className={`inline-block h-2 w-2 shrink-0 rounded-full ${pulse ? 'pulse' : ''}`}
      style={{ background: statusColor(status) }}
      title={status}
    />
  )
}

export function StatusPill({ status }: { status: string }) {
  const color = statusColor(status)
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded px-1.5 py-0.5 text-[11px] font-medium"
      style={{ color, background: `color-mix(in srgb, ${color} 14%, transparent)` }}
    >
      <StatusDot status={status} pulse={status === 'running'} />
      {status}
    </span>
  )
}

/** Compact duration. Ages here run from seconds to days, so pick one unit and stop. */
export function duration(seconds: number | null | undefined): string {
  if (seconds == null) return '-'
  if (seconds < 60) return `${Math.floor(seconds)}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`
  return `${Math.floor(seconds / 86400)}d`
}

export function Age({
  seconds,
  warnAbove,
}: {
  seconds: number | null | undefined
  warnAbove?: number
}) {
  const danger = warnAbove != null && seconds != null && seconds > warnAbove
  return (
    <span className={`nums ${danger ? 'text-[var(--color-danger)]' : 'text-[var(--color-muted)]'}`}>
      {duration(seconds)}
    </span>
  )
}

export function Panel({
  title,
  right,
  children,
  className = '',
}: {
  title?: ReactNode
  right?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section
      className={`rounded-lg border border-[var(--color-line)] bg-[var(--color-surface)] ${className}`}
    >
      {(title || right) && (
        <header className="flex items-center justify-between border-b border-[var(--color-line)] px-3 py-2">
          <h2 className="text-[12px] font-semibold tracking-wide text-[var(--color-muted)] uppercase">
            {title}
          </h2>
          {right}
        </header>
      )}
      {children}
    </section>
  )
}

export function Metric({
  label,
  value,
  tone,
}: {
  label: string
  value: ReactNode
  tone?: 'danger' | 'warn' | 'ok'
}) {
  const color =
    tone === 'danger'
      ? 'var(--color-danger)'
      : tone === 'warn'
        ? 'var(--color-warn)'
        : tone === 'ok'
          ? 'var(--color-ok)'
          : 'var(--color-text)'
  return (
    <div>
      <div className="nums text-2xl leading-tight font-semibold" style={{ color }}>
        {value}
      </div>
      <div className="text-[11px] tracking-wide text-[var(--color-faint)] uppercase">{label}</div>
    </div>
  )
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="px-3 py-8 text-center text-[var(--color-faint)]">{children}</div>
}

/** Names the boards that did not answer. Silently under-reporting the fleet is worse
 *  than showing a partial answer and saying so. */
export function PartialNotice({
  partial,
  unavailable,
}: {
  partial: boolean
  unavailable: { slug: string; reason: string }[]
}) {
  if (!partial || unavailable.length === 0) return null
  return (
    <div className="rounded border border-[var(--color-warn)]/30 bg-[var(--color-warn)]/10 px-3 py-2 text-[12px] text-[var(--color-warn)]">
      Partial data. {unavailable.length} board{unavailable.length === 1 ? '' : 's'} did not
      answer:{' '}
      {unavailable.map((u) => (
        <span key={u.slug} className="mr-2">
          <b>{u.slug}</b> ({u.reason})
        </span>
      ))}
    </div>
  )
}

export const ORDERED_STATUSES: Status[] = [
  'triage',
  'todo',
  'scheduled',
  'ready',
  'running',
  'blocked',
  'review',
  'done',
  'archived',
]
