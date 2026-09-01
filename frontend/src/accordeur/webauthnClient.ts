// WebAuthn-browserglue voor de accordeur-PWA (blok 1/2, besluit auth-cadans 2026-08-11).
// De options-JSON komt byte-exact van py_webauthn (base64url-strings); we converteren hier
// handmatig van/naar ArrayBuffers i.p.v. PublicKeyCredential.parseCreationOptionsFromJSON
// (pas Safari 17.4+/Chrome 129+ — handmatig dekt ook oudere toestellen).
//
// NATIVE SEAM (store-app fase 2, 2026-08-17): in de Capacitor-schil bestaat
// navigator.credentials niet (WKWebView heeft geen WebAuthn — verkenning/17). Draait de app
// native, dan lopen create/get via de NatievePasskey-plugin (ASAuthorizationController /
// Credential Manager) — zelfde options-JSON erin, zelfde credential-JSON eruit, dus de
// backend (py_webauthn) én de schermen merken het verschil niet. rp_id blijft de apex
// (besluit 0022): bestaande passkeys van PWA-gebruikers blijven in de native app geldig.

import { ApiError, apiJson, apiPostJson, kaleAuthFetch } from '../api/client'
import type { TokenPaarResponseDto } from '../api/types'
import { natievePasskeyPlugin } from './nativePasskey'

export interface WebauthnConfigDto {
  dev_stub: boolean
  rp_id: string
  /** Store-links (blok F): null/afwezig zolang leeg — dan niets tonen (geen placeholders). */
  store_link_ios?: string | null
  store_link_android?: string | null
}

export interface AccordeurLoginResponseDto {
  passkey_setup_token: string
  heeft_passkeys: boolean
}

export function haalWebauthnConfig(): Promise<WebauthnConfigDto> {
  return apiJson('/auth/webauthn/config')
}

/** Secure-context-check: op een LAN-IP (telefoontest zonder https) bestaat de API niet —
 * de dev-stub (server-side gemarkeerd + vergrendeld buiten dev) is dan de enige route.
 * In de native schil is de plugin de beschikbaarheidsbron (de webview heeft geen WebAuthn). */
export function webauthnBeschikbaar(): boolean {
  if (natievePasskeyPlugin() !== null) return true
  return typeof window !== 'undefined' && 'PublicKeyCredential' in window && window.isSecureContext
}

function b64urlNaarBuffer(s: string): ArrayBuffer {
  const b64 = s.replace(/-/g, '+').replace(/_/g, '/')
  const bin = atob(b64 + '='.repeat((4 - (b64.length % 4)) % 4))
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  return bytes.buffer
}

