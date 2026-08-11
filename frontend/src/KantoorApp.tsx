// Kantoor-web-app (alles behalve /accordeur) — een eigen lazy chunk zodat de accordeur-PWA
// géén kantoor-bundels laadt (performance-budget accordeur-PWA, BESLISSINGEN punt 4).

import { Navigate, Route, Routes } from 'react-router-dom'
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
        <Route path="/instellingen" element={<InstellingenScreen />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default function KantoorApp() {
  return (
    <Routes>
      <Route path="/login" element={<LoginScreen />} />
      <Route path="/activeren" element={<ActivateScreen />} />
      <Route path="/*" element={<BeschermdeRoutes />} />
    </Routes>
  )
}
