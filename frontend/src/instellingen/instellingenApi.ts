import { ApiError, apiJson } from '../api/client'
import type {
  ArchiveringResultaatDto,
  AutoboekBulkAanzettenResultaatDto,
  AutoboekBulkVerbergenResultaatDto,
  AutoboekKandidatenLijstDto,
  AutoboekTellersDto,
  AdministratieInstellingenLijstDto,
  BoekenIngeschakeldDto,
  EersteSyncRunDto,
  IsVastgoedResultaatDto,
  LeverancierAutoboekenDto,
  LeverancierAutoboekenLijstDto,
} from '../api/types'

/** Alle instellingen-verkeer op één plek (zelfde patroon als vragenApi.ts/ibanAccorderingApi.ts),
 * met absolute, door de dev-proxy gedekte paden — de guard-test instellingenApi.test.ts toetst
 * élk pad hier tegen de proxy-prefixen in vite.config.ts. Aanleiding (browserreview 2026-07-15):
 * '/instellingen/…' ontbrak in de proxy, waardoor Vite's SPA-fallback index.html (status 200)
 * teruggaf en de hele Instellingen-pagina omviel op JSON.parse — een fetch-mock in de
 * componenttest verbergt precies dat soort URL-fouten. */

const PUT_JSON = { method: 'PUT', headers: { 'Content-Type': 'application/json' } }

export function haalInstellingenAdministratiesOp(inclusiefGearchiveerd = false): Promise<AdministratieInstellingenLijstDto> {
  return apiJson<AdministratieInstellingenLijstDto>(
    inclusiefGearchiveerd ? '/instellingen/administraties?inclusief_gearchiveerd=true' : '/instellingen/administraties',
  )
}

/** Archiveren (v2 30-08, 🗑 — nooit verwijderen): actief uit, webservice-login uit de store, syncs stoppen,
 * documenten/historie blijven; registersync levert de rij niet meer. Beheerder-only. */
export function archiveerAdministratie(administratieId: string): Promise<ArchiveringResultaatDto> {
  return apiJson<ArchiveringResultaatDto>(`/instellingen/administraties/${administratieId}/archiveren`, { method: 'POST' })
}

/** Dearchiveren vereist een nieuwe webservice-login (probe groen, 422 mét rapport anders). */
export function dearchiveerAdministratie(
  administratieId: string,
  webservice_username: string,
  wachtwoord: string,
): Promise<{ rapport: Record<string, string> }> {
  return apiJson(`/instellingen/administraties/${administratieId}/dearchiveren`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ webservice_username, wachtwoord }),
  })
}

export function haalBoekenKillSwitchOp(): Promise<BoekenIngeschakeldDto> {
  return apiJson<BoekenIngeschakeldDto>('/instellingen/boeken-kill-switch')
}

export function zetBoekenKillSwitch(ingeschakeld: boolean): Promise<BoekenIngeschakeldDto> {
  return apiJson<BoekenIngeschakeldDto>('/instellingen/boeken-kill-switch', {
    ...PUT_JSON,
    body: JSON.stringify({ ingeschakeld }),
  })
}

/** Platformbrede noodrem duplicaat-auto-afvoer (blok A1 04-09, migratie 0109) — Beheerder-only, standaard
 * AAN; zelfde patroon als "Boeken platformbreed". Vervangt de per-administratie-toggle van 0105. */
export function haalDuplicaatAutoafvoerOp(): Promise<BoekenIngeschakeldDto> {
  return apiJson<BoekenIngeschakeldDto>('/instellingen/duplicaat-autoafvoer')
}

export function zetDuplicaatAutoafvoer(ingeschakeld: boolean): Promise<BoekenIngeschakeldDto> {
  return apiJson<BoekenIngeschakeldDto>('/instellingen/duplicaat-autoafvoer', {
    ...PUT_JSON,
    body: JSON.stringify({ ingeschakeld }),
  })
}

export function haalIntakeAiInstellingOp(): Promise<BoekenIngeschakeldDto> {
  return apiJson<BoekenIngeschakeldDto>('/instellingen/intake-ai')
}

