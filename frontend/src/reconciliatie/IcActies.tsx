// Handeling "Factuur opvragen bij ‹BV›" op een `ic_inkoop_ontbreekt`-bevinding (run D 02-10 blok D, Peter 02-10; casus
// Universal: 36 Nederland-facturen "nergens in de module" — de verkopende BV heeft de factuur, de ontvanger kreeg 'm
// nooit). De server bouwt een MAILCONCEPT aan de boekhouding van de verkopende BV (vraag om de PDF/UBL naar onze
// boekhoudmail te sturen) en legt audit `ic_factuur_opgevraagd_concept` vast; er wordt NOOIT automatisch gemaild — de
// mens opent het concept in zijn mailprogramma (mailto) of kopieert de tekst. De module kent geen adres per administratie:
// het concept toont een plaatshouder voor het "aan"-adres. Eén component, één schrijver (server).
import { useState } from 'react'
import { ApiError, apiJson } from '../api/client'
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from '../ui/basis'
import type { BevindingDto } from './reconciliatieApi'

export function isIcInkoopOntbreekt(r: BevindingDto): boolean {
  return (
    r.blok === 'intercompany' &&
    r.soort === 'afwijking' &&
    r.detail?.afwijking_soort === 'ic_inkoop_ontbreekt' &&
    r.administratie_id !== null
  )
}

export interface IcMailConceptDto {
  bevinding_id: string
  administratie_id: string
  verkoper_naam: string
  ontvanger_naam: string
  nummer: string | null
  datum: string | null
  bedrag: string | null
  aan: string | null
  aan_tekst: string
  onderwerp: string
  tekst: string
  mailto: string
  intake_adres: string | null
}

export function icFactuurOpvragen(bevindingId: string, administratieId: string): Promise<IcMailConceptDto> {
  return apiJson(`/reconciliatie/intercompany/${bevindingId}/factuur-opvragen`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ administratie_id: administratieId }),
  })
}

export function FactuurOpvragenActie({ bevinding, onGelukt }: { bevinding: BevindingDto; onGelukt: (melding: string) => void }) {
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [concept, setConcept] = useState<IcMailConceptDto | null>(null)
  const [gekopieerd, setGekopieerd] = useState(false)
  const verkoper = typeof bevinding.detail?.verkoper_naam === 'string' ? (bevinding.detail.verkoper_naam as string) : 'de verkopende BV'
  const nummer = typeof bevinding.detail?.nummer === 'string' ? (bevinding.detail.nummer as string) : bevinding.id

  const opvragen = async () => {
    if (bevinding.administratie_id === null) return
    setBezig(true)
    setFout(null)
    try {
      const c = await icFactuurOpvragen(bevinding.id, bevinding.administratie_id)
      setConcept(c)
      onGelukt(`Mailconcept klaar voor ${c.verkoper_naam} (factuur ${c.nummer ?? '?'}) — nog niet verzonden.`)
    } catch (err) {
      // 404 = buiten scope, 409 = geen ic_inkoop_ontbreekt-bevinding — zichtbaar, nooit stil.
      setFout(err instanceof ApiError ? err.message : 'Factuur opvragen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  const kopieer = async () => {
    if (!concept) return
    try {
      await navigator.clipboard.writeText(`Onderwerp: ${concept.onderwerp}\n\n${concept.tekst}`)
      setGekopieerd(true)
    } catch {
      setGekopieerd(false)
      setFout('Kopiëren naar het klembord lukte niet — selecteer de tekst zelf.')
    }
  }

  return (
    <>
      <Button variant="primair" maat="klein" onClick={() => void opvragen()} disabled={bezig} aria-label={`Factuur ${nummer} opvragen bij ${verkoper}`}>
        {bezig ? 'Bezig…' : `Factuur opvragen bij ${verkoper}`}
      </Button>
      {fout && (
        <>
          {' '}
          <span className="hint" style={{ color: 'var(--red)' }}>
            {fout}
          </span>
        </>
      )}
      {concept && (
        <Dialog open onOpenChange={(o) => !o && setConcept(null)}>
          <DialogContent aria-describedby={undefined} data-testid="ic-factuur-opvragen-dialoog">
            <DialogTitle>Mailconcept — factuur {concept.nummer ?? '?'} opvragen bij {concept.verkoper_naam}</DialogTitle>
            <DialogDescription>
              Niets is verzonden. Open het concept in je mailprogramma of kopieer de tekst; het adres van de boekhouding van{' '}
              {concept.verkoper_naam} vul je zelf in.
            </DialogDescription>
            <dl className="ic-concept" style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '4px 12px', margin: '8px 0' }}>
              <dt>Aan</dt>
              <dd data-testid="ic-concept-aan">{concept.aan ?? concept.aan_tekst}</dd>
              <dt>Onderwerp</dt>
              <dd data-testid="ic-concept-onderwerp">{concept.onderwerp}</dd>
            </dl>
            <pre data-testid="ic-concept-tekst" style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', margin: 0 }}>
              {concept.tekst}
            </pre>
            <DialogFooter>
              <a className="btn" href={concept.mailto} target="_blank" rel="noreferrer" data-testid="ic-concept-mailto">
                Openen in mailprogramma
              </a>{' '}
              <Button variant="secundair" onClick={() => void kopieer()}>
                {gekopieerd ? 'Gekopieerd' : 'Tekst kopiëren'}
              </Button>{' '}
              <Button variant="secundair" onClick={() => setConcept(null)}>
                Sluiten
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </>
  )
}
