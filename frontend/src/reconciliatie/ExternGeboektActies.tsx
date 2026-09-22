// "Intussen buiten de module geboekt" — Peter 22-09 (casus Bouwadvies Oost Nederland / Beter Assemblage F/2026/01235:
// drie accordeurs klikten akkoord terwijl RLZ-04-00000518 al vijf dagen rechtstreeks in Reeleezee stond; de module
// blokkeerde pas ná het laatste akkoord mét proza "los de oorzaak op"). Sinds 22-09 toetst de dagelijkse reconciliatie élk
// open document vers en draagt de rij TWEE handelingen; dezelfde twee knoppen staan op het controlescherm als het boeken
// ná het laatste akkoord op precies deze oorzaak strandt (AccorderingSectie). Eén component, één schrijver (server).
//   • "Afwijzen — al geboekt als ‹boekstuk›" = bestaande afwijs-route mét voorgevulde reden; de lopende accordering
//     wordt ingetrokken mét de tijdlijnregel "niet meer nodig: al geboekt in Reeleezee" (accordeurs zien 'm niet meer).
//   • "Toch verschillend — doorgaan" = de mens verklaart mét reden dat het een andere factuur is; het externe stuk telt
//     daarna niet meer als treffer (hercontrole én harde check), de boeking kan door.
// Het woord "bug" komt in geen enkele klanttekst voor (copy-check backend/tests/unit/test_geen_bug_in_klanttekst.py).
import { useState } from 'react'
import { ApiError } from '../api/client'
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle, FormField } from '../ui/basis'
import { afwijsAlGeboekt, tochVerschillend, type ExternGeboektKern } from './reconciliatieApi'

/** Minimale lengte van de reden bij "Toch verschillend" — spiegelt `intussen_extern_geboekt.MIN_REDEN_LENGTE`. */
export const REDEN_MINIMUM = 5

export function externGeboektZin(kern: ExternGeboektKern): string {
  const stuk = kern.extern_boekstuk ?? 'boekstuk onbekend'
  const stand = kern.stand === 'concept' ? 'staat al als concept' : 'is al geboekt'
  const extra = [kern.bedrag_extern ? `€ ${Number(kern.bedrag_extern).toLocaleString('nl-NL', { minimumFractionDigits: 2 })}` : null, kern.extern_datum ? datumNl(kern.extern_datum) : null]
    .filter(Boolean)
    .join(', ')
  return `Deze factuur ${stand} in ${kern.systeem} als ${stuk}${extra ? ` (${extra})` : ''} — buiten de module om.`
}

function datumNl(iso: string): string {
  const [j, m, d] = iso.slice(0, 10).split('-')
  return d && m && j ? `${d}-${m}-${j}` : iso
}

