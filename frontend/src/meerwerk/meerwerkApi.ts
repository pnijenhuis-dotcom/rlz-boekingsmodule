import { apiJson, apiPostJson } from '../api/client'

/* Uren & meerwerk — kantoorkant (fase 3, mockup meerwerk-kantoor.html). Alle paden onder
 * /uren/* (proxy-gedekt); het module-recht "Meerwerk & urenstaten" wordt server-side
 * afgedwongen — een 403 betekent hier: geen recht, verberg de module (toon-regel). */

export interface UrenStandDto {
  meerwerk_te_beoordelen: number
  meerwerk_nog_doorbelasten: number
  meerwerk_te_lang_niet_doorbelast: number
  urenstaten_wachten_op_keuring: number
  // ZZP-dossier (A1, 25-08): werkvoorraad-signaal — veldwerkers met ontbrekend/verlopen/
  // binnenkort-verlopend document, documenten ter controle, geblokkeerde veldwerkers.
  dossier_veldwerkers_met_signaal: number
  dossier_ter_controle: number
  dossier_geblokkeerd: number
}

export interface MeerwerkDto {
  id: string
  administratie_id: string
  project_id: string
  project_naam: string | null
  omschrijving: string
  aantal: string
  eenheid: string
  datum_uitgevoerd: string
  in_opdracht_van: string | null
  heeft_foto: boolean
  foto_bestandsnaam: string | null
  gemeld_door_naam: string | null
  gemeld_op: string
  status: 'gemeld' | 'goedgekeurd' | 'doorbelast' | 'afgewezen'
  prijs_per_eenheid: string | null
  bedrag: string | null
  facturatie_notitie: string | null
  beoordeeld_op: string | null
  beoordeeld_door_naam: string | null
  afwijs_reden: string | null
  doorbelast_op: string | null
  verkoopfactuur_referentie: string | null
  vraag_tekst: string | null
  vraag_gesteld_op: string | null
  vraag_antwoord: string | null
  vraag_beantwoord_op: string | null
}

export interface StaffelRegelDto {
  id: string
  omschrijving: string
  eenheid: string
  prijs_per_eenheid: string
  verrekenbaar: boolean
  bron: string | null
}

export const EENHEID_LABELS: Record<string, string> = {
  m2: 'm²',
  m1: 'm¹',
  stuks: 'stuks',
  manuren: 'manuren',
}

export function eenheidLabel(eenheid: string): string {
  return EENHEID_LABELS[eenheid] ?? eenheid
}

export function haalUrenStand(administratieId: string): Promise<UrenStandDto> {
  return apiJson<UrenStandDto>(`/uren/kantoor/stand?administratie_id=${administratieId}`)
}

export function haalMeerwerkLijst(administratieId: string): Promise<MeerwerkDto[]> {
  return apiJson<MeerwerkDto[]>(`/uren/kantoor/meerwerk?administratie_id=${administratieId}`)
}

export function haalContractToets(administratieId: string, meerwerkId: string): Promise<StaffelRegelDto[]> {
  return apiJson<StaffelRegelDto[]>(`/uren/kantoor/meerwerk/${administratieId}/${meerwerkId}/contract-toets`)
}

export function keurMeerwerkGoed(
  administratieId: string,
  meerwerkId: string,
  payload: { prijs_per_eenheid: string; bedrag: string; facturatie_notitie: string | null },
): Promise<MeerwerkDto> {
  return apiPostJson<MeerwerkDto>(`/uren/kantoor/meerwerk/${administratieId}/${meerwerkId}/goedkeuren`, payload)
}

export function wijsMeerwerkAf(administratieId: string, meerwerkId: string, reden: string): Promise<MeerwerkDto> {
  return apiPostJson<MeerwerkDto>(`/uren/kantoor/meerwerk/${administratieId}/${meerwerkId}/afwijzen`, { reden })
}

export function markeerDoorbelast(
  administratieId: string,
  meerwerkId: string,
  verkoopfactuurReferentie: string,
): Promise<MeerwerkDto> {
  return apiPostJson<MeerwerkDto>(`/uren/kantoor/meerwerk/${administratieId}/${meerwerkId}/doorbelast`, {
    verkoopfactuur_referentie: verkoopfactuurReferentie,
  })
}

export function stelMeerwerkVraag(administratieId: string, meerwerkId: string, tekst: string): Promise<MeerwerkDto> {
  return apiPostJson<MeerwerkDto>(`/uren/kantoor/meerwerk/${administratieId}/${meerwerkId}/vraag`, { tekst })
}

export function meerwerkFotoUrl(administratieId: string, meerwerkId: string): string {
  return `/uren/meerwerk/${administratieId}/${meerwerkId}/foto`
}

/* --- beheer (Beheerder-only): veldgebruikers + koppelingen + module-recht --------------------- */

export interface ToewijzingDto {
  administratie_id: string
  administratie_naam: string | null
  project_id: string
  project_naam: string | null
}