export function zetIntakeAiInstelling(ingeschakeld: boolean): Promise<BoekenIngeschakeldDto> {
  return apiJson<BoekenIngeschakeldDto>('/instellingen/intake-ai', {
    ...PUT_JSON,
    body: JSON.stringify({ ingeschakeld }),
  })
}

/** AI-kostenmeter (besluit 2026-08-14): verbruik/limiet van de lopende kalendermaand
 * (Europe/Amsterdam). Bedragen als string — Decimal-precisie uit de backend, nooit float. */
export interface AiKostenStatusDto {
  maand: string
  verbruik_eur: string
  limiet_eur: string
  percentage: number
  waarschuwing_80: boolean
  limiet_bereikt: boolean
  geblokkeerd: boolean
  /** Deterministische extractie-terugval (01-09): veldvoorstellen deze maand per bron + actieve
   * leverancier-templates. Optioneel voor oudere responses/mocks. */
  extracties_template_maand?: number
  extracties_ai_maand?: number
  templates_actief?: number
}

export function haalAiKostenStatusOp(): Promise<AiKostenStatusDto> {
  return apiJson<AiKostenStatusDto>('/instellingen/ai-kosten')
}

export function zetAiKostenLimiet(maandlimietEur: string): Promise<AiKostenStatusDto> {
  return apiJson<AiKostenStatusDto>('/instellingen/ai-kosten-limiet', {
    ...PUT_JSON,
    body: JSON.stringify({ maandlimiet_eur: maandlimietEur }),
  })
}

export function zetBoekenInstelling(administratieId: string, ingeschakeld: boolean): Promise<unknown> {
  return apiJson(`/administraties/${administratieId}/boeken-instelling`, {
    ...PUT_JSON,
    body: JSON.stringify({ ingeschakeld }),
  })
}

/** Afdelingen-toggle (blok A 28-08, project_verplicht-patroon) — Beheerder-only; AAN maakt de
 * terugval-afdeling "Algemeen" aan. */
export function zetAfdelingenInstelling(administratieId: string, ingeschakeld: boolean): Promise<unknown> {
  return apiJson(`/administraties/${administratieId}/afdelingen-instelling`, {
    ...PUT_JSON,
    body: JSON.stringify({ ingeschakeld }),
  })
}

/** Opt-in "Voorraad bijhouden" (blok D 28-08, migratie 0086) — Beheerder-only, default UIT. */
export function zetVoorraadInstelling(administratieId: string, ingeschakeld: boolean): Promise<unknown> {
  return apiJson(`/administraties/${administratieId}/voorraad-instelling`, {
    ...PUT_JSON,
    body: JSON.stringify({ ingeschakeld }),
  })
}

export function zetProjectInstelling(administratieId: string, verplicht: boolean): Promise<unknown> {
  return apiJson(`/administraties/${administratieId}/project-instelling`, {
    ...PUT_JSON,
    body: JSON.stringify({ verplicht }),
  })
}

/** Autoboek-opt-in VASTLY-VERKOOP (migratie 0051) — Beheerder-only; aanzetten kan alleen
 * voor vastgoed-administraties (backend geeft dan 409). */
export function zetUrenMeerwerkInstelling(administratieId: string, ingeschakeld: boolean): Promise<unknown> {
  return apiJson(`/administraties/${administratieId}/uren-meerwerk-instelling`, {
    ...PUT_JSON,
    body: JSON.stringify({ ingeschakeld }),
  })
}

/** Signaal >N uur per dag (A6, 25-08): drempel per administratie (0 < N ≤ 24), Beheerder-only. */
export function zetUrenDagmaxInstelling(administratieId: string, dagmaxUren: string): Promise<{ dagmax_uren: string }> {
  return apiJson(`/administraties/${administratieId}/uren-dagmax-instelling`, {
    ...PUT_JSON,
    body: JSON.stringify({ dagmax_uren: dagmaxUren }),
  })
}

