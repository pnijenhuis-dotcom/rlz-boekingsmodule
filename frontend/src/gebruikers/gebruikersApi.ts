import { apiJson, apiPostJson } from '../api/client'

/* Gebruikers & toegang (fase 3 modernisering 15-08, mockup #scherm-gebruikers) — dunne laag op
 * de bestaande auth-endpoints; alleen de gebruikerslijst en "opnieuw mailen" zijn nieuw. */

export interface GebruikerOverzichtDto {
  /** Half geactiveerd (casus Haci, 28-08): externe rol mét wachtwoord, zónder passkey — de
   * Herstel-link is de opruimroute. Nieuwe activaties zijn atomair en komen hier niet meer in. */
  half_geactiveerd: boolean
  id: string
  naam: string
  e_mail: string
  rol: string
  status: string
  administratie_ids: string[]
  heeft_totp: boolean
  aantal_passkeys: number
  open_uitnodiging_verloopt_op: string | null
  /** Open wachtwoord-herstel-link (feedbackronde 25-08 punt 7) — alleen externe app-gebruikers. */
  open_herstel_verloopt_op: string | null
  staande_goedkeuringen: number
  geblokkeerd_op: string | null
  geblokkeerd_door_naam: string | null
  /** Archivering (feedbackronde 26-08 punt 1, migratie 0075) — alleen bij status 'gearchiveerd'. */
  gearchiveerd_op?: string | null
  gearchiveerd_door_naam?: string | null
}

/** Open werk vóór archiveren: waarschuwing mét aantallen, geen blokkade. */
export interface OpenWerkDto {
  open_accorderingen: number
  weekstaten_ter_keuring: number
  eigen_open_weekstaten: number
}

export interface GebruikersLijstDto {
  gebruikers: GebruikerOverzichtDto[]
}

export interface UitnodigingResultaatDto {
  uitnodiging_id: string
  gebruiker_id: string
  token: string
  verloopt_op: string
  mail_verzonden: boolean
  mail_fout: string | null
  /** A4 (25-08): bewust niet gemaild ("uitnodiging later versturen") — geen fout. */
  mail_uitgesteld?: boolean
}

export interface ApparaatDto {
  id: string
  apparaat_naam: string | null
  is_dev_stub: boolean
  aangemaakt_op: string
  laatst_gebruikt_op: string | null
  ingetrokken_op: string | null
}

export const ROL_LABELS: Record<string, string> = {
  beheerder: 'Beheerder',
  boekhouding_projecten: 'Boekhouding + Projecten',
  boekhouding: 'Boekhouding',
  klant_accordeur: 'Klant-accordeur',
  zzper: "ZZP'er",
  uitvoerder: 'Uitvoerder',
  detacheerder: 'Detacheerder',
}

/** Veldrollen uren & meerwerk (migratie 0056) — externe app-rollen naast de accordeur. */
export const VELD_ROLLEN = ['zzper', 'uitvoerder', 'detacheerder'] as const
export function isVeldrol(rol: string): boolean {
  return (VELD_ROLLEN as readonly string[]).includes(rol)
}

export function rolLabel(rol: string): string {
  return ROL_LABELS[rol] ?? rol
}

/** Externe app-rollen (accordeur + veldrollen): passkey-cadans, herstel-link-doelgroep. */
export function isExterneAppRol(rol: string): boolean {
  return rol === 'klant_accordeur' || isVeldrol(rol)
}

/** Komt deze gebruiker in aanmerking voor "Herstel-link sturen" (server-side dezelfde poort:
 * externe rol + wachtwoord ooit gezet; geblokkeerd = eerst heractiveren)? */
export function kanHerstelLinkKrijgen(g: { rol: string; status: string }): boolean {
  return isExterneAppRol(g.rol) && (g.status === 'actief' || g.status === 'wacht_op_passkey')
}

export function formatVerloop(iso: string): string {
  const uren = Math.max(0, Math.round((new Date(iso).getTime() - Date.now()) / 3_600_000))
  return uren <= 1 ? 'verloopt binnen een uur' : `verloopt over ${uren} uur`
}

/** De link zoals de mail 'm draagt — terugval om handmatig te delen als de mail mislukt. */
export function herstelLinkUrl(token: string): string {
  return `${window.location.origin}/activeren?token=${encodeURIComponent(token)}&herstel=1`
}

