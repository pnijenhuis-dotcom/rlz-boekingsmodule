import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import {
  apiFetch,
  BackendOnbereikbaarError,
  decodeerJwtPayload,
  getAccessToken,
  getOntgrendelingNodig,
  setAccessToken,
  setSessieVerlopenHandler,
  verversSessie,
} from '../api/client'
import { bewaarNatiefRefreshToken, wisNatiefRefreshToken } from '../api/nativeSessie'
import type { TokenPaarResponseDto } from '../api/types'

type AuthStatus = 'laden' | 'ingelogd' | 'uitgelogd'

interface AuthContextWaarde {
  status: AuthStatus
  rol: string | null
  /** Eigen gebruikers-id (JWT `sub`-claim) — nodig voor rol-afhankelijke UI zoals de
   * vier-ogen-IBAN-accordering (ben ík de aanvrager/een accordeur?). De backend blijft de
   * waarheid: elke actie wordt server-side opnieuw gecontroleerd. */
  gebruikerId: string | null
  /** True als het laden van de app niet kon vaststellen of er een sessie is doordat de backend
   * niet bereikbaar was (i.p.v. gewoon geen geldige refresh-cookie) — zie LoginScreen voor de
   * bijbehorende melding. */
  backendOnbereikbaar: boolean
  /** Ontgrendel-frequentie accordeur (besluit Peter 27-08, server-side 24-uursvenster): de
   * uitspraak van de stille refresh — false = de app opent direct, true = ontgrendelscherm,
   * null = geen uitspraak (kantoor, of nog niet geladen). Alleen de accordeur-shell leest dit. */
  ontgrendelingNodig: boolean | null
  inloggen: (paar: TokenPaarResponseDto) => void
  uitloggen: () => Promise<void>
}

const AuthContext = createContext<AuthContextWaarde | null>(null)

function rolUitToken(token: string): string | null {
  const payload = decodeerJwtPayload(token)
  return typeof payload?.rol === 'string' ? payload.rol : null
}

function gebruikerIdUitToken(token: string): string | null {
  const payload = decodeerJwtPayload(token)
  return typeof payload?.sub === 'string' ? payload.sub : null
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('laden')
  const [rol, setRol] = useState<string | null>(null)
  const [gebruikerId, setGebruikerId] = useState<string | null>(null)
  const [backendOnbereikbaar, setBackendOnbereikbaar] = useState(false)
  const [ontgrendelingNodig, setOntgrendelingNodig] = useState<boolean | null>(null)

  useEffect(() => {
    setSessieVerlopenHandler(() => {
      setStatus('uitgelogd')
      setRol(null)
      setGebruikerId(null)
    })

    // Silent refresh bij het laden van de app: de httpOnly-cookie overleeft een paginaherlaad,
    // het in-memory access-token niet — dit haalt 'm terug zonder opnieuw TOTP te vragen.
    void verversSessie()
      .then((gelukt) => {
        if (gelukt) {
          const token = getAccessToken()
          setRol(token ? rolUitToken(token) : null)
          setGebruikerId(token ? gebruikerIdUitToken(token) : null)
          setOntgrendelingNodig(getOntgrendelingNodig())
          setStatus('ingelogd')
        } else {
          setStatus('uitgelogd')
        }
      })
      .catch((err: unknown) => {
        // Backend onbereikbaar bij het laden van de app: dit is geen "niet ingelogd" (dat weten
        // we niet), maar de gebruiker moet wél iets zien i.p.v. eindeloos "Laden…".
        if (err instanceof BackendOnbereikbaarError) setBackendOnbereikbaar(true)
        setStatus('uitgelogd')
      })

    return () => setSessieVerlopenHandler(null)
  }, [])

  const inloggen = (paar: TokenPaarResponseDto) => {
    setAccessToken(paar.access_token)
    setRol(rolUitToken(paar.access_token))
    setGebruikerId(gebruikerIdUitToken(paar.access_token))
    setStatus('ingelogd')
    setBackendOnbereikbaar(false)
    setOntgrendelingNodig(typeof paar.ontgrendeling_nodig === 'boolean' ? paar.ontgrendeling_nodig : null)
    // Native schil (fase 4): het refresh-token uit de body naar de Keychain/Keystore — de
    // volgende app-opening ontgrendelt dan gewoon i.p.v. een volledige login te eisen.
    if (paar.refresh_token) void bewaarNatiefRefreshToken(paar.refresh_token)
  }

  const uitloggen = async () => {
    // Onder het cookie-pad (/auth/token/vernieuwen): alleen dáár stuurt de browser de
    // path-gebonden refresh-cookie mee, anders wordt er server-side niets ingetrokken.
    // Native reist het token als header (client.ts) — zelfde endpoint, zelfde intrekking.
    await apiFetch('/auth/token/vernieuwen/logout', { method: 'POST' })
    await wisNatiefRefreshToken()
    setAccessToken(null)
    setRol(null)
    setGebruikerId(null)
    setOntgrendelingNodig(null)
    setStatus('uitgelogd')
  }

  return (
    <AuthContext.Provider value={{ status, rol, gebruikerId, backendOnbereikbaar, ontgrendelingNodig, inloggen, uitloggen }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextWaarde {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth moet binnen AuthProvider gebruikt worden')
  return ctx
}

/** Als useAuth, maar zonder harde Provider-eis: voor optionele franje (bv. de AI-kostenbanner in
 * de werkvoorraad) die ook gerenderd kan worden waar geen AuthProvider staat — dan gewoon niets
 * tonen i.p.v. crashen. Gebruik voor alles dat van de rol afhángt gewoon useAuth. */
export function useAuthOptioneel(): AuthContextWaarde | null {
  return useContext(AuthContext)
}