export function ExternGeboektActies({
  administratieId,
  documentId,
  kern,
  bevindingId,
  leverancier,
  factuurnummer,
  onGelukt,
  compact = false,
}: {
  administratieId: string
  documentId: string
  kern: ExternGeboektKern
  /** Alleen vanuit Inzicht › Reconciliatie: een Beheerder accepteert dan óók de bevinding. */
  bevindingId?: string
  leverancier?: string | null
  factuurnummer?: string | null
  onGelukt: (melding: string) => void
  /** Kleine knoppen (tabelrij) i.p.v. normale (controlescherm). */
  compact?: boolean
}) {
  const [open, setOpen] = useState<'afwijzen' | 'verschillend' | null>(null)
  const [toelichting, setToelichting] = useState('')
  const [reden, setReden] = useState('')
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const maat = compact ? 'klein' : undefined
  const boekstuk = kern.extern_boekstuk ?? 'boekstuk onbekend'
  const redenGeldig = reden.trim().length >= REDEN_MINIMUM

  const sluit = () => {
    if (bezig) return
    setOpen(null)
    setFout(null)
  }

  const afwijzen = async () => {
    setBezig(true)
    setFout(null)
    try {
      const r = await afwijsAlGeboekt(documentId, administratieId, kern, toelichting)
      setOpen(null)
      onGelukt(
        r.accordering_vervallen
          ? `Afgewezen als al geboekt (${boekstuk}); de accordering is ingetrokken — de accordeurs zien deze factuur niet meer.`
          : `Afgewezen als al geboekt (${boekstuk}).`,
      )
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Afwijzen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  const verschillend = async () => {
    if (!redenGeldig) return
    setBezig(true)
    setFout(null)
    try {
      const r = await tochVerschillend(documentId, administratieId, kern, reden, bevindingId)
      setOpen(null)
      onGelukt(
        r.bevinding_geaccepteerd
          ? `Vastgelegd als "toch verschillend"; ${boekstuk} telt niet meer als dubbel en de bevinding is geaccepteerd.`
          : `Vastgelegd als "toch verschillend"; ${boekstuk} telt niet meer als dubbel — de bevinding verdwijnt bij de volgende dagelijkse controle.`,
      )
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Vastleggen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <>
      <Button maat={maat} aria-label={`Afwijzen — al geboekt als ${boekstuk}: ${factuurnummer ?? documentId}`} onClick={() => setOpen('afwijzen')}>
        Afwijzen — al geboekt als {boekstuk}
      </Button>{' '}
      <Button variant="secundair" maat={maat} aria-label={`Toch verschillend — doorgaan: ${factuurnummer ?? documentId}`} onClick={() => setOpen('verschillend')}>
        Toch verschillend — doorgaan
      </Button>
      {open === 'afwijzen' && (
        <Dialog open onOpenChange={(o) => !o && sluit()}>
          <DialogContent aria-describedby={undefined} data-testid="extern-geboekt-afwijzen-dialoog">
            <DialogTitle>Afwijzen — al geboekt als {boekstuk}</DialogTitle>
            <DialogDescription>
              {externGeboektZin(kern)} Het document wordt afgewezen met de reden "Al geboekt in {kern.systeem} als {boekstuk} (buiten
              de module)". Loopt er een klant-accordering, dan wordt die ingetrokken met de tijdlijnregel "niet meer nodig: al geboekt
              in {kern.systeem}" — de accordeurs hoeven niets meer te doen. Terugdraaien kan via "Heropenen" op het afgewezen document.
            </DialogDescription>
            <dl className="hint" style={{ margin: '4px 0 0', display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '2px 10px' }}>
              <dt>Leverancier</dt>
              <dd style={{ margin: 0 }}>{leverancier ?? '—'}</dd>
              <dt>Factuurnummer</dt>
              <dd style={{ margin: 0 }}>{factuurnummer ?? '—'}</dd>
              <dt>Boekstuk in {kern.systeem}</dt>
              <dd style={{ margin: 0 }}>{boekstuk}</dd>
            </dl>
            <form
              onSubmit={(e) => {
                e.preventDefault()
                void afwijzen()
              }}
            >
              <FormField label="Toelichting (optioneel)" htmlFor="extern-geboekt-toelichting">
                <textarea
                  id="extern-geboekt-toelichting"
                  rows={2}
                  value={toelichting}
                  onChange={(e) => setToelichting(e.target.value)}
                  placeholder="Bijvoorbeeld: door collega rechtstreeks in Reeleezee geboekt op 17-09."
                  style={{ width: '100%', fontFamily: 'inherit', fontSize: 12.5 }}
                />
              </FormField>
              {fout && <div className="fout">{fout}</div>}
              <DialogFooter>
                <Button type="button" variant="ghost" onClick={sluit} disabled={bezig}>
                  Annuleren
                </Button>
                <Button type="submit" disabled={bezig}>
                  {bezig ? 'Bezig…' : 'Afwijzen en accordering intrekken'}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      )}
      {open === 'verschillend' && (
        <Dialog open onOpenChange={(o) => !o && sluit()}>
          <DialogContent aria-describedby={undefined} data-testid="extern-geboekt-verschillend-dialoog">
            <DialogTitle>Toch verschillend — doorgaan</DialogTitle>
            <DialogDescription>
              {externGeboektZin(kern)} Is dit écht een andere factuur (bijvoorbeeld een creditnota of een tweede levering met hetzelfde
              nummer)? Leg dat vast met een reden: {boekstuk} telt daarna niet meer als dubbel voor dit document, de controles draaien
              opnieuw en de accordering of boeking gaat gewoon door.
            </DialogDescription>
            <form
              onSubmit={(e) => {
                e.preventDefault()
                void verschillend()
              }}
            >
              <FormField label="Reden" htmlFor="extern-geboekt-reden">
                <textarea
                  id="extern-geboekt-reden"
                  required
                  rows={3}
                  value={reden}
                  onChange={(e) => setReden(e.target.value)}
                  placeholder="Bijvoorbeeld: tweede levering met hetzelfde nummer, ander bedrag — gecontroleerd met de leverancier."
                  style={{ width: '100%', fontFamily: 'inherit', fontSize: 12.5 }}
                />
              </FormField>
              {!redenGeldig && reden.trim() !== '' && <div className="hint">Geef een inhoudelijke reden (minimaal {REDEN_MINIMUM} tekens).</div>}
              {fout && <div className="fout">{fout}</div>}
              <DialogFooter>
                <Button type="button" variant="ghost" onClick={sluit} disabled={bezig}>
                  Annuleren
                </Button>
                <Button type="submit" disabled={bezig || !redenGeldig}>
                  {bezig ? 'Bezig…' : 'Vastleggen en doorgaan'}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      )}
    </>
  )
}
