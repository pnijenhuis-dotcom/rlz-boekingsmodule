import { useState } from 'react'
import { ApiError } from '../api/client'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '../ui/basis'
import { voegSamen, type SamenvoegResultaatDto, type VerzamelbakItemDto } from './intakeApi'

function isXml(item: VerzamelbakItemDto): boolean {
  return /\.xml$/i.test(item.bestandsnaam)
}

/** Handmatig samenvoegen van twee verzamelbak-rijen (toevoeging Peter 02-09, vangnet voor wat de
 * automatische paar-detectie mist): de mens kiest het LEIDENDE bestand (UBL → velden deterministisch;
 * PDF → normale extractie ná toewijzing), het andere wordt beeld/bron. Waarschuwingen (andere mail,
 * zelfde bestandstype) zijn zichtbaar vóór de klik; twee UBL's/PDF's vragen een expliciete vink. */
export function SamenvoegDialog({
  items,
  onGereed,
  onSluit,
}: {
  items: [VerzamelbakItemDto, VerzamelbakItemDto]
  onGereed: (resultaat: SamenvoegResultaatDto) => void
  onSluit: () => void
}) {
  const [a, b] = items
  const xmlA = isXml(a)
  const xmlB = isXml(b)
  const zelfdeType = xmlA === xmlB
  // Default leidend: de UBL als er precies één is (data deterministisch), anders het eerste bestand.
  const [leidendId, setLeidendId] = useState<string>(xmlA !== xmlB ? (xmlA ? a.document_id : b.document_id) : a.document_id)
  const [bevestigZelfdeType, setBevestigZelfdeType] = useState(false)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  const leidend = leidendId === a.document_id ? a : b
  const ander = leidendId === a.document_id ? b : a
  const andereMail = (a.intake_bericht_id ?? null) !== (b.intake_bericht_id ?? null)

  const bevestig = async () => {
    setBezig(true)
    setFout(null)
    try {
      const r = await voegSamen(leidend.document_id, ander.document_id, bevestigZelfdeType)
      onGereed(r)
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Samenvoegen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onSluit()}>
      <DialogContent>
        <DialogTitle>Twee bestanden samenvoegen tot één document</DialogTitle>
        <DialogDescription>
          Kies welk bestand leidend is voor de gegevens. Het andere bestand blijft bewaard als beeld/bron van
          hetzelfde document — er wordt niets verwijderd en samenvoegen is ongedaan te maken zolang het document in
          de verzamelbak staat.
        </DialogDescription>
        <div role="radiogroup" aria-label="Leidend bestand" style={{ display: 'grid', gap: 8, margin: '10px 0' }}>
          {[a, b].map((item) => (
            <label key={item.document_id} style={{ display: 'flex', gap: 10, alignItems: 'flex-start', cursor: 'pointer' }}>
              <input
                type="radio"
                name="leidend"
                checked={leidendId === item.document_id}
                onChange={() => setLeidendId(item.document_id)}
              />
              <span>
                <b>{item.bestandsnaam}</b>{' '}
                <span className="chip klaar">{isXml(item) ? 'UBL — velden deterministisch' : 'PDF — extractie ná toewijzing'}</span>
                {item.tenaamstelling && (
                  <div className="hint" style={{ margin: 0 }}>
                    tenaamstelling &ldquo;{item.tenaamstelling}&rdquo;
                  </div>
                )}
              </span>
            </label>
          ))}
        </div>
        {andereMail && (
          <p className="hint" style={{ color: 'var(--orange)' }} data-testid="samenvoeg-waarschuwing-mail">
            ⚠ De twee bestanden komen uit verschillende e-mails/uploads — controleer of het echt dezelfde factuur is.
          </p>
        )}
        {zelfdeType && (
          <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12.5 }}>
            <input type="checkbox" checked={bevestigZelfdeType} onChange={(e) => setBevestigZelfdeType(e.target.checked)} />
            Beide bestanden zijn {xmlA ? 'UBL-bestanden' : "PDF's"} — dat is zelden één factuur. Toch samenvoegen.
          </label>
        )}
        {fout && <div className="fout">{fout}</div>}
        <div className="actions" style={{ marginTop: 12 }}>
          <button type="button" className="btn secondary" onClick={onSluit} disabled={bezig}>
            Annuleren
          </button>
          <button type="button" className="btn" disabled={bezig || (zelfdeType && !bevestigZelfdeType)} onClick={() => void bevestig()}>
            {bezig ? 'Bezig…' : `Samenvoegen — ${leidend.bestandsnaam} leidend ✓`}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
