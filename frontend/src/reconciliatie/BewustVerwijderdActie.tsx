// "Bewust verwijderd in RLZ" — blok D, opdracht Peter 16-09 (casus Kempen Facilities: drie keer "RLZ-document
// verdwenen", door Peter zélf in Reeleezee verwijderd als dubbel/test). Derde knop naast "Opnieuw boeken…" en
// "Accepteren…" op een documenten-afwijking `ontbreekt_in_rlz`/`ontbreekt_in_odoo`, alleen voor de Beheerder: één klik
// = bevinding geaccepteerd mét de VASTE reden + het document in de module van geboekt naar 'afgevoerd als duplicaat'
// (boekstuknummer blijft als historie). Geen vrije reden meer typen; een toelichting is optioneel.
// Terugweg (zelfde scherm, facet "geaccepteerd"): `BewustVerwijderdTerugweg` → document terug naar geboekt + acceptatie
// ingetrokken, mét verplichte reden — géén heropenen op het document (dat pad kent geen herkomst 'geboekt').
import { useState } from 'react'
import { ApiError } from '../api/client'
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle, FormField } from '../ui/basis'
import { accepteerBewustVerwijderd, BEWUST_VERWIJDERD_REDEN, type BevindingDto } from './reconciliatieApi'

const MAX_TOELICHTING = 500

function tekst(r: BevindingDto, sleutel: string): string | null {
  const w = r.detail?.[sleutel]
  return typeof w === 'string' && w.trim() !== '' ? w : null
}

export function BewustVerwijderdActie({
  bevinding,
  onGelukt,
}: {
  bevinding: BevindingDto
  onGelukt: (melding: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [toelichting, setToelichting] = useState('')
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const kan = bevinding.administratie_id !== null
  const teLang = toelichting.trim().length > MAX_TOELICHTING

  const leverancier = tekst(bevinding, 'leverancier_naam')
  const factuurnummer = tekst(bevinding, 'factuurnummer')
  const boekstuk = tekst(bevinding, 'rlz_boekstuk')
  const pakket = tekst(bevinding, 'backend') === 'odoo' ? 'Odoo' : 'Reeleezee'

  const sluit = () => {
    if (bezig) return
    setOpen(false)
    setFout(null)
  }

  const bevestig = async () => {
    if (bevinding.administratie_id === null || teLang) return
    setBezig(true)
    setFout(null)
    try {
      const r = await accepteerBewustVerwijderd(bevinding.id, bevinding.administratie_id, toelichting)
      setOpen(false)
      onGelukt(
        r.document_status_gewijzigd
          ? `Bevinding geaccepteerd; document staat nu op 'afgevoerd als duplicaat' (boekstuk ${r.boekstuknummer ?? 'onbekend'} blijft als historie).`
          : `Bevinding geaccepteerd; het document stond niet op geboekt (${r.document_status_nieuw}) en is ongewijzigd gelaten.`,
      )
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Bewust verwijderd markeren mislukt.')
    } finally {
      setBezig(false)
    }
  }

  if (!kan) return null
  return (
    <>
      <Button
        variant="secundair"
        maat="klein"
        aria-label={`Bewust verwijderd in ${pakket}: ${factuurnummer ?? bevinding.tekst}`}
        onClick={() => setOpen(true)}
      >
        Bewust verwijderd in RLZ
      </Button>
      {open && (
        <Dialog open onOpenChange={(o) => !o && sluit()}>
          <DialogContent aria-describedby={undefined} data-testid="bewust-verwijderd-dialoog">
            <DialogTitle>Bewust verwijderd in {pakket}</DialogTitle>
            <DialogDescription>
              Je hebt dit document zelf in {pakket} verwijderd (dubbel of test). De bevinding wordt geaccepteerd met de vaste reden
              '{BEWUST_VERWIJDERD_REDEN}' en het document in de module gaat naar 'afgevoerd als duplicaat' zodat het niet als
              geboekt blijft staan. Terugdraaien kan op deze pagina onder 'geaccepteerd' met 'Terugdraaien…' (document weer
              geboekt, acceptatie ingetrokken).
            </DialogDescription>
            <dl className="hint" style={{ margin: '4px 0 0', display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '2px 10px' }}>
              <dt>Leverancier</dt>
              <dd style={{ margin: 0 }}>{leverancier ?? '—'}</dd>
              <dt>Factuurnummer</dt>
              <dd style={{ margin: 0 }}>{factuurnummer ?? '—'}</dd>
              <dt>Boekstuk</dt>
              <dd style={{ margin: 0 }}>{boekstuk ?? '—'}</dd>
              <dt>Administratie</dt>
              <dd style={{ margin: 0 }}>{bevinding.administratie_naam ?? '—'}</dd>
            </dl>
            <form
              onSubmit={(e) => {
                e.preventDefault()
                void bevestig()
              }}
            >
              <FormField label="Toelichting (optioneel)" htmlFor="bewust-verwijderd-toelichting">
                <textarea
                  id="bewust-verwijderd-toelichting"
                  rows={2}
                  value={toelichting}
                  onChange={(e) => setToelichting(e.target.value)}
                  placeholder="Bijvoorbeeld: dubbel geboekt met boekstuk RLZ-04-00004012."
                  style={{ width: '100%', fontFamily: 'inherit', fontSize: 12.5 }}
                />
              </FormField>
              {teLang && <div className="hint">Toelichting is te lang (maximaal {MAX_TOELICHTING} tekens).</div>}
              {fout && <div className="fout">{fout}</div>}
              <DialogFooter>
                <Button type="button" variant="ghost" onClick={sluit} disabled={bezig}>
                  Annuleren
                </Button>
                <Button type="submit" disabled={bezig || teLang}>
                  {bezig ? 'Bezig…' : 'Bevestigen'}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      )}
    </>
  )
}
