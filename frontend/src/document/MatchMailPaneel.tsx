import { useState } from 'react'
import { ApiError, apiJson, apiPostJson } from '../api/client'
import type { MatchMailConceptDto } from '../api/types'

/** Concept-mail aan de veldwerker over een urenmatch-afwijking (factuurmatch fase 2).
 * Flow: kantoor klikt → de server genereert een CONCEPT uit de match-cijfers (+ de
 * afwijzingsreden) → de mens leest, bewerkt en verstuurt expliciet. Er wordt nooit
 * automatisch gemaild; verzending landt zichtbaar in tijdlijn + audit. */
export function MatchMailPaneel({
  administratieId,
  documentId,
  onVerzonden,
}: {
  administratieId: string
  documentId: string
  onVerzonden: () => void
}) {
  const [concept, setConcept] = useState<MatchMailConceptDto | null>(null)
  const [onderwerp, setOnderwerp] = useState('')
  const [tekst, setTekst] = useState('')
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [verzondenAan, setVerzondenAan] = useState<string | null>(null)

  const laadConcept = async () => {
    setBezig(true)
    setFout(null)
    try {
      const dto = await apiJson<MatchMailConceptDto>(
        `/administraties/${administratieId}/documenten/${documentId}/factuurmatch/concept-mail`,
      )
      setConcept(dto)
      setOnderwerp(dto.onderwerp)
      setTekst(dto.tekst)
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Concept kon niet gegenereerd worden.')
    } finally {
      setBezig(false)
    }
  }

  const versturen = async () => {
    setBezig(true)
    setFout(null)
    try {
      const resultaat = await apiPostJson<{ verzonden_aan: string }>(
        `/administraties/${administratieId}/documenten/${documentId}/factuurmatch/mail`,
        { onderwerp, tekst },
      )
      setVerzondenAan(resultaat.verzonden_aan)
      setConcept(null)
      onVerzonden()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Versturen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  if (verzondenAan) {
    return (
      <p className="hint" style={{ marginBottom: 0 }}>
        ✓ Mail verzonden aan <b>{verzondenAan}</b> — vastgelegd in de tijdlijn.
      </p>
    )
  }

  if (concept === null) {
    return (
      <div style={{ marginTop: 8 }}>
        {fout && <div className="fout">{fout}</div>}
        <button type="button" className="btn secondary" disabled={bezig} onClick={() => void laadConcept()}>
          {bezig ? 'Bezig…' : '✉ Concept-mail aan veldwerker…'}
        </button>
      </div>
    )
  }

  return (
    <div style={{ marginTop: 10 }}>
      <p className="hint" style={{ marginTop: 0 }}>
        Concept aan <b>{concept.ontvanger_naam ?? concept.ontvanger_e_mail}</b> ({concept.ontvanger_e_mail}) —
        controleer en pas aan vóór verzending; er wordt niets automatisch verstuurd.
      </p>
      <label style={{ display: 'block', marginBottom: 8 }}>
        <span className="hint">Onderwerp</span>
        <input
          type="text"
          value={onderwerp}
          onChange={(e) => setOnderwerp(e.target.value)}
          style={{ width: '100%' }}
        />
      </label>
      <label style={{ display: 'block' }}>
        <span className="hint">Bericht</span>
        <textarea value={tekst} onChange={(e) => setTekst(e.target.value)} rows={12} style={{ width: '100%' }} />
      </label>
      {fout && <div className="fout">{fout}</div>}
      <div className="actions" style={{ marginTop: 8 }}>
        <button type="button" className="btn secondary" disabled={bezig} onClick={() => setConcept(null)}>
          Annuleren
        </button>
        <button
          type="button"
          className="btn"
          disabled={bezig || !onderwerp.trim() || !tekst.trim()}
          onClick={() => void versturen()}
        >
          {bezig ? 'Bezig…' : 'Versturen'}
        </button>
      </div>
    </div>
  )
}
