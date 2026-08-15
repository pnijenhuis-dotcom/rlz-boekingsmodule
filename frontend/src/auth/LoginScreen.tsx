import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { haalWebauthnConfig, ondertekenAssertie, webauthnBeschikbaar } from '../accordeur/webauthnClient'
import { ApiError, apiPostJson, BACKEND_ONBEREIKBAAR_MELDING } from '../api/client'
import type { TokenPaarResponseDto } from '../api/types'
import { FormFouten, useFormFouten } from '../ui/FormFouten'
import { useAuth } from './AuthContext'
import { kantoorLoginOpties, kantoorLoginVoltooien } from './passkeyApi'

const LOGIN_VELD_LABELS: Record<string, string> = {
  'login-email': 'E-mailadres',
  'login-wachtwoord': 'Wachtwoord',
  'login-totp': 'TOTP-code',
}

/** Kantoor-login (platformbesluit 0020): passkey is de EERSTE lijn — stap 1 vraagt alleen het
 * e-mailadres (usernameless mag niet, 0022/0006-lijn) en probeert een passkey-assertion;
 * wachtwoord + TOTP blijft het volwaardige terugvalpad (het /auth/login-pad is ongewijzigd).
 * Passkey-loze gebruikers merken niets: het 409-antwoord van de opties-route schuift het
 * formulier stil door naar de terugval — dat antwoord is server-side identiek voor onbekende
 * adressen, dus hier valt geen account-bestaan af te leiden. */
export function LoginScreen() {
  const { inloggen, backendOnbereikbaar } = useAuth()
  const navigate = useNavigate()
  const [stap, setStap] = useState<'passkey' | 'terugval'>('passkey')
  const [eMail, setEMail] = useState('')
  const [wachtwoord, setWachtwoord] = useState('')
  const [totpCode, setTotpCode] = useState('')
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const { fouten: veldFouten, controleer } = useFormFouten(LOGIN_VELD_LABELS)

  const naarTerugval = () => {
    setFout(null)
    setStap('terugval')
  }

  const probeerPasskey = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (!controleer(e.currentTarget)) return
    setFout(null)
    setBezig(true)
    try {
      let stubOmgeving = false
      if (!webauthnBeschikbaar()) {
        // Geen secure context (LAN-kliktest) of geen WebAuthn-API: alleen de dev-stub kan dan
        // nog een passkey-pad dragen — anders meteen door naar wachtwoord + TOTP.
        const config = await haalWebauthnConfig()
        if (!config.dev_stub) {
          setStap('terugval')
          return
        }
        stubOmgeving = true
      }
      let opties
      try {
        opties = await kantoorLoginOpties(eMail)
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) {
          // Geen bruikbare passkey voor dit adres — stil door naar de terugval.
          setStap('terugval')
          return
        }
        throw err
      }
      let paar: TokenPaarResponseDto
      if (opties.opties !== null && !stubOmgeving) {
        const credential = await ondertekenAssertie(opties.opties)
        paar = await kantoorLoginVoltooien(eMail, { credential })
      } else if (opties.dev_stub) {
        paar = await kantoorLoginVoltooien(eMail, { dev_stub: true })
      } else {
        // Wel echte passkeys, maar dit apparaat kan geen assertion doen (geen secure context).
        setStap('terugval')
        return
      }
      inloggen(paar)
      navigate('/')
    } catch (err) {
      setFout(
        err instanceof Error && err.message
          ? `${err.message} — probeer opnieuw of log in met wachtwoord + TOTP.`
          : 'Passkey-login mislukt — probeer opnieuw of log in met wachtwoord + TOTP.',
      )
    } finally {
      setBezig(false)
    }
  }

  const inzendenTerugval = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (!controleer(e.currentTarget)) return
    setFout(null)
    setBezig(true)
    try {
      const paar = await apiPostJson<TokenPaarResponseDto>('/auth/login', {
        e_mail: eMail,
        wachtwoord,
        totp_code: totpCode,
      })
      inloggen(paar)
      navigate('/')
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Inloggen mislukt — probeer het opnieuw.')
    } finally {
      setBezig(false)
    }
  }

  const eMailVeld = (
    <div className="row">
      <label htmlFor="login-email">E-mailadres</label>
      <input
        id="login-email"
        type="email"
        autoComplete="username"
        required
        value={eMail}
        onChange={(e) => setEMail(e.target.value)}
      />
    </div>
  )

  return (
    <div className="auth-shell">
      <div className="panel auth-card">
        <h1>Inloggen</h1>
        <div className="sub">RLZ Boekingsmodule</div>
        {backendOnbereikbaar && !fout && <div className="fout">{BACKEND_ONBEREIKBAAR_MELDING}</div>}
        {fout && <div className="fout">{fout}</div>}
        <FormFouten fouten={veldFouten} />
        {stap === 'passkey' ? (
          <form noValidate onSubmit={(e) => void probeerPasskey(e)}>
            {eMailVeld}
            <button className="btn" type="submit" disabled={bezig} style={{ width: '100%' }}>
              {bezig ? 'Bezig…' : 'Verder met passkey'}
            </button>
            <button
              className="linkbtn"
              type="button"
              onClick={naarTerugval}
              style={{ width: '100%', marginTop: 10 }}
            >
              Inloggen met wachtwoord + TOTP
            </button>
          </form>
        ) : (
          <form noValidate onSubmit={(e) => void inzendenTerugval(e)}>
            {eMailVeld}
            <div className="row">
              <label htmlFor="login-wachtwoord">Wachtwoord</label>
              <input
                id="login-wachtwoord"
                type="password"
                autoComplete="current-password"
                required
                value={wachtwoord}
                onChange={(e) => setWachtwoord(e.target.value)}
              />
            </div>
            <div className="row">
              <label htmlFor="login-totp">TOTP-code</label>
              <input
                id="login-totp"
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]{6}"
                maxLength={6}
                required
                value={totpCode}
                onChange={(e) => setTotpCode(e.target.value)}
              />
            </div>
            <button className="btn" type="submit" disabled={bezig} style={{ width: '100%' }}>
              {bezig ? 'Bezig…' : 'Inloggen'}
            </button>
            <button
              className="linkbtn"
              type="button"
              onClick={() => {
                setFout(null)
                setStap('passkey')
              }}
              style={{ width: '100%', marginTop: 10 }}
            >
              Toch met passkey inloggen
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
