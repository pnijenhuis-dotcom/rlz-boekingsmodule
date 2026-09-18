import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  bulkAccorderingPreview,
  haalAccorderingInstellingen,
  zetAccorderingInstellingen,
  type AccorderingInstellingenDto,
  type AccorderingLaagDto,
} from '../accordering/accorderingApi'
import { rondesPreviewTekst, rondesTekst } from '../accordering/rondesTekst'
import { ApiError } from '../api/client'
import type { AdministratieDto } from '../api/types'
import { BevestigDialog } from '../instellingen/BevestigDialog'
import { detailPad } from '../instellingen/instellingenRegistry'
import {
  Badge,
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  Select,
  useToastOptioneel,
} from '../ui/basis'
import { verwijderScope, voegScopeToe, type GebruikerOverzichtDto, type ScopeAdministratieDto } from './gebruikersApi'
import { ScopeLijst, type ScopeLijstItem } from './ScopeLijst'

/* Blok 5 herstelrun "Basis eerst" (08-09, besluit Peter): de scope van een klant-accordeur is vanuit de
 * accordeur zelf te beheren — Gebruikers › Klant-accordeurs › "Administraties van ‹accordeur›".
 *
 * BUG 18-09 (Peter, live bij Bouwadvies Oost Nederland — drie lagen Peter N. → Sophia → Kempen stil vervangen door
 * één laag Romy; "Verwijderen" trok óók de toegang in → kringetje): TOEGANG ≠ LAAG.
 *  (1) "Administraties toevoegen…" = ScopeLijst → keuze-stap PER administratie mét de huidige stand zichtbaar
 *      ("3 lagen: Peter N. → Sophia → Kempen") en wat het wordt. Default "Alleen toegang" = uitsluitend de bestaande
 *      scope-route (POST /auth/gebruikers/{id}/scope; audit via DB-trigger) — geen laag, geen herberekening.
 *      "Ook als laag toevoegen: vóór laag 1 / ná de laatste laag" = scope + PUT instellingen mét de BESTAANDE lagen
 *      plús deze accordeur (nooit vervangen). "Alleen in een leveranciersroute" = scope + link naar de route-editor.
 *      De bulk-instelroute wordt hier niet meer aangeroepen.
 *  (2) "Verwijderen…" = twee gescheiden vinkjes: uit de accorderingslagen halen (default aan als hij erin staat, mét
 *      de herberekend-/vervallen-telling zoals eerder) en/of de toegang intrekken (default UIT, mét uitleg). Is hij
 *      de laatste laag, dan blijft de aparte uitschakel-bevestiging (Peter 08-09). Een gearchiveerde administratie
 *      heeft geen accordering meer: alleen toegang intrekken.
 *  (3) administratienamen zijn links naar Instellingen › Administraties › ‹BV› › tab Klant-accordering;
 *  (4) een gearchiveerde administratie heet "‹naam› — gearchiveerd", nooit een kale GUID.
 * Tekstknop = linkbtn, echte knop = Button. */

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

/** Keuze per administratie in de toevoeg-stap (BUG 18-09 regel 1). */
export type ToevoegKeuze = 'toegang' | 'laag_voor' | 'laag_na' | 'route'

const KEUZE_LABEL: Record<ToevoegKeuze, string> = {
  toegang: 'Alleen toegang',
  laag_voor: 'Ook als laag toevoegen: vóór laag 1',
  laag_na: 'Ook als laag toevoegen: ná de laatste laag',
  route: 'Alleen in een leveranciersroute (opent de route-editor)',
}

const LAAG_AANLEIDING = 'laag toegevoegd via Klant-accordeurs'

function lagenNamen(lagen: AccorderingLaagDto[]): string {
  return lagen.map((l) => l.accordeur_naam ?? l.accordeur_gebruiker_id).join(' → ')
}

