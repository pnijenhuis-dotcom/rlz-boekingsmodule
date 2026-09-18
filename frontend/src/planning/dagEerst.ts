import { normaliseerTekst } from '../bank/bankZoek'
import {
  kaartPastInFilter,
  type AfwezigheidDto,
  type PlanningKaartDto,
  type PlanningPoolPersoonDto,
  type PlanningProjectRijDto,
  type PlanningReserveringDto,
  type PlanningWeekDto,
  type UrenFilter,
  type UrenStatus,
} from './planningApi'

/* Planning v3 "dag-eerst" (Peter 18-09, mockup planning-v3-dag-eerst.html = bouwnorm): pure transformaties van de
 * bestaande weekrespons (rij per project × dag) naar dagkolommen mét projectkaarten, dagtotalen, kaartstatus (laagste
 * urenstatus van de ploeg), de client-side conflict-toets (dubbel op één dag, afwezig, > 5 op één kaart, ZZP'er zonder
 * dossier), beschikbaarheid per persoon × dag (ploeg-paneel), het vulhandvat (kopiëren over dagen binnen de week,
 * bestaande kaart van hetzelfde project overslaan) en de projectbalk-sortering. Geen React, geen fetch — vitest dekt 'm. */

export type ConflictSoort = 'dubbel' | 'afwezig' | 'te_groot' | 'geen_dossier'

export interface Conflict {
  soort: ConflictSoort
  gebruiker_id: string | null
  naam: string | null
  datum: string
  project_id: string
  /** Bij `dubbel`: alle projecten van die dag; bij de rest alleen `project_id`. */
  project_ids: string[]
  tekst: string
}

export interface DagKaart {
  /** Sleutel `${project_id}|${datum}` — ook het `?kaart=`-deeplink-formaat. */
  sleutel: string
  project_id: string
  project_naam: string | null
  opdrachtgever: string | null
  soort_werk: string | null
  datum: string
  ploeg: PlanningKaartDto[]
  /** Lege kaart (grijs, dashed) — een `planning_reservering` zonder ploeg. */
  reservering: PlanningReserveringDto | null
  gereserveerd: boolean
  status: UrenStatus
  conflicten: Conflict[]
  werkopdracht_tekst: string | null
  werkopdracht_afwijkend: boolean
  na_einddatum: boolean
  achteraf: boolean
}

export interface DagKolom {
  datum: string
  naam: string
  kaarten: DagKaart[]
  /** Dagtotaal: aantal persoon-kaarten (½ dag telt als 1 persoon) en aantal projecten mét ploeg of reservering. */
  aantal_man: number
  aantal_projecten: number
}

const STATUS_RANG: Record<UrenStatus, number> = { vraag: 0, geen: 1, ingevuld: 2, gekeurd: 3 }

/** Kaartniveau = de LAAGSTE status van de ploeg (afgekeurd/vraag < geen < ingevuld < gekeurd); lege ploeg = geen. */
export function laagsteStatus(ploeg: Pick<PlanningKaartDto, 'uren_status'>[]): UrenStatus {
  let laagste: UrenStatus | null = null
  for (const k of ploeg) {
    const s = k.uren_status ?? 'geen'
    if (laagste === null || STATUS_RANG[s] < STATUS_RANG[laagste]) laagste = s
  }
  return laagste ?? 'geen'
}

export function isAfwezig(afwezigheid: AfwezigheidDto[] | undefined, gebruikerId: string, datum: string): AfwezigheidDto | null {
  for (const a of afwezigheid ?? []) {
    if (a.gebruiker_id === gebruikerId && a.van <= datum && datum <= a.tot) return a
  }
  return null
}

export const MAX_PLOEG_ZONDER_SIGNAAL = 5

/** Alle conflicten van de week — nooit blokkerend, kantoor beslist. Dubbel = dezelfde persoon op één dag op 2+ projecten
 * (uit `per_datum`, dus óók vóór de server-melding `dubbele_dagen` die pas ná uren ontstaat); afwezig = gepland binnen een
 * afwezigheid; te_groot = > 5 op één kaart (besluit C); geen_dossier = pool-vlag (optioneel in de DTO). */
