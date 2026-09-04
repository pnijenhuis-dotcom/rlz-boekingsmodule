import { useMemo, useState } from 'react'
import { SearchableCombobox, type ComboboxOptie } from '../document/SearchableCombobox'
import { Badge, Checkbox } from '../ui/basis'
import type {
  OdooMappingInvoerDto,
  OdooMappingSoort,
  OdooMappingStandDto,
  OdooOverstapVoorbereidingDto,
  OdooProjectDto,
  OdooRekeningDto,
  OdooTariefDto,
} from './instellingenApi'

/** Rekening-mapping RLZ → Odoo (blok A 04-09, besluit Peter beslispunt 1 van "ODOO-ADAPTER BLOK E"): bij een
 * overstap vertaalt het boekingsgeheugen zijn grootboek/btw via deze tabel, zodat de autoboek-opt-ins blijven
 * werken. Eén component, twee afnemers:
 *   - wizard-stap "mapping" (modus 'kiezen'): het deterministische voorstel staat vooringevuld, de mens bevestigt
 *     de HELE tabel — "Koppeling opslaan" blijft uit tot élke in-gebruik-rij een Odoo-tegenhanger heeft;
 *   - detail-dialoog "Mapping bekijken/corrigeren…" (modus 'corrigeren'): élke wijziging is direct een PUT =
 *     nieuwe versie (append-only), zichtbaar als versie-badge.
 * Slotstuk 04-09 (blok B, besluit Peter beslispunt 2): een DERDE blok "Projecten" — RLZ-project ↔ Odoo analytic
 * account. Projectrijen zijn OPTIONEEL: een lege rij telt niet mee in `mappingCompleet` (projectplicht is een aparte
 * boek-check), maar wél zichtbaar in de kop als "K vervalt"; "Aanmaken in Odoo" (alleen bij `kan_aanmaken`) maakt bij
 * de overstap een analytic account aan op het RLZ-projectnummer.
 * UX-patronen als norm: de kop-teller is een restant-balk (open = teal, compleet = groen ✓); de herkomst-chip
 * volgt de voorstel-kaart-semantiek (groen = exact, oranje = bevestigen mét reden, rood = nog te kiezen, neutraal =
 * status zonder oordeel); de lege stand is één zin, geen lege tabel. Geld-/rekeninglogica staat NIET hier: het
 * voorstel komt van de server (`app/odoo/mapping.py`), dit component kiest alleen. */

export type MappingBronWeergave = 'zelfde_code' | 'code_verlengd' | 'tarief' | 'handmatig' | 'projectnummer' | 'projectnaam' | 'aangemaakt' | null

export interface MappingTabelRij {
  soort: OdooMappingSoort
  rlz_id: string
  rlz_code: string | null
  rlz_naam: string | null
  /** Alleen btw: percentage als string ("21.00") en de verlegd-vlag — voor de RLZ-kolom. */
  rlz_percentage?: string | null
  verlegd?: boolean
  /** Alleen project: leidende cijfers van de RLZ-naam (vet in de rij), actief-vlag, of aanmaken in Odoo kan. */
  rlz_nummer?: string | null
  actief?: boolean | null
  kan_aanmaken?: boolean
  /** Alleen project, kies-modus: de mens koos "Aanmaken in Odoo" (→ `odoo_id` null, reist als `aanmaken: true`). */
  aanmaken?: boolean
  in_gebruik_observaties: number
  in_gebruik_open_regels: number
  /** Huidige keuze (voorstel, mens-keuze of geldende mapping); null = nog te kiezen (project: = vervalt). */
  odoo_id: number | null
  /** Herkomst van de huidige keuze; null zolang er niets gekozen is. */
  bron: MappingBronWeergave
  /** Alleen corrigeer-modus: geldende versie (1 = bij de overstap; > 1 = gecorrigeerd). */
  versie?: number
}

