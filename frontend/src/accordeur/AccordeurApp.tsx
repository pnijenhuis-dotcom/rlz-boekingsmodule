// Accordeur-PWA — eigen minimale shell op /accordeur (géén kantoor-navigatie; route-based
// code splitting: dit bestand is een lazy chunk, zie App.tsx). Mockup/accordeur.html is het
// goedgekeurde ontwerp (eindakkoord Peter 2026-08-11): mobiel leading, dark default
// (systeemvolgend, ◐ = handmatige override), biometrie-ontgrendeling bij app-opening.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { isKantoorRol, isVeldRol } from '../auth/rollen'
import type { TokenPaarResponseDto } from '../api/types'
import './accordeur.css'
import { AccordeurLogin } from './AccordeurLogin'
import { AccordeurActiveren } from './AccordeurActiveren'
import { GoedkeurenFlow } from './GoedkeurenFlow'
import { installeerNativeTapAfhandeling } from './nativePush'
import { installeerNativeUrlAfhandeling } from './nativeAppUrl'
import { Ontgrendel } from './Ontgrendel'
import { UrenFlow } from '../uren/UrenFlow'
import {
  ACHTERGROND_VERGRENDEL_MS,
  appSlotBeschikbaar,
  isAppSlotIngesteld,
  isDirectVergrendelen,
  isOntgrendeld,
  stelCodeIn,
  vergrendel,
} from '../api/appSlot'
import { AppSlotScherm } from './appslot/AppSlotScherm'
import { PincodeKiezen } from './appslot/PincodeKiezen'
import { ToegangInstellingen } from './appslot/ToegangInstellingen'

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
    voegMeta('theme-color', '#0b0d0e')
    return () => {
      elementen.forEach((el) => el.remove())
      document.title = vorigeTitel
    }
  }, [])
}

