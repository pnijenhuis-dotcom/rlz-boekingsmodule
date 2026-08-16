// Kantoor-web-app (alles behalve /accordeur) — een eigen lazy chunk zodat de accordeur-PWA
// géén kantoor-bundels laadt (performance-budget accordeur-PWA, BESLISSINGEN punt 4).

import { lazy, Suspense, useEffect } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { initThema } from './ui/thema'
import { ActivateScreen } from './auth/ActivateScreen'
import { useAuth } from './auth/AuthContext'
import { LoginScreen } from './auth/LoginScreen'
import { BankDetailScreen } from './bank/BankDetailScreen'
import { BankOverzichtScreen } from './bank/BankOverzichtScreen'
import { DocumentDetailScreen } from './document/DocumentDetailScreen'
import { InstellingenScreen } from './instellingen/InstellingenScreen'
import { OmzetReviewScreen } from './omzet/OmzetReviewScreen'
import { Shell } from './shell/Shell'
import { VerkoopReviewScreen } from './verkoop/VerkoopReviewScreen'
import { WaarborgReviewScreen } from './waarborg/WaarborgReviewScreen'
import { VragenScreen } from './vragen/VragenScreen'
import { WerkvoorraadScreen } from './werkvoorraad/WerkvoorraadScreen'
import { ArchiefScreen } from './zoeken/ArchiefScreen'
import { ZoekenScreen } from './zoeken/ZoekenScreen'

// Kempen-doorbelasting (blok 3): lazy — het reviewscherm is alleen relevant voor de enkele
// administratie mét doorbelasting; de rest van het kantoor laadt deze chunk nooit.
const DoorbelastingReviewScreen = lazy(() =>
  import('./doorbelasting/DoorbelastingReviewScreen').then((m) => ({ default: m.DoorbelastingReviewScreen })),
)

function BeschermdeRoutes() {
  const { status, rol } = useAuth()

  if (status === 'laden') {
    return (
      <p className="hint" style={{ padding: 24 }}>
        Laden…
      </p>
    )
  }
  if (status === 'uitgelogd') {
    return <Navigate to="/login" replace />
  }
  if (rol === 'klant_accordeur') {
    // Accordeurs landen automatisch in hun eigen surface (blok 2a accordeur-PWA).
    return <Navigate to="/accordeur" replace />
  }

  return (
    <Routes>
      <Route element={<Shell />}>
        <Route path="/" element={<WerkvoorraadScreen />} />
        <Route path="/bank" element={<BankOverzichtScreen />} />
        <Route path="/bank/:administratieId" element={<BankDetailScreen />} />
        <Route path="/vragen" element={<VragenScreen />} />
        <Route path="/zoeken" element={<ZoekenScreen />} />
        <Route path="/archief" element={<ArchiefScreen />} />
        <Route path="/documenten/:administratieId/:documentId" element={<DocumentDetailScreen />} />
        <Route path="/omzet/:administratieId/:documentId" element={<OmzetReviewScreen />} />
        <Route path="/verkoop/:administratieId/:documentId" element={<VerkoopReviewScreen />} />
        <Route path="/waarborg/:administratieId/:documentId" element={<WaarborgReviewScreen />} />
        <Route
          path="/doorbelasting/:administratieId/:documentId"
          element={
            <Suspense fallback={<p className="hint">Laden…</p>}>
              <DoorbelastingReviewScreen />
            </Suspense>
          }
        />
        <Route path="/instellingen" element={<InstellingenScreen />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default function KantoorApp() {
  // Thema (fase 1 modernisering): keuze wint, anders systeem — hier zodat óók de login-/
  // activatieroutes buiten de Shell meteen het juiste thema dragen. De accordeur-PWA heeft
  // een eigen, losstaand thema en zit niet onder deze app.
  useEffect(() => {
    initThema()
  }, [])

  return (
    <Routes>
      <Route path="/login" element={<LoginScreen />} />
      <Route path="/activeren" element={<ActivateScreen />} />
      <Route path="/*" element={<BeschermdeRoutes />} />
    </Routes>
  )
}
