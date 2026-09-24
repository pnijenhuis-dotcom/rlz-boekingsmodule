// AI-kostenmelding op de werkvoorraad (besluit 2026-08-14; herzien BUG Peter 24-09): de tekst komt uit één bron
// (`instellingen/aiKostenStand.ts`) — rood ("geblokkeerd") uitsluitend op de LIVE stand `geblokkeerd`; ná een verhoging
// één regel "weer actief sinds … ; N documenten wachten op heraanbieding" mét een tekstknop naar de verzamelbak
// (Kernprincipe 7.2: signalering draagt een handeling). Alleen voor de Beheerder (de kostenmeter is Beheerder-only).
import { useEffect, useState } from 'react'
import { useAuthOptioneel } from '../auth/AuthContext'
import { bepaalAiKostenStand } from '../instellingen/aiKostenStand'
import { haalAiKostenStatusOp, type AiKostenStatusDto } from '../instellingen/instellingenApi'

export const VERZAMELBAK_ANKER = 'verzamelbak'

export function AiKostenBannerInhoud({ status }: { status: AiKostenStatusDto }) {
  const stand = bepaalAiKostenStand(status)
  if (stand.soort === 'geen') return null
  if (stand.soort === 'geblokkeerd') {
    return (
      <div className="fout" role="alert" style={{ marginBottom: 12 }} data-testid="ai-kosten-banner">
        {stand.tekst}
      </div>
    )
  }
  if (stand.soort === 'weer_actief') {
    return (
      <div className="hint" role="status" style={{ marginBottom: 12 }} data-testid="ai-kosten-banner">
        {stand.tekst}
        {stand.wachten > 0 && (
          <>
            {' '}
            <button
              type="button"
              className="linkbtn"
              onClick={() => document.getElementById(VERZAMELBAK_ANKER)?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
            >
              Naar de verzamelbak
            </button>
          </>
        )}
      </div>
    )
  }
  return (
    <div className="hint" role="status" style={{ marginBottom: 12, color: 'var(--orange, #b45309)' }} data-testid="ai-kosten-banner">
      {stand.tekst}
    </div>
  )
}

export function AiKostenBanner() {
  const rol = useAuthOptioneel()?.rol ?? null
  const [status, setStatus] = useState<AiKostenStatusDto | null>(null)
  useEffect(() => {
    if (rol !== 'beheerder') return
    haalAiKostenStatusOp()
      .then(setStatus)
      .catch(() => undefined) // melding is best-effort; de harde poort zit in de backend
  }, [rol])
  if (!status) return null
  return <AiKostenBannerInhoud status={status} />
}
