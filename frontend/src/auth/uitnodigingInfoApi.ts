import { apiJson } from '../api/client'

/* Publieke uitnodigingsinfo + app-config voor de kantoor-web-activatiepagina (`/activeren`).
 * App-auth zonder passkey (besluit Peter 08-09): de accordeur-/veldwerker-app kent nog één toegangspad
 * (uitnodiging → activatie op het toestel → toegangscode). De kantoor-webapp hoeft daar niets van te weten
 * behalve: "is dit een app-link of een kantoor-link?" — dat leeft hier, los van de app-bundel. */

export interface UitnodigingInfoDto {
  /** 'app' = externe app-rol (accordeur/veldwerker; was 'passkey' — oude waarde tijdelijk geaccepteerd voor
   * een lopende link), 'totp' = kantoor-rol (wachtwoord + TOTP hieronder). */
  flow: 'app' | 'passkey' | 'totp'
  naam: string
  herstel: boolean
  verloopt_op: string
}

/** Publiek, op token: welke activatieflow hoort bij deze link — verzilvert niets. */
export function haalUitnodigingInfo(token: string): Promise<UitnodigingInfoDto> {
  return apiJson(`/auth/uitnodigingen/info?token=${encodeURIComponent(token)}`)
}

export function isAppFlow(flow: UitnodigingInfoDto['flow']): boolean {
  return flow === 'app' || flow === 'passkey'
}

export interface AppConfigDto {
  dev_stub: boolean
  rp_id: string
  /** Store-links (blok F): null/afwezig zolang leeg — dan niets tonen (geen placeholders). */
  store_link_ios?: string | null
  store_link_android?: string | null
}

/** Endpoint-pad blijft `/auth/webauthn/config` (contract §5e) — de inhoud is inmiddels app-config (store-links). */
export function haalAppConfig(): Promise<AppConfigDto> {
  return apiJson('/auth/webauthn/config')
}

/** iPadOS (≥ 13) meldt zich als "Macintosh"; het onderscheid met een Mac is het aanraakscherm
 * (`navigator.maxTouchPoints` > 1). Kopie van de regel uit de iPad-ronde 29-08. */
export function isIpadOs(ua: string, maxTouchPoints: number): boolean {
  return /Macintosh/.test(ua) && maxTouchPoints > 1
}

export function isMobielUserAgent(
  ua: string = navigator.userAgent,
  maxTouchPoints: number = navigator.maxTouchPoints ?? 0,
): boolean {
  return /iPhone|iPad|iPod|Android/.test(ua) || isIpadOs(ua, maxTouchPoints)
}

/** Beslisregel activatielink zonder passkey (fail-safe richting telefoon): een app-link loopt door naar de
 * app-flow op een mobiel apparaat (dáár staat de app of de PWA); op een desktop = stop-scherm mét QR en de
 * activatiecode-hint — de link verzilvert dáár niets. Geen capability-toets meer: er is niets te toetsen. */
export function activatieOpDitApparaat(mobielUa: boolean): 'doorgaan' | 'stop' {
  return mobielUa ? 'doorgaan' : 'stop'
}