/** "Nu: 3 lagen: Peter N. → Sophia → Kempen" / "Nu: klant-accordering uit, geen lagen". Pure functie (test). */
export function huidigeStandTekst(instellingen: AccorderingInstellingenDto): string {
  const n = instellingen.lagen.length
  const aan = instellingen.ingeschakeld ? 'klant-accordering aan' : 'klant-accordering uit'
  if (n === 0) return `${aan}, geen lagen`
  return `${aan}, ${n === 1 ? '1 laag' : `${n} lagen`}: ${lagenNamen(instellingen.lagen)}`
}

/** De lagen ná de keuze — bestaande lagen blijven ALTIJD staan; de accordeur komt erbij op de gekozen positie. Pure functie (test). */
export function lagenNaToevoegen(
  bestaand: AccorderingLaagDto[],
  accordeur: { id: string; naam: string },
  keuze: 'laag_voor' | 'laag_na',
): AccorderingLaagDto[] {
  const nieuw: AccorderingLaagDto = { volgnummer: 0, accordeur_gebruiker_id: accordeur.id, accordeur_naam: accordeur.naam, bedrag_drempel: null }
  const rij = keuze === 'laag_voor' ? [nieuw, ...bestaand] : [...bestaand, nieuw]
  return rij.map((l, index) => ({ ...l, volgnummer: index + 1 }))
}

/** "Wordt: …" per keuze (preview, BUG 18-09 regel 1). Pure functie (test). */
export function wordtTekst(
  instellingen: AccorderingInstellingenDto | null,
  accordeur: { id: string; naam: string },
  keuze: ToevoegKeuze,
): string {
  if (keuze === 'toegang') return 'toegang; lagen ongewijzigd'
  if (keuze === 'route') return 'toegang; lagen ongewijzigd — kies daarna de leveranciers in de route-editor'
  if (!instellingen) return 'toegang + laag (huidige stand niet geladen)'
  const lagen = lagenNaToevoegen(instellingen.lagen, accordeur, keuze)
  const uit = instellingen.ingeschakeld ? '' : ' (klant-accordering staat uit; aanzetten via Instellingen)'
  return `toegang + ${lagen.length === 1 ? '1 laag' : `${lagen.length} lagen`}: ${lagenNamen(lagen)}${uit}`
}

interface ToevoegAdministratie {
  id: string
  naam: string
  actief: boolean
}

interface ToevoegResultaat {
  id: string
  naam: string
  tekst: string
  variant: 'ok' | 'warn'
  routeLink?: string
}

