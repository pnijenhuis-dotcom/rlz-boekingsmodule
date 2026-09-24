// "Factuur-PDF herstellen" — stap 4 van de RLZ-vorm-opdracht 24-09 (BESLISSINGEN "DOORBELASTING — BTW PER TARIEF OVER HET
// SUBTOTAAL (RLZ-VORM) + DATA-STAP + FACTUUR-PDF-HERSTEL (Peter 24-09)"): een geboekte doorbelasting zonder rechtsgeldige
// factuur-PDF op de spiegel (art. 35a) ouder dan een dag krijgt op Inzicht › Reconciliatie de bevinding
// `doorbelasting_factuur_pdf_ontbreekt`. De knop is exact het bestaande herstelpad voor dít record (server:
// POST /reconciliatie/doorbelasting/{boeking_id}/factuur-herstellen): RLZ rendert de verkoopfactuur opnieuw, de module toetst
// 'm cent-exact tegen de geregistreerde bedragen en zet 'm als bijlage op beide kanten — nooit een herboeking. Lukt het niet
// (422), dan staat de reden naast de knop én op de boeking. Teal = actie.
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, apiJson } from '../api/client'
import { Button } from '../ui/basis'
import type { BevindingDto } from './reconciliatieApi'

export interface FactuurPdfHerstellenResultaatDto {
  boeking_id: string
  document_id: string
  doelentiteit_naam: string
  verkoop_referentie: string | null
  factuur_pdf_status: string
  doel_pad: string
}

/** Is dit de rij waarop de actie hoort? Eén regel in `actieVoor`. */
export function isDoorbelastingFactuurPdfOntbreekt(r: BevindingDto): boolean {
  return (
    r.blok === 'doorbelasting' &&
    r.detail?.afwijking_soort === 'doorbelasting_factuur_pdf_ontbreekt' &&
    typeof r.detail?.boeking_id === 'string' &&
    r.administratie_id !== null
  )
}

export function factuurPdfHerstellen(boekingId: string, administratieId: string): Promise<FactuurPdfHerstellenResultaatDto> {
  return apiJson(`/reconciliatie/doorbelasting/${boekingId}/factuur-herstellen`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ administratie_id: administratieId }),
  })
}

export function FactuurPdfHerstellenActie({
  bevinding,
  onGelukt,
}: {
  bevinding: BevindingDto
  onGelukt: (melding: string, doelPad: string) => void
}) {
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [klaar, setKlaar] = useState<FactuurPdfHerstellenResultaatDto | null>(null)
  const boekingId = String(bevinding.detail?.boeking_id ?? '')
  const kan = bevinding.administratie_id !== null && boekingId !== ''

  const uitvoeren = async () => {
    if (!kan || bevinding.administratie_id === null) return
    setBezig(true)
    setFout(null)
    try {
      const r = await factuurPdfHerstellen(boekingId, bevinding.administratie_id)
      setKlaar(r)
      onGelukt(
        `Factuur-PDF hersteld: de factuur voor ${r.doelentiteit_naam}${r.verkoop_referentie ? ` (${r.verkoop_referentie})` : ''} staat nu als bijlage op beide kanten.`,
        r.doel_pad,
      )
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Factuur-PDF herstellen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  if (klaar) {
    return (
      <Link to={klaar.doel_pad} className="btn" aria-label="Naar de doorbelasting">
        Naar de doorbelasting →
      </Link>
    )
  }
  return (
    <>
      {kan ? (
        <Button maat="klein" aria-label={`Factuur-PDF herstellen: ${bevinding.titel}`} disabled={bezig} onClick={() => void uitvoeren()}>
          {bezig ? 'Bezig…' : 'Factuur-PDF herstellen'}
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
