import { useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { QRCodeSVG } from 'qrcode.react'
import { ApiError, apiJson, apiPostJson } from '../api/client'
import type { TokenPaarResponseDto, UitnodigingAccepterenResponseDto } from '../api/types'
import { useAuth } from './AuthContext'

function formatteerSecret(secret: string): string {
  return secret.match(/.{1,4}/g)?.join(' ') ?? secret
}

export function ActivateScreen() {
  const { inloggen } = useAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token')

  const [stap, setStap] = useState<'wachtwoord' | 'totp'>('wachtwoord')
  const [wachtwoord, setWachtwoord] = useState('')
  const [bevestiging, setBevestiging] = useState('')
  const [enrollment, setEnrollment] = useState<UitnodigingAccepterenResponseDto | null>(null)
  const [code, setCode] = useState('')
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)

  if (!token) {
    return (
      <div className="auth-shell">
        <div className="panel auth-card">
          <h1>Activatielink ongeldig</h1>
          <p className="hint">Er ontbreekt een token in de URL. Vraag een nieuwe uitnodiging aan.</p>
        </div>
      </div>
    )
  }

  const wachtwoordInzenden = async (e: FormEvent) => {
    e.preventDefault()
    setFout(null)
    if (wachtwoord !== bevestiging) {
      setFout('Wachtwoorden komen niet overeen.')
      return
    }
    setBezig(true)
    try {
      const resultaat = await apiPostJson<UitnodigingAccepterenResponseDto>('/auth/uitnodigingen/accepteren', {
        token,
        wachtwoord,
      })
      setEnrollment(resultaat)
      setStap('totp')
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Activeren mislukt.')
    } finally {
      setBezig(false)
    }
  }

  const totpInzenden = async (e: FormEvent) => {
    e.preventDefault()
    if (!enrollment) return
    setFout(null)
    setBezig(true)
    try {
      const paar = await apiJson<TokenPaarResponseDto>('/auth/totp/bevestigen', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${enrollment.totp_setup_token}` },
        body: JSON.stringify({ code }),
      })
      inloggen(paar)
      navigate('/')
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'TOTP-bevestiging mislukt.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <div className="auth-shell">
      <div className="panel auth-card">
        <h1>Account activeren</h1>
        <div className="sub">RLZ Boekingsmodule</div>
        {fout && <div className="fout">{fout}</div>}

        {stap === 'wachtwoord' && (
          <form onSubmit={(e) => void wachtwoordInzenden(e)}>
            <div className="row">
              <label htmlFor="activeer-wachtwoord">Nieuw wachtwoord (minimaal 12 tekens)</label>
              <input
                id="activeer-wachtwoord"
                type="password"
                autoComplete="new-password"
                minLength={12}
                required
                value={wachtwoord}
                onChange={(e) => setWachtwoord(e.target.value)}
              />
            </div>
            <div className="row">
              <label htmlFor="activeer-bevestiging">Bevestig wachtwoord</label>
              <input
                id="activeer-bevestiging"
                type="password"
                autoComplete="new-password"
                required
                value={bevestiging}
                onChange={(e) => setBevestiging(e.target.value)}
              />
            </div>
            <button className="btn" type="submit" disabled={bezig} style={{ width: '100%' }}>
              {bezig ? 'Bezig…' : 'Wachtwoord instellen'}
            </button>
          </form>
        )}

        {stap === 'totp' && enrollment && (
          <form onSubmit={(e) => void totpInzenden(e)}>
            <p className="hint" style={{ marginTop: 0 }}>
              Voeg dit account toe aan een authenticator-app (bv. Google Authenticator, 1Password) — scan de
              onderstaande QR-code, of gebruik de geheime sleutel als scannen niet lukt.
            </p>
            <div className="row" style={{ alignItems: 'center' }}>
              <span id="activeer-qr-label">QR-code voor de authenticator-app</span>
              <div
                role="img"
                aria-labelledby="activeer-qr-label"
                style={{ background: '#fff', padding: 12, borderRadius: 8, width: 'fit-content' }}
              >
                <QRCodeSVG value={enrollment.otpauth_uri} size={180} />
              </div>
            </div>
            <div className="row">
              <span id="activeer-secret-label">Geheime sleutel (terugval als scannen niet lukt)</span>
              <div className="secret-blok" aria-labelledby="activeer-secret-label">
                {formatteerSecret(enrollment.secret)}
              </div>
              <a href={enrollment.otpauth_uri} style={{ fontSize: 12 }}>
                otpauth-link openen in authenticator-app
              </a>
            </div>
            <div className="row">
              <label htmlFor="activeer-code">Code uit de authenticator-app</label>
              <input
                id="activeer-code"
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]{6}"
                maxLength={6}
                required
                value={code}
                onChange={(e) => setCode(e.target.value)}
              />
            </div>
            <button className="btn" type="submit" disabled={bezig} style={{ width: '100%' }}>
              {bezig ? 'Bezig…' : 'Bevestigen en inloggen'}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
