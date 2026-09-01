import { apiJson, apiPostJson } from '../api/client'

// DTO's spiegelen backend/app/accordering/schemas.py — bedragen als string (Decimal), nooit
// berekend in de client.

export interface AccorderingLaagDto {
  volgnummer: number
  accordeur_gebruiker_id: string
  accordeur_naam: string | null
  bedrag_drempel: string | null
}

export interface AccorderingInstellingenDto {
  ingeschakeld: boolean
  lagen: AccorderingLaagDto[]
  /** Alleen op de PUT-response (27/28-08 punt 2a): lopende rondes die door déze wijziging vervielen. */
  rondes_vervallen?: number
}

/** Eenmalige werkvoorraad-melding (punt 2a): één configuratiewijziging die lopende rondes liet
 * vervallen; `nog_niet_opnieuw_aangeboden` 0 = de melding is vanzelf klaar. */
export interface VervallenMeldingDto {
  batch_id: string
  tijdstip: string
  door_gebruiker_id: string
  door_naam: string | null
  aantal: number
  nog_niet_opnieuw_aangeboden: number
  reden: string
}

export interface BulkAanbiedResultaatDto {
  document_id: string
  bestandsnaam: string | null
  uitkomst: 'aangeboden' | 'geboekt' | 'overgeslagen' | string
  reden: string | null
  boek_fout: string | null
}

export interface BulkAanbiedenResponseDto {
  resultaten: BulkAanbiedResultaatDto[]
  aangeboden: number
  geboekt: number
  overgeslagen: number
}

export function haalVervallenMeldingen(administratieId: string): Promise<VervallenMeldingDto[]> {
  return apiJson(`/administraties/${administratieId}/accordering/vervallen-meldingen`)
}

/** Bulk "Ter accordering aanbieden" (punt 2b) — zelfde poorten als de losse knop, per document;
 * geweigerd = `overgeslagen` mét reden in de response, nooit stil. */
export function bulkTerAccorderingAanbieden(
  administratieId: string,
  documentIds: string[],
): Promise<BulkAanbiedenResponseDto> {
  return apiPostJson(`/administraties/${administratieId}/accordering/documenten/bulk-aanbieden`, {
    document_ids: documentIds,
  })
}

export interface AccorderingStapDto {
  volgnummer: number
  accordeur_gebruiker_id: string
  accordeur_naam: string | null
  bedrag_drempel: string | null
  vereist: boolean
  besluit: string | null
  besluit_bron: string | null
  reden: string | null
  besloten_op: string | null
  aan_de_beurt: boolean
}

export interface AccorderingDto {
  id: string
  document_id: string
  status: string
  aangeboden_op: string
  afgerond_op: string | null
  stappen: AccorderingStapDto[]
  /** Bugfix-run 28-08: laatste boekfout ná het laatste akkoord (persistent op de ronde) — de
   * accorderingssectie toont 'm rood mét de knop "Opnieuw boeken". Null = geen. */
  boek_fout?: string | null
  boek_fout_op?: string | null
}

export interface BesluitResultaatDto {
  accordering: AccorderingDto
  alles_akkoord: boolean
  geboekt: boolean
  boek_fout: string | null
  staande_regel_id: string | null
}

export interface StaandeRegelDto {
  id: string
  accordeur_gebruiker_id: string
  accordeur_naam: string | null
  vendor_id: string
  leverancier_naam: string | null
  bedrag: string
  actief: boolean
  aangemaakt_op: string
  ingetrokken_op: string | null
}

export interface KandidaatDto {
  id: string
  naam: string
}

export function haalAccorderingInstellingen(administratieId: string): Promise<AccorderingInstellingenDto> {
  return apiJson(`/administraties/${administratieId}/accordering/instellingen`)
}

