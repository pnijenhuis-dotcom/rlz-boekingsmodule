// App-auth zonder passkey en TOTP (besluit Peter 08-09-2026, contract §4a/§4b/§5h): de API-glue van
// het ENIGE toegangspad van de accordeur-/veldwerker-app — uitnodiging → activatie op dít toestel
// (link óf 8-tekens activatiecode) → 5-cijferige toegangscode (lokaal anker, api/appSlot.ts).
// Toestel = factor 1 (langlevend apparaat-token achter het slot), toegangscode = factor 2 (bereikt de
// server nooit). De DTO-typen leven hier lokaal (§5h) — api/types.ts is van de kantoor-kant.

import { ApiError, BackendOnbereikbaarError, apiFetch, apiJson, kaleAuthFetch } from '../api/client'
import { haalCredentialId } from '../api/appSlot'

// ---- activatiecode --------------------------------------------------------------------------------

/** Alfabet van de activatiecode (contract §3): 32 tekens zonder 0/O/1/I. */
export const ACTIVATIECODE_ALFABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
export const ACTIVATIECODE_LENGTE = 8

/** Normalisatie (identiek aan de server): hoofdletters, spaties/koppeltekens en elk ander niet-
 * alfanumeriek teken weg. Wat overblijft wordt hooguit op de lengte afgekapt — de geldigheid toetst
 * de server. */
export function normaliseerActivatiecode(ruw: string): string {
  return ruw
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, '')
    .slice(0, ACTIVATIECODE_LENGTE)
}

/** Weergave `XXXX-XXXX` (ook van een halve invoer: `ABC` → `ABC`, `ABCDE` → `ABCD-E`). */
export function formatteerActivatiecode(genormaliseerd: string): string {
  if (genormaliseerd.length <= 4) return genormaliseerd
  return `${genormaliseerd.slice(0, 4)}-${genormaliseerd.slice(4)}`
}

export function isVolledigeActivatiecode(genormaliseerd: string): boolean {
  return genormaliseerd.length === ACTIVATIECODE_LENGTE
}

// ---- platform / toestel -----------------------------------------------------------------------------

export type AppPlatform = 'ios' | 'android' | 'web'

export function huidigPlatform(): AppPlatform {
  if (typeof window === 'undefined') return 'web'
  const cap = (window as { Capacitor?: { isNativePlatform?: () => boolean; getPlatform?: () => string } }).Capacitor
  if (!cap?.isNativePlatform?.()) return 'web'
  const p = cap.getPlatform?.()
  return p === 'ios' || p === 'android' ? p : 'web'
}

/** iPadOS (≥ 13) meldt zich in Safari én in de native webview als "Macintosh" (desktop-UA); het
 * enige onderscheid met een echte Mac is het aanraakscherm (`navigator.maxTouchPoints` > 1). */
export function isIpadOs(ua: string, maxTouchPoints: number): boolean {
  if (/iPad/.test(ua)) return true
  return /Macintosh/.test(ua) && maxTouchPoints > 1
}

/** Leesbaar toestel-label voor de kantoor-apparatenlijst (kill-switch) — puur informatief. */
export function apparaatNaam(ua: string = navigator.userAgent, maxTouchPoints: number = navigator.maxTouchPoints ?? 0): string {
  if (/iPhone/.test(ua)) return 'iPhone'
  if (isIpadOs(ua, maxTouchPoints)) return 'iPad'
  if (/Android/.test(ua)) return 'Android-toestel'
  if (/Macintosh/.test(ua)) return 'Mac'
  if (/Windows/.test(ua)) return 'Windows-pc'
  return 'Onbekend apparaat'
}

// ---- DTO's (lokaal, §5h) -------------------------------------------------------------------------------

export interface AppActiverenResponseDto {
  access_token: string
  token_type: string
  refresh_token: string
  /** b64url van het toestel-`credential_id` — de meldsleutel voor /auth/app-lock/* (5× fout, hulp). */
  apparaat_credential_id: string
  naam: string
  herstel: boolean
}

