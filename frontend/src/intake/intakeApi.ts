import { apiFetch, apiJson, apiPostJson } from '../api/client'

export interface SplitsSegmentDto {
  start_pagina: number
  eind_pagina: number
  tenaamstelling: string | null
  leverancier: string | null
  factuurnummer: string | null
  zekerheid: number
  /** Proportionele validatie (02-09): dít deel doorstond de paginabereik-toets niet — mens beslist. */
  ongeldig_reden?: string | null
}

export interface VerzamelbakItemDto {
  document_id: string
  bestandsnaam: string
  soort: string
  bron: string
  afzender_hint: string | null
  tenaamstelling: string | null
  suggestie_administratie_id: string | null
  suggestie_bron: string | null
  /** Intake-reden (02-09): technisch + leesbaar label — waaróm het document in de bak ligt. */
  reden?: string | null
  reden_label?: string | null
  aangemaakt_op: string
  splitsing_id: string | null
  splitsing_voorstel: SplitsSegmentDto[] | null
  /** Bundeling/samenvoegen (02-09): PDF-beeld naast een UBL-document; samengevoegde tweede rij; herkomst-mail. */
  beeld_bestandsnaam?: string | null
  samengevoegd_document_id?: string | null
  samengevoegd_bestandsnaam?: string | null
  intake_bericht_id?: string | null
  /** Zusje-signaal (02-09): de PDF/UBL van dezelfde factuur uit dezelfde mail is al toegewezen. */
  zusje_document_id?: string | null
  zusje_bestandsnaam?: string | null
  zusje_administratie_id?: string | null
}

export interface VerzamelbakLijstDto {
  items: VerzamelbakItemDto[]
}

export interface IntakeBijlageResultaatDto {
  bestandsnaam: string
  uitkomst: string
  document_id: string | null
  detail: string | null
}

export interface IntakeVerwerkResponseDto {
  bericht_id: string | null
  al_eerder_verwerkt: boolean
  bijlagen: IntakeBijlageResultaatDto[]
}

export function haalVerzamelbakOp(): Promise<VerzamelbakLijstDto> {
  return apiJson<VerzamelbakLijstDto>('/verzamelbak')
}

export interface VerzamelbakBestand {
  /** Object-URL van de blob (Authorization-header vereist — een kale <object src> kan niet). */
  url: string
  contentType: string
}

/** Bestand van een verzamelbak-document (D1, besluit 25-08): lazy — pas bij hover/klik. Default =
 * het BEELD (bij een gebundeld UBL+PDF-document de PDF); `vorm: 'data'` = het opgeslagen hoofdbestand. */
export async function haalVerzamelbakBestandBlob(documentId: string, vorm: 'beeld' | 'data' = 'beeld'): Promise<VerzamelbakBestand> {
  const resp = await apiFetch(`/verzamelbak/${documentId}/bestand${vorm === 'data' ? '?vorm=data' : ''}`)
  if (!resp.ok) throw new Error(`Bestand niet te laden (${resp.status})`)
  const blob = await resp.blob()
  return { url: URL.createObjectURL(blob), contentType: blob.type || resp.headers.get('content-type') || '' }
}

export function verwerkEml(bestand: File): Promise<IntakeVerwerkResponseDto> {
  const formData = new FormData()
  formData.append('bestand', bestand)
  return apiJson<IntakeVerwerkResponseDto>('/intake/eml', { method: 'POST', body: formData })
}

/** Los bestand (PDF/UBL/afbeelding) op de werkvoorraad-sleepzone — zelfde tenaamstelling-routing
 * als een mailbijlage (feedbackronde 25-08 deel 3 punt 2). Een .eml gaat via verwerkEml. */
export function verwerkLosBestand(bestand: File): Promise<IntakeBijlageResultaatDto> {
  const formData = new FormData()
  formData.append('bestand', bestand)
  return apiJson<IntakeBijlageResultaatDto>('/intake/bestand', { method: 'POST', body: formData })
}

/** Bestandstypen die de sleepzones accepteren (naast .eml op de werkvoorraad). */
export const UPLOAD_ACCEPT = '.pdf,.xml,.eml,.jpg,.jpeg,.png,.heic,.heif'