export interface CrediteurKoppelingDto {
  administratie_id: string
  administratie_naam: string | null
  vendor_id: string
  vendor_naam: string | null
  uurtarief: string | null
  // Autoboek-opt-in per koppeling (factuurmatch fase 4, besluit 4 — default UIT).
  autoboeken_ingeschakeld: boolean
}

export interface VeldgebruikerDto {
  gebruiker_id: string
  naam: string
  e_mail: string
  rol: string
  status: string
  projecten: ToewijzingDto[]
  // uurtarief = het bureau-tarief per detacheerder↔zzp'er-koppeling (hoofdmechanisme match).
  zzpers: { gebruiker_id: string; naam: string; uurtarief: string | null }[]
  crediteuren: CrediteurKoppelingDto[]
  // Afwijkings-logging (besluit 22-08, kantoor-only): afkeuringen mét correctievoorstel +
  // opgetelde uren-delta (ingediend − goedgekeurd) — de veldwerker ziet dit nooit.
  uren_afwijking_aantal: number
  uren_afwijking_som: string
  // ZZP-dossier per administratie (A1): teller + signalen voor de dossier-badge.
  dossiers: DossierSamenvattingDto[]
}

/* --- ZZP-dossier per veldwerker (steigerbouw-run blok A, migratie 0072) ---------------------- */

export interface DossierSamenvattingDto {
  administratie_id: string
  administratie_naam: string | null
  aantal_verplicht: number
  aantal_aanwezig: number
  aantal_ontbrekend: number
  aantal_verlopen: number
  aantal_verloopt_binnenkort: number
  aantal_ter_controle: number
  herinneringen_teller: number
  geblokkeerd: boolean
  compleet: boolean
}

export type DossierDocumentStatus =
  | 'ontbreekt'
  | 'ter_controle'
  | 'afgewezen'
  | 'goedgekeurd'
  | 'verloopt_binnenkort'
  | 'verlopen'

export interface DossierDocumentDto {
  code: string
  naam: string
  verplicht: boolean
  geldig_tot_vereist: boolean
  bsn_gevoelig: boolean
  status: DossierDocumentStatus
  document_id: string | null
  geldig_tot: string | null
  verloopt_over_dagen: number | null
  bestandsnaam: string | null
  content_type: string | null
  geupload_op: string | null
  geupload_door_naam: string | null
  bron: 'kantoor' | 'app' | null
  afwijs_reden: string | null
  beoordeeld_door_naam: string | null
  beoordeeld_op: string | null
}

export interface DossierDto {
  administratie_id: string
  gebruiker_id: string
  gebruiker_naam: string
  documenten: DossierDocumentDto[]
  aantal_verplicht: number
  aantal_aanwezig: number
  aantal_ontbrekend: number
  aantal_verlopen: number
  aantal_verloopt_binnenkort: number
  aantal_ter_controle: number
  compleet: boolean
  compleet_incl_ter_controle: boolean
  herinneringen_teller: number
  herinneringen_max: number
  laatste_herinnering_op: string | null
  geblokkeerd: boolean
  geblokkeerd_op: string | null
  kan_herinneren_vandaag: boolean
  kvk_nummer: string | null
  btw_nummer: string | null
  kvk_naam: string | null
  kvk_plaats: string | null
  kvk_rechtsvorm: string | null
  kvk_bevestigd_op: string | null
  kvk_bevestigd_door_naam: string | null
  signalen: string[]
}

export interface DossierDocumenttypeDto {
  code: string
  naam: string
  verplicht: boolean
  geldig_tot_vereist: boolean
  bsn_gevoelig: boolean
  volgorde: number
  actief: boolean
}

export interface KvkLookupDto {
  kvk_nummer: string
  gevonden: boolean
  naam: string | null
  rechtsvorm: string | null
  adres: string | null
  postcode: string | null
  plaats: string | null
  uitgeschreven: boolean
  datum_einde: string | null
  testomgeving: boolean
}

export function haalDossier(administratieId: string, gebruikerId: string): Promise<DossierDto> {
  return apiJson<DossierDto>(`/uren/kantoor/dossier/${administratieId}/${gebruikerId}`)
}

export async function uploadDossierDocument(
  administratieId: string,
  gebruikerId: string,
  payload: { type_code: string; geldig_tot: string | null; bestand: File },
): Promise<DossierDto> {
  const form = new FormData()
  form.append('type_code', payload.type_code)
  if (payload.geldig_tot) form.append('geldig_tot', payload.geldig_tot)
  form.append('bestand', payload.bestand, payload.bestand.name)
  return apiJson<DossierDto>(`/uren/kantoor/dossier/${administratieId}/${gebruikerId}/upload`, {
    method: 'POST',
    body: form,
  })
}

export function beoordeelDossierDocument(
  administratieId: string,
  documentId: string,
  payload: { goedgekeurd: boolean; reden?: string | null },
): Promise<DossierDto> {
  return apiPostJson<DossierDto>(`/uren/kantoor/dossier/${administratieId}/documenten/${documentId}/beoordelen`, payload)
}

export function dossierBestandPad(administratieId: string, documentId: string): string {
  return `/uren/kantoor/dossier/${administratieId}/documenten/${documentId}/bestand`
}

