import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

export function Shell() {
  const { rol, uitloggen } = useAuth()

  return (
    <div className="app">
      <div className="sidebar">
        <div className="logo">
          RLZ <span style={{ opacity: 0.6, fontWeight: 400 }}>Boekingsmodule</span>
        </div>
        <div className="sub">Administratiekantoor Nijenhuis</div>
        <div className="nav">
          <NavLink to="/" end className={({ isActive }) => (isActive ? 'active' : undefined)}>
            Werkvoorraad
          </NavLink>
          <NavLink to="/vragen" className={({ isActive }) => (isActive ? 'active' : undefined)}>
            Vragen
          </NavLink>
          {rol === 'beheerder' && (
            <NavLink to="/instellingen" className={({ isActive }) => (isActive ? 'active' : undefined)}>
              Instellingen
            </NavLink>
          )}
        </div>
        <div className="userbox">
          <b>{rol ?? 'Ingelogd'}</b>
          <button className="linkbtn" onClick={() => void uitloggen()}>
            Uitloggen
          </button>
        </div>
      </div>
      <div className="main">
        <Outlet />
      </div>
    </div>
  )
}
