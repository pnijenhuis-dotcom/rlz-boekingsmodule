// Activatie-hulp op het login-scherm (blok E2 opdracht 06-09, casus detacheerder 04-09): wie de
// app opent VÓÓR de activatie (of wiens uitnodigingslink in de browser opende) liep dood op het
// login-scherm. Dit blok legt eerlijk uit wat er aan de hand kan zijn mét handelingsperspectief:
// open de uitnodigingslink uit de mail op dít toestel (universal link → activatie-/code-flow),
// of — native — plak de link hier; geen mail (meer) = kantoor "Opnieuw mailen".
//
// SECURITY-KADER (0022-lijn): de server antwoordt op een onbekend/niet-geactiveerd/passkey-loos
// adres bewust IDENTIEK (generieke 409 `GeenPasskeys`, 401 op het wachtwoord) — geen
// user-enumeration. Dit blok is daarom generiek ("Nog niet geactiveerd?") en verschijnt ná élke
// mislukte login of op verzoek; het stelt nergens vast óf het adres bestaat. "Link plakken" gaat
// door exact dezelfde token-poort als de mail-link (inAppPadVoorUrl → /accordeur/activeren?
// uitnodiging=) — geen activatie zonder token, geen omzeiling van de passkey-laag.

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { inAppPadVoorUrl } from './nativeAppUrl'

type Platform = 'ios' | 'android' | 'web'

function platform(): Platform {
  const cap = (window as { Capacitor?: { isNativePlatform?: () => boolean; getPlatform?: () => string } }).Capacitor
  if (!cap?.isNativePlatform?.()) return 'web'
  const p = cap.getPlatform?.()
  return p === 'ios' || p === 'android' ? p : 'web'
}

/** URL die de mail-INBOX opent (niet een nieuw bericht): iOS `message://` (Mail), Android de
 * APP_EMAIL-categorie via een intent-URL; Capacitor's webview-client geeft niet-http(s)-schema's
 * aan het OS. Web: geen betrouwbare vorm → null (alleen de tekst). */
export function mailAppUrl(p: Platform): string | null {
  if (p === 'ios') return 'message://'
  if (p === 'android') return 'intent:#Intent;action=android.intent.action.MAIN;category=android.intent.category.APP_EMAIL;end'
  return null
}

export const GEEN_UITNODIGINGSLINK =
  'Dit is geen uitnodigingslink van de Nijenhuis Boekingsmodule. Plak de volledige link uit de e-mail van het kantoor.'
export const LINK_ZONDER_CODE = 'Deze link bevat geen uitnodigingscode — plak de volledige link uit de e-mail.'

/** Pure vertaling van een geplakte link naar de in-app-activatieroute; string = fout. Zelfde
 * poort als de universal link (alleen /activeren?token= en /accordeur/activeren?uitnodiging=). */
export function activatiePadVanGeplakteLink(ruw: string): { pad: string } | { fout: string } {
  const tekst = ruw.trim().replace(/^<|>$/g, '')
  if (!tekst) return { fout: GEEN_UITNODIGINGSLINK }
  const pad = inAppPadVoorUrl(tekst)
  if (!pad || !pad.startsWith('/accordeur/activeren')) return { fout: GEEN_UITNODIGINGSLINK }
  const params = new URLSearchParams(pad.slice(pad.indexOf('?')))
  if (!pad.includes('?') || !params.get('uitnodiging')) return { fout: LINK_ZONDER_CODE }
  return { pad }
}

interface Props {
  /** Open = uitgevouwen tonen (ná een mislukte login automatisch); dicht = alleen de tekstlink. */
  open: boolean
  onToggle: () => void
}

export function ActivatieHulp({ open, onToggle }: Props) {
  const navigate = useNavigate()
  const p = platform()
  const native = p !== 'web'
  const [link, setLink] = useState('')
  const [linkFout, setLinkFout] = useState<string | null>(null)
  const [plakOpen, setPlakOpen] = useState(false)
  const mailUrl = mailAppUrl(p)

  const openMailApp = () => {
    if (!mailUrl) return
    try {
      window.location.assign(mailUrl)
    } catch {
      // Het OS weigert het schema: de tekst eronder zegt wat de gebruiker zelf kan doen.
    }
  }

  const naarActivatie = () => {
    const uitkomst = activatiePadVanGeplakteLink(link)
    if ('fout' in uitkomst) {
      setLinkFout(uitkomst.fout)
      return
    }
    setLinkFout(null)
    void navigate(uitkomst.pad)
  }

  if (!open) {
    return (
      <button type="button" className="acc-tekstlink" onClick={onToggle}>
        Nog niet geactiveerd?
      </button>
    )
  }

  return (
    <div className="acc-hulp" data-testid="acc-activatie-hulp" aria-live="polite">
      <div>
        <b>Nog niet geactiveerd?</b> Bent u door het kantoor uitgenodigd, open dan de <b>uitnodigingslink uit de
        e-mail op dít toestel</b> — de app opent dan vanzelf de activatie (u kiest een code, daarna Face ID of
        vingerafdruk). Geen e-mail (meer)? Vraag het kantoor de uitnodiging <b>opnieuw te mailen</b>; de oude link
        vervalt dan.
      </div>
      {native && mailUrl && (
        <>
          <button type="button" className="acc-btn secundair" onClick={openMailApp}>
            Mail-app openen
          </button>
          <div className="acc-vertrouwen" style={{ textAlign: 'left', maxWidth: 'none' }}>
            Opent de mail-app niet? Open hem dan zelf en tik op de link in de uitnodiging.
          </div>
        </>
      )}
      {native && !plakOpen && (
        <button type="button" className="acc-tekstlink" style={{ alignSelf: 'flex-start', padding: 0 }} onClick={() => setPlakOpen(true)}>
          Link plakken
        </button>
      )}
      {native && plakOpen && (
        <div className="acc-form" style={{ width: '100%' }}>
          <label htmlFor="acc-plaklink">Uitnodigingslink uit de e-mail</label>
          <input
            id="acc-plaklink"
            type="url"
            inputMode="url"
            autoComplete="off"
            placeholder="https://app.…/activeren?token=…"
            value={link}
            onChange={(e) => {
              setLink(e.target.value)
              setLinkFout(null)
            }}
          />
          {linkFout && <div className="acc-fout">{linkFout}</div>}
          <button type="button" className="acc-btn primair" disabled={link.trim() === ''} onClick={naarActivatie}>
            Naar de activatie
          </button>
        </div>
      )}
    </div>
  )
}