export interface DossierHerinneringResultaatDto {
  gebruiker_id: string
  volgnummer: number
  kanaal: string
  verzonden_op: string
  geblokkeerd: boolean
}

export function herinnerDossier(administratieId: string, gebruikerId: string): Promise<DossierHerinneringResultaatDto> {
  return apiPostJson<DossierHerinneringResultaatDto>(`/uren/kantoor/dossier/${administratieId}/${gebruikerId}/herinneren`, {})
}

export function zoekKvk(kvkNummer: string): Promise<KvkLookupDto> {
  return apiJson<KvkLookupDto>(`/uren/kantoor/kvk/${encodeURIComponent(kvkNummer)}`)
}

export function bevestigBedrijfsgegevens(
  administratieId: string,
  gebruikerId: string,
  payload: { kvk_nummer: string | null; btw_nummer: string | null; naam: string | null; plaats: string | null; rechtsvorm: string | null },
): Promise<DossierDto> {
  return apiPostJson<DossierDto>(`/uren/kantoor/dossier/${administratieId}/${gebruikerId}/bedrijfsgegevens`, payload)
}

export function haalDossierDocumenttypen(
  administratieId: string,
): Promise<{ typen: DossierDocumenttypeDto[]; is_standaard: boolean }> {
  return apiJson(`/uren/beheer/dossier-documenttypen/${administratieId}`)
}

export function zetDossierDocumenttypen(
  administratieId: string,
  typen: DossierDocumenttypeDto[],
): Promise<{ typen: DossierDocumenttypeDto[]; is_standaard: boolean }> {
  return apiJson(`/uren/beheer/dossier-documenttypen/${administratieId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ typen }),
  })
}

export function haalVeldgebruikers(): Promise<VeldgebruikerDto[]> {
  return apiJson<VeldgebruikerDto[]>('/uren/beheer/veldgebruikers')
}

export async function koppelProject(payload: {
  administratie_id: string
  gebruiker_id: string
  project_id: string
}): Promise<void> {
  await apiPostJson('/uren/beheer/projectkoppelingen', payload)
}

export async function ontkoppelProject(payload: {
  administratie_id: string
  gebruiker_id: string
  project_id: string
}): Promise<void> {
  await apiPostJson('/uren/beheer/projectkoppelingen/verwijderen', payload)
}

export async function koppelDetacheerder(detacheerderIid: string, zzperId: string): Promise<void> {
  await apiPostJson('/uren/beheer/detacheerderkoppelingen', { detacheerder_id: detacheerderIid, zzper_id: zzperId })
}

export async function ontkoppelDetacheerder(detacheerderIid: string, zzperId: string): Promise<void> {
  await apiPostJson('/uren/beheer/detacheerderkoppelingen/verwijderen', {
    detacheerder_id: detacheerderIid,
    zzper_id: zzperId,
  })
}

/** Crediteur-koppeling + los ZZP-uurtarief (factuurmatch fase 3, upsert, Beheerder-only). */
export async function koppelVeldwerkerCrediteur(payload: {
  administratie_id: string
  gebruiker_id: string
  vendor_id: string
  uurtarief: string | null
}): Promise<void> {
  await apiPostJson('/uren/beheer/veldwerkercrediteuren', payload)
}

export async function ontkoppelVeldwerkerCrediteur(administratieId: string, gebruikerId: string): Promise<void> {
  await apiPostJson('/uren/beheer/veldwerkercrediteuren/verwijderen', {
    administratie_id: administratieId,
    gebruiker_id: gebruikerId,
  })
}

/** Autoboek-opt-in per veldwerker-koppeling (factuurmatch fase 4, Beheerder-only, default
 * UIT). Het slot blijft strikt: alleen een GROENE match incl. bedrag + alle bestaande poorten
 * van het inkoop-autoboekpad boekt automatisch. */
export async function zetVeldwerkerAutoboeken(
  administratieId: string,
  gebruikerId: string,
  ingeschakeld: boolean,
): Promise<void> {
  await apiPostJson('/uren/beheer/veldwerkercrediteuren/autoboeken', {
    administratie_id: administratieId,
    gebruiker_id: gebruikerId,
    ingeschakeld,
  })
}

/** Bureau-tarief op een bestaande detacheerder↔zzp'er-koppeling; null wist het tarief. */
export async function zetDetacheerderTarief(
  detacheerderIid: string,
  zzperId: string,
  uurtarief: string | null,
): Promise<void> {
  await apiPostJson('/uren/beheer/detacheerderkoppelingen/tarief', {
    detacheerder_id: detacheerderIid,
    zzper_id: zzperId,
    uurtarief,
  })
}

export function haalModuleRechtHouders(): Promise<{ gebruiker_ids: string[] }> {
  return apiJson<{ gebruiker_ids: string[] }>('/uren/beheer/module-recht')
}

export async function zetModuleRecht(gebruikerId: string, ingeschakeld: boolean): Promise<void> {
  await apiJson('/uren/beheer/module-recht', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ gebruiker_id: gebruikerId, ingeschakeld }),
  })
}