export default function AccordeurApp() {
  const { status, rol, ontgrendelingNodig, inloggen, uitloggen } = useAuth()
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

  // App-lock (besluit Peter 31-08, mockup app-lock-pincode.html): in de native schil vervangt
  // het lokale slot (code = anker, Face ID = gemak) de 24-uurs passkey-assertion bij het
  // openen — de server-side sliding-refresh en kill-switch blijven ongewijzigd de poort. De
  // PWA/web houdt de bestaande Ontgrendel-cadans (scope-besluit).
  const nativeSlot = appSlotBeschikbaar()
  const [slotStatus, setSlotStatus] = useState<'laden' | 'geen' | 'vergrendeld' | 'ontgrendeld'>(
    nativeSlot ? 'laden' : 'geen',
  )
  const [toegangOpen, setToegangOpen] = useState(false)

  useEffect(() => {
    if (!nativeSlot) return
    void isAppSlotIngesteld().then((ingesteld) =>
      setSlotStatus(ingesteld ? (isOntgrendeld() ? 'ontgrendeld' : 'vergrendeld') : 'geen'),
    )
  }, [nativeSlot])

  // Vergrendelen bij achtergrond: "direct vergrendelen" aan = meteen bij het verlaten, uit =
  // pas ná 5 minuten achtergrond (mockup scherm 7). Een koude start is sowieso vergrendeld
  // (het anker leeft alleen in het geheugen).
  useEffect(() => {
    if (!nativeSlot) return
    let verborgenSinds: number | null = null
    const naarSlot = () => {
      vergrendel()
      setToegangOpen(false)
      setSlotStatus('vergrendeld')
    }
    const opWissel = () => {
      if (document.visibilityState === 'hidden') {
        verborgenSinds = Date.now()
        void isDirectVergrendelen().then((direct) => {
          if (direct && isOntgrendeld()) naarSlot()
        })
        return
      }
      if (isOntgrendeld() && verborgenSinds !== null && Date.now() - verborgenSinds > ACHTERGROND_VERGRENDEL_MS) {
        naarSlot()
      }
      verborgenSinds = null
    }
    document.addEventListener('visibilitychange', opWissel)
    return () => document.removeEventListener('visibilitychange', opWissel)
  }, [nativeSlot])

  // Ontgrendel-frequentie (besluit Peter 27-08): hooguit 1× per 24 uur per apparaat. De stille
  // refresh bij het openen draagt de server-uitspraak (venster op het apparaat, geen client-
  // klok): false = de laatste passkey-ceremonie is jonger dan 24 u → direct door, ook bij een
  // koude start; true/null = het bestaande gedrag (ontgrendelscherm, tenzij al ontgrendeld in
  // deze app-sessie). De 7-dagen-inactiviteitsregel en de kill-switch zitten in de refresh zelf.
  useEffect(() => {
    if (status === 'ingelogd' && ontgrendelingNodig === false && !ontgrendeld) {
      sessionStorage.setItem(ONTGRENDELD_VLAG, '1')
      setOntgrendeld(true)
    }
  }, [status, ontgrendelingNodig, ontgrendeld])

  // Native schil (fase 3): melding-tap → /accordeur-deep-link. No-op buiten de schil;
  // de auth-cadans blijft de poort (de app opent gewoon op ontgrendelen/login).
  useEffect(() => {
    installeerNativeTapAfhandeling()
    // Universal links (31-08): een activatie-/accordeur-mail-link die de app opent.
    installeerNativeUrlAfhandeling()
  }, [])

  const naIngelogd = useCallback(
    (paar: TokenPaarResponseDto) => {
      inloggen(paar)
      sessionStorage.setItem(ONTGRENDELD_VLAG, '1')
      setOntgrendeld(true)
      setForceerLogin(false)
      // App-lock: ná een activatie staat het slot al (ontgrendeld); ná een her-login is het
      // bewust gewist — de gebruiker kiest dan opnieuw een code (setup-branch hieronder).
      if (nativeSlot) {
        void isAppSlotIngesteld().then((ingesteld) =>
          setSlotStatus(ingesteld && isOntgrendeld() ? 'ontgrendeld' : ingesteld ? 'vergrendeld' : 'geen'),
        )
      }
      // Vanaf /activeren expliciet DOOR naar de flow (kliktest Peter 2026-08-15, 2e
      // reproductie): zonder deze navigatie bleef het scherm ná een geslaagde registratie
      // op de registratiestap staan — het setup-token in de navigation-state won het in de
      // render-vertakking van de ingelogde status, en niets ruimde de /activeren-route op.
      if (location.pathname.endsWith('/activeren')) void navigate('/accordeur', { replace: true })
    },
    [inloggen, location.pathname, navigate, nativeSlot],
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

  // App-lock-handlers (native): ontgrendeld = verse sessie uit de stille refresh; naar login =
  // de sessie was server-side dood en het slot is al lokaal gewist (AppSlotScherm).
  const naSlotOntgrendeld = useCallback(
    (paar: TokenPaarResponseDto) => {
      setSlotStatus('ontgrendeld')
      naIngelogd(paar)
    },
    [naIngelogd],
  )
  const naSlotNaarLogin = useCallback(() => {
    setSlotStatus('geen')
    setForceerLogin(true)
  }, [])
  const uitloggenVanToegang = useCallback(async () => {
    setToegangOpen(false)
    setSlotStatus('geen')
    await uitloggenAccordeur()
  }, [uitloggenAccordeur])
  const openToegang = nativeSlot && slotStatus === 'ontgrendeld' ? () => setToegangOpen(true) : undefined

  const opActiveren = location.pathname.endsWith('/activeren')
  const activatieToken = useMemo(() => {
    const state = location.state as { passkeySetupToken?: string } | null
    return opActiveren ? (state?.passkeySetupToken ?? null) : null
  }, [location, opActiveren])
  // Mobiel-first + atomaire activatie (28-08): het /activeren-scherm van de kantoor-bundel
  // stuurt externe rollen hierheen mét de uitnodigingslink in de URL (`?uitnodiging=`), zodat
  // de drie stappen (wachtwoord → passkey → klaar) in de app-stijl lopen en een refresh de flow
  // gewoon opnieuw begint — de link blijft verzilverbaar tot de passkey staat.
  const uitnodigingToken = useMemo(() => {
    if (!opActiveren) return null
    const params = new URLSearchParams(location.search)
    return params.get('uitnodiging')
  }, [location.search, opActiveren])
  const uitnodigingHerstel = new URLSearchParams(location.search).get('herstel') === '1'

  // Token-loos /activeren (kliktest 2026-08-15): het setup-token leeft alleen in de
  // navigation-state en is na een refresh weg — zonder deze branch viel de app stil terug
  // op de status-branches. Eén duidelijke actie: opnieuw inloggen; de nieuwe-apparaat-route
  // (AccordeurLogin → passkey_setup_token) vangt de registratie daarna gewoon op.
  const naarLoginNaVerlopenSessie = useCallback(() => {
    setForceerLogin(true)
    void navigate('/accordeur', { replace: true })
  }, [navigate])

  const veldrol = isVeldRol(rol)
  if (status === 'ingelogd' && isKantoorRol(rol)) {
    // Kantoor-rollen horen in de web-app; deze surface is voor de externe app-rollen
    // (accordeur + veldrollen uren & meerwerk, migratie 0056 — zelfde auth-cadans).
    // Allowlist i.p.v. "niet accordeur/veld" (rollen-gate-fix 2026-08-21): een onbekende
    // rol blijft hier (en ziet niets — de backend geeft 403), in plaats van eindeloos
    // tussen de twee surfaces te ping-pongen.
    return <Navigate to="/" replace />
  }

  let inhoud: React.ReactNode
  if (uitnodigingToken) {
    inhoud = <AccordeurActiveren uitnodigingToken={uitnodigingToken} herstel={uitnodigingHerstel} naIngelogd={naIngelogd} />
  } else if (activatieToken) {
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
            Nijenhuis <span>Boekingsmodule</span>
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
          Nijenhuis <span>Boekingsmodule</span>
        </div>
        <div className="acc-bio">
          <div className="acc-icoon">☉</div>
          <b>Sessie verlopen</b>
          <div className="acc-sub">
            Deze activatiestap is verlopen (bijvoorbeeld door de pagina te verversen). Log opnieuw
            in met je e-mailadres en wachtwoord — daarna kun je dit apparaat direct registreren.
          </div>
        </div>
        <button className="acc-btn primair" onClick={naarLoginNaVerlopenSessie}>
          Opnieuw inloggen
        </button>
      </div>
    )
  } else if (nativeSlot && slotStatus === 'laden') {
    // Native: eerst weten of er een slot staat vóór er iets anders toont — een vergrendeld slot
    // wint van het login-scherm (de stille refresh faalt bewust zolang het refresh-token op
    // slot staat).
    inhoud = (
      <div className="acc-vol">
        <div className="acc-appnaam">
          Nijenhuis <span>Boekingsmodule</span>
        </div>
        <div className="acc-bio">
          <div className="acc-sub">Laden…</div>
        </div>
      </div>
    )
  } else if (nativeSlot && slotStatus === 'vergrendeld' && !forceerLogin) {
    inhoud = <AppSlotScherm naOntgrendeld={naSlotOntgrendeld} naarLogin={naSlotNaarLogin} />
  } else if (status === 'laden') {
    inhoud = (
      <div className="acc-vol">
        <div className="acc-appnaam">
          Nijenhuis <span>Boekingsmodule</span>
        </div>
        <div className="acc-bio">
          <div className="acc-sub">Laden…</div>
        </div>
      </div>
    )
  } else if (status === 'uitgelogd' || forceerLogin) {
    inhoud = <AccordeurLogin naIngelogd={naIngelogd} />
  } else if (nativeSlot && slotStatus === 'geen') {
    // Slot instellen: ná een her-login (slot bewust gewist) of op een legacy-toestel van vóór
    // 31-08 — de code is verplicht vóór de app verdergaat (het refresh-token gaat erachter).
    inhoud = (
      <PincodeKiezen
        onGekozen={(codeNieuw) => {
          void stelCodeIn(codeNieuw).then(() => setSlotStatus('ontgrendeld'))
        }}
      />
    )
  } else if (!ontgrendeld && !nativeSlot) {
    inhoud = <Ontgrendel naOntgrendeld={naIngelogd} naarLogin={() => setForceerLogin(true)} />
  } else if (toegangOpen && nativeSlot) {
    inhoud = <ToegangInstellingen sluit={() => setToegangOpen(false)} uitloggen={uitloggenVanToegang} />
  } else if (veldrol) {
    // Uren & meerwerk (fase 4, mockup/uren-uitvoerder.html): zelfde app, rolafhankelijke tabs.
    inhoud = <UrenFlow wisselThema={wissel} uitloggen={uitloggenAccordeur} openToegang={openToegang} />
  } else {
    inhoud = <GoedkeurenFlow wisselThema={wissel} uitloggen={uitloggenAccordeur} openToegang={openToegang} />
  }

  return (
    <div className="acc" data-thema={licht ? 'licht' : undefined}>
      <div className="acc-phone">{inhoud}</div>
    </div>
  )
}