export function conflictenVoorWeek(data: PlanningWeekDto): Conflict[] {
  const uit: Conflict[] = []
  const perPersoonDag = new Map<string, { kaart: PlanningKaartDto; project_id: string }[]>()
  for (const rij of data.projecten) {
    for (const [datum, kaarten] of Object.entries(rij.per_datum)) {
      if (kaarten.length > MAX_PLOEG_ZONDER_SIGNAAL) {
        uit.push({
          soort: 'te_groot',
          gebruiker_id: null,
          naam: null,
          datum,
          project_id: rij.project_id,
          project_ids: [rij.project_id],
          tekst: `${dagKort(datum)}: ${kaarten.length} man op ${rij.project_naam ?? rij.project_id} (meer dan ${MAX_PLOEG_ZONDER_SIGNAAL})`,
        })
      }
      for (const k of kaarten) {
        const sleutel = `${k.gebruiker_id}|${datum}`
        const lijst = perPersoonDag.get(sleutel) ?? []
        lijst.push({ kaart: k, project_id: rij.project_id })
        perPersoonDag.set(sleutel, lijst)
        const afw = isAfwezig(data.afwezigheid, k.gebruiker_id, datum)
        if (afw) {
          uit.push({
            soort: 'afwezig',
            gebruiker_id: k.gebruiker_id,
            naam: k.naam,
            datum,
            project_id: rij.project_id,
            project_ids: [rij.project_id],
            tekst: `${dagKort(datum)}: ${k.naam ?? '?'} afwezig${afw.reden ? ` (${afw.reden})` : ''} maar gepland op ${rij.project_naam ?? rij.project_id}`,
          })
        }
        const pool = data.pool.find((p) => p.gebruiker_id === k.gebruiker_id)
        if (pool?.dossier_onvolledig) {
          uit.push({
            soort: 'geen_dossier',
            gebruiker_id: k.gebruiker_id,
            naam: k.naam,
            datum,
            project_id: rij.project_id,
            project_ids: [rij.project_id],
            tekst: `${dagKort(datum)}: ${k.naam ?? '?'} zonder compleet ZZP-dossier op ${rij.project_naam ?? rij.project_id}`,
          })
        }
      }
    }
  }
  for (const [sleutel, lijst] of perPersoonDag) {
    if (lijst.length < 2) continue
    const [gebruikerId, datum] = sleutel.split('|')
    const namen = lijst.map((l) => data.projecten.find((r) => r.project_id === l.project_id)?.project_naam ?? l.project_id)
    for (const l of lijst) {
      uit.push({
        soort: 'dubbel',
        gebruiker_id: gebruikerId,
        naam: lijst[0].kaart.naam,
        datum,
        project_id: l.project_id,
        project_ids: lijst.map((x) => x.project_id),
        tekst: `${dagKort(datum)}: ${lijst[0].kaart.naam ?? '?'} op ${namen.join(' én ')}`,
      })
    }
  }
  return uit.sort((a, b) => (a.datum < b.datum ? -1 : a.datum > b.datum ? 1 : 0))
}

/** Voor de conflictenbalk: elk conflict één keer (dubbel over meerdere kaarten = één regel). */
export function conflictenUniek(conflicten: Conflict[]): Conflict[] {
  const gezien = new Set<string>()
  return conflicten.filter((c) => {
    const s = `${c.soort}|${c.gebruiker_id ?? ''}|${c.datum}|${c.soort === 'dubbel' ? '' : c.project_id}`
    if (gezien.has(s)) return false
    gezien.add(s)
    return true
  })
}

export function dagKort(iso: string): string {
  const d = new Date(`${iso}T12:00:00Z`)
  return `${['zo', 'ma', 'di', 'wo', 'do', 'vr', 'za'][d.getUTCDay()]} ${d.getUTCDate()}-${d.getUTCMonth() + 1}`
}

/** Geldende werkopdracht-tekst op een dag: de dag-override wint, anders de (eerste) periode-tekst die de dag dekt. */
export function werkopdrachtOpDag(rij: PlanningProjectRijDto, datum: string): { tekst: string; afwijkend: boolean } | null {
  const override = (rij.werkopdracht_overrides ?? {})[datum]?.[0]
  if (override) return { tekst: override.tekst, afwijkend: true }
  const periode = (rij.werkopdrachten ?? []).find((w) => w.van <= datum && datum <= w.tot_en_met)
  return periode ? { tekst: periode.tekst, afwijkend: false } : null
}

/** Rij-grid → dagkolommen. Eén kaart per project × dag; een reservering zónder ploeg = lege kaart, mét ploeg = de
 * ploegkaart (de reserveringsrij blijft drager, de UI ontdubbelt). `urenFilter` werkt als KAARTFILTER: alleen de ploegleden
 * die in het filter passen blijven; een kaart zonder passende leden valt weg (reserveringen blijven bij 'alle'). */