/** Opt-in omzet-autoboeken (kassarapporten; GO Peter 01-09, migratie 0096) — Beheerder-only, default UIT. */
export function zetOmzetAutoboekenInstelling(administratieId: string, ingeschakeld: boolean): Promise<unknown> {
  return apiJson(`/administraties/${administratieId}/omzet-autoboeken-instelling`, {
    ...PUT_JSON,
    body: JSON.stringify({ ingeschakeld }),
  })
}

export function zetVerkoopAutoboekenInstelling(administratieId: string, ingeschakeld: boolean): Promise<unknown> {
  return apiJson(`/administraties/${administratieId}/verkoop-autoboeken-instelling`, {
    ...PUT_JSON,
    body: JSON.stringify({ ingeschakeld }),
  })
}

/** Vastgoed-koppeling per administratie (avondrun 26-08, S2 R1) — Beheerder-only; UIT neemt
 * verkoop-autoboeken server-side mee uit (zichtbaar in het resultaat). */
export function zetIsVastgoed(administratieId: string, isVastgoed: boolean): Promise<IsVastgoedResultaatDto> {
  return apiJson<IsVastgoedResultaatDto>(`/administraties/${administratieId}/is-vastgoed`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ is_vastgoed: isVastgoed }),
  })
}

export function zetAiExtractieInstelling(administratieId: string, ingeschakeld: boolean): Promise<unknown> {
  return apiJson(`/administraties/${administratieId}/ai-extractie-instelling`, {
    ...PUT_JSON,
    body: JSON.stringify({ ingeschakeld }),
  })
}

/** Autoboeken-opt-in per leverancier (lezen: iedere medewerker binnen de scope). */
export function haalLeveranciersAutoboeken(administratieId: string): Promise<LeverancierAutoboekenLijstDto> {
  return apiJson<LeverancierAutoboekenLijstDto>(`/administraties/${administratieId}/leveranciers-autoboeken`)
}

/** Autoboeken-opt-in zetten (Beheerder-only — backend geeft 403 voor andere rollen). */
export function zetLeverancierAutoboeken(
  administratieId: string,
  vendorId: string,
  ingeschakeld: boolean,
): Promise<LeverancierAutoboekenDto> {
  return apiJson<LeverancierAutoboekenDto>(
    `/administraties/${administratieId}/leveranciers/${vendorId}/autoboeken-instelling`,
    {
      ...PUT_JSON,
      body: JSON.stringify({ ingeschakeld }),
    },
  )
}

export function zetEigenaar(administratieId: string, eigenaarGebruikerId: string | null): Promise<unknown> {
  return apiJson(`/administraties/${administratieId}/eigenaar`, {
    ...PUT_JSON,
    body: JSON.stringify({ eigenaar_gebruiker_id: eigenaarGebruikerId }),
  })
}

/* --- Administratie toevoegen (wizard, feedbackronde 26-08 punt 5) ---------------------------- */

export interface GevondenAdministratieDto {
  rlz_admin_id: string
  naam: string
  al_aangesloten: boolean
}

export interface AangemaakteAdministratieDto {
  id: string
  naam: string
  rlz_admin_id: string
  probe: Record<string, string>
  sync_run_id: string | null
}

export type { EersteSyncRunDto } from '../api/types'

export interface SchrijftestResultaatDto {
  uitkomst: 'ok' | 'fout' | string
  referentie: string
  document_id: string
  stappen: { stap: string; status: string; detail: string | null }[]
}

const POST_JSON = { method: 'POST', headers: { 'Content-Type': 'application/json' } }

/** Stap a+c: login proberen → gevonden administraties. Het wachtwoord reist alleen in de body. */
export function testVerbinding(webservice_username: string, wachtwoord: string): Promise<{ administraties: GevondenAdministratieDto[] }> {
  return apiJson('/instellingen/administraties/verbinding-testen', {
    ...POST_JSON,
    body: JSON.stringify({ webservice_username, wachtwoord }),
  })
}

