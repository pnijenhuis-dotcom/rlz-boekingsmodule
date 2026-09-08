import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  haalAccorderingInstellingen,
  zetAccorderingInstellingen,
  type AccorderingInstellingenDto,
} from '../accordering/accorderingApi'
import { ApiError } from '../api/client'
import type { AdministratieDto } from '../api/types'
import { BevestigDialog } from '../instellingen/BevestigDialog'
import { BulkAccorderingDialog } from '../instellingen/BulkAccorderingDialog'
import { detailPad } from '../instellingen/instellingenRegistry'
import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  MultiSelect,
  useToastOptioneel,
} from '../ui/basis'
import { verwijderScope, type GebruikerOverzichtDto, type ScopeAdministratieDto } from './gebruikersApi'

/* Blok 5 herstelrun "Basis eerst" (08-09, besluit Peter): de scope van een klant-accordeur is vanuit de
 * accordeur zelf te beheren — Gebruikers › Klant-accordeurs › "Administraties van ‹accordeur›":
 *  (1) "Administraties toevoegen…" = multi-select van actieve BV's → de BESTAANDE bulk-route
 *      /accordering/bulk-instellen (preview + uitkomsten per administratie) mét de accordeur vooringevuld in
 *      laag 1 en de scope-vink aan — geen nieuwe schrijfroute;
 *  (2) per administratie "Verwijderen…" = dezelfde vervallen-rondes-waarschuwing als instellingen_opslaan, dan
 *      de accordeur uit de lagen (PUT instellingen zonder hem, `aanleiding` "verwijderd via Klant-accordeurs" in
 *      audit + tijdlijn) en uit de scope (bestaande DELETE-route, Beheerder-poort) — nooit een nieuwe
 *      verwijderroute. Aanvulling Peter 08-09: is hij de laatste laag, dan volgt een APARTE tweede bevestiging
 *      "accordering voor ‹BV› wordt hiermee uitgeschakeld" vóór er iets gebeurt;
 *  (3) administratienamen zijn links naar Instellingen › Administraties › ‹BV› › tab Klant-accordering;
 *  (4) een gearchiveerde administratie heet "‹naam› — gearchiveerd", nooit een kale GUID (naam komt mee in de
 *      gebruikers-DTO; /auth/administraties kent alleen actieve). Tekstknop = linkbtn, echte knop = Button. */

/** Scope-administraties van een gebruiker mét naam + status: DTO-naam wint, anders de actieve lijst, anders de id. */
export function scopeAdministraties(
  gebruiker: GebruikerOverzichtDto,
  naamPerAdministratie: Map<string, string>,
): ScopeAdministratieDto[] {
  const perId = new Map((gebruiker.administraties ?? []).map((a) => [a.id, a]))
  return gebruiker.administratie_ids
    .map((id) => perId.get(id) ?? { id, naam: naamPerAdministratie.get(id) ?? id, actief: true })
    .sort((a, b) => a.naam.localeCompare(b.naam, 'nl'))
}

export function administratieLabel(a: ScopeAdministratieDto): string {
  return a.actief ? a.naam : `${a.naam} — gearchiveerd`
}

