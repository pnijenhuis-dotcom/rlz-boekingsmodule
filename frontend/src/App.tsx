import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'

// Route-based code splitting (performance-budget accordeur-PWA, BESLISSINGEN punt 4): de
// accordeur-route laadt geen kantoor-bundels en andersom — beide surfaces zijn een eigen
// lazy chunk; deze root bevat alleen router + auth.
const KantoorApp = lazy(() => import('./KantoorApp'))
const AccordeurApp = lazy(() => import('./accordeur/AccordeurApp'))

// Trailing slash → variant zonder (randgeval kliktest 2026-08-08: /bank/ is geen route en de
// dev-proxy behandelt zulke paden anders dan /bank). Redirect vóór de route-matching, query blijft.
function AppRoutes() {
  const { pathname, search } = useLocation()
  if (pathname.length > 1 && pathname.endsWith('/')) {
    return <Navigate to={`${pathname.replace(/\/+$/, '')}${search}`} replace />
  }
  return (
    <Suspense
      fallback={
        <p className="hint" style={{ padding: 24 }}>
          Laden…
        </p>
      }
    >
      <Routes>
        <Route path="/accordeur/*" element={<AccordeurApp />} />
        <Route path="/*" element={<KantoorApp />} />
      </Routes>
    </Suspense>
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
