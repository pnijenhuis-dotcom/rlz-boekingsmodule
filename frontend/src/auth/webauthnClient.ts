// WebAuthn-browserglue voor de KANTOOR-web (platformbesluit 0020: passkeys eerste lijn, wachtwoord +
// TOTP terugval — ONGEWIJZIGD door het app-besluit van 08-09-2026). Verhuisd uit
// `accordeur/webauthnClient.ts` (run app-auth zonder passkey, contract §5e): de app-oppervlakte kent
// geen passkeys meer, de kantoor-web wél. De accordeur-only functies (setup-token-registratie,
// ontgrendel-opties, accordeur-login) zijn hier bewust niet meegekomen.
//
// De options-JSON komt byte-exact van py_webauthn (base64url-strings); we converteren hier
// handmatig van/naar ArrayBuffers i.p.v. PublicKeyCredential.parseCreationOptionsFromJSON
// (pas Safari 17.4+/Chrome 129+ — handmatig dekt ook oudere toestellen).

import { apiJson } from '../api/client'

export interface WebauthnConfigDto {
  dev_stub: boolean
  rp_id: string
  /** Store-links (blok F): null/afwezig zolang leeg — dan niets tonen (geen placeholders). */
  store_link_ios?: string | null
  store_link_android?: string | null
}

export function haalWebauthnConfig(): Promise<WebauthnConfigDto> {
  return apiJson('/auth/webauthn/config')
}

/** Secure-context-check: op een LAN-IP (telefoontest zonder https) bestaat de API niet —
 * de dev-stub (server-side gemarkeerd + vergrendeld buiten dev) is dan de enige route. */
export function webauthnBeschikbaar(): boolean {
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
 * JSON-geserialiseerde response terug zoals de backend die verwacht. */
export async function registreerPasskey(optiesJson: string): Promise<Record<string, unknown>> {
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
 * de OS-fallbacks zitten in WebAuthn zelf). */
export async function ondertekenAssertie(optiesJson: string): Promise<Record<string, unknown>> {
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

/** iPadOS (≥ 13) meldt zich in Safari als "Macintosh" (desktop-UA); het enige onderscheid met een
 * echte Mac is het aanraakscherm (`navigator.maxTouchPoints` > 1 — een Mac geeft 0). iPad-ronde
 * 29-08: zonder deze toets heette het apparaat "Mac" in de apparatenlijst. De uitnodigings-/
 * activatie-info-routes van de kantoor-web leven in `auth/uitnodigingInfoApi.ts` (agent D). */
export function isIpadOs(ua: string, maxTouchPoints: number): boolean {
  if (/iPad/.test(ua)) return true
  return /Macintosh/.test(ua) && maxTouchPoints > 1
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
