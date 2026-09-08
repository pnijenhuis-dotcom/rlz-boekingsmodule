import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { QRCodeSVG } from 'qrcode.react'
import { StoreLinks } from './StoreLinks'
import { ApiError, apiJson, apiPostJson } from '../api/client'
import type { TokenPaarResponseDto, UitnodigingAccepterenResponseDto } from '../api/types'
import {
  activatieOpDitApparaat,
  haalAppConfig,
  haalUitnodigingInfo,
  isAppFlow,
  isMobielUserAgent,
  type AppConfigDto,
  type UitnodigingInfoDto,
} from './uitnodigingInfoApi'
import { FormFouten, useFormFouten } from '../ui/FormFouten'
import { useAuth } from './AuthContext'

/** Externe rollen activeren in de app-flow (/accordeur/activeren) mét de link in de URL —
 * een refresh begint de flow gewoon opnieuw, de link blijft geldig tot het toestel gekoppeld is
 * (app-auth zonder passkey, besluit Peter 08-09: activatiecode/link → toegangscode). */
function accordeurActivatiePad(token: string, herstel: boolean): string {
  return `/accordeur/activeren?uitnodiging=${encodeURIComponent(token)}${herstel ? '&herstel=1' : ''}`
}

function formatteerSecret(secret: string): string {
  return secret.match(/.{1,4}/g)?.join(' ') ?? secret
}

const ACTIVEER_VELD_LABELS: Record<string, string> = {
  'activeer-wachtwoord': 'Nieuw wachtwoord',
  'activeer-bevestiging': 'Bevestig wachtwoord',
  'activeer-code': 'Code uit de authenticator-app',
}

