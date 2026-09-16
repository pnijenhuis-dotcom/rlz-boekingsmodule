// "Type wijzigen → kassarapport" — blok C (Peter 16-09 avond): een INKOOPFACTUUR in de werkvoorraad die op inhoud een
// kassarapport is (herkende bron op de PDF-tekstlaag, of alle regels op omzetrekeningen) krijgt op Inzicht › Reconciliatie
// de bevinding `kassarapport_in_werkvoorraad`. De actie is exact de bestaande soort-wissel uit de documentenlijst (bulk
// 16-09): document → kassarapport, terug naar Ontvangen, extractie opnieuw via het omzetpad. Geen reden nodig (geen
// afvoer, niets in RLZ); geboekt/ter accordering = 409 uit de enkelvoudige route.
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, apiJson } from '../api/client'
import { Button } from '../ui/basis'
import type { BevindingDto } from './reconciliatieApi'

export interface TypeWijzigenKassarapportResultaatDto {
  document_id: string
  status: string
  van_soort: string
  naar_soort: string
  doel_pad: string
}

/** Is dit de rij waarop de actie hoort? Eén regel in `actieVoor`. */
export function isKassarapportInWerkvoorraad(r: BevindingDto): boolean {
  return r.blok === 'omzet' && r.detail?.afwijking_soort === 'kassarapport_in_werkvoorraad'
}

export function typeWijzigenKassarapport(bevindingId: string, administratieId: string): Promise<TypeWijzigenKassarapportResultaatDto> {
  return apiJson(`/reconciliatie/bevindingen/${bevindingId}/type-wijzigen-kassarapport`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ administratie_id: administratieId }),
  })
}

export function TypeWijzigenKassarapportActie({
  bevinding,
  onGelukt,
}: {
  bevinding: BevindingDto
  onGelukt: (melding: string, doelPad: string) => void
}) {
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [klaar, setKlaar] = useState<TypeWijzigenKassarapportResultaatDto | null>(null)
  const kan = bevinding.administratie_id !== null

  const uitvoeren = async () => {
    if (!kan || bevinding.administratie_id === null) return
    setBezig(true)
    setFout(null)
    try {
      const r = await typeWijzigenKassarapport(bevinding.id, bevinding.administratie_id)
      setKlaar(r)
      onGelukt('Het document is nu een kassarapport en gaat opnieuw door de omzet-verwerking.', r.doel_pad)
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Type wijzigen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  if (klaar) {
    return (
      <Link to={klaar.doel_pad} className="btn" aria-label="Naar het kassarapport">
        Naar het kassarapport →
      </Link>
    )
  }
  return (
    <>
      {kan ? (
        <Button maat="klein" aria-label={`Type wijzigen naar kassarapport: ${bevinding.titel}`} disabled={bezig} onClick={() => void uitvoeren()}>
          {bezig ? 'Bezig…' : 'Type wijzigen → kassarapport'}
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
