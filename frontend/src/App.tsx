import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { ActivateScreen } from './auth/ActivateScreen'
import { AuthProvider, useAuth } from './auth/AuthContext'
import { LoginScreen } from './auth/LoginScreen'
import { BankDetailScreen } from './bank/BankDetailScreen'
import { BankOverzichtScreen } from './bank/BankOverzichtScreen'
import { DocumentDetailScreen } from './document/DocumentDetailScreen'
import { InstellingenScreen } from './instellingen/InstellingenScreen'
import { OmzetReviewScreen } from './omzet/OmzetReviewScreen'
import { Shell } from './shell/Shell'
import { VerkoopReviewScreen } from './verkoop/VerkoopReviewScreen'
import { VragenScreen } from './vragen/VragenScreen'
import { WerkvoorraadScreen } from './werkvoorraad/WerkvoorraadScreen'

function BeschermdeRoutes() {
  const { status } = useAuth()

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

  return (
    <Routes>
      <Route element={<Shell />}>
        <Route path="/" element={<WerkvoorraadScreen />} />
        <Route path="/bank" element={<BankOverzichtScreen />} />
        <Route path="/bank/:administratieId" element={<BankDetailScreen />} />
        <Route path="/vragen" element={<VragenScreen />} />
        <Route path="/documenten/:administratieId/:documentId" element={<DocumentDetailScreen />} />
        <Route path="/omzet/:administratieId/:documentId" element={<OmzetReviewScreen />} />
        <Route path="/verkoop/:administratieId/:documentId" element={<VerkoopReviewScreen />} />
        <Route path="/instellingen" element={<InstellingenScreen />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

// Trailing slash → variant zonder (randgeval kliktest 2026-08-08: /bank/ is geen route en de
// dev-proxy behandelt zulke paden anders dan /bank). Redirect vóór de route-matching, query blijft.
function AppRoutes() {
  const { pathname, search } = useLocation()
  if (pathname.length > 1 && pathname.endsWith('/')) {
    return <Navigate to={`${pathname.replace(/\/+$/, '')}${search}`} replace />
  }
  return (
    <Routes>
      <Route path="/login" element={<LoginScreen />} />
      <Route path="/activeren" element={<ActivateScreen />} />
      <Route path="/*" element={<BeschermdeRoutes />} />
    </Routes>
  )
}

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  )
}

export default App
