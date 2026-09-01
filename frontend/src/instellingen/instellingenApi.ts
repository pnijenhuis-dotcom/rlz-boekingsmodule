import { apiJson } from '../api/client'
import type {
  ArchiveringResultaatDto,
  AutoboekBulkAanzettenResultaatDto,
  AutoboekKandidatenLijstDto,
  AutoboekTellersDto,
  CrediteurKvkDto,
  DubbeleCrediteurenResponseDto,
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

/** Punt 14 (28-08): dubbel-signalering bestaande crediteuren (naam/IBAN/btw-/KvK-nummer) — alleen
 * lezen; samenvoegen blijft RLZ-mensenwerk, de app verwijdert niets. */
export function haalDubbeleCrediteurenOp(administratieId: string): Promise<DubbeleCrediteurenResponseDto> {
  return apiJson<DubbeleCrediteurenResponseDto>(`/administraties/${administratieId}/crediteuren/dubbelen`)
}

/** KvK-controle bij een dubbel-groep (hergebruik van de A3-KvK-client): officiële naam ter beoordeling. */
export function controleerCrediteurKvk(administratieId: string, kvkNummer: string): Promise<CrediteurKvkDto> {
  return apiJson<CrediteurKvkDto>(`/administraties/${administratieId}/crediteuren/kvk/${encodeURIComponent(kvkNummer)}`)
}

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

/** "Autoboeken aanzetten (n)": per rij live hertoetst; niet-kwalificerend = overgeslagen mét reden. */
export function zetAutoboekKandidatenAan(items: { administratie_id: string; vendor_id: string }[]): Promise<AutoboekBulkAanzettenResultaatDto> {
  return apiJson<AutoboekBulkAanzettenResultaatDto>('/instellingen/autoboeken/kandidaten/aanzetten', {
    ...POST_JSON,
    body: JSON.stringify({ items }),
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

export function toonAutoboekKandidaatWeer(administratieId: string, vendorId: string): Promise<unknown> {
  return apiJson(`/instellingen/autoboeken/kandidaten/${administratieId}/${vendorId}/weer-tonen`, { method: 'POST' })
}

export function zetAutoboekDrempel(drempelOpRij: number): Promise<{ drempel_op_rij: number; laatste_run_op: string | null }> {
  return apiJson('/instellingen/autoboeken/instelling', { ...PUT_JSON, body: JSON.stringify({ drempel_op_rij: drempelOpRij }) })
}