export function AccordeurAdministraties({
  gebruiker,
  administraties,
  naamPerAdministratie,
  onGewijzigd,
  initieelToevoegen = false,
}: {
  gebruiker: GebruikerOverzichtDto
  /** Actieve administraties (GET /auth/administraties) — de keuzelijst voor "toevoegen". */
  administraties: AdministratieDto[]
  naamPerAdministratie: Map<string, string>
  onGewijzigd: () => void
  /** Alleen voor het visuele harnas (overflow-sweep `?scope=71&variant=accordeur`): start met de dialoog open in
   * de toevoeg-stand, zodat headless Chrome de ScopeLijst meet zonder te klikken. */
  initieelToevoegen?: boolean
}) {
  const { meld } = useToastOptioneel()
  const [open, setOpen] = useState(initieelToevoegen)
  const [toevoegKeuze, setToevoegKeuze] = useState<string[] | null>(initieelToevoegen ? [] : null)
  // Keuze-stap (BUG 18-09): per gekozen administratie de huidige stand + de keuze toegang/laag/route.
  const [keuzeStap, setKeuzeStap] = useState<ToevoegAdministratie[] | null>(null)
  const [standPer, setStandPer] = useState<Record<string, AccorderingInstellingenDto | 'laden' | 'fout'>>({})
  const [keuzePer, setKeuzePer] = useState<Record<string, ToevoegKeuze>>({})
  const [toevoegResultaat, setToevoegResultaat] = useState<ToevoegResultaat[] | null>(null)
  const [toevoegBezig, setToevoegBezig] = useState(false)

  const [verwijderVoor, setVerwijderVoor] = useState<ScopeAdministratieDto | null>(null)
  // Instellingen van de te verwijderen administratie, vooraf opgehaald: bepaalt of dit de laatste laag is.
  const [instellingenVoor, setInstellingenVoor] = useState<AccorderingInstellingenDto | null | 'laden'>(null)
  // BUG 18-09 regel 2: twee gescheiden vragen.
  const [uitLagen, setUitLagen] = useState(true)
  const [toegangIntrekken, setToegangIntrekken] = useState(false)
  // Tweede, expliciete bevestigingsstap: accordering voor deze BV gaat uit (laatste laag verdwijnt).
  const [uitschakelBevestiging, setUitschakelBevestiging] = useState(false)
  // Vooraf-telling (bundel 09-09 blok 2): "N lopende rondes worden herberekend, waarvan M vervallen" — via het
  // bestaande, alleen-lezende preview-endpoint met exact de lagen die overblijven (zelfde pure regel als de PUT).
  const [rondesVooraf, setRondesVooraf] = useState<{ herberekend: number; vervallen: number } | null>(null)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  const lijst = useMemo(() => scopeAdministraties(gebruiker, naamPerAdministratie), [gebruiker, naamPerAdministratie])
  const inScope = useMemo(() => new Set(gebruiker.administratie_ids), [gebruiker.administratie_ids])
  /** Lijst voor "toevoegen": alle actieve BV's + de (gearchiveerde) administraties die al in de scope staan. */
  const keuzeItems = useMemo<ScopeLijstItem[]>(() => {
    const perId = new Map<string, ScopeLijstItem>(administraties.map((a) => [a.id, { id: a.id, naam: a.naam, actief: true }]))
    for (const a of lijst) if (!perId.has(a.id)) perId.set(a.id, { id: a.id, naam: a.naam, actief: a.actief })
    return [...perId.values()]
  }, [administraties, lijst])
  const aantalToevoegbaar = keuzeItems.filter((it) => !inScope.has(it.id)).length

  const AANLEIDING = 'verwijderd via Klant-accordeurs'
  const accordeur = { id: gebruiker.id, naam: gebruiker.naam }

  /* ---------- toevoegen (BUG 18-09 regel 1) ---------- */

  const naarKeuzeStap = (ids: string[]) => {
    const admins: ToevoegAdministratie[] = ids.map((id) => {
      const item = keuzeItems.find((it) => it.id === id)
      return { id, naam: item?.naam ?? naamPerAdministratie.get(id) ?? id, actief: item?.actief ?? true }
    })
    setKeuzeStap(admins)
    setKeuzePer(Object.fromEntries(admins.map((a) => [a.id, 'toegang' as ToevoegKeuze])))
    setStandPer(Object.fromEntries(admins.map((a) => [a.id, 'laden' as const])))
    setFout(null)
    for (const a of admins) {
      haalAccorderingInstellingen(a.id)
        .then((i) => setStandPer((h) => ({ ...h, [a.id]: i })))
        .catch(() => setStandPer((h) => ({ ...h, [a.id]: 'fout' })))
    }
  }

  const standVan = (id: string): AccorderingInstellingenDto | null => {
    const s = standPer[id]
    return s && s !== 'laden' && s !== 'fout' ? s : null
  }

  const toevoegen = async () => {
    if (!keuzeStap) return
    setToevoegBezig(true)
    setFout(null)
    const resultaten: ToevoegResultaat[] = []
    for (const a of keuzeStap) {
      const keuze = keuzePer[a.id] ?? 'toegang'
      try {
        // Stap 1 — altijd en alleen: toegang via de bestaande scope-route (audit via de DB-trigger). Nooit een laag stil.
        await voegScopeToe(gebruiker.id, a.id)
        if (keuze === 'laag_voor' || keuze === 'laag_na') {
          // Stap 2 — expliciet gekozen: de BESTAANDE lagen blijven, deze accordeur komt erbij op de gekozen positie.
          const stand = standVan(a.id) ?? (await haalAccorderingInstellingen(a.id))
          const lagen = lagenNaToevoegen(stand.lagen, accordeur, keuze)
          const resultaat = await zetAccorderingInstellingen(a.id, {
            ingeschakeld: stand.ingeschakeld,
            lagen: lagen.map((l) => ({ volgnummer: l.volgnummer, accordeur_gebruiker_id: l.accordeur_gebruiker_id, bedrag_drempel: l.bedrag_drempel })),
            aanleiding: LAAG_AANLEIDING,
          })
          const herberekend = resultaat.rondes_herberekend ?? 0
          const vervallen = resultaat.rondes_vervallen ?? 0
          resultaten.push({
            id: a.id,
            naam: a.naam,
            tekst:
              `toegang + laag ${keuze === 'laag_voor' ? '1 (vóór de bestaande lagen)' : `${lagen.length} (ná de laatste laag)`} — nu ${lagen.length === 1 ? '1 laag' : `${lagen.length} lagen`}: ${lagenNamen(lagen)}.` +
              rondesTekst(herberekend, vervallen),
            variant: vervallen > 0 ? 'warn' : 'ok',
          })
        } else if (keuze === 'route') {
          resultaten.push({
            id: a.id,
            naam: a.naam,
            tekst: 'toegang gegeven; lagen ongewijzigd — kies nu de leveranciers in de route-editor',
            variant: 'ok',
            routeLink: detailPad(a.id, 'accordering'),
          })
        } else {
          resultaten.push({ id: a.id, naam: a.naam, tekst: 'toegang gegeven; lagen ongewijzigd', variant: 'ok' })
        }
      } catch (err) {
        resultaten.push({
          id: a.id,
          naam: a.naam,
          tekst: `mislukt: ${err instanceof ApiError ? err.message : 'onbekende fout'} — al doorgevoerde stappen blijven staan`,
          variant: 'warn',
        })
      }
    }
    setToevoegResultaat(resultaten)
    setToevoegBezig(false)
    const gelukt = resultaten.filter((r) => r.variant === 'ok').length
    meld(
      `${gebruiker.naam}: toegang bij ${gelukt} van ${resultaten.length} administraties — geauditeerd; de goedkeuringsroute is alleen gewijzigd waar je dat koos.`,
      gelukt === resultaten.length ? 'ok' : 'warn',
    )
    onGewijzigd()
  }

  const sluitToevoegen = () => {
    setKeuzeStap(null)
    setStandPer({})
    setKeuzePer({})
    setToevoegResultaat(null)
    setToevoegKeuze(null)
  }

  /* ---------- verwijderen (BUG 18-09 regel 2) ---------- */

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
    uitLagen &&
    instellingenVoor !== null &&
    instellingenVoor !== 'laden' &&
    instellingenVoor.ingeschakeld &&
    zitInLagen &&
    restLagen?.length === 0
  // Een laag zonder toegang kan niet goedkeuren: toegang intrekken terwijl hij in de lagen staat = ook uit de lagen.
  const uitLagenEffectief = zitInLagen && (uitLagen || toegangIntrekken)

  const startVerwijderen = (a: ScopeAdministratieDto) => {
    setFout(null)
    setUitschakelBevestiging(false)
    setVerwijderVoor(a)
    setUitLagen(true)
    setToegangIntrekken(!a.actief)
    if (!a.actief) {
      setInstellingenVoor(null)
      return
    }
    setInstellingenVoor('laden')
    setRondesVooraf(null)
    haalAccorderingInstellingen(a.id)
      .then((i) => {
        setInstellingenVoor(i)
        const rest = i.lagen.filter((l) => l.accordeur_gebruiker_id !== gebruiker.id)
        if (rest.length === 0 || rest.length === i.lagen.length) return
        // Alleen lezen; een mislukte telling houdt het verwijderen niet tegen (de tekst blijft dan generiek).
        bulkAccorderingPreview({
          administratie_ids: [a.id],
          lagen: rest.map((l, index) => ({
            volgnummer: index + 1,
            accordeur_gebruiker_id: l.accordeur_gebruiker_id,
            bedrag_drempel: l.bedrag_drempel,
          })),
          scope_toevoegen: false,
        })
          .then((p) => {
            const u = p.uitkomsten.find((x) => x.administratie_id === a.id)
            if (u) setRondesVooraf({ herberekend: u.rondes_herberekend ?? u.rondes_vervallen, vervallen: u.rondes_vervallen })
          })
          .catch(() => setRondesVooraf(null))
      })
      .catch((err: unknown) => {
        setInstellingenVoor(null)
        setFout(err instanceof ApiError ? err.message : 'Accorderingsinstellingen konden niet geladen worden.')
      })
  }

  const lopendeRondesTekst =
    rondesVooraf && rondesVooraf.herberekend > 0
      ? ` Nu: ${rondesPreviewTekst(rondesVooraf.herberekend, rondesVooraf.vervallen)}.`
      : ''

  const annuleerVerwijderen = () => {
    setVerwijderVoor(null)
    setRondesVooraf(null)
    setInstellingenVoor(null)
    setUitschakelBevestiging(false)
    setFout(null)
  }

  const verwijderen = async () => {
    if (!verwijderVoor) return
    setBezig(true)
    setFout(null)
    try {
      let herberekend = 0
      let vervallen = 0
      if (verwijderVoor.actief && uitLagenEffectief) {
        // Uit de accorderingslagen via de bestaande configuratieroute (zelfde validatie, herberekeningsregel en audit
        // als een losse wijziging — bundel 09-09 blok 2; `aanleiding` maakt in audit én tijdlijn zichtbaar waar dit
        // vandaan kwam).
        const instellingen: AccorderingInstellingenDto =
          typeof instellingenVoor === 'object' && instellingenVoor !== null
            ? instellingenVoor
            : await haalAccorderingInstellingen(verwijderVoor.id)
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
          herberekend = resultaat.rondes_herberekend ?? 0
          vervallen = resultaat.rondes_vervallen ?? 0
        }
      }
      // Toegang intrekken alleen als dat expliciet is aangevinkt (BUG 18-09 regel 2: default blijft de toegang).
      if (toegangIntrekken) await verwijderScope(gebruiker.id, verwijderVoor.id)
      const wat = [
        verwijderVoor.actief && uitLagenEffectief ? 'uit de accorderingslagen gehaald' : null,
        toegangIntrekken ? 'toegang ingetrokken' : null,
      ]
        .filter(Boolean)
        .join(' en ')
      meld(
        `${gebruiker.naam} bij ${verwijderVoor.naam}: ${wat}` +
          (wordtUitgeschakeld ? ` — klant-accordering voor ${verwijderVoor.naam} staat nu uit` : '') +
          (toegangIntrekken ? '' : ' — toegang blijft') +
          '.' +
          rondesTekst(herberekend, vervallen),
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
    sluitToevoegen()
  }

  const kanVerwijderen = verwijderVoor !== null && (toegangIntrekken || (verwijderVoor.actief && uitLagenEffectief))

  return (
    <>
      {lijst.length === 0 && <>— </>}
      {lijst.length > 0 && lijst.length <= 2 && (
        <>
          {lijst.map((a) => (
            <span key={a.id}>
              {/* Bug Peter 15-09: een lange (gearchiveerde) naam liep over de apparatenkolom heen → ellipsis binnen de
                  kolom (`.admin-badge`, max-width 100 %) mét de volledige naam als title. */}
              <Badge variant={a.actief ? 'info' : 'stil'} className="admin-badge" title={administratieLabel(a)}>
                {administratieLabel(a)}
              </Badge>{' '}
            </span>
          ))}
        </>
      )}
      {lijst.length > 2 && <Badge variant="info">{lijst.length} administraties</Badge>}{' '}
      <Button variant="ghost" maat="klein" aria-label={`Administraties van ${gebruiker.naam} bekijken`} onClick={() => setOpen(true)}>
        beheren
      </Button>
      <Dialog open={open} onOpenChange={(o) => (o ? setOpen(true) : sluit())}>
        <DialogContent data-testid="accordeur-administraties-dialoog" className="flex max-h-[calc(100vh-32px)] flex-col">
          <DialogTitle>Administraties van {gebruiker.naam}</DialogTitle>
          <DialogDescription>
            {lijst.length === 1 ? '1 administratie' : `${lijst.length} administraties`} — de wachtrij en de dagelijkse
            herinnering voegen ze samen. Toegang geven verandert de goedkeuringsroute van een administratie niet: een
            laag komt er alleen bij als je dat per administratie kiest, en bestaande lagen blijven altijd staan.
            Verwijderen vraagt apart of {gebruiker.naam} uit de lagen gaat en of de toegang wordt ingetrokken. Klik een
            naam voor de accorderingslagen van die administratie.
          </DialogDescription>
          {toevoegKeuze === null && lijst.length === 0 && (
            <p className="hint">Nog geen administraties — voeg er hieronder een toe.</p>
          )}
          {toevoegKeuze === null && lijst.length > 0 && (
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
          {toevoegKeuze !== null && keuzeStap === null && (
            <div style={{ marginTop: 12 }}>
              <span className="hint" style={{ margin: '0 0 6px', display: 'block', fontWeight: 700, fontSize: 11, textTransform: 'uppercase', letterSpacing: '.05em' }}>
                Administraties toevoegen
              </span>
              {aantalToevoegbaar === 0 && (
                <p className="hint" style={{ margin: '0 0 6px' }}>
                  {gebruiker.naam} heeft al toegang tot alle actieve administraties.
                </p>
              )}
              <ScopeLijst
                items={keuzeItems}
                geselecteerd={toevoegKeuze}
                onChange={setToevoegKeuze}
                vergrendeld={inScope}
                zoekPlaceholder="Zoek administratie…"
                data-testid="accordeur-toevoeg-lijst"
              />
            </div>
          )}
          {keuzeStap !== null && toevoegResultaat === null && (
            <div style={{ marginTop: 12, display: 'grid', gap: 10, minWidth: 0 }} data-testid="accordeur-toevoeg-keuze">
              <span className="hint" style={{ margin: 0, display: 'block', fontWeight: 700, fontSize: 11, textTransform: 'uppercase', letterSpacing: '.05em' }}>
                Toegang en laag per administratie
              </span>
              <p className="hint" style={{ margin: 0 }}>
                Standaard krijgt {gebruiker.naam} alleen toegang; de goedkeuringsroute blijft zoals hij is. Kies per
                administratie of {gebruiker.naam} ook als laag erbij komt (bestaande lagen blijven staan) of alleen in een
                leveranciersroute hoort.
              </p>
              {keuzeStap.map((a) => {
                const stand = standPer[a.id]
                const keuze = keuzePer[a.id] ?? 'toegang'
                const geladen = standVan(a.id)
                const laagMogelijk = a.actief && geladen !== null
                return (
                  <div key={a.id} data-testid="accordeur-toevoeg-rij" style={{ border: '1px solid var(--border)', borderRadius: 10, padding: '8px 12px', display: 'grid', gap: 6, minWidth: 0 }}>
                    <b>{a.actief ? a.naam : `${a.naam} — gearchiveerd`}</b>
                    <span className="hint" style={{ margin: 0 }}>
                      Nu:{' '}
                      {!a.actief
                        ? 'gearchiveerd — alleen toegang mogelijk'
                        : stand === 'laden'
                          ? 'laden…'
                          : !geladen
                            ? 'huidige stand niet geladen — alleen toegang mogelijk'
                            : huidigeStandTekst(geladen)}
                    </span>
                    <Select
                      aria-label={`Keuze voor ${a.naam}`}
                      value={keuze}
                      onChange={(e) => setKeuzePer((h) => ({ ...h, [a.id]: e.target.value as ToevoegKeuze }))}
                      style={{ width: 'auto', maxWidth: '100%' }}
                    >
                      {(Object.keys(KEUZE_LABEL) as ToevoegKeuze[]).map((k) => (
                        <option key={k} value={k} disabled={(k === 'laag_voor' || k === 'laag_na') && !laagMogelijk}>
                          {KEUZE_LABEL[k]}
                        </option>
                      ))}
                    </Select>
                    <span className="hint" style={{ margin: 0 }}>
                      Wordt: {wordtTekst(geladen, accordeur, keuze)}
                    </span>
                  </div>
                )
              })}
              {fout && <div className="fout">{fout}</div>}
            </div>
          )}
          {toevoegResultaat !== null && (
            <div style={{ marginTop: 12, display: 'grid', gap: 6 }} data-testid="accordeur-toevoeg-resultaat">
              <span className="hint" style={{ margin: 0, display: 'block', fontWeight: 700, fontSize: 11, textTransform: 'uppercase', letterSpacing: '.05em' }}>
                Resultaat (per administratie)
              </span>
              {toevoegResultaat.map((r) => (
                <div key={r.id} style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
                  <Badge variant={r.variant}>{r.variant === 'ok' ? 'gedaan' : 'let op'}</Badge>
                  <span>
                    <b>{r.naam}</b> — {r.tekst}
                    {r.routeLink && (
                      <>
                        {' '}
                        <Link to={r.routeLink} onClick={sluit}>
                          Route-editor openen →
                        </Link>
                      </>
                    )}
                  </span>
                </div>
              ))}
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
            ) : keuzeStap === null ? (
              <>
                <Button variant="ghost" onClick={() => setToevoegKeuze(null)}>
                  Annuleren
                </Button>
                <Button disabled={toevoegKeuze.length === 0} onClick={() => naarKeuzeStap(toevoegKeuze)}>
                  Verder ({toevoegKeuze.length})
                </Button>
              </>
            ) : toevoegResultaat === null ? (
              <>
                <Button variant="ghost" onClick={() => setKeuzeStap(null)} disabled={toevoegBezig}>
                  Terug
                </Button>
                <Button onClick={() => void toevoegen()} disabled={toevoegBezig}>
                  {toevoegBezig ? 'Bezig…' : `Toepassen op ${keuzeStap.length === 1 ? '1 administratie' : `${keuzeStap.length} administraties`}`}
                </Button>
              </>
            ) : (
              <Button onClick={sluitToevoegen}>Klaar</Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
      {verwijderVoor && !uitschakelBevestiging && (
        <Dialog open onOpenChange={(o) => !o && !bezig && annuleerVerwijderen()}>
          <DialogContent data-testid="accordeur-verwijderen-dialoog">
            <DialogTitle>
              {verwijderVoor.naam} — {gebruiker.naam} verwijderen
            </DialogTitle>
            <DialogDescription>
              {verwijderVoor.actief
                ? `Twee losse keuzes: haal ${gebruiker.naam} uit de accorderingslagen van ${verwijderVoor.naam} en/of trek de toegang tot die administratie in. Standaard blijft de toegang staan.`
                : `${verwijderVoor.naam} is gearchiveerd: er loopt geen accordering meer, alleen de toegang van ${gebruiker.naam} kan worden ingetrokken. Historie blijft staan.`}
            </DialogDescription>
            <div style={{ display: 'grid', gap: 10 }}>
              {verwijderVoor.actief && (
                <label style={{ display: 'flex', gap: 9, alignItems: 'flex-start', margin: 0, fontSize: 13 }}>
                  <Checkbox
                    aria-label="Uit de accorderingslagen halen"
                    checked={uitLagenEffectief}
                    disabled={bezig || instellingenVoor === 'laden' || !zitInLagen || toegangIntrekken}
                    onChange={(e) => setUitLagen(e.target.checked)}
                  />
                  <span>
                    <b>Uit de accorderingslagen halen</b>
                    <span className="hint" style={{ display: 'block', margin: '2px 0 0' }}>
                      {instellingenVoor === 'laden'
                        ? 'Lagen laden…'
                        : !zitInLagen
                          ? `${gebruiker.naam} staat niet in de accorderingslagen van ${verwijderVoor.naam} (wél mogelijk in een afdelings- of leveranciersroute — die beheer je op de klant-accorderingstab).`
                          : `Wijzigt dit het effectieve schema, dan worden de lopende accorderingsrondes van ${verwijderVoor.naam} herberekend: gegeven akkoorden van de overige accordeurs blijven staan, ontbrekende lagen worden opnieuw aangevraagd.${lopendeRondesTekst} Alleen een ronde waarvan geen enkel gegeven akkoord meer past vervalt (reden op de tijdlijn: "accorderingsconfiguratie gewijzigd — opnieuw aanbieden vereist"); die documenten gaan terug naar "Klaar om te boeken". Staande goedkeuringen en historie blijven staan. Geauditeerd (aanleiding: ${AANLEIDING}).` +
                            (toegangIntrekken ? ' Zonder toegang kan een laag niet goedkeuren, daarom staat dit vinkje vast aan.' : '') +
                            (wordtUitgeschakeld
                              ? ` LET OP: ${gebruiker.naam} is de laatste accorderingslaag — na "Bevestigen" volgt nog een aparte bevestiging voor het uitschakelen.`
                              : '')}
                    </span>
                  </span>
                </label>
              )}
              <label style={{ display: 'flex', gap: 9, alignItems: 'flex-start', margin: 0, fontSize: 13 }}>
                <Checkbox
                  aria-label="Toegang intrekken"
                  checked={toegangIntrekken}
                  disabled={bezig}
                  onChange={(e) => setToegangIntrekken(e.target.checked)}
                />
                <span>
                  <b>Toegang intrekken</b>
                  <span className="hint" style={{ display: 'block', margin: '2px 0 0' }}>
                    {gebruiker.naam} ziet {verwijderVoor.naam} dan niet meer in de app en is daar niet meer kiesbaar als
                    accordeur (ook niet voor een leveranciersroute). Toegang teruggeven kan altijd via "Administraties
                    toevoegen…". Scope-wijzigingen worden geauditeerd.
                  </span>
                </span>
              </label>
            </div>
            {fout && <div className="fout">{fout}</div>}
            <DialogFooter>
              <Button type="button" variant="secundair" onClick={annuleerVerwijderen} disabled={bezig}>
                Annuleren
              </Button>
              <Button
                type="button"
                disabled={bezig || instellingenVoor === 'laden' || !kanVerwijderen}
                onClick={() => {
                  if (wordtUitgeschakeld) setUitschakelBevestiging(true)
                  else void verwijderen()
                }}
              >
                {bezig ? 'Bezig…' : 'Bevestigen'}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
      {verwijderVoor && uitschakelBevestiging && (
        <BevestigDialog
          titel={`Klant-accordering voor ${verwijderVoor.naam} uitschakelen?`}
          bericht={`${gebruiker.naam} is de laatste accordeur in de accorderingslagen van ${verwijderVoor.naam}: accordering voor ${verwijderVoor.naam} wordt hiermee uitgeschakeld. Nieuwe facturen van ${verwijderVoor.naam} gaan dan zonder klant-akkoord naar de boekknop; lopende accorderingsrondes vervallen (er blijft geen laag over om tegen te herberekenen; documenten terug naar "Klaar om te boeken"). Opnieuw aanzetten kan altijd via Instellingen › ${verwijderVoor.naam} › Klant-accordering.${toegangIntrekken ? ' De toegang wordt daarna ook ingetrokken.' : ' De toegang blijft staan.'} Audit en tijdlijn vermelden de aanleiding "${AANLEIDING}".`}
          bezig={bezig}
          fout={fout}
          onBevestigen={() => void verwijderen()}
          onAnnuleren={annuleerVerwijderen}
        />
      )}
    </>
  )
}