function bufferNaarB64url(b: ArrayBuffer): string {
  const bytes = new Uint8Array(b)
  let bin = ''
  for (const byte of bytes) bin += String.fromCharCode(byte)
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

interface CredentialDescriptorJson {
  id: string
  type: string
  transports?: string[]
}

/** navigator.credentials.create() op py_webauthn-registratie-options; geeft de
 * JSON-geserialiseerde response terug zoals de backend die verwacht. Native: via de plugin,
 * die exact dezelfde credential-JSON teruggeeft. */
export async function registreerPasskey(optiesJson: string): Promise<Record<string, unknown>> {
  const plugin = natievePasskeyPlugin()
  if (plugin) {
    const { credentialJson } = await plugin.registreer({ optiesJson })
    return JSON.parse(credentialJson) as Record<string, unknown>
  }
  const opties = JSON.parse(optiesJson) as {
    challenge: string
    rp: PublicKeyCredentialRpEntity
    user: { id: string; name: string; displayName: string }
    pubKeyCredParams: PublicKeyCredentialParameters[]
    timeout?: number
    excludeCredentials?: CredentialDescriptorJson[]
    authenticatorSelection?: AuthenticatorSelectionCriteria
    attestation?: AttestationConveyancePreference
  }
  const credential = (await navigator.credentials.create({
    publicKey: {
      ...opties,
      challenge: b64urlNaarBuffer(opties.challenge),
      user: { ...opties.user, id: b64urlNaarBuffer(opties.user.id) },
      excludeCredentials: (opties.excludeCredentials ?? []).map((c) => ({
        ...c,
        id: b64urlNaarBuffer(c.id),
        type: 'public-key' as const,
        transports: c.transports as AuthenticatorTransport[] | undefined,
      })),
    },
  })) as PublicKeyCredential | null
  if (!credential) throw new Error('Passkey-registratie geannuleerd')
  const response = credential.response as AuthenticatorAttestationResponse
  return {
    id: credential.id,
    rawId: bufferNaarB64url(credential.rawId),
    type: credential.type,
    clientExtensionResults: credential.getClientExtensionResults(),
    response: {
      clientDataJSON: bufferNaarB64url(response.clientDataJSON),
      attestationObject: bufferNaarB64url(response.attestationObject),
      transports: typeof response.getTransports === 'function' ? response.getTransports() : [],
    },
  }
}

/** navigator.credentials.get() op py_webauthn-assertie-options (Face ID/Touch ID/pincode —
 * de OS-fallbacks zitten in WebAuthn zelf). Native: via de plugin. */
export async function ondertekenAssertie(optiesJson: string): Promise<Record<string, unknown>> {
  const plugin = natievePasskeyPlugin()
  if (plugin) {
    const { credentialJson } = await plugin.onderteken({ optiesJson })
    return JSON.parse(credentialJson) as Record<string, unknown>
  }
  const opties = JSON.parse(optiesJson) as {
    challenge: string
    timeout?: number
    rpId?: string
    allowCredentials?: CredentialDescriptorJson[]
    userVerification?: UserVerificationRequirement
  }
  const credential = (await navigator.credentials.get({
    publicKey: {
      ...opties,
      challenge: b64urlNaarBuffer(opties.challenge),
      allowCredentials: (opties.allowCredentials ?? []).map((c) => ({
        ...c,
        id: b64urlNaarBuffer(c.id),
        type: 'public-key' as const,
        transports: c.transports as AuthenticatorTransport[] | undefined,
      })),
    },
  })) as PublicKeyCredential | null
  if (!credential) throw new Error('Passkey-verificatie geannuleerd')
  const response = credential.response as AuthenticatorAssertionResponse
  return {
    id: credential.id,
    rawId: bufferNaarB64url(credential.rawId),
    type: credential.type,
    // Cross-device-detectie (kantoor-banner 28-08): 'platform' | 'cross-platform' | undefined.
    // `ondertekenAssertieMetMeta` haalt 'm er weer uit vóór het naar de backend gaat.
    authenticatorAttachment: (credential as unknown as { authenticatorAttachment?: string }).authenticatorAttachment,
    clientExtensionResults: credential.getClientExtensionResults(),
    response: {
      clientDataJSON: bufferNaarB64url(response.clientDataJSON),
      authenticatorData: bufferNaarB64url(response.authenticatorData),
      signature: bufferNaarB64url(response.signature),
      userHandle: response.userHandle ? bufferNaarB64url(response.userHandle) : null,
    },
  }
}

/** Leesbaar apparaat-label voor de kantoor-apparatenlijst (kill-switch) — puur informatief. */
export function apparaatNaam(ua: string = navigator.userAgent, maxTouchPoints: number = navigator.maxTouchPoints ?? 0): string {
  if (/iPhone/.test(ua)) return 'iPhone'
  if (isIpadOs(ua, maxTouchPoints)) return 'iPad'
  if (/Android/.test(ua)) return 'Android-toestel'
  if (/Macintosh/.test(ua)) return 'Mac'
  if (/Windows/.test(ua)) return 'Windows-pc'
  return 'Onbekend apparaat'
}

// ---- auth-endpoints (accordeur-cadans) ----------------------------------------------------------

export function accordeurLogin(eMail: string, wachtwoord: string): Promise<AccordeurLoginResponseDto> {
  return apiPostJson('/auth/accordeur/login', { e_mail: eMail, wachtwoord })
}

/** Via kaleAuthFetch (niet apiFetch): het setup-token vervangt hier het access-token, en een
 * niet-antwoordende backend moet een nette BackendOnbereikbaarError worden i.p.v. een
 * eeuwig hangende submit (kliktest 2026-08-12). */
function metSetupToken(pad: string, token: string, body: unknown): Promise<Response> {
  return kaleAuthFetch(pad, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  })
}

