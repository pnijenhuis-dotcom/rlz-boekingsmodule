// WebAuthn-browserglue voor de accordeur-PWA (blok 1/2, besluit auth-cadans 2026-08-11).
// De options-JSON komt byte-exact van py_webauthn (base64url-strings); we converteren hier
// handmatig van/naar ArrayBuffers i.p.v. PublicKeyCredential.parseCreationOptionsFromJSON
// (pas Safari 17.4+/Chrome 129+ — handmatig dekt ook oudere toestellen).

import { apiJson, apiPostJson, kaleAuthFetch } from '../api/client'
import type { TokenPaarResponseDto } from '../api/types'

export interface WebauthnConfigDto {
  dev_stub: boolean
  rp_id: string
}

export interface AccordeurLoginResponseDto {
  passkey_setup_token: string
  heeft_passkeys: boolean
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
export function apparaatNaam(): string {
  const ua = navigator.userAgent
  if (/iPhone/.test(ua)) return 'iPhone'
  if (/iPad/.test(ua)) return 'iPad'
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
    throw new Error(detail || `Fout (${resp.status})`)
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
