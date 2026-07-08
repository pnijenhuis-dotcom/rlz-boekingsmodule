import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import {
  apiFetch,
  decodeerJwtPayload,
  getAccessToken,
  setAccessToken,
  setSessieVerlopenHandler,
  verversSessie,
} from '../api/client'
import type { TokenPaarResponseDto } from '../api/types'

type AuthStatus = 'laden' | 'ingelogd' | 'uitgelogd'

interface AuthContextWaarde {
  status: AuthStatus
  rol: string | null
  inloggen: (paar: TokenPaarResponseDto) => void
  uitloggen: () => Promise<void>
}

const AuthContext = createContext<AuthContextWaarde | null>(null)

function rolUitToken(token: string): string | null {
  const payload = decodeerJwtPayload(token)
  return typeof payload?.rol === 'string' ? payload.rol : null
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('laden')
  const [rol, setRol] = useState<string | null>(null)

  useEffect(() => {
    setSessieVerlopenHandler(() => {
      setStatus('uitgelogd')
      setRol(null)
    })

    // Silent refresh bij het laden van de app: de httpOnly-cookie overleeft een paginaherlaad,
    // het in-memory access-token niet — dit haalt 'm terug zonder opnieuw TOTP te vragen.
    void verversSessie().then((gelukt) => {
      if (gelukt) {
        const token = getAccessToken()
        setRol(token ? rolUitToken(token) : null)
        setStatus('ingelogd')
      } else {
        setStatus('uitgelogd')
      }
    })

    return () => setSessieVerlopenHandler(null)
  }, [])

  const inloggen = (paar: TokenPaarResponseDto) => {
    setAccessToken(paar.access_token)
    setRol(rolUitToken(paar.access_token))
    setStatus('ingelogd')
  }

  const uitloggen = async () => {
    await apiFetch('/auth/logout', { method: 'POST' })
    setAccessToken(null)
    setRol(null)
    setStatus('uitgelogd')
  }

  return <AuthContext.Provider value={{ status, rol, inloggen, uitloggen }}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextWaarde {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth moet binnen AuthProvider gebruikt worden')
  return ctx
}