async function alsJson<T>(resp: Response): Promise<T> {
  const body: unknown = await resp.json().catch(() => null)
  if (!resp.ok) {
    const detail =
      body && typeof body === 'object' && 'detail' in body ? String((body as { detail: unknown }).detail) : ''
    // ApiError mét status: de activeringsflow onderscheidt 401 (setup-token verlopen → terug
    // naar de wachtwoordstap) van 400 (registratie mislukt → foutscherm).
    throw new ApiError(resp.status, detail || `Fout (${resp.status})`, detail || undefined)
  }
  return body as T
}

export async function registratieOpties(setupToken: string): Promise<string> {
  const resp = await metSetupToken('/auth/webauthn/registratie/opties', setupToken, {})
  return (await alsJson<{ opties: string }>(resp)).opties
}

export async function registratieVoltooien(
  setupToken: string,
  payload: { credential?: Record<string, unknown>; apparaat_naam: string; dev_stub?: boolean },
): Promise<TokenPaarResponseDto> {
  const resp = await metSetupToken('/auth/webauthn/registratie/voltooien', setupToken, payload)
  return alsJson<TokenPaarResponseDto>(resp)
}

export async function loginOpties(setupToken: string): Promise<string> {
  const resp = await metSetupToken('/auth/webauthn/login/opties', setupToken, {})
  return (await alsJson<{ opties: string }>(resp)).opties
}

export async function loginVoltooien(
  setupToken: string,
  payload: { credential?: Record<string, unknown>; dev_stub?: boolean },
): Promise<TokenPaarResponseDto> {
  const resp = await metSetupToken('/auth/webauthn/login/voltooien', setupToken, payload)
  return alsJson<TokenPaarResponseDto>(resp)
}

// ---- her-login zonder wachtwoord (pincode-flow 31-08) --------------------------------------------

/** e-mail → assertion-options voor externe app-rollen. ApiError 409 = geen bruikbare passkey
 * (de client valt terug op de wachtwoordflow of verwijst naar een verse kantoor-link). */
export async function accordeurPasskeyLoginOpties(eMail: string): Promise<{ opties: string | null; dev_stub: boolean }> {
  const resp = await kaleAuthFetch('/auth/accordeur/passkey-login/opties', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ e_mail: eMail }),
  })
  return alsJson<{ opties: string | null; dev_stub: boolean }>(resp)
}

export async function accordeurPasskeyLoginVoltooien(
  eMail: string,
  payload: { credential?: Record<string, unknown>; dev_stub?: boolean },
): Promise<TokenPaarResponseDto> {
  const resp = await kaleAuthFetch('/auth/accordeur/passkey-login/voltooien', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ e_mail: eMail, ...payload }),
  })
  return alsJson<TokenPaarResponseDto>(resp)
}

/** App-opening (bekend apparaat): assertion-options op de refresh-cookie. 401 = sessie
 * verlopen (ná 7 dagen) → volledige login; 409 = geen passkeys → registratie. */
export async function ontgrendelOpties(): Promise<{ status: number; opties: string | null; detail: string }> {
  const resp = await kaleAuthFetch('/auth/token/vernieuwen/ontgrendel-opties', { method: 'POST' })
  const body: unknown = await resp.json().catch(() => null)
  if (!resp.ok) {
    const detail =
      body && typeof body === 'object' && 'detail' in body ? String((body as { detail: unknown }).detail) : ''
    return { status: resp.status, opties: null, detail }
  }
  return { status: resp.status, opties: (body as { opties: string }).opties, detail: '' }
}