/** Stap b+d: probe groen vereist (422 mét rapport, niets opgeslagen) → aanmaken + eerste sync. */
export function maakAdministratiesAan(
  webservice_username: string,
  wachtwoord: string,
  rlz_admin_ids: string[],
): Promise<{ administraties: AangemaakteAdministratieDto[] }> {
  return apiJson('/instellingen/administraties/aanmaken', {
    ...POST_JSON,
    body: JSON.stringify({ webservice_username, wachtwoord, rlz_admin_ids }),
  })
}

export function haalEersteSyncStatusOp(administratieId: string): Promise<EersteSyncRunDto> {
  return apiJson<EersteSyncRunDto>(`/instellingen/administraties/${administratieId}/eerste-sync/status`)
}

export function startEersteSync(administratieId: string): Promise<EersteSyncRunDto> {
  return apiJson<EersteSyncRunDto>(`/instellingen/administraties/${administratieId}/eerste-sync`, { method: 'POST' })
}

export function wijzigWebserviceGegevens(
  administratieId: string,
  webservice_username: string,
  wachtwoord: string,
): Promise<{ rapport: Record<string, string> }> {
  return apiJson(`/instellingen/administraties/${administratieId}/webservice-gegevens`, {
    ...PUT_JSON,
    body: JSON.stringify({ webservice_username, wachtwoord }),
  })
}

export function voerSchrijftestUit(administratieId: string): Promise<SchrijftestResultaatDto> {
  return apiJson<SchrijftestResultaatDto>(`/instellingen/administraties/${administratieId}/schrijftest`, { method: 'POST' })
}

/* De per-administratie dubbelen-/KvK-calls (punt 14, 28-08) zijn per 03-09 vervangen door het kantoorbrede
 * scherm Inzicht › Crediteuren (frontend/src/crediteuren/api.ts); de backend-routes blijven bestaan. */

/* --- Autoboek-kandidaten (blok B 01-09, Beheerder-only) ------------------------------------------- */

export type AutoboekTab = 'kandidaten' | 'actief' | 'heroverwegen'

export function haalAutoboekKandidatenOp(opties: {
  tab: AutoboekTab
  q?: string
  pagina?: number
  verborgen?: boolean
}): Promise<AutoboekKandidatenLijstDto> {
  const params = new URLSearchParams({ tab: opties.tab, pagina: String(opties.pagina ?? 1) })
  if (opties.q) params.set('q', opties.q)
  if (opties.verborgen) params.set('verborgen', 'true')
  return apiJson<AutoboekKandidatenLijstDto>(`/instellingen/autoboeken/kandidaten?${params.toString()}`)
}

/** Nav-stand-chip + tab-tellers (stand van de laatste run mét tijdstip). */
export function haalAutoboekStandOp(): Promise<AutoboekTellersDto> {
  return apiJson<AutoboekTellersDto>('/instellingen/autoboeken/stand')
}

export function herberekenAutoboekKandidaten(): Promise<{ administraties: number; fouten: number; tellers: AutoboekTellersDto }> {
  return apiJson('/instellingen/autoboeken/herbereken', { method: 'POST' })
}

/** Bulk-selectie (B5.2, 03-09): óf de aangevinkte rijen (`items`), óf `alle: true` mét dezelfde filters als
 * de lijst — de server herleidt dan de rijen zónder paginering ("Selecteer alle N resultaten"). */
export type AutoboekBulkSelectie =
  | { items: { administratie_id: string; vendor_id: string }[] }
  | { alle: true; tab: AutoboekTab; q: string; verborgen: boolean }

/** "Autoboeken aanzetten (n)": per rij live hertoetst; niet-kwalificerend = overgeslagen mét reden. */
export function zetAutoboekKandidatenAan(selectie: AutoboekBulkSelectie): Promise<AutoboekBulkAanzettenResultaatDto> {
  return apiJson<AutoboekBulkAanzettenResultaatDto>('/instellingen/autoboeken/kandidaten/aanzetten', {
    ...POST_JSON,
    body: JSON.stringify(selectie),
  })
}

export function zetAutoboekKandidaatUit(administratieId: string, vendorId: string): Promise<unknown> {
  return apiJson(`/instellingen/autoboeken/kandidaten/${administratieId}/${vendorId}/uitzetten`, { method: 'POST' })
}

