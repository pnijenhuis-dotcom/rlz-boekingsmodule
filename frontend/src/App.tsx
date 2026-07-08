import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { ActivateScreen } from './auth/ActivateScreen'
import { AuthProvider, useAuth } from './auth/AuthContext'
import { LoginScreen } from './auth/LoginScreen'
import { DocumentDetailScreen } from './document/DocumentDetailScreen'
import { Shell } from './shell/Shell'
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
        <Route path="/documenten/:administratieId/:documentId" element={<DocumentDetailScreen />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

function AppRoutes() {
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