export async function ontgrendelen(payload: {
  credential?: Record<string, unknown>
  dev_stub?: boolean
}): Promise<TokenPaarResponseDto> {
  const resp = await kaleAuthFetch('/auth/token/vernieuwen/ontgrendelen', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return alsJson<TokenPaarResponseDto>(resp)
}

// --- Mobiel-first activatie externe rollen (besluit Peter 28-08, mockup activatie-mobiel.html) --

/** Grove apparaatklasse uit de user-agent — uitsluitend als VANGNET naast de
 * WebAuthn-capability-check (mockup-beslispunt 1). */
export function isMobielUserAgent(ua: string = navigator.userAgent, maxTouchPoints: number = navigator.maxTouchPoints ?? 0): boolean {
  return /iPhone|iPad|iPod|Android/.test(ua) || isIpadOs(ua, maxTouchPoints)
}

/** iPadOS (≥ 13) meldt zich in Safari én in de native webview als "Macintosh" (desktop-UA);
 * het enige onderscheid met een echte Mac is het aanraakscherm (`navigator.maxTouchPoints` > 1 —
 * een Mac geeft 0). iPad-ronde 29-08: zonder deze toets kreeg een iPad-gebruiker op de
 * activatielink het desktop-stop-scherm en heette het apparaat "Mac" in de apparatenlijst. */
export function isIpadOs(ua: string, maxTouchPoints: number): boolean {
  if (/iPad/.test(ua)) return true
  return /Macintosh/.test(ua) && maxTouchPoints > 1
}

/** `PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable()` — true/false, of null
 * als de browser de vraag niet kan beantwoorden (geen API, geen secure context, exception).
 * Null = twijfel; de beslisfunctie hieronder behandelt twijfel als "stop". */
export async function platformAuthenticatorBeschikbaar(): Promise<boolean | null> {
  try {
    if (typeof window === 'undefined' || !('PublicKeyCredential' in window)) return null
    const vraag = (window.PublicKeyCredential as unknown as Record<string, unknown>)
      .isUserVerifyingPlatformAuthenticatorAvailable
    if (typeof vraag !== 'function') return null
    const uitkomst: unknown = await (vraag as () => Promise<unknown>)()
    return uitkomst === true
  } catch {
    return null
  }
}

export interface ActivatieApparaatToets {
  /** Native schil (Capacitor) — de passkey-plugin is de bron; altijd doorgaan. */
  native: boolean
  mobielUa: boolean
  platformAuthenticator: boolean | null
  /** Dev-stub actief (LAN-kliktest zonder https): de stub vervangt de biometrie. */
  devStub: boolean
}

/** Beslisregel activatielink (fail-safe richting telefoon): een externe activatie loopt alleen
 * door op een apparaat dat een platform-authenticator HEEFT en mobiel IS; elke twijfel
 * (onbekende capability, desktop-UA) = stop-scherm mét QR — de link verzilvert dáár niets.
 * Puur, zodat de regel los van de browser getest wordt. */
export function activatieOpDitApparaat(toets: ActivatieApparaatToets): 'doorgaan' | 'stop' {
  if (toets.native) return 'doorgaan'
  if (toets.devStub) return 'doorgaan'
  if (!toets.mobielUa) return 'stop'
  return toets.platformAuthenticator === true ? 'doorgaan' : 'stop'
}

/** Voert de toets uit op dít apparaat (capability + UA-vangnet + native + dev-stub). */
export async function toetsActivatieApparaat(devStub: boolean): Promise<'doorgaan' | 'stop'> {
  return activatieOpDitApparaat({
    native: natievePasskeyPlugin() !== null,
    mobielUa: isMobielUserAgent(),
    platformAuthenticator: await platformAuthenticatorBeschikbaar(),
    devStub,
  })
}

export interface UitnodigingInfoDto {
  flow: 'passkey' | 'totp'
  naam: string
  herstel: boolean
  verloopt_op: string
}

/** Publiek, op token: welke activatieflow hoort bij deze link — verzilvert niets. */
export function haalUitnodigingInfo(token: string): Promise<UitnodigingInfoDto> {
  return apiJson(`/auth/uitnodigingen/info?token=${encodeURIComponent(token)}`)
}

/** Foutscherm stap 2: "Ik kom er niet uit — meld het kantoor" (audit + mail aan het kantoor). */
export async function meldActivatieProbleem(token: string): Promise<void> {
  await apiPostJson<unknown>('/auth/uitnodigingen/activatie-probleem', { token })
}

export interface AssertieMetMeta {
  credential: Record<string, unknown>
  /** true = de passkey kwam van een ánder apparaat (QR/cross-device, `authenticatorAttachment`
   * 'cross-platform') — het moment voor de kantoor-banner "Passkey toevoegen op dit apparaat?". */
  crossDevice: boolean
}

/** Als `ondertekenAssertie`, mét de attachment-meta van de ceremonie. De backend krijgt alleen
 * het credential-object; de meta blijft client-side. */
export async function ondertekenAssertieMetMeta(optiesJson: string): Promise<AssertieMetMeta> {
  const credential = await ondertekenAssertie(optiesJson)
  const attachment = credential.authenticatorAttachment
  delete credential.authenticatorAttachment
  return { credential, crossDevice: attachment === 'cross-platform' }
}