/** "Kandidaat verbergen" = snooze mét verplichte reden (geaudit, terugvindbaar onder het filter). */
export function verbergAutoboekKandidaat(administratieId: string, vendorId: string, reden: string): Promise<unknown> {
  return apiJson(`/instellingen/autoboeken/kandidaten/${administratieId}/${vendorId}/verbergen`, {
    ...POST_JSON,
    body: JSON.stringify({ reden }),
  })
}

/** Bulk-verbergen in ÉÉN call (B5.1, 03-09): uitkomst per rij (verborgen | overgeslagen mét reden | fout),
 * zelfde patroon als aanzetten; reden verplicht (server 422 zonder). */
export function verbergAutoboekKandidaten(selectie: AutoboekBulkSelectie, reden: string): Promise<AutoboekBulkVerbergenResultaatDto> {
  return apiJson<AutoboekBulkVerbergenResultaatDto>('/instellingen/autoboeken/kandidaten/verbergen', {
    ...POST_JSON,
    body: JSON.stringify({ ...selectie, reden }),
  })
}

export function toonAutoboekKandidaatWeer(administratieId: string, vendorId: string): Promise<unknown> {
  return apiJson(`/instellingen/autoboeken/kandidaten/${administratieId}/${vendorId}/weer-tonen`, { method: 'POST' })
}

export function zetAutoboekDrempel(drempelOpRij: number): Promise<{ drempel_op_rij: number; laatste_run_op: string | null }> {
  return apiJson('/instellingen/autoboeken/instelling', { ...PUT_JSON, body: JSON.stringify({ drempel_op_rij: drempelOpRij }) })
}

/* --- Odoo-koppeling (adapter blok E, 03-09 — mockup odoo-koppeling-ui.html) ----------------------- */

/** Stand van de Odoo-koppeling op een administratie (GET …/odoo; 404 = geen koppeling). De API-sleutel
 * komt nooit terug — alleen het label `api_gebruiker` + de vervaldatum. `alleen_lezen` = leesbron-variant
 * (backend blijft RLZ, voorraad-uitstroom vanaf `voorraad_knip_datum`). */
export interface OdooStandDto {
  company_id: number
  company_naam: string | null
  odoo_url: string
  api_gebruiker: string | null
  api_key_verloopt_op: string | null
  probe_groen: boolean | null
  probe_op: string | null
  alleen_lezen: boolean
  voorraad_knip_datum: string | null
  probe_rapport: Record<string, string> | null
  stamgegevens: { ledgers: number; taxrates: number; vendors: number; projects: number } | null
  laatste_sync_op: string | null
  overgangsdatum: string | null
  rlz_admin_id_voor_overstap: string | null
}

/** Uitkomst van een (her)probe: per onderdeel 'ok' óf een leesbare foutregel mét handelingsperspectief
 * (notitie ⑥ — vertaal_rlz_boekfout-patroon). */
export interface OdooProbeDto {
  groen: boolean
  rapport: Record<string, string>
  company_naam: string | null
  versie: string | null
  lock_dates: Record<string, string | null>
}

export interface OdooSyncResultaatDto {
  run_id: string
  onderdelen: Record<string, { status: string; aangemaakt?: number; bijgewerkt?: number; fout?: string }>
}

export interface OdooCompanyDto {
  company_id: number
  naam: string
  al_gekoppeld: boolean
}

/** Resultaat van koppelen/overstap: probe-rapport + eerste-sync-run (zelfde subrij-patroon als RLZ). */
export interface OdooGekoppeldeAdministratieDto {
  id: string
  naam: string
  company_id: number
  probe: Record<string, string>
  sync_run_id: string | null
  sync: Record<string, { status: string; aangemaakt?: number; bijgewerkt?: number; fout?: string }>
}

/** Stamgegevens-onderdelen van een Odoo-administratie (geen bankrekeningen — de bank blijft RLZ-domein). */
export const ODOO_SYNC_ONDERDELEN = ['ledgers', 'taxrates', 'vendors', 'projects']