export interface UitnodigingInfoDto {
  /** Flow-etiket van de server ('app' voor app-rollen); de app leest alleen naam + herstel — een
   * kantoor-link wordt door /auth/app/activeren zelf met 400 geweigerd. */
  flow: string
  naam: string
  herstel: boolean
  verloopt_op: string
}

export interface AppConfigDto {
  dev_stub: boolean
  rp_id: string
  /** Store-links (blok F): null/afwezig zolang leeg — dan niets tonen (geen placeholders). */
  store_link_ios?: string | null
  store_link_android?: string | null
}

// ---- endpoints -----------------------------------------------------------------------------------------

export const GEEN_VERBINDING_MELDING = 'Geen verbinding — controleer je internet en probeer het opnieuw.'

async function alsJson<T>(resp: Response): Promise<T> {
  const body: unknown = await resp.json().catch(() => null)
  if (!resp.ok) {
    const detail =
      body && typeof body === 'object' && 'detail' in body ? String((body as { detail: unknown }).detail) : ''
    throw new ApiError(resp.status, detail || `Fout (${resp.status})`, detail || undefined)
  }
  return body as T
}

/** `POST /auth/app/activeren` (§4a, publiek): precies één van `token`/`activatiecode`. De
 * client-aankondiging (X-Native-Client / X-App-Slot) zet api/client.ts zelf in de slotmodus; het
 * token-paar komt in de body. 400/409/429 = ApiError mét de servertekst; offline =
 * BackendOnbereikbaarError (de schermen tonen dan GEEN_VERBINDING_MELDING). */
export async function activeerApp(invoer: {
  token?: string | null
  activatiecode?: string | null
}): Promise<AppActiverenResponseDto> {
  const resp = await kaleAuthFetch('/auth/app/activeren', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      token: invoer.token ?? null,
      activatiecode: invoer.activatiecode ? normaliseerActivatiecode(invoer.activatiecode) : null,
      toestel_naam: apparaatNaam().slice(0, 120),
      platform: huidigPlatform(),
    }),
  })
  return alsJson<AppActiverenResponseDto>(resp)
}

/** Leesbare fouttekst voor de activatieschermen (§5b): servertekst bij 400/409/429 (409 mét de hint
 * "nieuwe uitnodiging via het kantoor"), offline één vaste regel, alles anders generiek. Bewust geen
 * uitleg die het bestaan van een account verraadt (0022). */
export function activatieFoutmelding(err: unknown): string {
  if (err instanceof BackendOnbereikbaarError) return GEEN_VERBINDING_MELDING
  if (err instanceof ApiError) {
    if (err.status === 409) {
      // Hint alleen toevoegen als de servertekst 'm niet al draagt (de contract-tekst §4a eindigt er zelf mee).
      if (/nieuwe uitnodiging/i.test(err.message)) return err.message
      return `${err.message.replace(/\.?\s*$/, '.')} Vraag het kantoor om een nieuwe uitnodiging.`
    }
    if (err.status === 400 || err.status === 429) return err.message
    return err.message || 'Activeren is niet gelukt — probeer het opnieuw.'
  }
  return 'Activeren is niet gelukt — probeer het opnieuw.'
}

/** Publiek, op token: naam + herstel-vlag van de uitnodiging — verzilvert niets (§5b: het scherm
 * "Welkom {naam}, activeer dit toestel" vóór de gebruiker op de knop tikt). */
export function haalUitnodigingInfo(token: string): Promise<UitnodigingInfoDto> {
  return apiJson(`/auth/uitnodigingen/info?token=${encodeURIComponent(token)}`)
}

/** "Ik kom er niet uit — meld het kantoor" (audit + mail aan het kantoor). */
export async function meldActivatieProbleem(token: string): Promise<void> {
  const resp = await kaleAuthFetch('/auth/uitnodigingen/activatie-probleem', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token }),
  })
  await alsJson<unknown>(resp)
}

