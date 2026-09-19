/** Shapes the Flightdeck backend returns.
 *
 * Every task field is optional on purpose: the backend intersects its SELECT list with
 * the columns a board actually has, and the boards on this machine genuinely differ
 * (`nrt-unify` carries a `tasks.task_source` the others lack). A missing column arrives
 * as null rather than throwing, and the UI has to cope.
 */

export type Status =
  | 'triage'
  | 'todo'
  | 'scheduled'
  | 'ready'
  | 'running'
  | 'blocked'
  | 'review'
  | 'done'
  | 'archived'

export const STATUSES: Status[] = [
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

export interface Task {
  id: string
  title: string
  status: Status | string
  body?: string | null
  assignee?: string | null
  priority?: number | null
  tenant?: string | null
  created_by?: string | null
  created_at?: number | null
  started_at?: number | null
  completed_at?: number | null
  result?: string | null
  workspace_kind?: string | null
  workspace_path?: string | null
  branch_name?: string | null
  claim_lock?: string | null
  worker_pid?: number | null
  last_heartbeat_at?: number | null
  current_run_id?: number | null
  consecutive_failures?: number | null
  last_failure_error?: string | null
  model_override?: string | null
  provider_override?: string | null
  reasoning_effort?: string | null
  block_kind?: string | null
  block_recurrences?: number | null
  session_id?: string | null
}

export interface Run {
  id: number
  task_id: string
  profile?: string | null
  status: string
  outcome?: string | null
  summary?: string | null
  error?: string | null
  metadata?: string | null
  worker_pid?: number | null
  started_at?: number | null
  ended_at?: number | null
  last_heartbeat_at?: number | null
}

export interface TaskEvent {
  id: number
  task_id: string
  run_id?: number | null
  kind: string
  payload?: unknown
  created_at: number
}

export interface Comment {
  id: number
  author: string
  body: string
  created_at: number
}

export interface Attachment {
  id: number
  filename: string
  content_type?: string | null
  size?: number | null
  created_at?: number | null
}

export interface BoardStats {
  counts: Record<string, number>
  total: number
  running: number
  stale: number
  oldest_ready_age: number | null
}

export interface Board {
  slug: string
  state: 'available' | 'unavailable'
  reason: string | null
  name: string
  description?: string | null
  archived: boolean
  is_current: boolean
  schema_fingerprint?: string | null
  stats?: BoardStats | null
}

export interface HermesState {
  state: 'UP' | 'DEGRADED' | 'DOWN'
  writes_enabled: boolean
  last_ok_at: number | null
  last_error: string | null
  reason: string | null
}

export interface Unavailable {
  slug: string
  reason: string
}

export interface FleetResponse {
  boards: Board[]
  rollup: { total: number; running: number; stale: number; counts: Record<string, number> }
  now: number
  stale_heartbeat_seconds: number
  partial: boolean
  unavailable: Unavailable[]
  hermes: HermesState
}

export interface Worker extends Task {
  board: string
  heartbeat_age: number | null
  stale: boolean
  run?: Run | null
}

export interface RunningResponse {
  workers: Worker[]
  count: number
  stale_count: number
  now: number
  stale_heartbeat_seconds: number
  partial: boolean
  unavailable: Unavailable[]
}

export interface Alert {
  kind: 'stale_claim' | 'blocked' | 'stuck_queue'
  severity: 'error' | 'warning' | 'info'
  board: string
  task_id: string | null
  title: string
  detail: string
  task: Task | null
}

export interface AlertsResponse {
  alerts: Alert[]
  count: number
  partial: boolean
  unavailable: Unavailable[]
}

export interface QueueResponse {
  tasks: (Task & { board: string })[]
  count: number
  statuses: string[]
  partial: boolean
  unavailable: Unavailable[]
}

export interface BoardTasksResponse {
  board: string
  tasks: Task[]
  counts: Record<string, number>
  columns: string[]
  cursor: number
  /** True total from a GROUP BY over the whole table, not the size of this page. */
  total: number
  returned: number
  truncated: boolean
  limit: number
  now: number
  stale_heartbeat_seconds: number
}

export interface TaskDetail {
  board: string
  task: Task
  runs: Run[]
  events: TaskEvent[]
  comments: Comment[]
  attachments: Attachment[]
  links: { parents: string[]; children: string[] }
  allowed_transitions: string[]
  hermes_url: string
  now: number
}

export interface Health {
  ok: boolean
  version: string
  hermes: HermesState & { url: string; token_source: string; token_error: string | null }
  boards: { total: number; available: number; unavailable: Unavailable[] }
  schema_fingerprints: Record<string, string>
  fts5: boolean
  settings: { stale_heartbeat_seconds: number }
}