export function zetAccorderingInstellingen(
  administratieId: string,
  payload: {
    ingeschakeld: boolean
    lagen: { volgnummer: number; accordeur_gebruiker_id: string; bedrag_drempel: string | null }[]
  },
): Promise<AccorderingInstellingenDto> {
  return apiJson(`/administraties/${administratieId}/accordering/instellingen`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function haalAccorderingKandidaten(administratieId: string): Promise<{ kandidaten: KandidaatDto[] }> {
  return apiJson(`/administraties/${administratieId}/accordering/kandidaten`)
}

// --- Bulk klant-accordering instellen (mockup bulk-accordering.html, besluiten Peter 01-09) ------

export interface BulkInstellenInputDto {
  administratie_ids: string[]
  lagen: { volgnummer: number; accordeur_gebruiker_id: string; bedrag_drempel: string | null }[]
  /** De expliciete vink (besluit 1): ontbrekende accordeur-scope aanmaken i.p.v. BV overslaan. */
  scope_toevoegen: boolean
}

export interface BulkScopeOntbreektDto {
  accordeur_gebruiker_id: string
  accordeur_naam: string
  administratie_ids: string[]
  administratie_namen: string[]
}

/** Eén regel van de uitkomstenlijst — zelfde vorm vóór (preview) en ná (resultaat). */
export interface BulkInstelUitkomstDto {
  administratie_id: string
  administratie_naam: string
  uitkomst: 'ingesteld' | 'vervangen' | 'overgeslagen' | 'fout' | string
  rondes_vervallen: number
  toggle_aangezet: boolean
  scope_toegevoegd_voor: string[]
  reden: string | null
}

export interface BulkInstellenPreviewDto {
  uitkomsten: BulkInstelUitkomstDto[]
  scope_ontbreekt: BulkScopeOntbreektDto[]
}

/** Álle actieve klant-accordeurs, platform-breed (Beheerder-only) — de bulk-kiezer: scope kan
 * bij een geselecteerde BV immers nog ontbreken. */
export function haalAlleAccordeurKandidaten(): Promise<{ kandidaten: KandidaatDto[] }> {
  return apiJson('/accordering/accordeur-kandidaten')
}

export function bulkAccorderingPreview(invoer: BulkInstellenInputDto): Promise<BulkInstellenPreviewDto> {
  return apiPostJson('/accordering/bulk-instellen/preview', invoer)
}

export function bulkAccorderingToepassen(
  invoer: BulkInstellenInputDto,
): Promise<{ uitkomsten: BulkInstelUitkomstDto[] }> {
  return apiPostJson('/accordering/bulk-instellen', invoer)
}

export function haalAccorderingVanDocument(
  administratieId: string,
  documentId: string,
): Promise<AccorderingDto | null> {
  return apiJson(`/administraties/${administratieId}/accordering/documenten/${documentId}`)
}

export function trekAccorderingIn(administratieId: string, documentId: string): Promise<AccorderingDto> {
  return apiPostJson(`/administraties/${administratieId}/accordering/documenten/${documentId}/intrekken`, {})
}

// --- handmatige herinnering per document (beheer-mini 2026-08-16) --------------------------------

export interface HerinneringResultaatDto {
  document_id: string
  accordeur_naam: string
  verzonden_op: string
  kanaal: string
}

export function herinnerAccordeur(administratieId: string, documentId: string): Promise<HerinneringResultaatDto> {
  return apiPostJson(`/administraties/${administratieId}/accordering/documenten/${documentId}/herinneren`, {})
}

/** document_id -> laatste geslaagde handmatige herinnering ("laatst herinnerd"). */
export function haalLaatstHerinnerd(administratieId: string): Promise<{ laatst_herinnerd: Record<string, string> }> {
  return apiJson(`/administraties/${administratieId}/accordering/herinneringen`)
}

export function haalStaandeRegels(administratieId: string): Promise<{ regels: StaandeRegelDto[] }> {
  return apiJson(`/administraties/${administratieId}/accordering/staande-regels`)
}

export function trekStaandeRegelIn(administratieId: string, regelId: string): Promise<void> {
  return apiJson(`/administraties/${administratieId}/accordering/staande-regels/${regelId}/intrekken`, {
    method: 'POST',
  })
}

// --- apparaatbeheer / kill-switch (blok 4 accordeur-PWA, Beheerder-only) -------------------------

export interface ApparaatDto {
  id: string
  apparaat_naam: string | null
  is_dev_stub: boolean
  aangemaakt_op: string
  laatst_gebruikt_op: string | null
  ingetrokken_op: string | null
}

export function haalApparaten(gebruikerId: string): Promise<{ apparaten: ApparaatDto[] }> {
  return apiJson(`/auth/gebruikers/${gebruikerId}/apparaten`)
}

/** Kill-switch: trekt de passkey én alle sessies van dit apparaat per direct in. */
export function trekApparaatIn(apparaatId: string): Promise<void> {
  return apiJson(`/auth/apparaten/${apparaatId}/intrekken`, { method: 'POST' })
}
