// Access-token leeft alleen in het geheugen van dit module — NOOIT in localStorage (OWASP,
// zelfde reden als de httpOnly-refresh-cookie aan de backend-kant, zie Auth-0010-b). Een
// paginaherlaad verliest 'm bewust; verversSessie() haalt 'm dan terug via de refresh-cookie.
let accessToken: string | null = null
let sessieVerlopenHandler: (() => void) | null = null

export function setAccessToken(token: string | null): void {
  accessToken = token
}

export function getAccessToken(): string | null {
  return accessToken
}

export function setSessieVerlopenHandler(handler: (() => void) | null): void {
  sessieVerlopenHandler = handler
}

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export const BACKEND_ONBEREIKBAAR_MELDING =
  'De backend is momenteel niet bereikbaar. Probeer het straks opnieuw, of neem contact op met de beheerder ' +
  'als dit blijft gebeuren.'

/** 502/503/504 = de (dev-)proxy of loadbalancer kon de backend niet bereiken, geen echte
 * applicatiefout — die twee moeten niet hetzelfde kale statusteksten ("Bad Gateway") tonen. */
function isBackendOnbereikbaarStatus(status: number): boolean {
  return status === 502 || status === 503 || status === 504
}

/** Netwerkfout (bv. backend echt plat, geen proxy-response) én de 502/503/504-gatewaystatus delen
 * dezelfde gebruikersmelding — het onderscheid tussen "geen verbinding" en "verbinding maar geen
 * backend erachter" is voor de eindgebruiker niet relevant. */
export class BackendOnbereikbaarError extends ApiError {
  constructor() {
    super(0, BACKEND_ONBEREIKBAAR_MELDING)
  }
}

async function ruweFetch(pad: string, init: RequestInit): Promise<Response> {
  const headers = new Headers(init.headers)
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
  try {
    return await fetch(pad, { ...init, headers, credentials: 'include' })
  } catch {
    // fetch() gooit alleen bij een echte netwerkfout (geen enkele HTTP-response mogelijk) —
    // een 502 van de dev-proxy komt hier niet binnen, dat is een gewone (niet-ok) Response.
    throw new BackendOnbereikbaarError()
  }
}

/** Stille refresh via de httpOnly-cookie — geen TOTP nodig zolang de cookie geldig is. Gooit
 * BackendOnbereikbaarError door (in plaats van 'm als gewone mislukte refresh te behandelen) zodat
 * de aanroeper (AuthContext, bij het laden van de app) dat kan onderscheiden van "gewoon niet
 * ingelogd" en een nette melding kan tonen i.p.v. stil op het login-scherm te belanden. */
export async function verversSessie(): Promise<boolean> {
  const resp = await ruweFetch('/auth/token/vernieuwen', { method: 'POST' })
  if (isBackendOnbereikbaarStatus(resp.status)) throw new BackendOnbereikbaarError()
  if (!resp.ok) return false
  const body = (await resp.json()) as { access_token: string }
  accessToken = body.access_token
  return true
}

const GEEN_RETRY_PADEN = new Set(['/auth/login', '/auth/token/vernieuwen', '/auth/logout'])

/** Eén automatische refresh-poging bij een 401 — daarna geeft de aanroeper het zelf op. */
export async function apiFetch(pad: string, init: RequestInit = {}): Promise<Response> {
  let resp = await ruweFetch(pad, init)
  if (isBackendOnbereikbaarStatus(resp.status)) throw new BackendOnbereikbaarError()
  if (resp.status === 401 && !GEEN_RETRY_PADEN.has(pad)) {
    const ververst = await verversSessie()
    if (ververst) {
      resp = await ruweFetch(pad, init)
      if (isBackendOnbereikbaarStatus(resp.status)) throw new BackendOnbereikbaarError()
    } else {
      accessToken = null
      sessieVerlopenHandler?.()
    }
  }
  return resp
}

async function foutmelding(resp: Response): Promise<string> {
  try {
    const body: unknown = await resp.json()
    if (body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string') {
      return body.detail
    }
  } catch {
    // geen JSON-body — val terug op de statustekst
  }
  return resp.statusText || `Fout (${resp.status})`
}

export async function apiJson<T>(pad: string, init: RequestInit = {}): Promise<T> {
  const resp = await apiFetch(pad, init)
  if (!resp.ok) throw new ApiError(resp.status, await foutmelding(resp))
  if (resp.status === 204) return undefined as T
  return (await resp.json()) as T
}

export function apiPostJson<T>(pad: string, payload: unknown): Promise<T> {
  return apiJson<T>(pad, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

/** Decodeert alleen de payload, zonder de handtekening te verifiëren — puur voor UI-weergave
 * (welke rol tonen we in de sidebar). Autorisatie zelf wordt altijd server-side afgedwongen. */
export function decodeerJwtPayload(token: string): Record<string, unknown> | null {
  const delen = token.split('.')
  if (delen.length !== 3) return null
  try {
    const json = atob(delen[1].replace(/-/g, '+').replace(/_/g, '/'))
    return JSON.parse(json) as Record<string, unknown>
  } catch {
    return null
  }
}
