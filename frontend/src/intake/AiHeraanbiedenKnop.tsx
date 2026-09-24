// Knop "Opnieuw verwerken (N)" op de verzamelbak (BUG Peter 24-09): N = de rijen met reden `ai_limiet_bereikt` (de 202 van
// de herstelrun 23-09). Dezelfde motor als de automatische heraanbieding (`app/aikosten/heraanbieden.py`): POST → 202,
// de intake-job doet het werk; dit component pollt de stand en toont ná afloop de uitkomst per rij zoals bulk-upload
// (toegewezen / blijft in de bak mét andere reden / dubbel / wacht op budget / …). 409 = poort dicht mét reden —
// nooit stil. Beheerder/Boekhouding (kantoorrollen — de server is de poort).
import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/client'
import {
  AI_HERAANBIEDING_UITKOMST_LABEL,
  haalAiHeraanbiedingStandOp,
  startAiHeraanbieding,
  type AiHeraanbiedingRunDto,
  type AiHeraanbiedingStandDto,
} from './intakeApi'

export const AI_LIMIET_REDEN = 'ai_limiet_bereikt'

export function telAiLimietRijen(items: { reden?: string | null }[] | null): number {
  return (items ?? []).filter((i) => (i.reden ?? '').trim() === AI_LIMIET_REDEN).length
}

function tellerTekst(run: AiHeraanbiedingRunDto): string {
  const delen = Object.entries(run.tellers)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([k, n]) => `${n} ${AI_HERAANBIEDING_UITKOMST_LABEL[k] ?? k}`)
  const over = Object.entries(run.overgeslagen)
    .filter(([, n]) => n > 0)
    .map(([k, n]) => `${n} overgeslagen (${k})`)
  return [...delen, ...over].join(' · ') || 'niets te doen'
}

export function AiHeraanbiedenKnop({
  aantal,
  onKlaar,
  pollMs = 3000,
  maxPollMs = 15 * 60 * 1000,
}: {
  aantal: number
  onKlaar?: () => void
  pollMs?: number
  maxPollMs?: number
}) {
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [melding, setMelding] = useState<string | null>(null)
  const [run, setRun] = useState<AiHeraanbiedingRunDto | null>(null)
  const [toonAlles, setToonAlles] = useState(false)
  const gestartOp = useRef<number | null>(null)
  const timer = useRef<number | null>(null)

  const stop = useCallback(() => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current)
      timer.current = null
    }
  }, [])

  useEffect(() => stop, [stop])

  const verwerkStand = useCallback(
    (stand: AiHeraanbiedingStandDto): boolean => {
      const r = stand.laatste_run
      const klaarNaStart =
        r !== null && r.status === 'klaar' && r.klaar_op !== null && gestartOp.current !== null && Date.parse(r.klaar_op) >= gestartOp.current - 1000
      if (klaarNaStart && !stand.bezig) {
        setRun(r)
        setBezig(false)
        setMelding(null)
        onKlaar?.()
        return true
      }
      return false
    },
    [onKlaar],
  )

  const poll = useCallback(() => {
    const tik = async () => {
      try {
        const stand = await haalAiHeraanbiedingStandOp()
        if (verwerkStand(stand)) return
      } catch {
        // tijdelijke fout: gewoon opnieuw proberen tot het budget op is
      }
      if (gestartOp.current !== null && Date.now() - gestartOp.current > maxPollMs) {
        setBezig(false)
        setMelding('De heraanbieding loopt nog (of de job is nog niet gestart) — de rijen verdwijnen uit de lijst zodra ze verwerkt zijn; ververs later.')
        return
      }
      timer.current = window.setTimeout(() => void tik(), pollMs)
    }
    timer.current = window.setTimeout(() => void tik(), pollMs)
  }, [maxPollMs, pollMs, verwerkStand])

  const start = async () => {
    if (bezig) return
    setFout(null)
    setRun(null)
    setBezig(true)
    gestartOp.current = Date.now()
    try {
      const r = await startAiHeraanbieding()
      setMelding(
        r.voertuig === 'cloud_run_job'
          ? `Opnieuw verwerken gestart voor ${r.kandidaten_verzamelbak} verzamelbak-${r.kandidaten_verzamelbak === 1 ? 'rij' : 'rijen'}${r.kandidaten_documenten > 0 ? ` en ${r.kandidaten_documenten} document(en) met overgeslagen extractie` : ''} — de uitkomst per rij verschijnt hier zodra de verwerking klaar is.`
          : 'Opnieuw verwerken gestart (achtergrond) — de uitkomst per rij verschijnt hier zodra de verwerking klaar is.',
      )
      poll()
    } catch (err) {
      setBezig(false)
      // 409 = AI-maandlimiet bereikt (poort dicht) — de reden staat in de body, nooit een stille no-op.
      setFout(err instanceof ApiError ? err.message : 'Opnieuw verwerken kon niet gestart worden.')
    }
  }

  if (aantal === 0 && !bezig && !run && !fout && !melding) return null
  const rijen = run?.uitkomsten ?? []
  const zichtbaar = toonAlles ? rijen : rijen.slice(0, 10)
  return (
    <div data-testid="ai-heraanbieden" style={{ display: 'flex', flexDirection: 'column', gap: 6, flexBasis: '100%' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        {aantal > 0 && (
          <span className="hint" style={{ margin: 0 }}>
            {aantal} {aantal === 1 ? 'rij wacht' : 'rijen wachten'} sinds de AI-limiet op verwerking — dat gebeurt automatisch zodra er budget is;
            met de knop start je het nu.
          </span>
        )}
        <button
          type="button"
          className="btn"
          style={{ padding: '5px 12px' }}
          disabled={bezig || aantal === 0}
          onClick={() => void start()}
          aria-label={`Opnieuw verwerken (${aantal})`}
        >
          {bezig ? 'Bezig…' : `Opnieuw verwerken (${aantal})`}
        </button>
      </div>
      {fout && (
        <div className="fout" role="alert" data-testid="ai-heraanbieden-fout">
          {fout}
        </div>
      )}
      {melding && (
        <div className="hint" role="status" data-testid="ai-heraanbieden-melding" style={{ margin: 0 }}>
          {melding}
        </div>
      )}
      {run && (
        <div className="hint" data-testid="ai-heraanbieden-uitkomst" style={{ margin: 0 }}>
          <strong>Uitkomst opnieuw verwerken:</strong> {tellerTekst(run)}
          {run.gestopt_reden ? ` — ${run.gestopt_reden}` : ''}
          {rijen.length > 0 && (
            <div className="tabel-scroll" style={{ marginTop: 4 }}>
              <table style={{ fontSize: 12.5 }}>
                <tbody>
                  {zichtbaar.map((u) => (
                    <tr key={u.document_id}>
                      <td>{u.bestandsnaam}</td>
                      <td>{AI_HERAANBIEDING_UITKOMST_LABEL[u.uitkomst] ?? u.uitkomst}</td>
                      <td style={{ color: 'var(--muted)' }}>{u.detail ?? ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {rijen.length > zichtbaar.length && (
                <button type="button" className="linkbtn" onClick={() => setToonAlles(true)}>
                  Alle {rijen.length} tonen
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