export function bouwDagKolommen(
  data: PlanningWeekDto,
  dagen: { naam: string; datum: string }[],
  opties: { urenFilter?: UrenFilter; conflicten?: Conflict[] } = {},
): DagKolom[] {
  const filter = opties.urenFilter ?? 'alle'
  const conflicten = opties.conflicten ?? conflictenVoorWeek(data)
  const reserveringen = data.reserveringen ?? []
  return dagen.map((d) => {
    const kaarten: DagKaart[] = []
    for (const rij of data.projecten) {
      const alle = rij.per_datum[d.datum] ?? []
      const reservering = reserveringen.find((r) => r.project_id === rij.project_id && r.datum === d.datum) ?? null
      if (alle.length === 0 && !reservering) continue
      const ploeg = alle.filter((k) => kaartPastInFilter(k, filter))
      if (alle.length > 0 && ploeg.length === 0) continue
      if (alle.length === 0 && filter !== 'alle') continue
      const wo = werkopdrachtOpDag(rij, d.datum)
      kaarten.push({
        sleutel: `${rij.project_id}|${d.datum}`,
        project_id: rij.project_id,
        project_naam: rij.project_naam,
        opdrachtgever: rij.opdrachtgever,
        soort_werk: rij.soort_werk,
        datum: d.datum,
        ploeg,
        reservering,
        gereserveerd: alle.length === 0,
        status: laagsteStatus(ploeg),
        conflicten: conflicten.filter((c) => c.datum === d.datum && c.project_id === rij.project_id),
        werkopdracht_tekst: wo?.tekst ?? null,
        werkopdracht_afwijkend: wo?.afwijkend ?? false,
        na_einddatum: rij.looptijd_tot !== null && d.datum > rij.looptijd_tot,
        achteraf: ploeg.some((k) => k.achteraf),
      })
    }
    // Reserveringen van projecten die niet (meer) in de rijenlijst staan blijven zichtbaar (naam uit de reservering).
    for (const r of reserveringen) {
      if (r.datum !== d.datum || data.projecten.some((p) => p.project_id === r.project_id) || filter !== 'alle') continue
      kaarten.push({
        sleutel: `${r.project_id}|${d.datum}`,
        project_id: r.project_id,
        project_naam: r.projectnaam,
        opdrachtgever: null,
        soort_werk: null,
        datum: d.datum,
        ploeg: [],
        reservering: r,
        gereserveerd: true,
        status: 'geen',
        conflicten: [],
        werkopdracht_tekst: null,
        werkopdracht_afwijkend: false,
        na_einddatum: false,
        achteraf: false,
      })
    }
    kaarten.sort((a, b) => (a.project_naam ?? '').localeCompare(b.project_naam ?? '', 'nl'))
    return {
      datum: d.datum,
      naam: d.naam,
      kaarten,
      aantal_man: kaarten.reduce((som, k) => som + k.ploeg.length, 0),
      aantal_projecten: kaarten.length,
    }
  })
}

export function dagTotaalLabel(k: DagKolom): string {
  const man = `${k.aantal_man} man`
  return k.aantal_projecten === 0 ? '—' : `${man} · ${k.aantal_projecten} ${k.aantal_projecten === 1 ? 'project' : 'projecten'}`
}

/* --- beschikbaarheid (ploeg-paneel, pool) ----------------------------------------------------- */

export type Beschikbaarheid =
  | { soort: 'vrij' }
  | { soort: 'al_op'; project_id: string; project_naam: string | null }
  | { soort: 'afwezig'; tot: string; reden: string | null }

/** Beschikbaarheid van een persoon voor één dag, gezien vanaf de kaart `eigenProjectId` (die telt niet als "al op"). */
export function beschikbaarheid(data: PlanningWeekDto, gebruikerId: string, datum: string, eigenProjectId: string | null): Beschikbaarheid {
  const afw = isAfwezig(data.afwezigheid, gebruikerId, datum)
  if (afw) return { soort: 'afwezig', tot: afw.tot, reden: afw.reden }
  for (const rij of data.projecten) {
    if (rij.project_id === eigenProjectId) continue
    if ((rij.per_datum[datum] ?? []).some((k) => k.gebruiker_id === gebruikerId)) {
      return { soort: 'al_op', project_id: rij.project_id, project_naam: rij.project_naam }
    }
  }
  return { soort: 'vrij' }
}

export function beschikbaarheidLabel(b: Beschikbaarheid): string {
  if (b.soort === 'vrij') return 'vrij'
  if (b.soort === 'afwezig') return `afwezig t/m ${dagKort(b.tot).replace(/^\w+ /, '')}`
  return `al op ${b.project_naam ?? '?'}`
}

