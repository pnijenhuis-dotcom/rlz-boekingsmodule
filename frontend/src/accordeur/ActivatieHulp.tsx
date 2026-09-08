// Activatie-hulp op het activatiescherm (blok E2 06-09, herschreven 08-09 voor app-auth zonder
// passkey): wie de app opent zonder uitnodiging (of wiens uitnodigingslink in de browser opende)
// krijgt hier eerlijk uitgelegd wat er aan de hand kan zijn mét handelingsperspectief: open de link
// uit de uitnodigingsmail op dít toestel (universal link → activatie), voer de activatiecode uit
// dezelfde mail in, of — geen mail (meer) — vraag het kantoor om een nieuwe uitnodiging.
//
// SECURITY-KADER (0022-lijn): de server antwoordt op een onbekende code en een ongeldige link
// IDENTIEK — dit blok stelt nergens vast óf een account bestaat. "Link plakken" (AppActiveren) gaat
// door exact dezelfde token-poort als de mail-link (inAppPadVoorUrl → /accordeur/activeren?
// uitnodiging=) — geen activatie zonder uitnodiging.

import { inAppPadVoorUrl } from './nativeAppUrl'
import { huidigPlatform, type AppPlatform } from './appAuthApi'

/** URL die de mail-INBOX opent (niet een nieuw bericht): iOS `message://` (Mail), Android de
 * APP_EMAIL-categorie via een intent-URL; Capacitor's webview-client geeft niet-http(s)-schema's
 * aan het OS. Web: geen betrouwbare vorm → null (alleen de tekst). */
export function mailAppUrl(p: AppPlatform): string | null {
  if (p === 'ios') return 'message://'
  if (p === 'android') return 'intent:#Intent;action=android.intent.action.MAIN;category=android.intent.category.APP_EMAIL;end'
  return null
}

export const GEEN_UITNODIGINGSLINK =
  'Dit is geen uitnodigingslink van de Nijenhuis Boekingsmodule. Plak de volledige link uit de e-mail van het kantoor.'
export const LINK_ZONDER_CODE = 'Deze link bevat geen uitnodiging — plak de volledige link uit de e-mail.'

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
  /** Open = uitgevouwen tonen (ná een mislukte activatie automatisch); dicht = alleen de tekstlink. */
  open: boolean
  onToggle: () => void
}

export function ActivatieHulp({ open, onToggle }: Props) {
  const p = huidigPlatform()
  const native = p !== 'web'
  const mailUrl = mailAppUrl(p)

  const openMailApp = () => {
    if (!mailUrl) return
    try {
      window.location.assign(mailUrl)
    } catch {
      // Het OS weigert het schema: de tekst eronder zegt wat de gebruiker zelf kan doen.
    }
  }

  if (!open) {
    return (
      <button type="button" className="acc-tekstlink" onClick={onToggle}>
        Nog geen uitnodiging?
      </button>
    )
  }

  return (
    <div className="acc-hulp" data-testid="acc-activatie-hulp" aria-live="polite">
      <div>
        <b>Nog geen uitnodiging?</b> Je activeert de app met de uitnodiging van het kantoor: tik op de{' '}
        <b>link in de uitnodigingsmail op dít toestel</b> (de app opent dan vanzelf de activatie) of voer de{' '}
        <b>activatiecode</b> uit dezelfde mail hierboven in. Daarna kies je een code van 5 cijfers waarmee je de app
        voortaan opent. Geen e-mail (meer) of is de uitnodiging verlopen? Vraag het kantoor om een <b>nieuwe uitnodiging</b>;
        de oude vervalt dan.
      </div>
      {native && mailUrl && (
        <>
          <button type="button" className="acc-btn secundair" onClick={openMailApp}>
            Mail-app openen
          </button>
          <div className="acc-vertrouwen" style={{ textAlign: 'left', maxWidth: 'none' }}>
            Opent de mail-app niet? Open hem dan zelf en tik op de link in de uitnodiging, of typ de activatiecode over.
          </div>
        </>
      )}
    </div>
  )
}
