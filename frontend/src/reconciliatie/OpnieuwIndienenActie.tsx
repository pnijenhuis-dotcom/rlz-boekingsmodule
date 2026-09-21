// "Opnieuw indienen" op de regressie-LET-OP `boek_wachtrij_gestrand` (Inzicht › Reconciliatie, blok automatisering; BUG
// 21-09: rlz-boek-wachtrij startte drie dagen niet — vijf boekingen hingen op "Wordt geboekt…" zonder één signaal). De rij
// draagt `detail.document_id` + `administratie_id`; de actie is exact de documentroute
// `POST …/boek-wachtrij/opnieuw-indienen` (zelfde boeking, zelfde sleutel, verwerker opnieuw gestart — nooit dubbel geboekt)
// en toont de trigger-uitkomst direct. Signalering zonder handeling is niet af.
import { useState } from 'react'
import { ApiError } from '../api/client'
import { opnieuwIndienen, opnieuwIndienenMelding, type BoekWachtrijOpnieuwDto } from '../document/WordtGeboektBalk'
import { Button } from '../ui/basis'
import type { BevindingDto } from './reconciliatieApi'

/** Is dit de rij waarop de actie hoort? Eén regel in `actieVoor`. */
export function isBoekWachtrijGestrand(r: BevindingDto): boolean {
  return (
    r.blok === 'automatisering' &&
    r.soort === 'let_op' &&
    r.detail?.reden === 'boek_wachtrij_gestrand' &&
    typeof r.detail?.document_id === 'string' &&
    r.administratie_id !== null
  )
}

export function OpnieuwIndienenActie({
  bevinding,
  onGelukt,
}: {
  bevinding: BevindingDto
  onGelukt: (melding: string, soort: 'ok' | 'warn') => void
}) {
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [klaar, setKlaar] = useState<BoekWachtrijOpnieuwDto | null>(null)
  const documentId = String(bevinding.detail?.document_id ?? '')
  const kan = bevinding.administratie_id !== null && documentId !== ''

  const uitvoeren = async () => {
    if (!kan || bevinding.administratie_id === null) return
    setBezig(true)
    setFout(null)
    try {
      const r = await opnieuwIndienen(bevinding.administratie_id, documentId)
      setKlaar(r)
      const m = opnieuwIndienenMelding(r)
      onGelukt(m.tekst, m.soort)
    } catch (err) {
      // 409 = de boeking is intussen geboekt of mislukt — de rij verdwijnt bij de volgende run; nooit stil opnieuw.
      setFout(err instanceof ApiError ? err.message : 'Opnieuw indienen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  if (klaar) {
    return (
      <span className="hint">
        {klaar.trigger_uitkomst === 'mislukt' ? `opnieuw ingediend — start mislukt: ${klaar.trigger_fout ?? '?'}` : 'opnieuw ingediend'}
      </span>
    )
  }
  return (
    <>
      <Button
        variant="primair"
        maat="klein"
        onClick={() => void uitvoeren()}
        disabled={!kan || bezig}
        aria-label={`Boeking opnieuw indienen (${bevinding.administratie_naam ?? 'deze administratie'})`}
      >
        {bezig ? 'Bezig…' : 'Opnieuw indienen'}
      </Button>
      {fout && (
        <>
          {' '}
          <span className="hint" style={{ color: 'var(--red)' }}>
            {fout}
          </span>
        </>
      )}
    </>
  )
}