export function mappingSleutel(soort: OdooMappingSoort, rlzId: string): string {
  return `${soort}:${rlzId}`
}

const BRONNEN: ReadonlySet<string> = new Set(['zelfde_code', 'code_verlengd', 'tarief', 'handmatig', 'projectnummer', 'projectnaam', 'aangemaakt'])

function alsBron(reden: string | null | undefined): MappingBronWeergave {
  return reden && BRONNEN.has(reden) ? (reden as MappingBronWeergave) : null
}

/** Verplichte rijen = grootboek + btw; projectrijen zijn optioneel (blok B). */
export function isVerplichteRij(r: MappingTabelRij): boolean {
  return r.soort !== 'project'
}

/** Wizard: voorbereidings-response → tabelrijen mét het voorstel vooringevuld. */
export function rijenUitVoorbereiding(v: OdooOverstapVoorbereidingDto): MappingTabelRij[] {
  const grootboek: MappingTabelRij[] = v.grootboek.map((r) => ({
    soort: 'grootboek',
    rlz_id: r.rlz_id,
    rlz_code: r.rlz_code,
    rlz_naam: r.rlz_naam,
    in_gebruik_observaties: r.in_gebruik_observaties,
    in_gebruik_open_regels: r.in_gebruik_open_regels,
    odoo_id: r.voorstel_odoo_id,
    bron: r.voorstel_odoo_id == null ? null : alsBron(r.reden),
  }))
  const btw: MappingTabelRij[] = v.btw.map((r) => ({
    soort: 'btw',
    rlz_id: r.rlz_id,
    rlz_code: null,
    rlz_naam: r.rlz_naam,
    rlz_percentage: r.rlz_percentage,
    verlegd: r.verlegd,
    in_gebruik_observaties: r.in_gebruik_observaties,
    in_gebruik_open_regels: r.in_gebruik_open_regels,
    odoo_id: r.voorstel_odoo_id,
    bron: r.voorstel_odoo_id == null ? null : alsBron(r.reden),
  }))
  const project: MappingTabelRij[] = (v.project ?? []).map((r) => ({
    soort: 'project',
    rlz_id: r.rlz_id,
    rlz_code: r.rlz_nummer,
    rlz_naam: r.rlz_naam,
    rlz_nummer: r.rlz_nummer,
    actief: r.actief,
    kan_aanmaken: r.kan_aanmaken,
    aanmaken: false,
    in_gebruik_observaties: r.in_gebruik_observaties,
    in_gebruik_open_regels: r.in_gebruik_open_regels,
    odoo_id: r.voorstel_odoo_id,
    bron: r.voorstel_odoo_id == null ? null : alsBron(r.reden),
  }))
  return [...grootboek, ...btw, ...project]
}

/** Detail-dialoog: geldende mapping → tabelrijen (grootboek/btw altijd compleet — de overstap eiste dat al;
 * projectrijen alleen die er zijn). */
export function rijenUitStand(s: OdooMappingStandDto): MappingTabelRij[] {
  return [...s.grootboek, ...s.btw, ...(s.project ?? [])].map((r) => ({
    soort: r.soort,
    rlz_id: r.rlz_id,
    rlz_code: r.rlz_code,
    rlz_naam: r.rlz_naam,
    ...(r.soort === 'project' ? { rlz_nummer: r.rlz_code } : {}),
    in_gebruik_observaties: 0,
    in_gebruik_open_regels: 0,
    odoo_id: r.odoo_id,
    bron: alsBron(r.bron),
    versie: r.versie,
  }))
}

/** Request-body voor POST …/odoo/overstap: alleen de gekozen rijen (de server weigert een onvolledige mapping
 * met 422 zolang er in-gebruik-rijen zonder tegenhanger zijn — de knop staat dan al uit). Projectrijen: gekozen
 * → `{odoo_id, aanmaken: false}`, aan te maken → `{odoo_id: null, aanmaken: true}`, leeg → reist niet (vervalt). */
