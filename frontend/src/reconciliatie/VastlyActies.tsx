// Handelingen op de drie bevindingen van blok `vastly_verkoop` (Peter 28/29-09: "deze huurfacturen horen daar sowieso
// niet in te staan … moet gewoon als omzet geboekt worden, punt"; herzien 01-10: "vastly facturen 100% auto zonder
// menselijke tussenstap … hou het simpel"). Vastly-verkoopfacturen boeken automatisch op het administratie-id en de
// grootboekcode die Vastly in de UBL meestuurt. Wat hier staat is wat de UBL mist of wat gestrand is:
// - `vastly_entiteit_niet_gekoppeld` (kantoorbreed): de UBL draagt geen (bekend) administratie-id en geen bekende KvK →
//   melden bij Vastly; sinds 01-10 BEWUST geen koppelknop (de mens-koppeling van 29-09 is vervallen);
// - `vastly_omzetrekening_ontbreekt` (per document): regel zonder (bekende) grootboekcode → melden bij Vastly, ná de
//   herzending "Opnieuw aanbieden" (de knop "Rekening kiezen" en de instelling "Vastly-omzetrekeningen" zijn weg);
// - `vastly_verkoop_niet_geboekt` (per document): "Opnieuw aanbieden" → hetzelfde autoboek-pad als bij intake.
// Een mislukte handeling is zichtbaar naast de knop, nooit stil.
import { useState } from 'react'
import { ApiError, apiJson } from '../api/client'
import { Button } from '../ui/basis'
import type { BevindingDto } from './reconciliatieApi'

export function isVastlyEntiteitNietGekoppeld(r: BevindingDto): boolean {
  return (
    r.blok === 'vastly_verkoop' &&
    r.detail?.afwijking_soort === 'vastly_entiteit_niet_gekoppeld' &&
    typeof r.detail?.sleutel_soort === 'string' &&
    typeof r.detail?.sleutel === 'string'
  )
}

export function isVastlyOmzetrekeningOntbreekt(r: BevindingDto): boolean {
  return (
    r.blok === 'vastly_verkoop' &&
    r.detail?.afwijking_soort === 'vastly_omzetrekening_ontbreekt' &&
    typeof r.detail?.document_id === 'string' &&
    r.administratie_id !== null
  )
}

export function isVastlyVerkoopNietGeboekt(r: BevindingDto): boolean {
  return (
    r.blok === 'vastly_verkoop' &&
    r.detail?.afwijking_soort === 'vastly_verkoop_niet_geboekt' &&
    typeof r.detail?.document_id === 'string' &&
    r.administratie_id !== null
  )
}

export interface VastlyOpnieuwAanbiedenResultaatDto {
  document_id: string
  administratie_id: string
  uitkomst: 'geboekt' | 'geweigerd' | string
  reden: string | null
  doel_pad: string
}

export function opnieuwAanbieden(documentId: string, administratieId: string): Promise<VastlyOpnieuwAanbiedenResultaatDto> {
  return apiJson(`/reconciliatie/vastly/documenten/${documentId}/opnieuw-aanbieden`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ administratie_id: administratieId }),
  })
}

/** Tekst op de rij van `vastly_entiteit_niet_gekoppeld` (01-10): de handeling ligt bij Vastly, niet in de module. */
export function meldBijVastlyTekst(r: BevindingDto): string {
  const ruwId = typeof r.detail?.administratie_id_ubl === 'string' ? (r.detail.administratie_id_ubl as string) : null
  return ruwId
    ? `melden bij Vastly — de UBL noemt administratie-id ${ruwId}, dat de module niet kent; geen koppelknop in de module`
    : 'melden bij Vastly — de UBL draagt geen administratie-id (RLZ-ADMINISTRATIE) en geen bekende KvK; geen koppelknop in de module'
}

export function MeldBijVastlyHint({ bevinding }: { bevinding: BevindingDto }) {
  return <span className="hint">{meldBijVastlyTekst(bevinding)}</span>
}

export function OpnieuwAanbiedenActie({ bevinding, onGelukt }: { bevinding: BevindingDto; onGelukt: (melding: string) => void }) {
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [klaar, setKlaar] = useState<VastlyOpnieuwAanbiedenResultaatDto | null>(null)
  const documentId = String(bevinding.detail?.document_id ?? '')
  const bestand = typeof bevinding.detail?.bestandsnaam === 'string' ? (bevinding.detail.bestandsnaam as string) : documentId

  const uitvoeren = async () => {
    if (!documentId || bevinding.administratie_id === null) return
    setBezig(true)
    setFout(null)
    try {
      const r = await opnieuwAanbieden(documentId, bevinding.administratie_id)
      setKlaar(r)
      onGelukt(r.uitkomst === 'geboekt' ? `${bestand} is automatisch als omzet geboekt.` : `${bestand} nog niet geboekt: ${r.reden ?? 'reden onbekend'}`)
    } catch (err) {
      // 409 = geen kandidaat meer (status/soort), 404 = buiten scope — zichtbaar, nooit stil.
      setFout(err instanceof ApiError ? err.message : 'Opnieuw aanbieden mislukt.')
    } finally {
      setBezig(false)
    }
  }

  if (klaar) {
    return <span className="hint">{klaar.uitkomst === 'geboekt' ? 'geboekt' : `niet geboekt — ${klaar.reden ?? ''}`}</span>
  }
  return (
    <>
      <Button variant="primair" maat="klein" onClick={() => void uitvoeren()} disabled={!documentId || bezig} aria-label={`${bestand} opnieuw aanbieden`}>
        {bezig ? 'Bezig…' : 'Opnieuw aanbieden'}
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
