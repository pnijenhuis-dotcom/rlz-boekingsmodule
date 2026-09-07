// "Opnieuw boeken (extern document verdwenen)" — A11, fixrun 07-09 (casus BOOT / Kempen Facilities).
// Alleen op een documenten-afwijking `ontbreekt_in_rlz` / `ontbreekt_in_odoo`: het document staat in de app als
// geboekt, maar Reeleezee/Odoo kent het stuk niet meer. Tegenboeken kan dan niet (er is niets om tegen te
// boeken); de herstelroute is het bestaande herboek-mechanisme zonder tegenboeking — de server zet het document
// terug op "klaar om te boeken" met een nieuwe boekcyclus (vers extern nummer), legt reden/tijdlijn/audit vast en
// de mens boekt daarna op het controlescherm (harde checks opnieuw). Teal = actie; verplichte inhoudelijke reden.
//
// Aangifte-poort (correctie Peter 07-09 op A11 beslispunt 2): valt de boekdatum van de verdwenen boeking in een
// ingediende btw-aangifte (of is die status niet leesbaar), dan antwoordt de server 409 met code
// `btw_mogelijk_aangegeven` — de voorbelasting zit al in de aangifte en een herboeking zou 'm opnieuw claimen. De
// dialoog toont die melding; ALLEEN een Beheerder krijgt in dezelfde dialoog de tweede stap ("Ik bevestig: de btw van
// dit document zat NIET in de ingediende aangifte" + verplichte reden) en herhaalt de aanroep mét de vlag. De server
// toetst de rol opnieuw (403 voor elke andere rol) — de UI verbergt de stap alleen.
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, apiJson } from '../api/client'
import { Button, Checkbox, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle, FormField } from '../ui/basis'
import type { BevindingDto } from './reconciliatieApi'

/** Minimale lengte van de reden — spiegelt de server (`herboeken.MIN_REDEN_LENGTE`). */
const REDEN_MINIMUM = 5

/** 409-code van de aangifte-poort — spiegelt `herboeken.BTW_BLOKKADE_CODE`. */
export const BTW_BLOKKADE_CODE = 'btw_mogelijk_aangegeven'

export interface OpnieuwBoekenResultaatDto {
  document_id: string
  status: string
  boek_cyclus: number
  doel_pad: string
}

/** Beheerder-doorzet ná de 409 `btw_mogelijk_aangegeven` (server: rol + reden ≥ 5 tekens verplicht). */
export interface BtwBevestiging {
  btw_niet_in_aangifte_bevestigd: true
  bevestiging_reden: string
}

/** Het 409-detail van de aangifte-poort (server: `BtwMogelijkAangegeven.als_detail`). */
export interface BtwBlokkadeDetail {
  code: typeof BTW_BLOKKADE_CODE
  bericht: string
  soort: 'ingediende_periode' | 'niet_controleerbaar'
  boekdatum: string | null
  periode_start: string | null
  periode_eind: string | null
  backend: string
  bevestiging_mogelijk: boolean
  bevestiging_rol: string
}

export function isBtwBlokkade(err: unknown): err is ApiError & { detail: BtwBlokkadeDetail } {
  if (!(err instanceof ApiError) || err.status !== 409) return false
  const d = err.detail
  return typeof d === 'object' && d !== null && (d as { code?: unknown }).code === BTW_BLOKKADE_CODE
}

export function opnieuwBoeken(
  bevindingId: string,
  administratieId: string,
  reden: string,
  bevestiging?: BtwBevestiging,
): Promise<OpnieuwBoekenResultaatDto> {
  return apiJson(`/reconciliatie/bevindingen/${bevindingId}/opnieuw-boeken`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ administratie_id: administratieId, reden, ...(bevestiging ?? {}) }),
  })
}