export function mappingInvoer(rijen: MappingTabelRij[]): OdooMappingInvoerDto {
  const invoer: OdooMappingInvoerDto = { grootboek: [], btw: [], project: [] }
  for (const r of rijen) {
    if (r.soort === 'project') {
      if (r.aanmaken) invoer.project.push({ rlz_id: r.rlz_id, odoo_id: null, aanmaken: true })
      else if (r.odoo_id != null) invoer.project.push({ rlz_id: r.rlz_id, odoo_id: r.odoo_id, aanmaken: false })
      continue
    }
    if (r.odoo_id == null) continue
    invoer[r.soort].push({ rlz_id: r.rlz_id, odoo_id: r.odoo_id })
  }
  return invoer
}

/** Telling over de VERPLICHTE rijen (grootboek + btw) — dit stuurt de restant-balk en de opslaan-knop. */
export function mappingTelling(rijen: MappingTabelRij[]): { gekozen: number; totaal: number } {
  const verplicht = rijen.filter(isVerplichteRij)
  return { gekozen: verplicht.filter((r) => r.odoo_id != null).length, totaal: verplicht.length }
}

/** Telling over de projectrijen: gekoppeld · wordt aangemaakt · vervalt (= leeg gelaten, telt niet als open). */
export function projectTelling(rijen: MappingTabelRij[]): { gekoppeld: number; aanmaken: number; vervalt: number; totaal: number } {
  const projecten = rijen.filter((r) => r.soort === 'project')
  const aanmaken = projecten.filter((r) => r.aanmaken).length
  const gekoppeld = projecten.filter((r) => !r.aanmaken && r.odoo_id != null).length
  return { gekoppeld, aanmaken, vervalt: projecten.length - gekoppeld - aanmaken, totaal: projecten.length }
}

/** Compleet = élke verplichte rij heeft een tegenhanger; projectrijen mogen leeg blijven. */
export function mappingCompleet(rijen: MappingTabelRij[]): boolean {
  return rijen.filter(isVerplichteRij).every((r) => r.odoo_id != null)
}

/** Herkomst-chip grootboek/btw: groen = exact, oranje = bevestigen (mét reden), neutraal = handmatig, rood = nog te kiezen. */
export function bronChip(bron: MappingBronWeergave, odooId: number | null): { klasse: string; tekst: string } {
  if (odooId == null) return { klasse: 'chip blokkerend', tekst: 'kies' }
  switch (bron) {
    case 'zelfde_code':
      return { klasse: 'chip ok', tekst: 'zelfde code' }
    case 'code_verlengd':
      return { klasse: 'chip afwijking', tekst: 'code + 00 — bevestig' }
    case 'tarief':
      return { klasse: 'chip afwijking', tekst: 'tarief' }
    case 'projectnummer':
      return { klasse: 'chip ok', tekst: 'projectnummer' }
    case 'projectnaam':
      return { klasse: 'chip afwijking', tekst: 'projectnaam — bevestig' }
    case 'aangemaakt':
      return { klasse: 'chip handmatig', tekst: 'aangemaakt in Odoo' }
    case 'handmatig':
      return { klasse: 'chip handmatig', tekst: 'handmatig' }
    default:
      return { klasse: 'chip handmatig', tekst: 'gekozen' }
  }
}

/** Herkomst-chip voor een PROJECTRIJ: leeg is hier géén rood "kies" maar een neutrale status "geen — project vervalt"
 * (optioneel), en "wordt aangemaakt in Odoo" is een STATUS (neutraal) — de actie is de checkbox ernaast. */
export function projectChip(rij: Pick<MappingTabelRij, 'bron' | 'odoo_id' | 'aanmaken'>): { klasse: string; tekst: string } {
  if (rij.aanmaken) return { klasse: 'chip handmatig', tekst: 'wordt aangemaakt in Odoo' }
  if (rij.odoo_id == null) return { klasse: 'chip handmatig', tekst: 'geen — project vervalt' }
  return bronChip(rij.bron, rij.odoo_id)
}