export function AccordeurAdministraties({
  gebruiker,
  administraties,
  naamPerAdministratie,
  onGewijzigd,
}: {
  gebruiker: GebruikerOverzichtDto
  /** Actieve administraties (GET /auth/administraties) — de keuzelijst voor "toevoegen". */
  administraties: AdministratieDto[]
  naamPerAdministratie: Map<string, string>
  onGewijzigd: () => void
}) {
  const { meld } = useToastOptioneel()
  const [open, setOpen] = useState(false)
  const [toevoegKeuze, setToevoegKeuze] = useState<string[] | null>(null)
  const [bulkVoor, setBulkVoor] = useState<{ id: string; naam: string }[] | null>(null)
  const [verwijderVoor, setVerwijderVoor] = useState<ScopeAdministratieDto | null>(null)
  // Instellingen van de te verwijderen administratie, vooraf opgehaald: bepaalt of dit de laatste laag is.
  const [instellingenVoor, setInstellingenVoor] = useState<AccorderingInstellingenDto | null | 'laden'>(null)
  // Tweede, expliciete bevestigingsstap: accordering voor deze BV gaat uit (laatste laag verdwijnt).
  const [uitschakelBevestiging, setUitschakelBevestiging] = useState(false)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  const lijst = useMemo(() => scopeAdministraties(gebruiker, naamPerAdministratie), [gebruiker, naamPerAdministratie])
  const inScope = useMemo(() => new Set(gebruiker.administratie_ids), [gebruiker.administratie_ids])
  const toevoegbaar = useMemo(
    () =>
      administraties
        .filter((a) => !inScope.has(a.id))
        .map((a) => ({ waarde: a.id, label: a.naam }))
        .sort((a, b) => a.label.localeCompare(b.label, 'nl')),
    [administraties, inScope],
  )

  const AANLEIDING = 'verwijderd via Klant-accordeurs'

  /** Lagen die overblijven zonder deze accordeur (null zolang de instellingen laden/ontbreken). */
  const restLagen = useMemo(
    () =>
      instellingenVoor && instellingenVoor !== 'laden'
        ? instellingenVoor.lagen.filter((l) => l.accordeur_gebruiker_id !== gebruiker.id)
        : null,
    [instellingenVoor, gebruiker.id],
  )
  const zitInLagen =
    instellingenVoor !== null && instellingenVoor !== 'laden' && restLagen !== null && restLagen.length !== instellingenVoor.lagen.length
  /** Laatste laag: zonder hem blijft er geen accorderingslaag over terwijl accordering aanstaat → toggle gaat uit. */
  const wordtUitgeschakeld =
    instellingenVoor !== null && instellingenVoor !== 'laden' && instellingenVoor.ingeschakeld && zitInLagen && restLagen?.length === 0

  const startVerwijderen = (a: ScopeAdministratieDto) => {
    setFout(null)
    setUitschakelBevestiging(false)
    setVerwijderVoor(a)
    if (!a.actief) {
      setInstellingenVoor(null)
      return
    }
    setInstellingenVoor('laden')
    haalAccorderingInstellingen(a.id)
      .then((i) => setInstellingenVoor(i))
      .catch((err: unknown) => {
        setInstellingenVoor(null)
        setFout(err instanceof ApiError ? err.message : 'Accorderingsinstellingen konden niet geladen worden.')
      })
  }

  const annuleerVerwijderen = () => {
    setVerwijderVoor(null)
    setInstellingenVoor(null)
    setUitschakelBevestiging(false)
    setFout(null)
  }

  const verwijderen = async () => {
    if (!verwijderVoor) return
    setBezig(true)
    setFout(null)
    try {
      let vervallen = 0
      if (verwijderVoor.actief) {
        // Uit de accorderingslagen via de bestaande configuratieroute (zelfde validatie, vervallen-regel en audit
        // als een losse wijziging; `aanleiding` maakt in audit én tijdlijn zichtbaar waar dit vandaan kwam). Een
        // gearchiveerde administratie heeft geen lopende accordering: alleen scope.
        const instellingen =
          instellingenVoor && instellingenVoor !== 'laden' ? instellingenVoor : await haalAccorderingInstellingen(verwijderVoor.id)
        const rest = instellingen.lagen.filter((l) => l.accordeur_gebruiker_id !== gebruiker.id)
        if (rest.length !== instellingen.lagen.length) {
          const resultaat = await zetAccorderingInstellingen(verwijderVoor.id, {
            ingeschakeld: instellingen.ingeschakeld && rest.length > 0,
            lagen: rest.map((l, index) => ({
              volgnummer: index + 1,
              accordeur_gebruiker_id: l.accordeur_gebruiker_id,
              bedrag_drempel: l.bedrag_drempel,
            })),
            aanleiding: AANLEIDING,
          })
          vervallen = resultaat.rondes_vervallen ?? 0
        }
      }
      await verwijderScope(gebruiker.id, verwijderVoor.id)
      meld(
        `${gebruiker.naam} is verwijderd bij ${verwijderVoor.naam}` +
          (wordtUitgeschakeld ? ` — klant-accordering voor ${verwijderVoor.naam} staat nu uit` : '') +
          (vervallen > 0
            ? ` — ${vervallen} lopende ${vervallen === 1 ? 'accorderingsronde is' : 'accorderingsrondes zijn'} vervallen; die documenten staan weer op "Klaar om te boeken".`
            : '.'),
        vervallen > 0 || wordtUitgeschakeld ? 'warn' : 'ok',
      )
      annuleerVerwijderen()
      onGewijzigd()
    } catch (err) {
      setFout(
        err instanceof ApiError
          ? `${err.message} — al doorgevoerde stappen blijven staan; de lijst wordt ververst.`
          : 'Verwijderen mislukt.',
      )
      onGewijzigd()
    } finally {
      setBezig(false)
    }
  }

  const sluit = () => {
    setOpen(false)
    setToevoegKeuze(null)
  }

  return (
    <>
      {lijst.length === 0 && <>— </>}
      {lijst.length > 0 && lijst.length <= 2 && (
        <>
          {lijst.map((a) => (
            <span key={a.id}>
              <Badge variant={a.actief ? 'info' : 'stil'}>{administratieLabel(a)}</Badge>{' '}
            </span>
          ))}
        </>
      )}
      {lijst.length > 2 && <Badge variant="info">{lijst.length} administraties</Badge>}{' '}
      <Button variant="ghost" maat="klein" aria-label={`Administraties van ${gebruiker.naam} bekijken`} onClick={() => setOpen(true)}>
        beheren
      </Button>
      <Dialog open={open} onOpenChange={(o) => (o ? setOpen(true) : sluit())}>
        <DialogContent data-testid="accordeur-administraties-dialoog">
          <DialogTitle>Administraties van {gebruiker.naam}</DialogTitle>
          <DialogDescription>
            {lijst.length === 1 ? '1 administratie' : `${lijst.length} administraties`} — de wachtrij en de dagelijkse
            herinnering voegen ze samen. Toevoegen zet {gebruiker.naam} als accordeur (laag 1) in de klant-accordering
            van die administratie en geeft toegang; verwijderen haalt {gebruiker.naam} uit de accorderingslagen én de
            toegang. Klik een naam voor de accorderingslagen van die administratie.
          </DialogDescription>
          {lijst.length === 0 && <p className="hint">Nog geen administraties — voeg er hieronder een toe.</p>}
          {lijst.length > 0 && (
            <ul style={{ margin: '10px 0 0', paddingLeft: 18, columns: lijst.length > 8 ? 2 : 1 }}>
              {lijst.map((a) => (
                <li key={a.id} style={{ marginBottom: 4, breakInside: 'avoid' }}>
                  <Link to={detailPad(a.id, 'accordering')} onClick={sluit}>
                    {administratieLabel(a)}
                  </Link>{' '}
                  <button
                    type="button"
                    className="linkbtn"
                    aria-label={`${a.naam} verwijderen bij ${gebruiker.naam}`}
                    onClick={() => startVerwijderen(a)}
                  >
                    Verwijderen…
                  </button>
                </li>
              ))}
            </ul>
          )}
          {toevoegKeuze !== null && (
            <div style={{ marginTop: 12 }}>
              <span className="hint" style={{ margin: '0 0 6px', display: 'block', fontWeight: 700, fontSize: 11, textTransform: 'uppercase', letterSpacing: '.05em' }}>
                Administraties toevoegen
              </span>
              {toevoegbaar.length === 0 ? (
                <p className="hint" style={{ margin: 0 }}>
                  {gebruiker.naam} heeft al toegang tot alle actieve administraties.
                </p>
              ) : (
                <MultiSelect
                  opties={toevoegbaar}
                  waarden={toevoegKeuze}
                  onChange={setToevoegKeuze}
                  zoekPlaceholder="Zoek administratie…"
                />
              )}
            </div>
          )}
          <DialogFooter>
            {toevoegKeuze === null ? (
              <>
                <Button variant="ghost" onClick={sluit}>
                  Sluiten
                </Button>
                <Button variant="secundair" onClick={() => setToevoegKeuze([])}>
                  Administraties toevoegen…
                </Button>
              </>
            ) : (
              <>
                <Button variant="ghost" onClick={() => setToevoegKeuze(null)}>
                  Annuleren
                </Button>
                <Button
                  disabled={toevoegKeuze.length === 0}
                  onClick={() =>
                    setBulkVoor(
                      toevoegKeuze.map((id) => ({ id, naam: naamPerAdministratie.get(id) ?? id })),
                    )
                  }
                >
                  Verder ({toevoegKeuze.length})
                </Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
      {bulkVoor && (
        <BulkAccorderingDialog
          administraties={bulkVoor}
          vooringevuldeAccordeurId={gebruiker.id}
          onSluiten={() => setBulkVoor(null)}
          onGereed={() => {
            setToevoegKeuze(null)
            onGewijzigd()
          }}
        />
      )}
      {verwijderVoor && !uitschakelBevestiging && (
        <BevestigDialog
          titel={`${verwijderVoor.naam} verwijderen bij ${gebruiker.naam}`}
          bericht={
            verwijderVoor.actief
              ? `${gebruiker.naam} wordt uit de accorderingslagen van ${verwijderVoor.naam} gehaald en verliest de toegang tot die administratie. Wijzigt dit het effectieve schema, dan vervallen de lopende accorderingsrondes van ${verwijderVoor.naam} (reden op de tijdlijn: "accorderingsconfiguratie gewijzigd — opnieuw aanbieden vereist"); die documenten gaan terug naar "Klaar om te boeken" en kunnen opnieuw aangeboden worden. Staande goedkeuringen en historie blijven staan. De wijziging wordt geauditeerd (aanleiding: ${AANLEIDING}).` +
                (wordtUitgeschakeld
                  ? ` LET OP: ${gebruiker.naam} is de laatste accorderingslaag van ${verwijderVoor.naam} — na "Bevestigen" volgt nog een aparte bevestiging voor het uitschakelen.`
                  : '')
              : `${verwijderVoor.naam} is gearchiveerd: alleen de toegang van ${gebruiker.naam} tot die administratie wordt weggehaald (er loopt geen accordering meer). Historie blijft staan. De wijziging wordt geauditeerd.`
          }
          bezig={bezig || instellingenVoor === 'laden'}
          fout={fout}
          onBevestigen={() => {
            if (wordtUitgeschakeld) setUitschakelBevestiging(true)
            else void verwijderen()
          }}
          onAnnuleren={annuleerVerwijderen}
        />
      )}
      {verwijderVoor && uitschakelBevestiging && (
        <BevestigDialog
          titel={`Klant-accordering voor ${verwijderVoor.naam} uitschakelen?`}
          bericht={`${gebruiker.naam} is de laatste accordeur in de accorderingslagen van ${verwijderVoor.naam}: accordering voor ${verwijderVoor.naam} wordt hiermee uitgeschakeld. Nieuwe facturen van ${verwijderVoor.naam} gaan dan zonder klant-akkoord naar de boekknop; lopende accorderingsrondes vervallen (documenten terug naar "Klaar om te boeken"). Opnieuw aanzetten kan altijd via Instellingen › ${verwijderVoor.naam} › Klant-accordering. Audit en tijdlijn vermelden de aanleiding "${AANLEIDING}".`}
          bezig={bezig}
          fout={fout}
          onBevestigen={() => void verwijderen()}
          onAnnuleren={annuleerVerwijderen}
        />
      )}
    </>
  )
}
