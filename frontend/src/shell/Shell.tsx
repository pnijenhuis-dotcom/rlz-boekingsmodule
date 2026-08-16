// Shell — vormgeving 1:1 uit mockup/kantoor-modern.html (designpass-norm, akkoord Peter
// 2026-08-15): panel-sidebar met sectiekoppen + slanke topbar met thema-toggle. Fase 1 =
// alleen vormgeving; de navigatie-items en routes zijn ongewijzigd (IA-verbouwing = fase 2).
import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { ThemaKnop } from '../ui/ThemaKnop'
import { ToastProvider } from '../ui/basis'

function NavItem({ to, end, children }: { to: string; end?: boolean; children: React.ReactNode }) {
  return (
    <NavLink to={to} end={end} className={({ isActive }) => `nav-item${isActive ? ' actief' : ''}`}>
      {children}
    </NavLink>
  )
}

export function Shell() {
  const { rol, uitloggen } = useAuth()

  return (
    <ToastProvider>
      <div className="app">
        <nav className="sidebar" aria-label="Hoofdnavigatie">
          <div className="logo">
            <div className="logo-mark" aria-hidden>
              N
            </div>
            <div>
              <b>Nijenhuis</b>
              <small>Boekingsmodule</small>
            </div>
          </div>
          <div className="nav-kop">Werk</div>
          <NavItem to="/" end>
            Werkvoorraad
          </NavItem>
          <NavItem to="/bank">Bank</NavItem>
          <NavItem to="/vragen">Vragen</NavItem>
          <div className="nav-kop">Inzicht</div>
          <NavItem to="/zoeken">Zoeken</NavItem>
          <NavItem to="/archief">Archief</NavItem>
          <div className="nav-kop">Beheer</div>
          {/* Sinds kantoor-passkeys (besluit 0020) voor élke kantoor-rol: niet-Beheerders zien
              er alleen de Beveiliging-sectie (eigen passkeys). */}
          <NavItem to="/instellingen">Instellingen</NavItem>
          <div className="onder">Administratiekantoor Nijenhuis</div>
        </nav>
        <div className="main">
          <div className="shell-topbar">
            <div className="spacer" />
            <ThemaKnop />
            <div className="userbox">
              <b>{rol ?? 'Ingelogd'}</b>
              <button className="linkbtn" onClick={() => void uitloggen()}>
                Uitloggen
              </button>
            </div>
          </div>
          <div className="content">
            <Outlet />
          </div>
        </div>
      </div>
    </ToastProvider>
  )
}
