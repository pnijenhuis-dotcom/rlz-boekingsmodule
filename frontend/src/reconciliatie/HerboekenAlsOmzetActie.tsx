// "Herboeken als omzet" — Peter 16-09, casus Van Boxtel: kassarapporten (omzet) waren als INKOOPFACTUUR geboekt en
// verschenen in Reeleezee onder Uitgaven (regels wél op omzetrekeningen). Op de omzet-afwijking `omzet_in_inkoopstroom`:
// de server storneert de inkoopfactuur (actie 19) achter de btw-aangiftepoort (409 `btw_mogelijk_aangegeven`, alleen een
// Beheerder zet door mét reden — zelfde tweede stap als "Opnieuw boeken"), maakt het document een kassarapport en de
// mens boekt het daarna in het omzet-controlescherm als Receipt onder Inkomsten. Nooit een delete in RLZ.
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, apiJson } from '../api/client'
import { Button, Checkbox, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle, FormField } from '../ui/basis'
import { type BtwBevestiging, type BtwBlokkadeDetail, isBtwBlokkade } from './OpnieuwBoekenActie'
import type { BevindingDto } from './reconciliatieApi'

const REDEN_MINIMUM = 5

export interface HerboekenAlsOmzetResultaatDto {
  document_id: string
  status: string
  gestorneerd: boolean
  doel_pad: string
}

/** Is dit de rij waarop de actie hoort? Eén regel in `actieVoor`. */
export function isOmzetInInkoopstroom(r: BevindingDto): boolean {
  return r.blok === 'omzet' && r.detail?.afwijking_soort === 'omzet_in_inkoopstroom'
}

export function herboekAlsOmzet(
  bevindingId: string,
  administratieId: string,
  reden: string,
  bevestiging?: BtwBevestiging,
): Promise<HerboekenAlsOmzetResultaatDto> {
  return apiJson(`/reconciliatie/bevindingen/${bevindingId}/herboeken-als-omzet`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ administratie_id: administratieId, reden, ...(bevestiging ?? {}) }),
  })
}

