import { useEffect, useState } from 'react'
import { formatteerActivatiecode } from './gebruikersApi'

/* Activatiecode-weergave (app-auth zonder passkey, besluit Peter 08-09, contract §6): overal waar het kantoor de
 * uitkomst van een uitnodiging / opnieuw mailen / herstel-link voor een APP-rol ziet, staat naast de link de
 * 8-tekens code `XXXX-XXXX` mét kopieerknop en één regel uitleg. Alleen gerenderd als de server een code
 * meegaf — kantoor-rollen krijgen null en zien niets. Bestaand patroon (linkbtn in een hint-regel), geen scherm. */
export function ActivatiecodeBlok({ code, naam }: { code: string | null | undefined; naam?: string }) {
  const [gekopieerd, setGekopieerd] = useState(false)
  useEffect(() => {
    if (!gekopieerd) return
    const t = setTimeout(() => setGekopieerd(false), 2500)
    return () => clearTimeout(t)
  }, [gekopieerd])
  if (!code) return null
  const weergave = formatteerActivatiecode(code)

  async function kopieer() {
    try {
      await navigator.clipboard.writeText(weergave)
      setGekopieerd(true)
    } catch {
      // Geen clipboard (http/LAN, oude browser): de code staat leesbaar in beeld — niets te melden.
      setGekopieerd(false)
    }
  }

  return (
    <div className="hint" role="status" data-testid="activatiecode-blok" style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
      <span>
        Activatiecode{naam ? ` voor ${naam}` : ''}:{' '}
        <b style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', letterSpacing: '0.08em' }} data-testid="activatiecode">
          {weergave}
        </b>
      </span>
      <button type="button" className="linkbtn" onClick={() => void kopieer()} aria-label={`Activatiecode ${weergave} kopiëren`}>
        {gekopieerd ? 'Gekopieerd' : 'Kopiëren'}
      </button>
      <span style={{ color: 'var(--muted)' }}>
        — voor wie de link niet kan openen: in te voeren in de app, zelfde geldigheid als de link (72 uur, eenmalig).
      </span>
    </div>
  )
}
