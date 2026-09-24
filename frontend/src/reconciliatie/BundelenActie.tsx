// "Bundelen" — blok 1 bundelrun 24-09 (Vastly-batch 23-09): een losse INKOOPFACTUUR-PDF in de werkvoorraad die de tweeling is
// van een UBL-verkoopfactuur uit dezelfde e-mail (zelfde naamstam ná `-ubl`/`_ubl`, of het factuurnummer in de PDF) krijgt op
// Inzicht › Reconciliatie de bevinding `ubl_pdf_ongebundeld` (in meting). De actie is exact het herstel van de nazorg-CLI voor
// dít document: de PDF wordt het beeld van het UBL-document, het PDF-document gaat naar "samengevoegd" (nooit verwijderd),
// tijdlijn + audit op beide kanten; is de verkoopfactuur al geboekt, dan gaat de PDF óók als bijlage naar Reeleezee.
// Geen reden nodig (geen afvoer). 404 = geen paar meer, 409 = twijfel/intussen verwerkt — beide zichtbaar naast de knop.
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, apiJson } from '../api/client'
import { Button } from '../ui/basis'
import type { BevindingDto } from './reconciliatieApi'

export interface BundelenResultaatDto {
  document_id: string
  ubl_document_id: string
  status: string
  match_basis: string | null
  rlz_bijlage: string | null
  doel_pad: string
}

/** Is dit de rij waarop de actie hoort? Eén regel in `actieVoor`. */
export function isUblPdfOngebundeld(r: BevindingDto): boolean {
  return (
    r.blok === 'documenten' &&
    r.detail?.afwijking_soort === 'ubl_pdf_ongebundeld' &&
    typeof r.detail?.document_id === 'string' &&
    r.administratie_id !== null
  )
}

export function bundelen(documentId: string, administratieId: string): Promise<BundelenResultaatDto> {
  return apiJson(`/reconciliatie/documenten/${documentId}/bundelen`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ administratie_id: administratieId }),
  })
}

export function BundelenActie({
  bevinding,
  onGelukt,
}: {
  bevinding: BevindingDto
  onGelukt: (melding: string, doelPad: string) => void
}) {
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [klaar, setKlaar] = useState<BundelenResultaatDto | null>(null)
  const documentId = String(bevinding.detail?.document_id ?? '')
  const kan = bevinding.administratie_id !== null && documentId !== ''

  const uitvoeren = async () => {
    if (!kan || bevinding.administratie_id === null) return
    setBezig(true)
    setFout(null)
    try {
      const r = await bundelen(documentId, bevinding.administratie_id)
      setKlaar(r)
      const bijlage = r.rlz_bijlage ? ` Reeleezee-bijlage: ${r.rlz_bijlage}.` : ''
      onGelukt(`Gebundeld: de PDF is nu het beeld van de verkoopfactuur en staat niet meer in de werkvoorraad.${bijlage}`, r.doel_pad)
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Bundelen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  if (klaar) {
    return (
      <Link to={klaar.doel_pad} className="btn" aria-label="Naar de verkoopfactuur">
        Naar de verkoopfactuur →
      </Link>
    )
  }
  return (
    <>
      {kan ? (
        <Button maat="klein" aria-label={`Bundelen: ${bevinding.titel}`} disabled={bezig} onClick={() => void uitvoeren()}>
          {bezig ? 'Bezig…' : 'Bundelen'}
        </Button>
      ) : null}
      {fout && (
        <span className="fout" role="alert" style={{ marginLeft: 6 }}>
          {fout}
        </span>
      )}
    </>
  )
}