export function HerboekenAlsOmzetActie({
  bevinding,
  onGelukt,
  isBeheerder = false,
}: {
  bevinding: BevindingDto
  onGelukt: (melding: string, doelPad: string) => void
  isBeheerder?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [reden, setReden] = useState('')
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const [klaar, setKlaar] = useState<HerboekenAlsOmzetResultaatDto | null>(null)
  const [btwBlokkade, setBtwBlokkade] = useState<BtwBlokkadeDetail | null>(null)
  const [bevestigd, setBevestigd] = useState(false)
  const [bevestigingReden, setBevestigingReden] = useState('')
  const redenGeldig = reden.trim().length >= REDEN_MINIMUM
  const bevestigingGeldig = bevestigd && bevestigingReden.trim().length >= REDEN_MINIMUM
  const geldig = redenGeldig && (btwBlokkade === null || (isBeheerder && bevestigingGeldig))
  const kan = bevinding.administratie_id !== null

  const sluit = () => {
    if (bezig) return
    setOpen(false)
    setFout(null)
    setBtwBlokkade(null)
    setBevestigd(false)
    setBevestigingReden('')
  }

  const bevestig = async () => {
    if (!geldig || bevinding.administratie_id === null) return
    setBezig(true)
    setFout(null)
    try {
      const metBevestiging: BtwBevestiging | undefined =
        btwBlokkade !== null && isBeheerder && bevestigingGeldig
          ? { btw_niet_in_aangifte_bevestigd: true, bevestiging_reden: bevestigingReden.trim() }
          : undefined
      const r = await herboekAlsOmzet(bevinding.id, bevinding.administratie_id, reden.trim(), metBevestiging)
      setKlaar(r)
      setOpen(false)
      onGelukt(
        `${r.gestorneerd ? 'Inkoopfactuur gestorneerd in Reeleezee; ' : ''}het document is nu een kassarapport — boek het als omzet in het omzet-controlescherm.`,
        r.doel_pad,
      )
    } catch (err) {
      if (isBtwBlokkade(err)) {
        setBtwBlokkade(err.detail)
        setBevestigd(false)
      } else {
        setFout(err instanceof ApiError ? err.message : 'Herboeken als omzet mislukt.')
      }
    } finally {
      setBezig(false)
    }
  }

  if (klaar) {
    return (
      <Link to={klaar.doel_pad} className="btn" aria-label="Naar het kassarapport om als omzet te boeken">
        Als omzet boeken →
      </Link>
    )
  }

  return (
    <>
      {kan ? (
        <Button maat="klein" aria-label={`Herboeken als omzet: ${bevinding.titel}`} onClick={() => setOpen(true)}>
          Herboeken als omzet…
        </Button>
      ) : null}
      {open && (
        <Dialog open onOpenChange={(o) => !o && sluit()}>
          <DialogContent aria-describedby={undefined} data-testid="herboeken-als-omzet-dialoog">
            <DialogTitle>Herboeken als omzet — inkoopfactuur storneren</DialogTitle>
            <DialogDescription>
              Dit kassarapport is als inkoopfactuur geboekt en staat daardoor in Reeleezee onder Uitgaven. De inkoopfactuur
              wordt gestorneerd (actie 19, nooit verwijderd) en het document wordt een kassarapport in de werkvoorraad; daarna
              boek je het in het omzet-controlescherm als omzetboeking onder Inkomsten. De btw-aangiftepoort blijft gelden.
            </DialogDescription>
            <form
              onSubmit={(e) => {
                e.preventDefault()
                void bevestig()
              }}
            >
              <FormField label="Reden" htmlFor="herboeken-als-omzet-reden">
                <textarea
                  id="herboeken-als-omzet-reden"
                  required
                  rows={3}
                  value={reden}
                  onChange={(e) => setReden(e.target.value)}
                  placeholder="Bijvoorbeeld: kassarapport 11-09 als inkoopfactuur geboekt — hoort onder Inkomsten."
                  style={{ width: '100%', fontFamily: 'inherit', fontSize: 12.5 }}
                />
              </FormField>
              {!redenGeldig && reden.trim() !== '' && <div className="hint">Geef een inhoudelijke reden (minimaal {REDEN_MINIMUM} tekens).</div>}
              {btwBlokkade && (
                <div data-testid="btw-blokkade" style={{ marginTop: 8 }}>
                  <div className="fout" role="alert">
                    <strong>Btw mogelijk al aangegeven — suppletie-pad.</strong> {btwBlokkade.bericht}
                  </div>
                  {isBeheerder ? (
                    <div style={{ marginTop: 8 }}>
                      <label style={{ display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 12.5 }}>
                        <Checkbox
                          checked={bevestigd}
                          onChange={(e) => setBevestigd(e.target.checked)}
                          disabled={bezig}
                          aria-label="Ik bevestig: de btw van dit document zat NIET in de ingediende aangifte"
                        />
                        <span>
                          Ik bevestig: de btw van deze inkoopboeking zat <strong>NIET</strong> in de ingediende aangifte. Zat die er
                          wél in, dan is een suppletie de route — niet deze knop.
                        </span>
                      </label>
                      {bevestigd && (
                        <FormField label="Reden van de bevestiging" htmlFor="herboeken-als-omzet-bevestiging-reden" className="mt-2">
                          <textarea
                            id="herboeken-als-omzet-bevestiging-reden"
                            required
                            rows={2}
                            value={bevestigingReden}
                            onChange={(e) => setBevestigingReden(e.target.value)}
                            style={{ width: '100%', fontFamily: 'inherit', fontSize: 12.5 }}
                          />
                        </FormField>
                      )}
                    </div>
                  ) : (
                    <div className="hint" style={{ marginTop: 6 }}>
                      Alleen een Beheerder kan deze blokkade doorzetten — leg de bevinding bij de Beheerder.
                    </div>
                  )}
                </div>
              )}
              {fout && (
                <div className="fout" role="alert" style={{ marginTop: 8 }}>
                  {fout}
                </div>
              )}
              <DialogFooter>
                <Button type="button" variant="ghost" onClick={sluit} disabled={bezig}>
                  Annuleren
                </Button>
                <Button type="submit" disabled={!geldig || bezig}>
                  {bezig ? 'Bezig…' : btwBlokkade ? 'Toch herboeken (Beheerder)' : 'Storneren en herclassificeren'}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      )}
    </>
  )
}