/** Inclusief gearchiveerden (0075): het scherm filtert ze standaard weg en telt ze in het
 * filter "gearchiveerd (N)" per tab — één request, geen tweede lijst. */
export function haalGebruikersOp(): Promise<GebruikersLijstDto> {
  return apiJson<GebruikersLijstDto>('/auth/gebruikers?inclusief_gearchiveerd=true')
}

export function nodigUit(payload: {
  naam: string
  e_mail: string
  rol: string
  administratie_ids: string[]
  uitnodiging_later?: boolean
}): Promise<UitnodigingResultaatDto> {
  return apiPostJson<UitnodigingResultaatDto>('/auth/uitnodigingen', payload)
}

export interface EMailWijzigenResultaatDto {
  gebruiker_id: string
  oud_e_mail: string
  nieuw_e_mail: string
  uitnodiging_vernieuwd: boolean
  token: string | null
  verloopt_op: string | null
  mail_verzonden: boolean
  mail_fout: string | null
}

/** A5 (25-08, Beheerder-only): e-mailadres = login wijzigen; niet-geactiveerd account krijgt
 * direct een verse uitnodiging op het nieuwe adres. */
export function wijzigEMail(gebruikerId: string, eMail: string): Promise<EMailWijzigenResultaatDto> {
  return apiJson<EMailWijzigenResultaatDto>(`/auth/gebruikers/${gebruikerId}/e-mail`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ e_mail: eMail }),
  })
}

export function mailUitnodigingOpnieuw(gebruikerId: string): Promise<UitnodigingResultaatDto> {
  return apiPostJson<UitnodigingResultaatDto>(`/auth/gebruikers/${gebruikerId}/uitnodiging-opnieuw`, {})
}

/** "Herstel-link sturen" (feedbackronde 25-08 punt 7): eenmalige 72-uurs link voor een actieve
 * accordeur/veldwerker die zijn wachtwoord kwijt is — zelfde responsvorm als de uitnodiging. */
export function stuurHerstelLink(gebruikerId: string): Promise<UitnodigingResultaatDto> {
  return apiPostJson<UitnodigingResultaatDto>(`/auth/gebruikers/${gebruikerId}/herstel-link`, {})
}

export async function wijzigRol(gebruikerId: string, rol: string): Promise<void> {
  await apiJson(`/auth/gebruikers/${gebruikerId}/rol`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ rol }),
  })
}

export async function voegScopeToe(gebruikerId: string, administratieId: string): Promise<void> {
  await apiPostJson(`/auth/gebruikers/${gebruikerId}/scope`, { administratie_id: administratieId })
}

export async function verwijderScope(gebruikerId: string, administratieId: string): Promise<void> {
  await apiJson(`/auth/gebruikers/${gebruikerId}/scope/${administratieId}`, { method: 'DELETE' })
}

export async function blokkeerGebruiker(gebruikerId: string): Promise<void> {
  await apiPostJson(`/auth/gebruikers/${gebruikerId}/blokkeren`, {})
}

export async function heractiveerGebruiker(gebruikerId: string): Promise<void> {
  await apiPostJson(`/auth/gebruikers/${gebruikerId}/heractiveren`, {})
}

export async function archiveerGebruiker(gebruikerId: string): Promise<void> {
  await apiPostJson(`/auth/gebruikers/${gebruikerId}/archiveren`, {})
}

export async function dearchiveerGebruiker(gebruikerId: string): Promise<void> {
  await apiPostJson(`/auth/gebruikers/${gebruikerId}/dearchiveren`, {})
}

export function haalOpenWerkOp(gebruikerId: string): Promise<OpenWerkDto> {
  return apiJson<OpenWerkDto>(`/auth/gebruikers/${gebruikerId}/open-werk`)
}

export function haalApparatenVan(gebruikerId: string): Promise<{ apparaten: ApparaatDto[] }> {
  return apiJson<{ apparaten: ApparaatDto[] }>(`/auth/gebruikers/${gebruikerId}/apparaten`)
}

export async function trekApparaatIn(apparaatId: string): Promise<void> {
  await apiPostJson(`/auth/apparaten/${apparaatId}/intrekken`, {})
}
