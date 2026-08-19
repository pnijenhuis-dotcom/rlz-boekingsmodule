// Accordeur-PWA — eigen minimale shell op /accordeur (géén kantoor-navigatie; route-based
// code splitting: dit bestand is een lazy chunk, zie App.tsx). Mockup/accordeur.html is het
// goedgekeurde ontwerp (eindakkoord Peter 2026-08-11): mobiel leading, dark default
// (systeemvolgend, ◐ = handmatige override), biometrie-ontgrendeling bij app-opening.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import type { TokenPaarResponseDto } from '../api/types'
import './accordeur.css'
import { AccordeurLogin } from './AccordeurLogin'
import { AccordeurActiveren } from './AccordeurActiveren'
import { GoedkeurenFlow } from './GoedkeurenFlow'
import { installeerNativeTapAfhandeling } from './nativePush'
import { Ontgrendel } from './Ontgrendel'

const ONTGRENDELD_VLAG = 'accordeur-ontgrendeld'
const THEMA_SLEUTEL = 'accordeur-thema'

type ThemaKeuze = 'donker' | 'licht' | null

/** Dark = default, systeemvolgend bij openen; handmatige override in localStorage
 * (besluit Peter 2026-08-11, mobiele review). */
function useThema(): { licht: boolean; wissel: () => void } {
  const [keuze, setKeuze] = useState<ThemaKeuze>(() => {
    const bewaard = localStorage.getItem(THEMA_SLEUTEL)
    return bewaard === 'licht' || bewaard === 'donker' ? bewaard : null
  })
  const [systeemLicht, setSysteemLicht] = useState(
    () => window.matchMedia?.('(prefers-color-scheme: light)').matches ?? false,
  )
  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-color-scheme: light)')
    if (!mq) return
    const luister = (e: MediaQueryListEvent) => setSysteemLicht(e.matches)
    mq.addEventListener('change', luister)
    return () => mq.removeEventListener('change', luister)
  }, [])
  const licht = keuze === null ? systeemLicht : keuze === 'licht'
  const wissel = useCallback(() => {
    const nieuw: ThemaKeuze = licht ? 'donker' : 'licht'
    localStorage.setItem(THEMA_SLEUTEL, nieuw)
    setKeuze(nieuw)
  }, [licht])
  return { licht, wissel }
}

/** PWA-installeerbaarheid zonder service worker: manifest + iOS-metatags worden alleen op de
 * /accordeur-route geïnjecteerd. Bewust géén service worker (service-worker-les 2026-07-13:
 * een achtergebleven SW kaapt requests op een gedeelde dev-origin) — iOS-thuisscherm-
 * installatie én Chrome-installatie werken zonder; push (wél SW nodig) is expliciet
 * GCP-fase. */
function useManifest(): void {
  useEffect(() => {
    const vorigeTitel = document.title
    document.title = 'Nijenhuis Boekingsmodule'
    const elementen: HTMLElement[] = []
    const voegLink = (rel: string, href: string, type?: string) => {
      const el = document.createElement('link')
      el.rel = rel
      el.href = href
      if (type) el.type = type
      document.head.appendChild(el)
      elementen.push(el)
    }
    const voegMeta = (naam: string, inhoud: string) => {
      const el = document.createElement('meta')
      el.name = naam
      el.content = inhoud
      document.head.appendChild(el)
      elementen.push(el)
    }
    voegLink('manifest', '/accordeur.webmanifest')
    // Eigen favicon (het N-beeldmerk) — overstemt de kantoor-favicon uit index.html zolang
    // de accordeur-app gemonteerd is; opruimen bij unmount zet de kantoor-favicon terug.
    voegLink('icon', '/icons/accordeur-icoon.svg', 'image/svg+xml')
    voegLink('apple-touch-icon', '/icons/apple-touch-icon-accordeur.png')
    voegMeta('apple-mobile-web-app-capable', 'yes')
    voegMeta('apple-mobile-web-app-status-bar-style', 'black-translucent')
    voegMeta('theme-color', '#0e1514')
    return () => {
      elementen.forEach((el) => el.remove())
      document.title = vorigeTitel
    }
  }, [])
}

