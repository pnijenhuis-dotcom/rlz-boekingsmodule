import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError, apiPostJson } from '../api/client'
import type { TokenPaarResponseDto } from '../api/types'
import { useAuth } from './AuthContext'

export function LoginScreen() {
  const { inloggen } = useAuth()
  const navigate = useNavigate()
  const [eMail, setEMail] = useState('')
  const [wachtwoord, setWachtwoord] = useState('')
  const [totpCode, setTotpCode] = useState('')
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)

  const inzenden = async (e: FormEvent) => {
    e.preventDefault()
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

  return (
    <div className="auth-shell">
      <div className="panel auth-card">
        <h1>Inloggen</h1>
        <div className="sub">RLZ Boekingsmodule</div>
        {fout && <div className="fout">{fout}</div>}
        <form onSubmit={(e) => void inzenden(e)}>
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
        </form>
      </div>
    </div>
  )
}