export async function haalOdooStandOp(administratieId: string): Promise<OdooStandDto | null> {
  try {
    return await apiJson<OdooStandDto>(`/administraties/${administratieId}/odoo`)
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null
    throw err
  }
}

/** Leeg object = herprobe ("Opnieuw testen"); mét api_key = "Sleutel wijzigen…" — probe-gated, de server
 * slaat alleen groen op (422 mét `detail: {bericht, rapport}` anders). De sleutel reist alleen in de body. */
export function probeOdooKoppeling(
  administratieId: string,
  body: { odoo_url?: string; api_key?: string; api_gebruiker?: string } = {},
): Promise<OdooProbeDto> {
  return apiJson<OdooProbeDto>(`/administraties/${administratieId}/odoo`, { ...PUT_JSON, body: JSON.stringify(body) })
}

export function startOdooSync(administratieId: string): Promise<OdooSyncResultaatDto> {
  return apiJson<OdooSyncResultaatDto>(`/administraties/${administratieId}/odoo/sync`, { method: 'POST' })
}

/** Wizard-stap Verbinding: URL + sleutel proberen → companies van die database (nooit een id typen). */
export function testOdooVerbinding(body: { odoo_url: string; api_key: string; api_gebruiker?: string }): Promise<{ companies: OdooCompanyDto[] }> {
  return apiJson('/instellingen/odoo/verbinding-testen', { ...POST_JSON, body: JSON.stringify(body) })
}

/** Ingang A: nieuwe Odoo-administratie(s) — probe groen vereist, daarna eerste sync als achtergrondrun. */
export function koppelOdooNieuw(body: {
  odoo_url: string
  api_key: string
  api_gebruiker?: string
  company_ids: number[]
  namen?: Record<string, string>
}): Promise<{ administraties: OdooGekoppeldeAdministratieDto[] }> {
  return apiJson('/instellingen/odoo/koppelen', { ...POST_JSON, body: JSON.stringify(body) })
}

/** Ingang B, volledige backend: bestaande RLZ-administratie stapt over per `overgangsdatum`. */
export function odooOverstap(
  administratieId: string,
  body: { odoo_url: string; api_key: string; api_gebruiker?: string; company_id: number; overgangsdatum: string },
): Promise<OdooGekoppeldeAdministratieDto> {
  return apiJson(`/administraties/${administratieId}/odoo/overstap`, { ...POST_JSON, body: JSON.stringify(body) })
}

/** Ingang B, alleen-lezen leesbron (voorraad-uitstroom vanaf de knip; backend blijft RLZ). */
export function koppelOdooLeesbron(
  administratieId: string,
  body: { odoo_url: string; api_key: string; api_gebruiker?: string; company_id: number; voorraad_knip_datum: string | null },
): Promise<OdooProbeDto> {
  return apiJson(`/administraties/${administratieId}/odoo/leesbron`, { ...POST_JSON, body: JSON.stringify(body) })
}

export function zetOdooKnipdatum(administratieId: string, voorraadKnipDatum: string | null): Promise<OdooStandDto> {
  return apiJson<OdooStandDto>(`/administraties/${administratieId}/odoo/leesbron`, {
    ...PUT_JSON,
    body: JSON.stringify({ voorraad_knip_datum: voorraadKnipDatum }),
  })
}

export function zetOdooOvergangsdatum(administratieId: string, overgangsdatum: string): Promise<OdooStandDto> {
  return apiJson<OdooStandDto>(`/administraties/${administratieId}/odoo/overgangsdatum`, {
    ...PUT_JSON,
    body: JSON.stringify({ overgangsdatum }),
  })
}

/* --- Maandagochtend-digest (D2 01-09): eigen weekmail-voorkeur, élke kantoorrol ---------------- */

export function haalMijnDigestOp(): Promise<{ opt_out: boolean }> {
  return apiJson('/auth/mijn/digest')
}

export function zetMijnDigest(optOut: boolean): Promise<{ opt_out: boolean }> {
  return apiJson('/auth/mijn/digest', { ...PUT_JSON, body: JSON.stringify({ opt_out: optOut }) })
}