/** `percentage`/`rlz_percentage` zijn de canonieke FRACTIE (0.21 — zoals `taxrate_cache.percentage` en de
 * Odoo-`amount`/100, backend-schema's 04-09) → "21%". Weergave-afronding op 2 decimalen; geen geldlogica. */
export function percentageTekst(p: string | null | undefined): string | null {
  if (p == null || p === '') return null
  const n = Number(p)
  if (Number.isNaN(n)) return `${p}%`
  return `${(Math.round(n * 10000) / 100).toLocaleString('nl-NL', { maximumFractionDigits: 2 })}%`
}

export function grootboekOpties(odoo: OdooRekeningDto[]): ComboboxOptie[] {
  return odoo.map((r) => ({ id: String(r.odoo_id), code: r.code, label: r.naam }))
}

/** Btw-opties mét percentage als code; de synthetische rij heet expliciet "geen btw-code in Odoo" (= geen
 * tax_ids), zodat niemand 'm voor een echt 0%-tarief houdt. */
export function btwOpties(odoo: OdooTariefDto[]): ComboboxOptie[] {
  return odoo.map((t) => ({
    id: String(t.odoo_id),
    code: percentageTekst(t.percentage) ?? '',
    label: t.synthetisch ? 'Geen btw (0%) — geen btw-code in Odoo' : `${t.naam}${t.verlegd ? ' (verlegd)' : ''}`,
  }))
}

/** Project-opties: code (= projectnummer) + naam. De gesyncte Odoo-naam draagt vaak al "[code] " als prefix
 * (`odoo/sync.py::lees_projecten`) — die wordt gestript zodat de code niet dubbel in de optie staat. */
export function projectOpties(odoo: OdooProjectDto[]): ComboboxOptie[] {
  return odoo.map((p) => {
    const zonderPrefix = p.code ? p.naam.replace(new RegExp(`^\\s*\\[${p.code.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\]\\s*`), '') : p.naam
    return { id: String(p.odoo_id), ...(p.code ? { code: p.code } : {}), label: zonderPrefix || p.naam }
  })
}

/** Splitst de RLZ-projectnaam in nummer (vet) + rest, zodat "26127 Tilburg (Heijmans)" leesbaar blijft. */
export function projectNaamDelen(naam: string | null, nummer: string | null | undefined): { nummer: string | null; rest: string } {
  const volledig = naam ?? ''
  if (nummer && volledig.trimStart().startsWith(nummer)) {
    return { nummer, rest: volledig.trimStart().slice(nummer.length).trim() }
  }
  return { nummer: nummer ?? null, rest: volledig }
}

function inGebruikTekst(r: MappingTabelRij): string {
  const delen: string[] = []
  if (r.in_gebruik_observaties > 0) delen.push(`${r.in_gebruik_observaties}× geheugen`)
  if (r.in_gebruik_open_regels > 0) delen.push(`${r.in_gebruik_open_regels} open ${r.in_gebruik_open_regels === 1 ? 'regel' : 'regels'}`)
  return delen.length ? `in gebruik: ${delen.join(' · ')}` : ''
}

function rlzLabel(r: MappingTabelRij): string {
  if (r.soort === 'btw') {
    // RLZ zet het percentage van een verlegd tarief op 0 — "0%" zou daar misleiden, dus alleen het label "verlegd".
    const pct = r.verlegd ? null : percentageTekst(r.rlz_percentage)
    return [r.rlz_naam ?? 'onbekend RLZ-tarief', pct, r.verlegd ? 'verlegd' : null].filter(Boolean).join(' · ')
  }
  if (r.soort === 'project') {
    return [r.rlz_naam ?? (r.rlz_nummer ? `project ${r.rlz_nummer}` : 'onbekend RLZ-project'), r.actief === false ? 'niet actief' : null].filter(Boolean).join(' · ')
  }
  return [r.rlz_code, r.rlz_naam].filter(Boolean).join(' · ') || 'onbekende RLZ-rekening'
}

