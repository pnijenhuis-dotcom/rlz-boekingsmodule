// Shell — vormgeving 1:1 uit mockup/kantoor-modern.html (designpass-norm, akkoord Peter
// 2026-08-15): panel-sidebar met sectiekoppen + slanke topbar met thema-toggle. Fase 1 =
// alleen vormgeving; de navigatie-items en routes zijn ongewijzigd (IA-verbouwing = fase 2).
import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { PasskeyToevoegenBanner } from '../auth/PasskeyToevoegenBanner'
import { isMonoKlant, planningMenuPad, useMijnToegang } from '../auth/useMijnToegang'
import { useAdministraties } from '../werkvoorraad/useAdministraties'
import { ThemaKnop } from '../ui/ThemaKnop'
import { WatIsNieuwKnop } from '../changelog/WatIsNieuw'
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
  // C1/C2 (25-08): mono-klant-medewerker ziet geen Werkvoorraad maar zijn klantpagina; Planning
  // als eigen hoofdmenu-item volgt module-recht + opt-in. Fail-closed: geen toegang-data = het
  // gewone menu.
  const toegang = useMijnToegang()
  const { administraties } = useAdministraties()
  const monoKlant = isMonoKlant(toegang, administraties)
  const planningPad = planningMenuPad(toegang)

  return (
    <ToastProvider>
      <div className="app">
        <nav className="sidebar" aria-label="Hoofdnavigatie">
          <div className="logo">
            {/* Definitief beeldmerk (besluit 18-08, geometrie ongewijzigd) — gegenereerd uit
                mockup/app-icoon-n.svg via native/scripts/genereer_assets.sh; ook de favicon. */}
            <img className="logo-mark" src="/beeldmerk-n.svg" alt="" aria-hidden />
            <div>
              <b>Nijenhuis</b>
              <small>Boekingsmodule</small>
            </div>
          </div>
          {/* IA-besluit 15-08: Vragen en Bank zijn geen eigen tabbladen meer — alles van één
              klant leeft op de klantpagina; kantoorbrede dwarsdoorsneden via de klikbare
              KPI-kaarten bovenaan de werkvoorraad. */}
          <div className="nav-kop">Werk</div>
          {monoKlant && administraties ? (
            <NavItem to={`/?administratie=${administraties[0].id}`}>{administraties[0].naam}</NavItem>
          ) : (
            <NavItem to="/" end>
              Werkvoorraad
            </NavItem>
          )}
          {planningPad && <NavItem to={planningPad}>Planning</NavItem>}
          <div className="nav-kop">Inzicht</div>
          <NavItem to="/zoeken">Zoeken</NavItem>
          <NavItem to="/archief">Archief</NavItem>
          {/* Voorraad-aansluiting (blok D 28-08): controle-laag per administratie mét de opt-in
              "Voorraad bijhouden" — het scherm zelf meldt leesbaar als de opt-in uit staat. */}
          <NavItem to="/voorraad">Voorraad</NavItem>
          {/* Terugkerende facturen (blok B 30-08): signaal-overzicht per administratie. */}
          <NavItem to="/terugkerend">Terugkerende facturen</NavItem>
          {/* Crediteuren-dubbelsignalering (Instellingen v3, 01-09): een signaleringsscherm, geen
              instelling — daarom onder Inzicht; rolpoort ongewijzigd (Beheerder, backend 403). */}
          {rol === 'beheerder' && <NavItem to="/crediteuren">Crediteuren</NavItem>}
          <div className="nav-kop">Beheer</div>
          {/* Gebruikers & toegang (fase 3, 15-08) is Beheerder-only — het endpoint weigert
              andere rollen, dus het menu-item verschijnt daar ook niet. */}
          {rol === 'beheerder' && <NavItem to="/gebruikers">Gebruikers</NavItem>}
          {/* Sinds kantoor-passkeys (besluit 0020) voor élke kantoor-rol: niet-Beheerders zien
              er alleen de Beveiliging-sectie (eigen passkeys). */}
          <NavItem to="/instellingen">Instellingen</NavItem>
          <div className="onder">Administratiekantoor Nijenhuis</div>
        </nav>
        <div className="main">
          <div className="shell-topbar">
            <div className="spacer" />
            {/* "Wat is nieuw" (D1, 01-09): hand-gecureerd changelog + ongelezen-dot per gebruiker. */}
            <WatIsNieuwKnop />
            <ThemaKnop />
            <div className="userbox">
              <b>{rol ?? 'Ingelogd'}</b>
              <button className="linkbtn" onClick={() => void uitloggen()}>
                Uitloggen
              </button>
            </div>
          </div>
          <div className="content">
            {/* Eenmalig ná een cross-device-passkey-login (28-08): passkey op dít apparaat toevoegen. */}
            <PasskeyToevoegenBanner />
            <Outlet />
          </div>
        </div>
      </div>
    </ToastProvider>
  )
}
