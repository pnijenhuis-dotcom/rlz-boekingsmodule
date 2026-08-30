import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { haalDocumentTerugkerendSignaal, type DocumentTerugkerendSignaalDto } from '../terugkerend/terugkerendApi'
import { formatBedrag, formatDatumKort } from '../werkvoorraad/format'

/** Prijsstijging-chip (terugkerende facturen, blok B 30-08 — patroon AanbetalingSignaal): de server
 * herkent per leverancier een regelmatig factuurritme en vergelijkt dit document met de vorige
 * vergelijkbare factuur; boven de drempel (default 10 %) een zichtbaar signaal. Alleen signaleren,
 * nooit blokkeren; leesfout = geen melding. */
const RELEVANTE_STATUSSEN = new Set([
  'te_controleren',
  'klaar_om_te_boeken',
  'handmatig_afmaken',
  'boeken_mislukt',
  'vraag_open',
  'ter_accordering',
  'wacht_op_iban_accordering',
  'geboekt',
])

export function TerugkerendSignaal({
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
  const [signaal, setSignaal] = useState<DocumentTerugkerendSignaalDto | null>(null)
  const relevant = soort === 'inkoopfactuur' && RELEVANTE_STATUSSEN.has(status)
  useEffect(() => {
    if (!relevant) return
    let actief = true
    haalDocumentTerugkerendSignaal(administratieId, documentId)
      .then((s) => {
        if (actief) setSignaal(s)
      })
      .catch(() => {
        if (actief) setSignaal(null)
      })
    return () => {
      actief = false
    }
  }, [administratieId, documentId, relevant, boekvoorstelVersie])

  if (!relevant || !signaal || signaal.prijsstijging_pct === null) return null
  return (
    <div className="panel terugkerend-signaal" role="status" style={{ borderColor: 'var(--orange)', padding: '10px 14px', marginBottom: 12 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
        <span className="chip afwijking">Prijsstijging +{Number(signaal.prijsstijging_pct).toLocaleString('nl-NL', { maximumFractionDigits: 1 })}%</span>
        <span>
          Terugkerende factuur ({signaal.patroon === 'maand' ? 'maandelijks' : 'per kwartaal'}
          {signaal.leverancier ? `, ${signaal.leverancier}` : ''}): <b>{signaal.laatste_bedrag ? formatBedrag(signaal.laatste_bedrag) : ''}</b> t.o.v.{' '}
          {signaal.vorige_bedrag ? formatBedrag(signaal.vorige_bedrag) : ''}
          {signaal.vorige_datum ? ` op ${formatDatumKort(signaal.vorige_datum)}` : ''}.
        </span>
        <Link to={`/terugkerend?administratie=${administratieId}`} style={{ fontSize: 12 }}>
          Alle terugkerende facturen →
        </Link>
      </div>
      <div className="hint" style={{ margin: '4px 0 0' }}>
        Signaal, geen blokkade — controleer of de stijging klopt (indexering, tariefwijziging) vóór het boeken.
      </div>
    </div>
  )
}
