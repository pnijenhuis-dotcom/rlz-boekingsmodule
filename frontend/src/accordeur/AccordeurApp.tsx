// Accordeur-/veldwerker-app — eigen minimale shell op /accordeur (géén kantoor-navigatie; route-
// based code splitting: dit bestand is een lazy chunk, zie App.tsx). Mockup/accordeur.html is het
// goedgekeurde ontwerp (eindakkoord Peter 2026-08-11): mobiel leading, dark default
// (systeemvolgend, ◐ = handmatige override).
//
// Toegang (app-auth zonder passkey en TOTP, besluit Peter 08-09-2026, contract §5c): precies één pad —
// uitnodiging → activatie op dít toestel (AppActiveren: link óf activatiecode) → 5-cijferige
// toegangscode (app-slot, mockup app-lock-pincode.html). Native én PWA volgen hetzelfde model; het
// slot bewaakt het toestel-token, de server-side sliding-TTL en kill-switch blijven de poort.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { isKantoorRol, isVeldRol } from '../auth/rollen'
import type { TokenPaarResponseDto } from '../api/types'
import './accordeur.css'
import { AppActiveren, TOEGANG_VERLOPEN_MELDING } from './AppActiveren'
import { GoedkeurenFlow } from './GoedkeurenFlow'
import { installeerNativeTapAfhandeling } from './nativePush'
import { installeerNativeUrlAfhandeling } from './nativeAppUrl'
import { UrenFlow } from '../uren/UrenFlow'
import {
  ACHTERGROND_VERGRENDEL_MS,
  appSlotBeschikbaar,
  isAppSlotIngesteld,
  isDirectVergrendelen,
  isOntgrendeld,
  stelCodeIn,
  vergrendel,
  wisAppSlotLokaal,
} from '../api/appSlot'
import { webSlotOnmogelijkOpAccordeur } from '../api/webVeiligeOpslag'
import { AppSlotScherm } from './appslot/AppSlotScherm'
import { PincodeKiezen } from './appslot/PincodeKiezen'
import { SlotOpslagFout } from './appslot/SlotOpslagFout'
import { ToegangInstellingen } from './appslot/ToegangInstellingen'
import { schrijfAppSlotAudit } from './appAuthApi'
import { markeer } from './koudeStart'
import { wisAlleStanden } from './standCache'

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
  const { status, rol, inloggen, uitloggen } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const { licht, wissel } = useThema()
  useManifest()

  // App-slot (besluit Peter 31-08, mockup app-lock-pincode.html; sinds 08-09 óók in de PWA): het
  // lokale slot (code = anker, Face ID = gemak) bewaakt het refresh-token; de server-side
  // sliding-refresh en kill-switch blijven ongewijzigd de poort. `slotKan` is false alleen zonder
  // veilige opslag (web zonder secure context) — dan kan de app niet werken en zegt dat eerlijk.
  const slotKan = appSlotBeschikbaar()
  const [slotStatus, setSlotStatus] = useState<'laden' | 'geen' | 'vergrendeld' | 'ontgrendeld'>(
    slotKan ? 'laden' : 'geen',
  )
  const [toegangOpen, setToegangOpen] = useState(false)
  // Legacy-pad (PincodeKiezen zonder slot): eerste opslag van de code mislukt → melding i.p.v. doorgang (10-09 (2)).
  const [legacySlotFout, setLegacySlotFout] = useState(false)
  // Melding op het activatiescherm ná een server-side dode sessie (kill-switch / 7-dagen-TTL).
  const [toegangVerlopen, setToegangVerlopen] = useState(false)

  useEffect(() => {
    if (!slotKan) return
    void isAppSlotIngesteld().then((ingesteld) => {
      setSlotStatus(ingesteld ? (isOntgrendeld() ? 'ontgrendeld' : 'vergrendeld') : 'geen')
      markeer('slot-status')
    })
  }, [slotKan])

  // Vergrendelen bij achtergrond: "direct vergrendelen" aan = meteen bij het verlaten, uit =
  // pas ná 5 minuten achtergrond (mockup scherm 7). Een koude start is sowieso vergrendeld
  // (het anker leeft alleen in het geheugen).
  useEffect(() => {
    if (!slotKan) return
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
  }, [slotKan])

  // Koude-start-meting (D1 06-09): het moment waarop er een access-token is.
  useEffect(() => {
    if (status === 'ingelogd') markeer('sessie')
  }, [status])

  // Sessie server-side dood terwijl het slot open stond (kill-switch, 7-dagen-TTL → 401 op een
  // gewone request): het slot is dan waardeloos — lokaal wissen, stand-cache mee weg (D2: die
  // leeft nooit langer dan zijn sessie) en terug naar het activatiescherm mét melding.
  useEffect(() => {
    if (status === 'uitgelogd' && slotStatus === 'ontgrendeld') {
      void wisAppSlotLokaal().then(() => {
        wisAlleStanden()
        setToegangOpen(false)
        setSlotStatus('geen')
        setToegangVerlopen(true)
      })
    }
  }, [status, slotStatus])

  // Native schil (fase 3): melding-tap → /accordeur-deep-link. No-op buiten de schil;
  // de slot-cadans blijft de poort (de app opent gewoon op het slot/de activatie).
  useEffect(() => {
    markeer('app-render')
    installeerNativeTapAfhandeling()
    // Universal links (31-08): een activatie-/accordeur-mail-link die de app opent.
    installeerNativeUrlAfhandeling()
  }, [])

  const opActiveren = location.pathname.endsWith('/activeren')
  // Mobiel-first activatie externe rollen (28-08): het kantoor-/activeren-scherm en de universal
  // link sturen hierheen mét de uitnodigingslink in de URL (`?uitnodiging=`); een refresh begint
  // de flow gewoon opnieuw — de link blijft verzilverbaar tot het toestel gekoppeld is.
  const uitnodigingToken = useMemo(() => {
    if (!opActiveren) return null
    return new URLSearchParams(location.search).get('uitnodiging')
  }, [location.search, opActiveren])
  const uitnodigingHerstel = new URLSearchParams(location.search).get('herstel') === '1'

  /** Ná activatie + toegangscode (AppActiveren): sessie starten (AuthContext bewaart het refresh-
   * token versleuteld — het slot staat al open), slot = ontgrendeld en dóór naar de flow. Vanaf
   * /activeren expliciet navigeren (kliktest 2026-08-15: anders bleef de activatieroute staan),
   * mét behoud van een `?document=`-deeplink uit de oorspronkelijke URL. */
  const naGeactiveerd = useCallback(
    (paar: TokenPaarResponseDto) => {
      inloggen(paar)
      setToegangVerlopen(false)
      setSlotStatus('ontgrendeld')
      if (opActiveren) {
        const document = new URLSearchParams(location.search).get('document')
        void navigate(document ? `/accordeur?document=${encodeURIComponent(document)}` : '/accordeur', { replace: true })
      }
    },
    [inloggen, location.search, navigate, opActiveren],
  )

  // Slot-handlers: ontgrendeld = verse sessie uit de stille refresh; sessie dood = het slot is al
  // lokaal gewist (AppSlotScherm) → activatiescherm mét melding (§5c).
  const naSlotOntgrendeld = useCallback(
    (paar: TokenPaarResponseDto) => {
      inloggen(paar)
      setSlotStatus('ontgrendeld')
    },
    [inloggen],
  )
  const naSlotSessieDood = useCallback(() => {
    wisAlleStanden()
    setSlotStatus('geen')
    setToegangVerlopen(true)
  }, [])

  // Header-"Vergrendelen" (tot 08-09 "Uitloggen") in de flow = de app vergrendelen (ING-model: het toestel blijft gekoppeld,
  // de volgende opening vraagt de toegangscode). Echt loskoppelen (server-side intrekken + slot
  // wissen) zit in ⚙ Toegang tot de app → "Dit toestel loskoppelen".
  const vergrendelApp = useCallback(async () => {
    vergrendel()
    setToegangOpen(false)
    setSlotStatus('vergrendeld')
  }, [])
  // Loskoppelen vanuit ⚙ Toegang: server-side intrekken + lokaal alles weg → activatiescherm.
  const losgekoppeld = useCallback(async () => {
    setToegangOpen(false)
    setSlotStatus('geen')
    setToegangVerlopen(false)
    wisAlleStanden()
    await uitloggen()
  }, [uitloggen])
  const openToegang = slotStatus === 'ontgrendeld' ? () => setToegangOpen(true) : undefined

  const veldrol = isVeldRol(rol)
  if (status === 'ingelogd' && isKantoorRol(rol)) {
    // Kantoor-rollen horen in de web-app; deze surface is voor de externe app-rollen
    // (accordeur + veldrollen uren & meerwerk, migratie 0056 — zelfde auth-cadans).
    // Allowlist i.p.v. "niet accordeur/veld" (rollen-gate-fix 2026-08-21): een onbekende
    // rol blijft hier (en ziet niets — de backend geeft 403), in plaats van eindeloos
    // tussen de twee surfaces te ping-pongen.
    return <Navigate to="/" replace />
  }

  const laden = (
    <div className="acc-vol">
      <div className="acc-appnaam">
        Nijenhuis <span>Boekingsmodule</span>
      </div>
      <div className="acc-bio">
        <div className="acc-sub">Laden…</div>
      </div>
    </div>
  )

  let inhoud: React.ReactNode
  if (!slotKan && webSlotOnmogelijkOpAccordeur()) {
    // Web zonder secure context (http-LAN-adres): geen WebCrypto → geen slot → geen app.
    inhoud = (
      <div className="acc-vol">
        <div className="acc-appnaam">
          Nijenhuis <span>Boekingsmodule</span>
        </div>
        <div className="acc-bio">
          <div className="acc-icoon">☉</div>
          <b>Beveiligde verbinding nodig</b>
          <div className="acc-sub">
            Deze app werkt alleen via een beveiligde verbinding (https) of in de app uit de App Store / Google Play.
            Open de link uit de uitnodiging opnieuw op je telefoon.
          </div>
        </div>
      </div>
    )
  } else if (slotStatus === 'laden') {
    // Eerst weten of er een slot staat vóór er iets anders toont — een vergrendeld slot wint van
    // het activatiescherm (de stille refresh slaat bewust over zolang het token op slot staat).
    inhoud = laden
  } else if (slotStatus === 'vergrendeld') {
    inhoud = <AppSlotScherm naOntgrendeld={naSlotOntgrendeld} naarLogin={naSlotSessieDood} />
  } else if (uitnodigingToken) {
    inhoud = <AppActiveren token={uitnodigingToken} herstel={uitnodigingHerstel} naGeactiveerd={naGeactiveerd} />
  } else if (status === 'laden') {
    inhoud = laden
  } else if (slotStatus === 'geen' && status === 'uitgelogd') {
    inhoud = <AppActiveren melding={toegangVerlopen ? TOEGANG_VERLOPEN_MELDING : null} naGeactiveerd={naGeactiveerd} />
  } else if (slotStatus === 'geen') {
    // Legacy toestel (plain token in de Keychain/Keystore van vóór 31-08) mét levende sessie: de
    // toegangscode is verplicht vóór de app verdergaat (het refresh-token gaat erachter).
    // Bugfix 10-09 (2): staat de slot-waarde niet aantoonbaar (stelCodeIn → false), dan niet door naar de
    // flow maar de eerlijke melding + diagnoseregel; "Opnieuw proberen" toont PincodeKiezen opnieuw.
    inhoud = legacySlotFout ? (
      <SlotOpslagFout opnieuw={() => setLegacySlotFout(false)} />
    ) : (
      <PincodeKiezen
        onGekozen={(codeNieuw) => {
          void stelCodeIn(codeNieuw).then((opgeslagen) => {
            if (opgeslagen) setSlotStatus('ontgrendeld')
            else {
              schrijfAppSlotAudit('toegangscode_opslag_mislukt')
              setLegacySlotFout(true)
            }
          })
        }}
      />
    )
  } else if (status === 'uitgelogd') {
    // Slot open maar (nog) geen sessie: het effect hierboven wist het slot en toont de activatie.
    inhoud = laden
  } else if (opActiveren) {
    // Token-loos /activeren mét levende sessie (bv. herladen ná een geslaagde activatie): door.
    inhoud = <Navigate to="/accordeur" replace />
  } else if (toegangOpen) {
    inhoud = <ToegangInstellingen sluit={() => setToegangOpen(false)} uitloggen={losgekoppeld} />
  } else if (veldrol) {
    // Uren & meerwerk (fase 4, mockup/uren-uitvoerder.html): zelfde app, rolafhankelijke tabs.
    inhoud = <UrenFlow wisselThema={wissel} uitloggen={vergrendelApp} openToegang={openToegang} />
  } else {
    inhoud = <GoedkeurenFlow wisselThema={wissel} uitloggen={vergrendelApp} openToegang={openToegang} />
  }

  return (
    <div className="acc" data-thema={licht ? 'licht' : undefined}>
      <div className="acc-phone">{inhoud}</div>
    </div>
  )
}