/** RLZ-kolom voor een projectrij: nummer vet, rest van de naam erachter. */
function ProjectRlzLabel({ r }: { r: MappingTabelRij }) {
  const { nummer, rest } = projectNaamDelen(r.rlz_naam, r.rlz_nummer)
  return (
    <span>
      {nummer && <b>{nummer}</b>}
      {nummer && rest ? ' ' : ''}
      {rest || (nummer ? '' : 'onbekend RLZ-project')}
      {r.actief === false && (
        <>
          {' '}
          <span className="hint" style={{ margin: 0, fontSize: 11 }}>
            · niet actief
          </span>
        </>
      )}
    </span>
  )
}

interface Props {
  rijen: MappingTabelRij[]
  odooGrootboek: OdooRekeningDto[]
  odooBtw: OdooTariefDto[]
  /** Odoo analytic accounts voor het projectblok (blok B); leeg/afwezig = alleen "Aanmaken in Odoo" of vervalt. */
  odooProjecten?: OdooProjectDto[]
  /** Keuze per rij; null = keuze gewist. In corrigeer-modus doet de aanroeper hier de PUT. */
  onKies: (rij: MappingTabelRij, odooId: number | null) => void
  /** Kies-modus, alleen projectrijen mét `kan_aanmaken`: "Aanmaken in Odoo" aan/uit. */
  onAanmaken?: (rij: MappingTabelRij, aanmaken: boolean) => void
  modus?: 'kiezen' | 'corrigeren'
  /** Corrigeer-modus: sleutel van de rij waarvan de PUT loopt (combobox even uit). */
  bezigSleutel?: string | null
}

