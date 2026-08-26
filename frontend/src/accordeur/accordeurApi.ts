// PWA-datalag: wachtrij/akkoord/afwijzen/staande regels/voorwaarden. DTO's spiegelen
// backend/app/accordering/schemas.py + app/auth/schemas.py — bedragen als string (Decimal),
// nooit berekend in de client.

import { apiFetch, ApiError, apiJson, apiPostJson } from '../api/client'
import type { BesluitResultaatDto, AccorderingDto, StaandeRegelDto } from '../accordering/accorderingApi'

export interface WachtrijItemDto {
  document_id: string
  administratie_id: string
  administratie_naam: string | null
  leverancier_naam: string | null
  referentie: string | null
  factuurdatum: string | null
  totaalbedrag: string | null
  aangeboden_op: string
  laag_volgnummer: number
  boeking_omschrijving: string | null
  staande_regel_kandidaat: boolean
  /** Klaargezette doorbelasting (besluit 25-08, A3): ALLEEN-LEZEN per doelentiteit; null =
   * geen doorbelasting bij dit document. Fout = de gewone afwijsknop met reden. */
  doorbelasting?: WachtrijDoorbelastingRegelDto[] | null
  /** Open vraag van het kantoor aan déze accordeur op dit document (blok B5, 26-08); null = geen. */
  vraag?: AccordeurVraagDto | null
}

export interface AccordeurVraagBerichtDto {
  id: string
  auteur_id: string
  van_mij: boolean
  tekst: string
  geplaatst_op: string
}

/** Vraag-thread zoals de accordeur 'm ziet (mockup accordeur-vragen.html): uitsluitend vragen die
 * aan de ingelogde accordeur gericht zijn — namen van kantoormedewerkers reizen niet mee. */
export interface AccordeurVraagDto {
  id: string
  administratie_id: string
  administratie_naam: string | null
  document_id: string
  document_status: string
  leverancier_naam: string | null
  totaalbedrag: string | null
  vraag_tekst: string
  gesteld_op: string
  ik_ben_aan_de_beurt: boolean
  berichten: AccordeurVraagBerichtDto[]
}

export function haalVragenAanMij(): Promise<{ items: AccordeurVraagDto[] }> {
  return apiJson('/accordering/vragen')
}

/** Antwoord in de thread (append-only). Afgehandeld verklaren kan alleen de vraagsteller (kantoor). */
export function beantwoordVraag(administratieId: string, vraagId: string, tekst: string): Promise<AccordeurVraagDto> {
  return apiPostJson(`/administraties/${administratieId}/accordering/vragen/${vraagId}/berichten`, { tekst })
}

export interface WachtrijDoorbelastingRegelDto {
  doelentiteit_naam: string
  percentage: string
  netto_totaal: string
  provisie_bedrag: string
}

export const VOORWAARDEN_AKKOORD_VEREIST = 'voorwaarden_akkoord_vereist'

export function haalWachtrij(): Promise<{ items: WachtrijItemDto[] }> {
  return apiJson('/accordering/wachtrij')
}

export function geefAkkoord(
  administratieId: string,
  documentId: string,
  staandeRegelAanmaken: boolean,
): Promise<BesluitResultaatDto> {
  return apiPostJson(`/administraties/${administratieId}/accordering/documenten/${documentId}/akkoord`, {
    staande_regel_aanmaken: staandeRegelAanmaken,
  })
}

export function wijsAf(administratieId: string, documentId: string, reden: string): Promise<AccorderingDto> {
  return apiPostJson(`/administraties/${administratieId}/accordering/documenten/${documentId}/afwijzen`, {
    reden,
  })
}

export interface VoorwaardenDto {
  tekst_versie: string
  tekst: string
  akkoord_gegeven: boolean
  administratie_namen: string[]
}

export function haalVoorwaarden(): Promise<VoorwaardenDto> {
  return apiJson('/auth/accordeur/voorwaarden')
}

export function legVoorwaardenAkkoordVast(): Promise<void> {
  return apiJson('/auth/accordeur/voorwaarden-akkoord', { method: 'POST' })
}

export function haalMijnAdministraties(): Promise<{ administraties: { id: string; naam: string }[] }> {
  return apiJson('/auth/administraties')
}

export function haalStaandeRegels(administratieId: string): Promise<{ regels: StaandeRegelDto[] }> {
  return apiJson(`/administraties/${administratieId}/accordering/staande-regels`)
}

export function trekStaandeRegelIn(administratieId: string, regelId: string): Promise<void> {
  return apiJson(`/administraties/${administratieId}/accordering/staande-regels/${regelId}/intrekken`, {
    method: 'POST',
  })
}

/** Factuurbeeld als blob-URL (Authorization-header vereist — een kale <object src> kan niet). */
export async function haalFactuurBlob(administratieId: string, documentId: string): Promise<string> {
  const resp = await apiFetch(`/administraties/${administratieId}/documenten/${documentId}/bestand`)
  if (!resp.ok) throw new ApiError(resp.status, 'Factuurbeeld kon niet geladen worden')
  return URL.createObjectURL(await resp.blob())
}

export function isVoorwaardenVereist(err: unknown): boolean {
  return err instanceof ApiError && err.status === 403 && err.message === VOORWAARDEN_AKKOORD_VEREIST
}

/** €-weergave van een Decimal-string — puur presentatie, geen rekenwerk. */
export function eurWeergave(bedrag: string | null): string {
  if (bedrag === null) return '—'
  const getal = Number(bedrag)
  if (Number.isNaN(getal)) return bedrag
  return new Intl.NumberFormat('nl-NL', { style: 'currency', currency: 'EUR' }).format(getal)
}

export function datumWeergave(datum: string | null): string {
  if (!datum) return '—'
  const d = new Date(datum)
  if (Number.isNaN(d.getTime())) return datum
  return d.toLocaleDateString('nl-NL', { day: '2-digit', month: '2-digit', year: 'numeric' })
}
