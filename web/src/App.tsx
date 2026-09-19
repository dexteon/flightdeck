/** Shell: nav, connection state, and the degraded-mode banner.
 *
 * The banner is the visible half of the degraded-mode contract. The structural half is
 * that every view above reads from our SQLite layer, so none of them goes blank when
 * Hermes stops answering; only the write affordances disappear.
 */

import { NavLink, Route, Routes } from 'react-router-dom'
import { useFleet, useHealth } from './api/client'
import { useFlightdeckSocket } from './api/ws'
import BoardView from './views/BoardView'
import FleetView from './views/FleetView'
import QueueView from './views/QueueView'
import WorkersView from './views/WorkersView'

function Nav() {
  const fleet = useFleet()
  const base =
    'px-3 py-1.5 rounded text-[12px] transition-colors hover:text-[var(--color-text)]'
  const link = ({ isActive }: { isActive: boolean }) =>
    `${base} ${isActive ? 'bg-[var(--color-surface-2)] text-[var(--color-text)]' : 'text-[var(--color-muted)]'}`

  return (
    <nav className="flex items-center gap-1">
      <NavLink to="/fleet" className={link}>
        Fleet
      </NavLink>
      <NavLink to="/workers" className={link}>
        Workers
        {!!fleet.data?.rollup.stale && (
          <span className="nums ml-1.5 text-[var(--color-danger)]">
            {fleet.data.rollup.stale}
          </span>
        )}
      </NavLink>
      <NavLink to="/queue" className={link}>
        Queue
      </NavLink>
    </nav>
  )
}

function ConnectionDot({ connected }: { connected: boolean }) {
  return (
    <span
      className="inline-block h-1.5 w-1.5 rounded-full"
      style={{ background: connected ? 'var(--color-ok)' : 'var(--color-faint)' }}
      title={connected ? 'live' : 'reconnecting'}
    />
  )
}

function HermesBanner() {
  const health = useHealth()
  const hermes = health.data?.hermes
  if (!hermes || hermes.state === 'UP') return null

  const down = hermes.state === 'DOWN'
  return (
    <div
      className="px-4 py-1.5 text-[12px]"
      style={{
        background: down ? 'color-mix(in srgb, var(--color-danger) 12%, transparent)' : 'color-mix(in srgb, var(--color-warn) 12%, transparent)',
        color: down ? 'var(--color-danger)' : 'var(--color-warn)',
      }}
    >
      <b>Hermes {hermes.state.toLowerCase()}</b>
      {hermes.reason ? ` (${hermes.reason})` : ''}. Reads are unaffected: this console
      reads the board databases directly. Writes and Hermes deep links are unavailable
      until the dashboard is back.
      {hermes.reason === 'token_scrape_failed' && (
        <> Set <code>HERMES_DASHBOARD_SESSION_TOKEN</code> to supply the token manually.</>
      )}
    </div>
  )
}

export default function App() {
  const socket = useFlightdeckSocket()
  const health = useHealth()

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex items-center gap-4 border-b border-[var(--color-line)] px-4 py-2">
        <span className="font-semibold tracking-tight">Flightdeck</span>
        <Nav />
        <div className="ml-auto flex items-center gap-3 text-[11px] text-[var(--color-faint)]">
          {health.data && (
            <span title="boards reporting">
              {health.data.boards.available}/{health.data.boards.total} boards
            </span>
          )}
          <span className="flex items-center gap-1.5">
            <ConnectionDot connected={socket.connected} />
            {socket.connected ? 'live' : 'reconnecting'}
          </span>
        </div>
      </header>

      <HermesBanner />

      <main className="relative min-h-0 flex-1 overflow-auto">
        <Routes>
          <Route path="/" element={<FleetView />} />
          <Route path="/fleet" element={<FleetView />} />
          <Route path="/workers" element={<WorkersView />} />
          <Route path="/queue" element={<QueueView />} />
          <Route path="/b/:slug" element={<BoardView />} />
          <Route path="/b/:slug/t/:taskId" element={<BoardView />} />
        </Routes>
      </main>
    </div>
  )
}