/** Antwoord van toewijzen / hoort-niet-bij-ons. `al_verwerkt` (avondrun 26-08): de actie was al
 * eerder gedaan (dubbelklik, retry ná time-out, collega) — géén fout, rustig melden. */
export interface VerzamelbakActieResultaatDto {
  document_id: string
  status: string
  al_verwerkt?: boolean
  melding?: string | null
}

export function wijsToe(documentId: string, administratieId: string): Promise<VerzamelbakActieResultaatDto> {
  return apiPostJson<VerzamelbakActieResultaatDto>(`/verzamelbak/${documentId}/toewijzen`, {
    administratie_id: administratieId,
  })
}

export function hoortNietBijOns(documentId: string, reden: string): Promise<VerzamelbakActieResultaatDto> {
  return apiPostJson<VerzamelbakActieResultaatDto>(`/verzamelbak/${documentId}/hoort-niet-bij-ons`, { reden })
}

export function bevestigSplitsing(
  splitsingId: string,
  delen: { start_pagina: number; eind_pagina: number; tenaamstelling: string | null }[],
): Promise<unknown> {
  return apiPostJson(`/intake/splitsingen/${splitsingId}/bevestigen`, { delen })
}

export function wijsSplitsingAf(splitsingId: string, reden: string | null): Promise<unknown> {
  return apiPostJson(`/intake/splitsingen/${splitsingId}/afwijzen`, { reden })
}

/** Leesbare kaart voor een losse UBL zonder beeld (02-09). */
export interface UblSamenvattingDto {
  leverancier: string | null
  afnemer: string | null
  factuurnummer: string | null
  factuurdatum: string | null
  totaal_excl: string | null
  totaal_incl: string | null
  valuta: string | null
  regelaantal: number
  regels: { omschrijving: string | null; netto_bedrag: string | null; aantal: string | null }[]
}

export function haalUblSamenvatting(documentId: string): Promise<UblSamenvattingDto> {
  return apiJson<UblSamenvattingDto>(`/verzamelbak/${documentId}/ubl-samenvatting`)
}

export interface SamenvoegResultaatDto {
  document_id: string
  samengevoegd_document_id: string
  beeld_bestandsnaam: string
  waarschuwingen: string[]
}

/** Handmatig samenvoegen (toevoeging Peter 02-09): de mens kiest het leidende bestand; 409 mét
 * code `zelfde_type` als twee UBL's/PDF's zonder bevestiging. */
export function voegSamen(leidendId: string, anderId: string, bevestigZelfdeType = false): Promise<SamenvoegResultaatDto> {
  return apiPostJson<SamenvoegResultaatDto>('/verzamelbak/samenvoegen', {
    leidend_document_id: leidendId,
    ander_document_id: anderId,
    bevestig_zelfde_type: bevestigZelfdeType,
  })
}

export function maakSamenvoegenOngedaan(documentId: string): Promise<{ document_id: string; teruggezet_document_id: string }> {
  return apiPostJson(`/verzamelbak/${documentId}/samenvoegen-ongedaan`, {})
}

/** Bulk (blok B 02-09, casus IC-stapel): één administratie of één reden voor de hele selectie —
 * server-side een orkestratie over de per-rij-routes; uitkomst per rij, altijd 200. */
export interface BulkRijUitkomstDto {
  document_id: string
  bestandsnaam: string | null
  uitkomst: 'verwerkt' | 'al_verwerkt' | 'fout'
  status: string | null
  reden: string | null
}

export interface BulkVerzamelbakResponseDto {
  uitkomsten: BulkRijUitkomstDto[]
  verwerkt: number
  al_verwerkt: number
  fout: number
}

export function bulkWijsToe(documentIds: string[], administratieId: string): Promise<BulkVerzamelbakResponseDto> {
  return apiPostJson<BulkVerzamelbakResponseDto>('/verzamelbak/bulk-toewijzen', {
    document_ids: documentIds,
    administratie_id: administratieId,
  })
}

export function bulkHoortNietBijOns(documentIds: string[], reden: string): Promise<BulkVerzamelbakResponseDto> {
  return apiPostJson<BulkVerzamelbakResponseDto>('/verzamelbak/bulk-hoort-niet-bij-ons', { document_ids: documentIds, reden })
}