export function OdooMappingTabel({ rijen, odooGrootboek, odooBtw, odooProjecten = [], onKies, onAanmaken, modus = 'kiezen', bezigSleutel = null }: Props) {
  const [alleenTeKiezen, setAlleenTeKiezen] = useState(false)
  const gbOpties = useMemo(() => grootboekOpties(odooGrootboek), [odooGrootboek])
  const btwOptieLijst = useMemo(() => btwOpties(odooBtw), [odooBtw])
  const projectOptieLijst = useMemo(() => projectOpties(odooProjecten), [odooProjecten])
  const telling = mappingTelling(rijen)
  const projecten = projectTelling(rijen)
  const compleet = telling.totaal > 0 && telling.gekozen === telling.totaal

  if (rijen.length === 0) {
    return (
      <p className="hint" style={{ margin: 0 }} data-testid="odoo-mapping-leeg">
        Geen boekingsgeheugen of open regels om te vertalen — mapping niet nodig.
      </p>
    )
  }

  // "Nog te kiezen" = een lege verplichte rij; een leeg project is een keuze (vervalt) maar blijft wél zichtbaar in het filter,
  // zodat de mens 'm alsnog kan koppelen of aanmaken.
  const openRij = (r: MappingTabelRij) => r.odoo_id == null && !r.aanmaken
  const zichtbaar = alleenTeKiezen ? rijen.filter(openRij) : rijen
  const grootboek = zichtbaar.filter((r) => r.soort === 'grootboek')
  const btw = zichtbaar.filter((r) => r.soort === 'btw')
  const project = zichtbaar.filter((r) => r.soort === 'project')
  const totaalGrootboek = rijen.filter((r) => r.soort === 'grootboek').length
  const totaalBtw = rijen.filter((r) => r.soort === 'btw').length
  const nog = telling.totaal - telling.gekozen

  return (
    <div data-testid="odoo-mapping-tabel">
      {/* Kop-teller als restant-balk (UX-patronen als norm): open = teal, compleet = groen ✓. Projecten tellen apart
          (optioneel) en staan als eigen fragment in de kop. */}
      <div className={`restant-balk${compleet || telling.totaal === 0 ? ' compleet' : ''}`} data-testid="odoo-mapping-teller">
        {telling.totaal > 0 ? (
          <>
            <span>
              <b>{telling.gekozen}</b> van {telling.totaal} gekoppeld
            </span>
            <span className="balk" aria-hidden>
              <span style={{ width: `${Math.round((telling.gekozen / telling.totaal) * 100)}%` }} />
            </span>
            {compleet ? <span className="compleet-tekst">✓ alles gekoppeld</span> : <span className="nog">nog {nog} te kiezen</span>}
          </>
        ) : (
          <span className="compleet-tekst">✓ geen grootboek of btw te vertalen</span>
        )}
        {projecten.totaal > 0 && (
          <span className="hint" style={{ margin: 0, fontSize: 12, whiteSpace: 'nowrap' }} data-testid="odoo-mapping-projecten-teller">
            projecten: {projecten.gekoppeld} van {projecten.totaal} gekoppeld
            {projecten.aanmaken > 0 ? ` · ${projecten.aanmaken} ${projecten.aanmaken === 1 ? 'wordt' : 'worden'} aangemaakt` : ''}
            {projecten.vervalt > 0 ? ` · ${projecten.vervalt} ${projecten.vervalt === 1 ? 'vervalt' : 'vervallen'}` : ''}
          </span>
        )}
        {modus === 'kiezen' && (
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, margin: 0, fontSize: 12, whiteSpace: 'nowrap' }}>
            <Checkbox checked={alleenTeKiezen} onChange={(e) => setAlleenTeKiezen(e.target.checked)} aria-label="Alleen nog te kiezen" />
            alleen nog te kiezen
          </label>
        )}
      </div>

      <MappingBlok
        titel={`Grootboek (${totaalGrootboek})`}
        rlzKop="RLZ-rekening"
        odooKop="Odoo-rekening"
        rijen={grootboek}
        verborgen={alleenTeKiezen && grootboek.length === 0 && totaalGrootboek > 0}
        opties={gbOpties}
        onKies={onKies}
        modus={modus}
        bezigSleutel={bezigSleutel}
      />
      <MappingBlok
        titel={`Btw-tarieven (${totaalBtw})`}
        rlzKop="RLZ-btw-tarief"
        odooKop="Odoo-tax"
        rijen={btw}
        verborgen={alleenTeKiezen && btw.length === 0 && totaalBtw > 0}
        opties={btwOptieLijst}
        onKies={onKies}
        modus={modus}
        bezigSleutel={bezigSleutel}
      />
      <MappingBlok
        titel={`Projecten (${projecten.totaal})`}
        rlzKop="RLZ-project"
        odooKop="Odoo-project"
        rijen={project}
        verborgen={alleenTeKiezen && project.length === 0 && projecten.totaal > 0}
        opties={projectOptieLijst}
        onKies={onKies}
        onAanmaken={onAanmaken}
        modus={modus}
        bezigSleutel={bezigSleutel}
        optioneel
      />
    </div>
  )
}

