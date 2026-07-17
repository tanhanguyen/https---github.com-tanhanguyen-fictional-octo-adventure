import { NavLink, Route, Routes } from 'react-router-dom'
import './App.css'
import { ConfigPage } from './pages/ConfigPage'
import { Dashboard } from './pages/Dashboard'
import { DecisionsPage } from './pages/DecisionsPage'
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
        <NavLink to="/decisions" className={({ isActive }) => (isActive ? 'active' : '')}>
          Decisions
        </NavLink>
        <NavLink to="/trades" className={({ isActive }) => (isActive ? 'active' : '')}>
          Trades
        </NavLink>
      </nav>
      <main className="app-main">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/config" element={<ConfigPage />} />
          <Route path="/decisions" element={<DecisionsPage />} />
          <Route path="/trades" element={<TradesPage />} />
        </Routes>
      </main>
    </div>
  )
}

export default App
