// "Wordt geboekt…"-balk op het controlescherm (BUG 21-09: job rlz-boek-wachtrij startte van 18-09 tot 21-09 niet — de
// boeking bleef op "Wordt geboekt…" zonder één zichtbaar signaal; de tijdlijn zei "de boeking loopt op de achtergrond"
// en daarna niets). De balk toont hoe lang de boeking al loopt, wordt ná WORDT_GEBOEKT_VAST_MINUTEN oranje mét "loopt
// vast" en draagt dan de handeling "Opnieuw indienen": zelfde boeking, zelfde sleutel — de server start alleen de
// achtergrond-schrijver opnieuw (nooit dubbel geboekt) en meldt de trigger-uitkomst direct terug. Teal = actie.
import { useEffect, useState } from 'react'
import { ApiError, apiPostJson } from '../api/client'
import { Button } from '../ui/basis'
import { WORDT_GEBOEKT_VAST_MINUTEN, wordtGeboektLooptVast, wordtGeboektMinuten } from '../werkvoorraad/status'

export interface BoekWachtrijOpnieuwDto {
  document_id: string
  status: string
  sleutel: string | null
  trigger_uitkomst: 'geslaagd' | 'mislukt' | 'lokaal'
  trigger_fout: string | null
}

export function opnieuwIndienen(administratieId: string, documentId: string): Promise<BoekWachtrijOpnieuwDto> {
  return apiPostJson<BoekWachtrijOpnieuwDto>(
    `/administraties/${administratieId}/documenten/${documentId}/boek-wachtrij/opnieuw-indienen`,
    {},
  )
}

export function opnieuwIndienenMelding(r: BoekWachtrijOpnieuwDto): { tekst: string; soort: 'ok' | 'warn' } {
  if (r.trigger_uitkomst === 'mislukt') {
    return {
      tekst: `Opnieuw ingediend, maar de achtergrond-schrijver start niet: ${r.trigger_fout ?? 'onbekende fout'} — het vangnet (elke 2 min) probeert het; blijft de rij hangen, dan is dit een systeemfout.`,
      soort: 'warn',
    }
  }
  return { tekst: 'Opnieuw ingediend — de achtergrond-schrijver is gestart; de rij ververst vanzelf.', soort: 'ok' }
}

export function WordtGeboektBalk({
  administratieId,
  documentId,
  laatstGewijzigdOp,
  onOpnieuw,
  nu,
}: {
  administratieId: string
  documentId: string
  laatstGewijzigdOp: string
  /** Ná een geslaagde aanroep: toast + detail herladen. */
  onOpnieuw: (melding: { tekst: string; soort: 'ok' | 'warn' }) => void
  /** Testhaak: vaste klok. */
  nu?: number
}) {
  const [tik, setTik] = useState(0)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  // Minuutklok zodat "N min" meeloopt zonder herladen.
  useEffect(() => {
    if (nu !== undefined) return
    const timer = setInterval(() => setTik((t) => t + 1), 30_000)
    return () => clearInterval(timer)
  }, [nu])
  void tik
  const klok = nu ?? Date.now()
  const minuten = wordtGeboektMinuten(laatstGewijzigdOp, klok)
  const vast = wordtGeboektLooptVast(laatstGewijzigdOp, klok)

  const uitvoeren = async () => {
    setBezig(true)
    setFout(null)
    try {
      const r = await opnieuwIndienen(administratieId, documentId)
      onOpnieuw(opnieuwIndienenMelding(r))
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Opnieuw indienen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <div
      className="panel"
      role="status"
      data-testid="wordt-geboekt-balk"
      style={vast ? { borderLeft: '4px solid var(--orange)' } : undefined}
    >
      <h2 style={{ marginBottom: 4 }}>
        {vast ? 'Wordt geboekt… — loopt vast' : 'Wordt geboekt…'}{' '}
        <span className={`chip ${vast ? 'vraag' : 'ai'}`}>{minuten} min</span>
      </h2>
      <p className="hint" style={{ marginTop: 0 }}>
        {vast
          ? `De boeking is ${minuten} minuten geleden ingediend en de achtergrond-schrijver rondde haar niet af (normaal binnen ${WORDT_GEBOEKT_VAST_MINUTEN} min). In Reeleezee is nog niets geboekt. "Opnieuw indienen" start de verwerker opnieuw voor dezelfde boeking — er wordt niets dubbel geboekt.`
          : 'De boeking in Reeleezee loopt op de achtergrond; dit scherm en de lijst verversen vanzelf. Duurt het langer dan een paar minuten, dan verschijnt hier "Opnieuw indienen".'}
      </p>
      {vast && (
        <Button variant="primair" maat="klein" onClick={() => void uitvoeren()} disabled={bezig} aria-label="Boeking opnieuw indienen">
          {bezig ? 'Bezig…' : 'Opnieuw indienen'}
        </Button>
      )}
      {fout && (
        <p className="hint" style={{ color: 'var(--red)', marginTop: 6 }}>
          {fout}
        </p>
      )}
    </div>
  )
}