function MappingBlok({
  titel,
  rlzKop,
  odooKop,
  rijen,
  verborgen,
  opties,
  onKies,
  onAanmaken,
  modus,
  bezigSleutel,
  optioneel = false,
}: {
  titel: string
  rlzKop: string
  odooKop: string
  rijen: MappingTabelRij[]
  verborgen: boolean
  opties: ComboboxOptie[]
  onKies: Props['onKies']
  onAanmaken?: Props['onAanmaken']
  modus: 'kiezen' | 'corrigeren'
  bezigSleutel: string | null
  /** Projectblok: een lege rij is geen fout (geen rode rand, neutrale chip) en de rij mag "Aanmaken in Odoo" dragen. */
  optioneel?: boolean
}) {
  if (rijen.length === 0 && !verborgen) return null
  return (
    <section style={{ marginBottom: 12 }}>
      <h4 style={{ margin: '0 0 6px', fontSize: 12.5 }}>{titel}</h4>
      {optioneel && modus === 'kiezen' && !verborgen && (
        <p className="hint" style={{ margin: '0 0 6px' }}>
          Optioneel: een project zonder Odoo-tegenhanger vervalt in het boekingsgeheugen (de projectplicht blijft een aparte check bij
          het boeken). "Aanmaken in Odoo" maakt bij de overstap een analytic account aan op het RLZ-projectnummer.
        </p>
      )}
      {verborgen ? (
        <p className="hint" style={{ margin: 0 }}>
          Alles in dit blok is gekoppeld.
        </p>
      ) : (
        <div className="tabel-scroll">
          <table className="odoo-mapping-tabel">
            <thead>
              <tr>
                <th>{rlzKop}</th>
                <th>{odooKop}</th>
                <th>Herkomst</th>
              </tr>
            </thead>
            <tbody>
              {rijen.map((r) => {
                const sleutel = mappingSleutel(r.soort, r.rlz_id)
                const chip = optioneel ? projectChip(r) : bronChip(r.bron, r.odoo_id)
                const inGebruik = inGebruikTekst(r)
                const bezig = bezigSleutel === sleutel
                const kanAanmaken = optioneel && modus === 'kiezen' && Boolean(r.kan_aanmaken) && Boolean(onAanmaken)
                return (
                  <tr key={sleutel} data-testid={`odoo-mapping-rij-${sleutel}`}>
                    <td>
                      <div>{r.soort === 'project' ? <ProjectRlzLabel r={r} /> : rlzLabel(r)}</div>
                      {inGebruik && (
                        <div className="hint" style={{ margin: 0, fontSize: 11 }}>
                          {inGebruik}
                        </div>
                      )}
                    </td>
                    <td style={{ minWidth: 220 }}>
                      {bezig ? (
                        <span className="hint" style={{ margin: 0 }}>
                          Opslaan…
                        </span>
                      ) : r.aanmaken ? (
                        <span className="hint" style={{ margin: 0 }} data-testid={`odoo-mapping-aanmaken-tekst-${sleutel}`}>
                          nieuw analytic account <b>{r.rlz_nummer ?? ''}</b> {projectNaamDelen(r.rlz_naam, r.rlz_nummer).rest}
                        </span>
                      ) : (
                        <SearchableCombobox
                          label={`${odooKop} voor ${rlzLabel(r)}`}
                          toonLabel={false}
                          opties={opties}
                          waarde={r.odoo_id == null ? null : String(r.odoo_id)}
                          onWijzig={(id) => onKies(r, id == null ? null : Number(id))}
                          placeholder={optioneel ? 'Kies Odoo-project (of laat leeg)…' : 'Kies Odoo-tegenhanger…'}
                          fout={!optioneel && r.odoo_id == null}
                        />
                      )}
                    </td>
                    <td style={{ whiteSpace: 'nowrap' }}>
                      <span className={chip.klasse}>{chip.tekst}</span>
                      {kanAanmaken && (
                        <>
                          {' '}
                          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 4, margin: 0, fontSize: 12 }}>
                            <Checkbox
                              checked={Boolean(r.aanmaken)}
                              onChange={(e) => onAanmaken?.(r, e.target.checked)}
                              aria-label={`Aanmaken in Odoo: ${rlzLabel(r)}`}
                              disabled={bezig}
                            />
                            Aanmaken in Odoo
                          </label>
                        </>
                      )}
                      {modus === 'corrigeren' && (r.versie ?? 1) > 1 && (
                        <>
                          {' '}
                          <Badge variant="info" title="Gecorrigeerd ná de overstap — append-only, eerdere versies blijven in de audit">
                            v{r.versie}
                          </Badge>
                        </>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
