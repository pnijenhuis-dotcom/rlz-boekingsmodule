import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiJson } from '../api/client'
import type { AanbetalingOpenDto, AanbetalingOpenTrefferDto } from '../api/types'
import { formatBedrag, formatDatumKort } from '../werkvoorraad/format'

/** Aanbetaling-open-signaal (besluit Peter 25-08, deel 4 punt 3 — 1-op-1 het patroon van
 * AlBetaaldSignaal): de server zoekt in de bank-directboekingen van deze administratie naar een
 * aanbetaling op een vooruitbetalingsrekening voor dezelfde leverancier (Entity, anders IBAN) die
 * nog niet verrekend is. Een treffer = zichtbaar signaal + één klik "Verrekenregel toevoegen": een
 * negatieve regel op de vooruit-rekening in het boekvoorstel (de mens controleert en boekt).
 * SIGNAAL, nooit blokkerend; leesfout = geen melding. */
const RELEVANTE_STATUSSEN = new Set([
  'te_controleren',
  'klaar_om_te_boeken',
  'handmatig_afmaken',
  'boeken_mislukt',
  'vraag_open',
  'ter_accordering',
  'wacht_op_iban_accordering',
])

export interface VerrekenRegel {
  ledger_id: string
  netto_bedrag: number
  btw_bedrag: 0
  omschrijving: string
}

export function verrekenRegelVoor(treffer: AanbetalingOpenTrefferDto): VerrekenRegel {
  return {
    ledger_id: treffer.vooruit_ledger_id,
    netto_bedrag: -Number(treffer.bedrag),
    btw_bedrag: 0,
    omschrijving: `Verrekening aanbetaling ${treffer.rlz_boekstuknummer ?? ''} ${treffer.boekdatum ?? ''}`.replace(/\s+/g, ' ').trim(),
  }
}

export function AanbetalingSignaal({
  administratieId,
  documentId,
  status,
  soort,
  boekvoorstelVersie,
  onVerrekenregel,
}: {
  administratieId: string
  documentId: string
  status: string
  soort: string
  boekvoorstelVersie: number
  /** Alleen meegegeven als het boekvoorstel bewerkbaar is — undefined verbergt de knop. */
  onVerrekenregel?: (regel: VerrekenRegel) => void
}) {
  const [signaal, setSignaal] = useState<AanbetalingOpenDto | null>(null)
  const relevant = soort === 'inkoopfactuur' && RELEVANTE_STATUSSEN.has(status)

  useEffect(() => {
    if (!relevant) return
    let actief = true
    apiJson<AanbetalingOpenDto>(`/administraties/${administratieId}/documenten/${documentId}/aanbetaling-open`)
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
  return (
    <div
      className="panel aanbetaling-signaal"
      role="status"
      style={{ borderColor: 'var(--orange)', padding: '10px 14px', marginBottom: 12 }}
    >
      {signaal.treffers.map((t) => (
        <div key={t.boeking_id} style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
          <span className="chip afwijking">Aanbetaling open</span>
          <span>
            Voor deze leverancier staat nog een aanbetaling open (
            <b>{formatBedrag(t.bedrag)}</b>
            {t.boekdatum ? `, ${formatDatumKort(t.boekdatum)}` : ''}
            {t.rlz_boekstuknummer ? ` · boekstuk ${t.rlz_boekstuknummer}` : ''})
          </span>
          {t.herkenning === 'iban' && (
            <span className="chip geheugen" title="Leverancier herkend op het IBAN van de bankmutatie, niet op de RLZ-crediteur">
              via IBAN
            </span>
          )}
          <Link to={`/bank/${administratieId}`} style={{ fontSize: 12 }}>
            Bekijk in bank →
          </Link>
          {onVerrekenregel && (
            <button type="button" className="btn secondary" style={{ padding: '3px 10px' }} onClick={() => onVerrekenregel(verrekenRegelVoor(t))}>
              Verrekenregel toevoegen
            </button>
          )}
        </div>
      ))}
      <div className="hint" style={{ margin: '4px 0 0' }}>
        Signaal, geen blokkade: een verrekenregel zet het aanbetaalde bedrag negatief op de vooruitbetalingsrekening
        {signaal.treffers.some((t) => t.entity_naam) ? ` (${signaal.treffers.find((t) => t.entity_naam)?.entity_naam})` : ''}
        — controleer de btw-code en het totaal vóór het boeken.
      </div>
    </div>
  )
}
