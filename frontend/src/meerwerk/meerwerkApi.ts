import { apiJson, apiPostJson } from '../api/client'

/* Uren & meerwerk — kantoorkant (fase 3, mockup meerwerk-kantoor.html). Alle paden onder
 * /uren/* (proxy-gedekt); het module-recht "Meerwerk & urenstaten" wordt server-side
 * afgedwongen — een 403 betekent hier: geen recht, verberg de module (toon-regel). */

export interface UrenStandDto {
  meerwerk_te_beoordelen: number
  meerwerk_nog_doorbelasten: number
  meerwerk_te_lang_niet_doorbelast: number
  urenstaten_wachten_op_keuring: number
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