export function ActivateScreen() {
  const { inloggen } = useAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token')
  // Herstel-link (feedbackronde 25-08 punt 7): zelfde token-mechaniek, alleen presentatie
  // anders — de server bepaalt de soort uit het token, niet uit deze parameter.
  const isHerstel = searchParams.get('herstel') === '1'

  const [stap, setStap] = useState<'wachtwoord' | 'totp'>('wachtwoord')
  // Mobiel-first activatie externe rollen (besluit Peter 28-08, mockup activatie-mobiel.html; app-auth 08-09):
  // vóór de wachtwoordstap weten we via de publieke info-route welke flow bij de link hoort.
  // App-rol + telefoon/tablet → door naar de app-flow (dáár: toestel koppelen + toegangscode); app-rol +
  // desktop → stop-scherm mét QR en de activatiecode-hint (de link verzilvert hier níéts); kantoor → het
  // bestaande wachtwoord + TOTP hieronder. Een passkey-capability-toets bestaat niet meer: er is niets te toetsen.
  const [linkToets, setLinkToets] = useState<'bezig' | 'kantoor' | 'stop' | 'ongeldig'>('bezig')
  const [linkInfo, setLinkInfo] = useState<UitnodigingInfoDto | null>(null)
  const [linkFout, setLinkFout] = useState<string | null>(null)
  // Blok F: store-links (leeg = niets tonen) voor het stop-scherm naast de QR.
  const [appConfig, setAppConfig] = useState<AppConfigDto | null>(null)
  useEffect(() => {
    if (!token) return
    let actief = true
    ;(async () => {
      try {
        const info = await haalUitnodigingInfo(token)
        if (!actief) return
        setLinkInfo(info)
        if (!isAppFlow(info.flow)) {
          setLinkToets('kantoor')
          return
        }
        if (activatieOpDitApparaat(isMobielUserAgent()) === 'doorgaan') {
          void navigate(accordeurActivatiePad(token, info.herstel), { replace: true })
          return
        }
        // Store-links alleen voor het stop-scherm — best-effort, nooit blokkerend.
        haalAppConfig()
          .then((c) => {
            if (actief) setAppConfig(c)
          })
          .catch(() => undefined)
        setLinkToets('stop')
      } catch (err) {
        if (!actief) return
        setLinkFout(err instanceof ApiError ? err.message : 'De link kon niet worden gecontroleerd.')
        setLinkToets('ongeldig')
      }
    })()
    return () => {
      actief = false
    }
  }, [token, navigate])
  const [wachtwoord, setWachtwoord] = useState('')
  const [bevestiging, setBevestiging] = useState('')
  const [enrollment, setEnrollment] = useState<UitnodigingAccepterenResponseDto | null>(null)
  const [code, setCode] = useState('')
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const { fouten: veldFouten, controleer } = useFormFouten(ACTIVEER_VELD_LABELS)

  if (!token) {
    return (
      <div className="auth-shell">
        <div className="panel auth-card">
          <h1>{isHerstel ? 'Herstel-link ongeldig' : 'Activatielink ongeldig'}</h1>
          <p className="hint">
            Er ontbreekt een token in de URL. Vraag een nieuwe {isHerstel ? 'herstel-link' : 'uitnodiging'} aan bij het
            kantoor.
          </p>
        </div>
      </div>
    )
  }

  if (linkToets === 'bezig') {
    return (
      <div className="auth-shell">
        <div className="panel auth-card">
          <h1>{isHerstel ? 'Nieuw wachtwoord instellen' : 'Account activeren'}</h1>
          <div className="sub">RLZ Boekingsmodule</div>
          <p className="hint">Link controleren…</p>
        </div>
      </div>
    )
  }

  if (linkToets === 'ongeldig') {
    return (
      <div className="auth-shell">
        <div className="panel auth-card">
          <h1>{isHerstel ? 'Herstel-link werkt niet meer' : 'Activatielink werkt niet meer'}</h1>
          <p className="hint">{linkFout}</p>
          <p className="hint">
            Al geactiveerd? Log dan gewoon in. Anders vraagt u het kantoor om een nieuwe{' '}
            {isHerstel ? 'herstel-link' : 'uitnodiging'} — er is niets vastgelegd.
          </p>
        </div>
      </div>
    )
  }

  if (linkToets === 'stop') {
    // Mockup §1: stop-scherm zonder wachtwoordveld; de QR bevat exact dezelfde activatie-URL.
    const dezelfdeLink = typeof window !== 'undefined' ? window.location.href : ''
    return (
      <div className="auth-shell">
        <div className="panel auth-card activatie-stop" data-testid="activatie-stopscherm">
          <h1>Open deze uitnodiging op uw telefoon</h1>
          <div className="sub">RLZ Boekingsmodule</div>
          <p className="hint" style={{ marginTop: 0 }}>
            {linkInfo?.naam ? `${linkInfo.naam}, u` : 'U'} activeert uw account op uw telefoon in de app. Scan de
            QR-code met de camera van uw telefoon, of open de link uit de e-mail dáár. Lukt dat niet? Voer dan in de
            app de activatiecode uit de e-mail in — die is even lang geldig als deze link.
          </p>
          <div className="row" style={{ alignItems: 'center' }}>
            <span id="activeer-stop-qr-label">QR-code met dezelfde activatielink</span>
            <div
              role="img"
              aria-labelledby="activeer-stop-qr-label"
              style={{ background: '#fff', padding: 12, borderRadius: 8, width: 'fit-content' }}
            >
              <QRCodeSVG value={dezelfdeLink} size={180} />
            </div>
          </div>
          <StoreLinks config={appConfig} variant="stop" />
          <p className="hint">🔒 De link blijft 72 uur geldig · niets is nog vastgelegd</p>
        </div>
      </div>
    )
  }

  const wachtwoordInzenden = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (!controleer(e.currentTarget)) return
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
      if (resultaat.soort === 'app' || resultaat.soort === 'passkey') {
        // Vangnet: een app-link die toch hier verzilverd wordt (info-route zei 'totp' of faalde) —
        // door naar de app-flow; dáár wordt het toestel gekoppeld.
        void navigate(accordeurActivatiePad(token, isHerstel), { replace: true })
        return
      }
      setEnrollment(resultaat)
      setStap('totp')
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Activeren mislukt.')
    } finally {
      setBezig(false)
    }
  }

  const totpInzenden = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (!enrollment) return
    if (!controleer(e.currentTarget)) return
    setFout(null)
    setBezig(true)
    try {
      const paar = await apiJson<TokenPaarResponseDto>('/auth/totp/bevestigen', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${enrollment.totp_setup_token ?? ''}` },
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
        <h1>{isHerstel ? 'Nieuw wachtwoord instellen' : 'Account activeren'}</h1>
        <div className="sub">RLZ Boekingsmodule</div>
        {isHerstel && stap === 'wachtwoord' && (
          <p className="hint" style={{ marginTop: 0 }}>
            Het kantoor heeft een herstel-link voor u aangemaakt. Stel een nieuw wachtwoord in; daarna volgt de
            tweede factor. Uw bestaande instellingen blijven bewaard.
          </p>
        )}
        {fout && <div className="fout">{fout}</div>}
        <FormFouten fouten={veldFouten} />

        {stap === 'wachtwoord' && (
          <form noValidate onSubmit={(e) => void wachtwoordInzenden(e)}>
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
          <form noValidate onSubmit={(e) => void totpInzenden(e)}>
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
                <QRCodeSVG value={enrollment.otpauth_uri ?? ''} size={180} />
              </div>
            </div>
            <div className="row">
              <span id="activeer-secret-label">Geheime sleutel (terugval als scannen niet lukt)</span>
              <div className="secret-blok" aria-labelledby="activeer-secret-label">
                {formatteerSecret(enrollment.secret ?? '')}
              </div>
              <a href={enrollment.otpauth_uri ?? '#'} style={{ fontSize: 12 }}>
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