/** Store-links + dev-stub-vlag voor de web-fallback van een universal link (app niet
 * geïnstalleerd). Het endpoint-pad blijft historisch `/auth/webauthn/config` (contract §5e) —
 * de inhoud is app-config; de guard `appBundelGuard.test.ts` zondert dit ene pad uit. */
export function haalAppConfig(): Promise<AppConfigDto> {
  return apiJson('/auth/webauthn/config')
}

/** `POST /auth/app/toegangscode-gewijzigd` (§4b): audit-event zonder code; best-effort (offline =
 * stil, de lokale audit-regel in ⚙ Toegang blijft). */
export async function meldToegangscodeGewijzigd(): Promise<boolean> {
  try {
    const resp = await apiFetch('/auth/app/toegangscode-gewijzigd', { method: 'POST' })
    return resp.ok
  } catch {
    return false
  }
}

/** Meldt de uitsluiting (5× fout) of hulpvraag bij de server op het toestel-`credential_id`;
 * zonder bekend id (legacy toestel) blijft het bij de lokale wissing — fail-soft, nooit een fout
 * richting de gebruiker. */
export async function meldAppLock(pad: '/auth/app-lock/uitgesloten' | '/auth/app-lock/hulp'): Promise<void> {
  const credentialId = await haalCredentialId()
  if (!credentialId) return
  try {
    await kaleAuthFetch(pad, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ credential_id: credentialId }),
    })
  } catch {
    // Offline of backend plat: de lokale wissing is al gebeurd; de kill-switch-melding is
    // best-effort (het kantoor ziet het toestel sowieso bij de nieuwe-uitnodiging-vraag).
  }
}

// ---- lokale audit toegangscode (§5d) ---------------------------------------------------------------------

export const APPSLOT_AUDIT_SLEUTEL = 'appslot_audit'
const APPSLOT_AUDIT_MAX = 20

export interface AppSlotAuditRegel {
  tijdstip: string
  actie: 'toegangscode_gewijzigd'
}

export function leesAppSlotAudit(): AppSlotAuditRegel[] {
  try {
    const ruw = localStorage.getItem(APPSLOT_AUDIT_SLEUTEL)
    if (!ruw) return []
    const lijst: unknown = JSON.parse(ruw)
    if (!Array.isArray(lijst)) return []
    return lijst.filter(
      (r): r is AppSlotAuditRegel =>
        !!r && typeof r === 'object' && typeof (r as AppSlotAuditRegel).tijdstip === 'string' && typeof (r as AppSlotAuditRegel).actie === 'string',
    )
  } catch {
    return []
  }
}

/** Voegt een regel toe (nieuwste achteraan), hooguit APPSLOT_AUDIT_MAX bewaard. Puur lokaal, geen
 * code, geen PII. */
export function schrijfAppSlotAudit(actie: AppSlotAuditRegel['actie'], nu: Date = new Date()): void {
  try {
    const lijst = [...leesAppSlotAudit(), { tijdstip: nu.toISOString(), actie }].slice(-APPSLOT_AUDIT_MAX)
    localStorage.setItem(APPSLOT_AUDIT_SLEUTEL, JSON.stringify(lijst))
  } catch {
    // opslag geblokkeerd — de server-audit (§4b) is de echte bron
  }
}

/** "dd-mm HH:MM" van de laatste code-wijziging, of null. */
export function laatsteCodeWijziging(): string | null {
  const regels = leesAppSlotAudit().filter((r) => r.actie === 'toegangscode_gewijzigd')
  const laatste = regels[regels.length - 1]
  if (!laatste) return null
  const d = new Date(laatste.tijdstip)
  if (Number.isNaN(d.getTime())) return null
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getDate())}-${pad(d.getMonth() + 1)} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
