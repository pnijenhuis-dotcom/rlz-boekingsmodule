// "Beschadiging melden…" (mockup mini-voorraad.html ⑧): de ENIGE mens-ingang op de mini-voorraad en
// bewust géén correctie maar een GEBEURTENISREGISTRATIE — wie (de melder, server-side), waar (project
// VERPLICHT, uit de gesyncte projectenlijst van de administratie), wanneer (datum, default vandaag),
// hoeveel (aantal > 0; de server slaat het negatief op) en optioneel een toelichting. UX-norm: één
// primaire knop. Zelfde project-lader als de project-kolom van het controlescherm (useProjectOpties).
import { useState } from 'react'
import { ApiError } from '../api/client'
import { SearchableCombobox } from '../document/SearchableCombobox'
import { useProjectOpties } from '../document/useSyncOpties'
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle, FormField } from '../ui/basis'
import { aantalTekst, meldBeschadiging, productNaam, type MiniProductDto, type MutatieDto } from './miniVoorraadApi'

function isoVandaag(): string {
  const d = new Date()
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${mm}-${dd}`
}

/** Aantal-invoer → Decimal-string voor de server ("4", "2,5" → "2.5"); null = ongeldig/≤ 0. */
export function normaliseerAantal(invoer: string): string | null {
  const t = invoer.trim().replace(',', '.')
  if (!/^\d+(\.\d{1,3})?$/.test(t)) return null
  return Number(t) > 0 ? t : null
}

export function BeschadigingDialog({
  administratieId,
  product,
  onSluiten,
  onGemeld,
}: {
  administratieId: string
  product: MiniProductDto
  onSluiten: () => void
  onGemeld: (mutatie: MutatieDto) => void
}) {
  const { opties: projecten, laden: projectenLaden, fout: projectenFout } = useProjectOpties(administratieId)
  const [aantal, setAantal] = useState('')
  const [projectId, setProjectId] = useState<string | null>(null)
  const [datum, setDatum] = useState(isoVandaag())
  const [toelichting, setToelichting] = useState('')
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [geprobeerd, setGeprobeerd] = useState(false)

  const aantalNorm = normaliseerAantal(aantal)
  const geldig = aantalNorm !== null && projectId !== null && /^\d{4}-\d{2}-\d{2}$/.test(datum)

  const melden = async () => {
    setGeprobeerd(true)
    if (!geldig || aantalNorm === null || projectId === null) return
    setBezig(true)
    setFout(null)
    try {
      const m = await meldBeschadiging(administratieId, {
        product_id: product.id,
        aantal: aantalNorm,
        project_id: projectId,
        datum,
        toelichting: toelichting.trim() || null,
      })
      onGemeld(m)
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Melden mislukt.')
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onSluiten()}>
      <DialogContent aria-describedby={undefined} data-testid="beschadiging-dialoog">
        <DialogTitle>Beschadiging melden</DialogTitle>
        <DialogDescription>
          Registreert een gebeurtenis in het voorraadlog van <b>{productNaam(product)}</b> (huidige stand {aantalTekst(product.stand)}
          {product.eenheid ? ` ${product.eenheid}` : ''}): wie meldt (u), waar (project) en wanneer. Dit is geen correctie — de stand
          volgt uit het log en telverschillen blijven zichtbaar in de voorraad-aansluiting.
        </DialogDescription>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void melden()
          }}
        >
          <FormField label={`Aantal beschadigd${product.eenheid ? ` (${product.eenheid})` : ''}`} htmlFor="beschadiging-aantal" fout={geprobeerd && aantalNorm === null ? 'Geef een aantal groter dan 0 (max. 3 decimalen).' : undefined}>
            <input id="beschadiging-aantal" inputMode="decimal" autoFocus value={aantal} onChange={(e) => setAantal(e.target.value)} placeholder="bv. 4" style={{ width: 120 }} />
          </FormField>
          <FormField
            label="Project (verplicht — waar is het gebeurd)"
            htmlFor="beschadiging-project"
            hint={projectenLaden ? 'projecten laden…' : projectenFout ? `projecten konden niet geladen worden: ${projectenFout}` : undefined}
            fout={geprobeerd && projectId === null ? 'Kies het project waar de beschadiging is ontstaan.' : undefined}
          >
            <SearchableCombobox
              label="Project"
              toonLabel={false}
              opties={projecten}
              waarde={projectId}
              onWijzig={setProjectId}
              placeholder={projectenLaden ? 'laden…' : 'Zoek project…'}
              vereist
              fout={geprobeerd && projectId === null}
            />
          </FormField>
          <FormField label="Datum" htmlFor="beschadiging-datum">
            <input id="beschadiging-datum" type="date" value={datum} onChange={(e) => setDatum(e.target.value)} style={{ width: 170 }} />
          </FormField>
          <FormField label="Toelichting (optioneel)" htmlFor="beschadiging-toelichting">
            <textarea
              id="beschadiging-toelichting"
              rows={3}
              value={toelichting}
              onChange={(e) => setToelichting(e.target.value)}
              placeholder="Bijvoorbeeld: gevallen bij het lossen, onbruikbaar."
              style={{ width: '100%', fontFamily: 'inherit', fontSize: 12.5 }}
            />
          </FormField>
          {fout && <div className="fout">{fout}</div>}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onSluiten} disabled={bezig}>
              Annuleren
            </Button>
            <Button type="submit" disabled={bezig}>
              {bezig ? 'Bezig…' : 'Beschadiging vastleggen'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
