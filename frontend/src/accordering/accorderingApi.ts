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