export default function AccordeurApp() {
  const { status, rol, inloggen, uitloggen } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const { licht, wissel } = useThema()
  useManifest()

  // "Geldig tot de app sluit": sessionStorage overleeft een reload binnen dezelfde
  // app-sessie, maar niet een koude start — precies de cadans (besluit 2026-08-11). De échte
  // verificatie is server-side (assertion + audit); dit vlaggetje bepaalt alleen wanneer het
  // ontgrendel-scherm terugkomt.
  const [ontgrendeld, setOntgrendeld] = useState(() => sessionStorage.getItem(ONTGRENDELD_VLAG) === '1')
  const [forceerLogin, setForceerLogin] = useState(false)

  // Native schil (fase 3): melding-tap → /accordeur-deep-link. No-op buiten de schil;
  // de auth-cadans blijft de poort (de app opent gewoon op ontgrendelen/login).
  useEffect(() => {
    installeerNativeTapAfhandeling()
  }, [])

  const naIngelogd = useCallback(
    (paar: TokenPaarResponseDto) => {
      inloggen(paar)
      sessionStorage.setItem(ONTGRENDELD_VLAG, '1')
      setOntgrendeld(true)
      setForceerLogin(false)
      // Vanaf /activeren expliciet DOOR naar de flow (kliktest Peter 2026-08-15, 2e
      // reproductie): zonder deze navigatie bleef het scherm ná een geslaagde registratie
      // op de registratiestap staan — het setup-token in de navigation-state won het in de
      // render-vertakking van de ingelogde status, en niets ruimde de /activeren-route op.
      if (location.pathname.endsWith('/activeren')) void navigate('/accordeur', { replace: true })
    },
    [inloggen, location.pathname, navigate],
  )

  // Uitloggen (kliktest 2026-08-12): trekt server-side de refresh-sessie in via het
  // cookie-pad (/auth/token/vernieuwen/logout, zie AuthContext) en zet de PWA terug naar
  // het login-scherm; het ontgrendeld-vlaggetje gaat mee weg zodat een volgende sessie
  // altijd opnieuw bij login/ontgrendelen begint.
  const uitloggenAccordeur = useCallback(async () => {
    await uitloggen()
    sessionStorage.removeItem(ONTGRENDELD_VLAG)
    setOntgrendeld(false)
  }, [uitloggen])

  const opActiveren = location.pathname.endsWith('/activeren')
  const activatieToken = useMemo(() => {
    const state = location.state as { passkeySetupToken?: string } | null
    return opActiveren ? (state?.passkeySetupToken ?? null) : null
  }, [location, opActiveren])

  // Token-loos /activeren (kliktest 2026-08-15): het setup-token leeft alleen in de
  // navigation-state en is na een refresh weg — zonder deze branch viel de app stil terug
  // op de status-branches. Eén duidelijke actie: opnieuw inloggen; de nieuwe-apparaat-route
  // (AccordeurLogin → passkey_setup_token) vangt de registratie daarna gewoon op.
  const naarLoginNaVerlopenSessie = useCallback(() => {
    setForceerLogin(true)
    void navigate('/accordeur', { replace: true })
  }, [navigate])

  if (status === 'ingelogd' && rol !== null && rol !== 'klant_accordeur') {
    // Kantoor-rollen horen in de web-app; de PWA is uitsluitend de accordeer-wachtrij.
    return <Navigate to="/" replace />
  }

  let inhoud: React.ReactNode
  if (activatieToken) {
    inhoud = <AccordeurActiveren passkeySetupToken={activatieToken} naIngelogd={naIngelogd} />
  } else if (opActiveren && status !== 'uitgelogd') {
    // Zelfherstel (kliktest 2026-08-15, 2e reproductie): scherm herladen ná een geslaagde
    // registratie = token-loos /activeren mét een levende sessie (de silent refresh op de
    // httpOnly-cookie is de server-side waarheid). Dan is "Sessie verlopen" fout — door naar
    // de flow (voorwaarden-poort zit fail-closed in GoedkeurenFlow; koude start → Ontgrendel).
    // Tijdens status 'laden' rendert de Navigate nog niet: eerst weten of de sessie leeft.
    inhoud =
      status === 'ingelogd' ? (
        <Navigate to="/accordeur" replace />
      ) : (
        <div className="acc-vol">
          <div className="acc-appnaam">
            RLZ <span>Goedkeuren</span>
          </div>
          <div className="acc-bio">
            <div className="acc-sub">Laden…</div>
          </div>
        </div>
      )
  } else if (opActiveren) {
    inhoud = (
      <div className="acc-vol">
        <div className="acc-appnaam">
          RLZ <span>Goedkeuren</span>
        </div>
        <div className="acc-bio">
          <div className="acc-icoon">☉</div>
          <b>Sessie verlopen</b>
          <div className="acc-sub">
            Deze activatiestap is verlopen (bijvoorbeeld door de pagina te verversen). Log opnieuw
            in met je e-mailadres en wachtwoord — daarna kun je dit apparaat direct registreren.
          </div>
        </div>
        <button className="acc-btn groen" onClick={naarLoginNaVerlopenSessie}>
          Opnieuw inloggen
        </button>
      </div>
    )
  } else if (status === 'laden') {
    inhoud = (
      <div className="acc-vol">
        <div className="acc-appnaam">
          RLZ <span>Goedkeuren</span>
        </div>
        <div className="acc-bio">
          <div className="acc-sub">Laden…</div>
        </div>
      </div>
    )
  } else if (status === 'uitgelogd' || forceerLogin) {
    inhoud = <AccordeurLogin naIngelogd={naIngelogd} />
  } else if (!ontgrendeld) {
    inhoud = <Ontgrendel naOntgrendeld={naIngelogd} naarLogin={() => setForceerLogin(true)} />
  } else {
    inhoud = <GoedkeurenFlow wisselThema={wissel} uitloggen={uitloggenAccordeur} />
  }

  return (
    <div className="acc" data-thema={licht ? 'licht' : undefined}>
      <div className="acc-phone">{inhoud}</div>
    </div>
  )
}