function datumNl(iso: string | null): string {
  if (!iso) return '—'
  const [j, m, d] = iso.split('-')
  return d && m && j ? `${d}-${m}-${j}` : iso
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
  isBeheerder = false,
}: {
  bevinding: BevindingDto
  /** Ná een geslaagde actie: melding + het pad naar het controlescherm (de mens boekt daar opnieuw). */
  onGelukt: (melding: string, doelPad: string) => void
  /** Optioneel: de bestaande "Accepteren…" (Beheerder) blijft naast de herboek-actie beschikbaar. */
  onAccepteren?: () => void
  /** Alleen een Beheerder ziet ná de 409 `btw_mogelijk_aangegeven` de bevestigingsstap (server toetst opnieuw). */
  isBeheerder?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [reden, setReden] = useState('')
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const [klaar, setKlaar] = useState<OpnieuwBoekenResultaatDto | null>(null)
  // Tweede stap (aangifte-poort): de 409-blokkade + de Beheerder-bevestiging.
  const [btwBlokkade, setBtwBlokkade] = useState<BtwBlokkadeDetail | null>(null)
  const [bevestigd, setBevestigd] = useState(false)
  const [bevestigingReden, setBevestigingReden] = useState('')
  const redenGeldig = reden.trim().length >= REDEN_MINIMUM
  const bevestigingGeldig = bevestigd && bevestigingReden.trim().length >= REDEN_MINIMUM
  // Ná een blokkade kan alleen een Beheerder mét bevestiging nog indienen.
  const geldig = redenGeldig && (btwBlokkade === null || (isBeheerder && bevestigingGeldig))
  const kan = bevinding.administratie_id !== null

  const leverancier = tekst(bevinding, 'leverancier_naam')
  const factuurnummer = tekst(bevinding, 'factuurnummer')
  const boekstuk = tekst(bevinding, 'rlz_boekstuk')
  const pakket = tekst(bevinding, 'backend') === 'odoo' ? 'Odoo' : 'Reeleezee'

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
      const r = await opnieuwBoeken(bevinding.id, bevinding.administratie_id, reden.trim(), metBevestiging)
      setKlaar(r)
      setOpen(false)
      onGelukt(
        `Document staat weer klaar om te boeken (boekcyclus ${r.boek_cyclus}) — controleer en boek het opnieuw op het controlescherm.`,
        r.doel_pad,
      )
    } catch (err) {
      if (isBtwBlokkade(err)) {
        // Geen gewone fout: de aangifte-poort vraagt om een Beheerder-besluit — tweede stap in dezelfde dialoog.
        setBtwBlokkade(err.detail)
        setBevestigd(false)
      } else {
        setFout(err instanceof ApiError ? err.message : 'Opnieuw boeken mislukt.')
      }
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
              {!redenGeldig && reden.trim() !== '' && <div className="hint">Geef een inhoudelijke reden (minimaal {REDEN_MINIMUM} tekens).</div>}
              {btwBlokkade && (
                <div data-testid="btw-blokkade" style={{ marginTop: 8 }}>
                  <div className="fout" role="alert">
                    <strong>Btw mogelijk al aangegeven — suppletie-pad.</strong> {btwBlokkade.bericht}
                  </div>
                  <dl className="hint" style={{ margin: '4px 0 0', display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '2px 10px' }}>
                    <dt>Boekdatum</dt>
                    <dd style={{ margin: 0 }}>{datumNl(btwBlokkade.boekdatum)}</dd>
                    <dt>Aangifteperiode</dt>
                    <dd style={{ margin: 0 }}>
                      {btwBlokkade.soort === 'ingediende_periode'
                        ? `${datumNl(btwBlokkade.periode_start)} t/m ${datumNl(btwBlokkade.periode_eind)} (ingediend)`
                        : 'niet controleerbaar — uit voorzorg geblokkeerd'}
                    </dd>
                  </dl>
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
                          Ik bevestig: de btw van dit document zat <strong>NIET</strong> in de ingediende aangifte (bijvoorbeeld: het
                          document was al verwijderd vóór de aangifte werd ingediend). Doorzetten claimt de voorbelasting in de
                          eerstvolgende open periode; zat de btw wél in de aangifte, dan is een suppletie de route — niet deze knop.
                        </span>
                      </label>
                      {bevestigd && (
                        <FormField label="Reden van de bevestiging" htmlFor="opnieuw-boeken-bevestiging-reden" className="mt-2">
                          <textarea
                            id="opnieuw-boeken-bevestiging-reden"
                            required
                            rows={2}
                            value={bevestigingReden}
                            onChange={(e) => setBevestigingReden(e.target.value)}
                            placeholder="Bijvoorbeeld: aangifte Q2 gecontroleerd — dit document zat er niet in (verwijderd op 16-08, aangifte ingediend 28-07)."
                            style={{ width: '100%', fontFamily: 'inherit', fontSize: 12.5 }}
                          />
                        </FormField>
                      )}
                      {bevestigd && !bevestigingGeldig && bevestigingReden.trim() !== '' && (
                        <div className="hint">Geef een inhoudelijke reden (minimaal {REDEN_MINIMUM} tekens).</div>
                      )}
                    </div>
                  ) : (
                    <div className="hint" style={{ marginTop: 6 }}>
                      Alleen een Beheerder kan dit doorzetten (met de bevestiging dat de btw niet in de aangifte zat). Vraag de Beheerder,
                      of verwerk het via het suppletie-pad.
                    </div>
                  )}
                </div>
              )}
              {fout && <div className="fout">{fout}</div>}
              <DialogFooter>
                <Button type="button" variant="ghost" onClick={sluit} disabled={bezig}>
                  Annuleren
                </Button>
                <Button type="submit" disabled={bezig || !geldig}>
                  {bezig ? 'Bezig…' : btwBlokkade ? 'Bevestig en zet terug naar klaar om te boeken' : 'Terug naar klaar om te boeken'}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      )}
    </>
  )
}
