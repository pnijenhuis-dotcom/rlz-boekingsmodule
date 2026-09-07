// "Opnieuw boeken (extern document verdwenen)" — A11, fixrun 07-09 (casus BOOT / Kempen Facilities).
// Alleen op een documenten-afwijking `ontbreekt_in_rlz` / `ontbreekt_in_odoo`: het document staat in de app als
// geboekt, maar Reeleezee/Odoo kent het stuk niet meer. Tegenboeken kan dan niet (er is niets om tegen te
// boeken); de herstelroute is het bestaande herboek-mechanisme zonder tegenboeking — de server zet het document
// terug op "klaar om te boeken" met een nieuwe boekcyclus (vers extern nummer), legt reden/tijdlijn/audit vast en
// de mens boekt daarna op het controlescherm (harde checks opnieuw). Teal = actie; verplichte inhoudelijke reden.
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, apiJson } from '../api/client'
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle, FormField } from '../ui/basis'
import type { BevindingDto } from './reconciliatieApi'

/** Minimale lengte van de reden — spiegelt de server (`herboeken.MIN_REDEN_LENGTE`). */
const REDEN_MINIMUM = 5

export interface OpnieuwBoekenResultaatDto {
  document_id: string
  status: string
  boek_cyclus: number
  doel_pad: string
}

export function opnieuwBoeken(bevindingId: string, administratieId: string, reden: string): Promise<OpnieuwBoekenResultaatDto> {
  return apiJson(`/reconciliatie/bevindingen/${bevindingId}/opnieuw-boeken`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ administratie_id: administratieId, reden }),
  })
}

/** Is dit de rij waarop de actie hoort? (contract A↔A8 punt 3 — één regel in `actieVoor`). */
export function isVerdwenenDocument(r: BevindingDto): boolean {
  const soort = r.detail?.afwijking_soort
  return r.blok === 'documenten' && (soort === 'ontbreekt_in_rlz' || soort === 'ontbreekt_in_odoo')
}

function tekst(r: BevindingDto, sleutel: string): string | null {
  const w = r.detail?.[sleutel]
  return typeof w === 'string' && w.trim() !== '' ? w : null
}

export function OpnieuwBoekenActie({
  bevinding,
  onGelukt,
  onAccepteren,
}: {
  bevinding: BevindingDto
  /** Ná een geslaagde actie: melding + het pad naar het controlescherm (de mens boekt daar opnieuw). */
  onGelukt: (melding: string, doelPad: string) => void
  /** Optioneel: de bestaande "Accepteren…" (Beheerder) blijft naast de herboek-actie beschikbaar. */
  onAccepteren?: () => void
}) {
  const [open, setOpen] = useState(false)
  const [reden, setReden] = useState('')
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const [klaar, setKlaar] = useState<OpnieuwBoekenResultaatDto | null>(null)
  const geldig = reden.trim().length >= REDEN_MINIMUM
  const kan = bevinding.administratie_id !== null

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
    if (!geldig || bevinding.administratie_id === null) return
    setBezig(true)
    setFout(null)
    try {
      const r = await opnieuwBoeken(bevinding.id, bevinding.administratie_id, reden.trim())
      setKlaar(r)
      setOpen(false)
      onGelukt(
        `Document staat weer klaar om te boeken (boekcyclus ${r.boek_cyclus}) — controleer en boek het opnieuw op het controlescherm.`,
        r.doel_pad,
      )
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Opnieuw boeken mislukt.')
    } finally {
      setBezig(false)
    }
  }

  if (klaar) {
    return (
      <Link to={klaar.doel_pad} className="btn" aria-label="Naar het document om opnieuw te boeken">
        Nu boeken →
      </Link>
    )
  }

  return (
    <>
      {kan ? (
        <Button
          maat="klein"
          aria-label={`Opnieuw boeken (document verdwenen uit ${pakket}): ${factuurnummer ?? bevinding.tekst}`}
          onClick={() => setOpen(true)}
        >
          Opnieuw boeken…
        </Button>
      ) : null}
      {onAccepteren && (
        <>
          {' '}
          <Button variant="ghost" maat="klein" aria-label={`Afwijking accepteren: ${factuurnummer ?? bevinding.tekst}`} onClick={onAccepteren}>
            Accepteren…
          </Button>
        </>
      )}
      {open && (
        <Dialog open onOpenChange={(o) => !o && sluit()}>
          <DialogContent aria-describedby={undefined} data-testid="opnieuw-boeken-dialoog">
            <DialogTitle>Opnieuw boeken — document verdwenen uit {pakket}</DialogTitle>
            <DialogDescription>
              Dit document staat in de app als geboekt, maar {pakket} kent het niet meer. Er is niets om tegen te boeken; het
              document gaat terug naar "klaar om te boeken" met een nieuwe boekcyclus en dezelfde velden. Daarna boek je het
              opnieuw op het controlescherm — de harde checks (waaronder de duplicaatcheck) draaien dan opnieuw.
            </DialogDescription>
            <dl className="hint" style={{ margin: '4px 0 0', display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '2px 10px' }}>
              <dt>Leverancier</dt>
              <dd style={{ margin: 0 }}>{leverancier ?? '—'}</dd>
              <dt>Factuurnummer</dt>
              <dd style={{ margin: 0 }}>{factuurnummer ?? '—'}</dd>
              <dt>Oud boekstuk</dt>
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
              <FormField label="Reden" htmlFor="opnieuw-boeken-reden">
                <textarea
                  id="opnieuw-boeken-reden"
                  required
                  rows={3}
                  value={reden}
                  onChange={(e) => setReden(e.target.value)}
                  placeholder="Bijvoorbeeld: document is op 16-08 per abuis in Reeleezee verwijderd (kliktest)."
                  style={{ width: '100%', fontFamily: 'inherit', fontSize: 12.5 }}
                />
              </FormField>
              {!geldig && reden.trim() !== '' && <div className="hint">Geef een inhoudelijke reden (minimaal {REDEN_MINIMUM} tekens).</div>}
              {fout && <div className="fout">{fout}</div>}
              <DialogFooter>
                <Button type="button" variant="ghost" onClick={sluit} disabled={bezig}>
                  Annuleren
                </Button>
                <Button type="submit" disabled={bezig || !geldig}>
                  {bezig ? 'Bezig…' : 'Terug naar klaar om te boeken'}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      )}
    </>
  )
}