/** Pool-regel: "vrij" (0 dagen), "afwezig t/m …" of niets extra. */
export function poolStand(p: PlanningPoolPersoonDto, weekDatums: string[], afwezigheid: AfwezigheidDto[] | undefined): 'vrij' | 'afwezig' | 'gepland' {
  const tot = p.afwezig_tot ?? weekDatums.map((d) => isAfwezig(afwezigheid, p.gebruiker_id, d)?.tot ?? null).find(Boolean) ?? null
  if (tot) return 'afwezig'
  return Number(p.geplande_dagen) === 0 ? 'vrij' : 'gepland'
}

export function afwezigTot(p: PlanningPoolPersoonDto, weekDatums: string[], afwezigheid: AfwezigheidDto[] | undefined): string | null {
  if (p.afwezig_tot) return p.afwezig_tot
  for (const d of weekDatums) {
    const a = isAfwezig(afwezigheid, p.gebruiker_id, d)
    if (a) return a.tot
  }
  return null
}

/* --- vulhandvat --------------------------------------------------------------------------------- */

export interface VulhandvatItem {
  gebruiker_id: string
  naam: string | null
  project_id: string
  datum: string
  dagdeel: 'heel' | 'half'
  /** Client-side voorspelling — de server geeft de echte uitkomst. */
  conflict: 'project' | 'afwezig' | null
  conflict_projectnaam: string | null
}

export interface VulhandvatVoorbeeld {
  doelen: { datum: string; overgeslagen: boolean; items: VulhandvatItem[]; conflicten: number }[]
  items: VulhandvatItem[]
  aantal_conflicten: number
  overgeslagen_datums: string[]
}

/** Kaart + ploeg kopiëren naar `doelDatums` (binnen de week; de aanroeper begrenst op ma–vr): een doeldag waarop hetzelfde
 * project al een kaart heeft wordt OVERGESLAGEN (nooit dubbel, nooit vervangen); per persoon-dag de conflict-toets. */
export function vulhandvatVoorbeeld(data: PlanningWeekDto, kaart: DagKaart, doelDatums: string[]): VulhandvatVoorbeeld {
  const rij = data.projecten.find((r) => r.project_id === kaart.project_id)
  const doelen = doelDatums
    .filter((d) => d !== kaart.datum)
    .map((datum) => {
      const bestaand = (rij?.per_datum[datum] ?? []).length > 0 || (data.reserveringen ?? []).some((r) => r.project_id === kaart.project_id && r.datum === datum)
      if (bestaand) return { datum, overgeslagen: true, items: [] as VulhandvatItem[], conflicten: 0 }
      const items = kaart.ploeg.map((k): VulhandvatItem => {
        const b = beschikbaarheid(data, k.gebruiker_id, datum, kaart.project_id)
        return {
          gebruiker_id: k.gebruiker_id,
          naam: k.naam,
          project_id: kaart.project_id,
          datum,
          dagdeel: 'heel',
          conflict: b.soort === 'vrij' ? null : b.soort === 'afwezig' ? 'afwezig' : 'project',
          conflict_projectnaam: b.soort === 'al_op' ? b.project_naam : null,
        }
      })
      return { datum, overgeslagen: false, items, conflicten: items.filter((i) => i.conflict).length }
    })
  const items = doelen.flatMap((d) => d.items)
  return {
    doelen,
    items,
    aantal_conflicten: items.filter((i) => i.conflict).length,
    overgeslagen_datums: doelen.filter((d) => d.overgeslagen).map((d) => d.datum),
  }
}

/** Van kaartdatum tot en met `totDatum` (of andersom), begrensd op de werkdagen van de week — nooit over de weekgrens. */
export function handvatBereik(werkdagen: string[], vanDatum: string, totDatum: string): string[] {
  const i = werkdagen.indexOf(vanDatum)
  const j = werkdagen.indexOf(totDatum)
  if (i < 0 || j < 0) return []
  const [a, b] = i < j ? [i, j] : [j, i]
  return werkdagen.slice(a, b + 1)
}

/* --- projectbalk --------------------------------------------------------------------------------- */

export interface ProjectTegel {
  project_id: string
  project_naam: string | null
  opdrachtgever: string | null
  gepland: boolean
  /** "ma–wo · 4 man" of "niet gepland". */
  samenvatting: string
}

