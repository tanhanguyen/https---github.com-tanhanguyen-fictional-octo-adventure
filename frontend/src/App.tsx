import type { ReactNode } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import './App.css'
import { AlertCenter } from './components/AlertCenter'
import { ErrorBoundary } from './components/ErrorBoundary'
import { GlobalErrorToasts } from './components/GlobalErrorToasts'
import { LiveBadge } from './components/LiveBadge'
import { TokenGate } from './components/TokenGate'
import { ConfigPage } from './pages/ConfigPage'
import { Dashboard } from './pages/Dashboard'
import { DatasetsPage } from './pages/DatasetsPage'
import { DecisionsPage } from './pages/DecisionsPage'
import { RunReportPage } from './pages/RunReportPage'
import { RunsPage } from './pages/RunsPage'
import { TradesPage } from './pages/TradesPage'

function App() {
  return (
    <div className="app-shell">
      <nav className="app-nav">
        <span className="brand">Trading Bot</span>
        <NavLink to="/" end className={({ isActive }) => (isActive ? 'active' : '')}>
          Dashboard
        </NavLink>
        <NavLink to="/config" className={({ isActive }) => (isActive ? 'active' : '')}>
          Config
        </NavLink>
        <NavLink to="/datasets" className={({ isActive }) => (isActive ? 'active' : '')}>
          Datasets
        </NavLink>
        <NavLink to="/decisions" className={({ isActive }) => (isActive ? 'active' : '')}>
          Decisions
        </NavLink>
        <NavLink to="/trades" className={({ isActive }) => (isActive ? 'active' : '')}>
          Trades
        </NavLink>
        <NavLink to="/runs" className={({ isActive }) => (isActive ? 'active' : '')}>
          Runs
        </NavLink>
        <LiveBadge />
        <AlertCenter />
        <TokenGate />
      </nav>
      <main className="app-main">
        <Routes>
          <Route path="/" element={page(<Dashboard />)} />
          <Route path="/config" element={page(<ConfigPage />)} />
          <Route path="/datasets" element={page(<DatasetsPage />)} />
          <Route path="/decisions" element={page(<DecisionsPage />)} />
          <Route path="/trades" element={page(<TradesPage />)} />
          <Route path="/runs" element={page(<RunsPage />)} />
          <Route path="/runs/:id/report" element={page(<RunReportPage />)} />
        </Routes>
      </main>
      <GlobalErrorToasts />
    </div>
  )
}

/** Each routed page gets its own error boundary so one page crashing never blanks the
 * whole app (plan 09 §3). */
function page(node: ReactNode) {
  return <ErrorBoundary>{node}</ErrorBoundary>
}

export default App
