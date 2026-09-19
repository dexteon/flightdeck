/** HTTP client and query hooks.
 *
 * Everything here is a read, served from SQLite by our backend. None of it touches
 * Hermes, which is why the console keeps working when the dashboard is not running.
 */

import { useQuery } from '@tanstack/react-query'
import type {
  AlertsResponse,
  BoardTasksResponse,
  FleetResponse,
  Health,
  QueueResponse,
  RunningResponse,
  TaskDetail,
} from './types'

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(`${status}: ${detail}`)
  }
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(path, { headers: { Accept: 'application/json' } })
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json()
      detail = body?.detail ?? detail
    } catch {
      // Non-JSON error body; the status text will do.
    }
    throw new ApiError(response.status, detail)
  }
  return response.json() as Promise<T>
}

/** Live views refetch on a slow heartbeat; the websocket carries the fast path. */
const SLOW_POLL = 60_000

export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: () => get<Health>('/api/health'),
    refetchInterval: 15_000,
  })
}

export function useFleet() {
  return useQuery({
    queryKey: ['fleet'],
    queryFn: () => get<FleetResponse>('/api/fleet'),
    refetchInterval: SLOW_POLL,
  })
}

export function useRunning() {
  return useQuery({
    queryKey: ['fleet', 'running'],
    queryFn: () => get<RunningResponse>('/api/fleet/running'),
    refetchInterval: 15_000,
  })
}

export function useAlerts() {
  return useQuery({
    queryKey: ['fleet', 'alerts'],
    queryFn: () => get<AlertsResponse>('/api/fleet/alerts'),
    refetchInterval: SLOW_POLL,
  })
}

export function useQueue(statuses?: string[]) {
  const query = statuses?.length
    ? `?${statuses.map((s) => `status=${encodeURIComponent(s)}`).join('&')}`
    : ''
  return useQuery({
    queryKey: ['fleet', 'queue', statuses ?? []],
    queryFn: () => get<QueueResponse>(`/api/fleet/queue${query}`),
    refetchInterval: SLOW_POLL,
  })
}

export function useBoardTasks(slug: string | undefined) {
  return useQuery({
    queryKey: ['board', slug],
    queryFn: () => get<BoardTasksResponse>(`/api/boards/${slug}/tasks?limit=2000`),
    enabled: Boolean(slug),
    refetchInterval: SLOW_POLL,
  })
}

export function useTask(slug: string | undefined, taskId: string | undefined) {
  return useQuery({
    queryKey: ['task', slug, taskId],
    queryFn: () => get<TaskDetail>(`/api/boards/${slug}/tasks/${taskId}`),
    enabled: Boolean(slug && taskId),
    refetchInterval: 30_000,
  })
}