export function projectTegels(data: PlanningWeekDto, werkdagen: { naam: string; datum: string }[], zoek: string): ProjectTegel[] {
  const termen = normaliseerTekst(zoek).split(' ').filter(Boolean)
  const reserveringen = data.reserveringen ?? []
  return data.projecten
    .filter((r) => r.is_actief || Object.keys(r.per_datum).length > 0)
    .filter((r) => termen.length === 0 || termen.every((t) => normaliseerTekst(`${r.project_naam ?? ''} ${r.opdrachtgever ?? ''}`).includes(t)))
    .map((r): ProjectTegel => {
      const datums = werkdagen.filter((d) => (r.per_datum[d.datum] ?? []).length > 0 || reserveringen.some((x) => x.project_id === r.project_id && x.datum === d.datum))
      const gepland = datums.length > 0
      const man = werkdagen.reduce((m, d) => Math.max(m, (r.per_datum[d.datum] ?? []).length), 0)
      const bereik = gepland ? (datums.length === 1 ? datums[0].naam : `${datums[0].naam}–${datums[datums.length - 1].naam}`) : ''
      return {
        project_id: r.project_id,
        project_naam: r.project_naam,
        opdrachtgever: r.opdrachtgever,
        gepland,
        samenvatting: gepland ? `${bereik} · ${man} man` : 'niet gepland',
      }
    })
    .sort((a, b) => (a.gepland === b.gepland ? (a.project_naam ?? '').localeCompare(b.project_naam ?? '', 'nl') : a.gepland ? -1 : 1))
}

/* --- per project (leesweergave) ------------------------------------------------------------------ */

export interface PerProjectRij {
  project_id: string
  project_naam: string | null
  opdrachtgever: string | null
  cellen: { datum: string; aantal: number; status: UrenStatus; conflicten: number; gereserveerd: boolean }[]
  mandagen: number
  week_tekst: string
}

export function perProjectRijen(kolommen: DagKolom[], data: PlanningWeekDto): { rijen: PerProjectRij[]; zonder_planning: number } {
  const perProject = new Map<string, PerProjectRij>()
  for (const kol of kolommen) {
    for (const k of kol.kaarten) {
      let rij = perProject.get(k.project_id)
      if (!rij) {
        rij = { project_id: k.project_id, project_naam: k.project_naam, opdrachtgever: k.opdrachtgever, cellen: [], mandagen: 0, week_tekst: '' }
        perProject.set(k.project_id, rij)
      }
    }
  }
  for (const rij of perProject.values()) {
    rij.cellen = kolommen.map((kol) => {
      const k = kol.kaarten.find((x) => x.project_id === rij.project_id)
      return { datum: kol.datum, aantal: k?.ploeg.length ?? 0, status: k?.status ?? 'geen', conflicten: k?.conflicten.length ?? 0, gereserveerd: k?.gereserveerd ?? false }
    })
    rij.mandagen = rij.cellen.reduce((s, c) => s + c.aantal, 0)
    const bron = data.projecten.find((p) => p.project_id === rij.project_id)
    const conflicten = rij.cellen.reduce((s, c) => s + c.conflicten, 0)
    const delen = [`${rij.mandagen} mandagen`]
    if (bron?.week_uren) {
      const totaal = rij.mandagen
      const metUren = rij.cellen.reduce((s, _c, i) => s + (kolommen[i].kaarten.find((x) => x.project_id === rij.project_id)?.ploeg.filter((p) => (p.uren_status ?? 'geen') !== 'geen').length ?? 0), 0)
      delen.push(`uren ${metUren}/${totaal}`)
    }
    if (conflicten > 0) delen.push(`${conflicten} ${conflicten === 1 ? 'conflict' : 'conflicten'}`)
    if (rij.mandagen === 0 && rij.cellen.some((c) => c.gereserveerd)) delen.splice(0, delen.length, 'gereserveerd — nog geen ploeg')
    rij.week_tekst = delen.join(' · ')
  }
  const rijen = [...perProject.values()].sort((a, b) => (a.project_naam ?? '').localeCompare(b.project_naam ?? '', 'nl'))
  const zonder = data.projecten.filter((p) => p.is_actief && !perProject.has(p.project_id)).length
  return { rijen, zonder_planning: zonder }
}

/** Initialen (max 2) — zelfde vorm als het oude grid. */
export function initialen(naam: string | null): string {
  if (!naam) return '?'
  return naam
    .split(/\s+/)
    .map((d) => d[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()
}

/** `?kaart=<project_id>|<datum>` (deeplink vanuit signalen/conflictenbalk) → sleutel of null. */
export function parseKaartParam(param: string | null): string | null {
  if (!param) return null
  return /^[0-9a-f-]{8,}\|\d{4}-\d{2}-\d{2}$/i.test(param) ? param : null
}
