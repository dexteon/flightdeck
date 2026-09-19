/** The single websocket, and the rule that makes it cheap.
 *
 * Incoming frames are applied as cache patches via `setQueryData`, never as refetch
 * triggers. That is the difference between a quiet UI and a render storm: heartbeats are
 * 5516 of the 16218 events on `ai-fraud-guide`, and a board payload is 1098 tasks. Only
 * a `resync` invalidates.
 */

import { useEffect, useRef, useState } from 'react'
import { useQueryClient, type QueryClient } from '@tanstack/react-query'
import type { BoardTasksResponse, HermesState, Task, TaskEvent } from './types'

type Frame =
  | { type: 'hello'; boards: unknown[]; cursors: Record<string, number>; hermes: HermesState }
  | { type: 'events'; board: string; events: TaskEvent[]; cursor: number }
  | { type: 'tasks'; board: string; tasks: Task[] }
  | { type: 'board_state'; board: string; state: string; reason: string | null }
  | { type: 'hermes_state'; hermes: HermesState }
  | { type: 'resync'; board: string; cursor: number; reason: string }
  | { type: 'log'; board: string; task_id: string; chunk: string; offset: number }
  | { type: 'pong' }

const RECONNECT_MIN = 1_000
const RECONNECT_MAX = 30_000

function patchBoardTasks(client: QueryClient, board: string, incoming: Task[]): void {
  client.setQueryData<BoardTasksResponse>(['board', board], (previous) => {
    if (!previous) return previous
    const byId = new Map(previous.tasks.map((t) => [t.id, t]))
    for (const task of incoming) byId.set(task.id, { ...byId.get(task.id), ...task })
    return { ...previous, tasks: [...byId.values()] }
  })
  for (const task of incoming) {
    client.setQueryData(['task', board, task.id], (previous: unknown) => {
      if (!previous || typeof previous !== 'object') return previous
      const detail = previous as { task: Task }
      return { ...detail, task: { ...detail.task, ...task } }
    })
  }
}

export interface WsStatus {
  connected: boolean
  hermes: HermesState | null
  lastFrameAt: number | null
}

export function useFlightdeckSocket(): WsStatus {
  const client = useQueryClient()
  const [status, setStatus] = useState<WsStatus>({
    connected: false,
    hermes: null,
    lastFrameAt: null,
  })
  const cursors = useRef<Record<string, number>>({})
  const backoff = useRef(RECONNECT_MIN)

  useEffect(() => {
    let socket: WebSocket | null = null
    let timer: number | undefined
    let closed = false

    const connect = () => {
      const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
      socket = new WebSocket(`${scheme}://${window.location.host}/ws`)

      socket.onopen = () => {
        backoff.current = RECONNECT_MIN
        setStatus((s) => ({ ...s, connected: true }))
        socket?.send(
          JSON.stringify({ type: 'subscribe', boards: ['*'], since: cursors.current }),
        )
      }

      socket.onmessage = (message) => {
        const frame = JSON.parse(message.data as string) as Frame
        setStatus((s) => ({ ...s, lastFrameAt: Date.now() }))

        switch (frame.type) {
          case 'hello':
            cursors.current = frame.cursors
            setStatus((s) => ({ ...s, hermes: frame.hermes }))
            break
          case 'events':
            cursors.current[frame.board] = frame.cursor
            // Alerts and the fleet rollup are derived, so let their slow poll carry
            // them rather than recomputing on every heartbeat.
            break
          case 'tasks':
            patchBoardTasks(client, frame.board, frame.tasks)
            break
          case 'hermes_state':
            setStatus((s) => ({ ...s, hermes: frame.hermes }))
            void client.invalidateQueries({ queryKey: ['health'] })
            break
          case 'board_state':
            void client.invalidateQueries({ queryKey: ['fleet'] })
            break
          case 'resync':
            cursors.current[frame.board] = frame.cursor
            void client.invalidateQueries({ queryKey: ['board', frame.board] })
            break
          default:
            break
        }
      }

      const retry = () => {
        setStatus((s) => ({ ...s, connected: false }))
        if (closed) return
        timer = window.setTimeout(connect, backoff.current + Math.random() * 500)
        backoff.current = Math.min(backoff.current * 2, RECONNECT_MAX)
      }

      socket.onclose = retry
      socket.onerror = () => socket?.close()
    }

    connect()
    return () => {
      closed = true
      window.clearTimeout(timer)
      socket?.close()
    }
  }, [client])

  return status
}
