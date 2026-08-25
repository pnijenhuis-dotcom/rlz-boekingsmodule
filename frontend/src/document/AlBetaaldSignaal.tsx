import { useEffect, useState } from 'react'
import { apiJson } from '../api/client'
import type { AlBetaaldSignaalDto } from '../api/types'
import { formatBedrag, formatDatumKort } from '../werkvoorraad/format'

/** Al-betaald-signaal (besluit Peter 25-08, deel 2 punt 1): zodra crediteur + totaalbedrag
 * bekend zijn toetst de server de ONafgeletterde bankmutaties uit de lokale bank-cache (geen
 * live RLZ-call). Een treffer = zichtbaar signaal "Waarschijnlijk al betaald — datum, rekening,
 * bedrag" mét de matchreden. SIGNAAL, nooit blokkerend: boeken blijft gewoon mogelijk en de
 * bestaande afletter-matching pakt de mutatie ná het boeken op. Alleen op het controlescherm
 * (bewust géén werkvoorraad-chip). Herlaadt bij elke voorstel-opslag (boekvoorstelVersie). */
const RELEVANTE_STATUSSEN = new Set([
  'te_controleren',
  'klaar_om_te_boeken',
  'handmatig_afmaken',
  'boeken_mislukt',
  'vraag_open',
  'ter_accordering',
  'wacht_op_iban_accordering',
])

export function AlBetaaldSignaal({
  administratieId,
  documentId,
  status,
  soort,
  boekvoorstelVersie,
}: {
  administratieId: string
  documentId: string
  status: string
  soort: string
  boekvoorstelVersie: number
}) {
  const [signaal, setSignaal] = useState<AlBetaaldSignaalDto | null>(null)
  const relevant = soort === 'inkoopfactuur' && RELEVANTE_STATUSSEN.has(status)

  useEffect(() => {
    if (!relevant) return
    let actief = true
    apiJson<AlBetaaldSignaalDto>(`/administraties/${administratieId}/documenten/${documentId}/al-betaald`)
      .then((s) => {
        if (actief) setSignaal(s)
      })
      .catch(() => {
        // Signalering: een leesfout is geen reden voor een foutmelding op het controlescherm.
        if (actief) setSignaal(null)
      })
    return () => {
      actief = false
    }
  }, [administratieId, documentId, relevant, boekvoorstelVersie])

  if (!relevant || !signaal || !signaal.toetsbaar || signaal.treffers.length === 0) return null
  const [beste, ...overige] = signaal.treffers
  const rekening = beste.rekening_naam ?? (beste.rekening_iban ? `…${beste.rekening_iban.slice(-4)}` : 'onbekende rekening')
  return (
    <div
      className="panel al-betaald-signaal"
      role="status"
      style={{ borderColor: 'var(--orange)', padding: '10px 14px', marginBottom: 12 }}
    >
      <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
        <span className="chip afwijking">Waarschijnlijk al betaald</span>
        <b>
          {formatDatumKort(beste.boekdatum)} · {rekening} · {formatBedrag(String(beste.bedrag))}
        </b>
        <span style={{ fontSize: 12, color: 'var(--muted)' }}>match: {beste.redenen.join(' + ')}</span>
      </div>
      <div className="hint" style={{ margin: '4px 0 0' }}>
        Onafgeletterde bankmutatie{beste.tegenpartij_naam ? ` van "${beste.tegenpartij_naam}"` : ''}
        {beste.omschrijving ? ` — "${beste.omschrijving}"` : ''}. Signaal, geen blokkade: na het boeken pakt het
        afletteren deze mutatie op.
        {overige.length > 0 && ` Nog ${overige.length} mutatie(s) met exact dit bedrag.`}
      </div>
    </div>
  )
}
