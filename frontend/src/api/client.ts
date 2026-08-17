// Access-token leeft alleen in het geheugen van dit module — NOOIT in localStorage (OWASP,
// zelfde reden als de httpOnly-refresh-cookie aan de backend-kant, zie Auth-0010-b). Een
// paginaherlaad verliest 'm bewust; verversSessie() haalt 'm dan terug via de refresh-cookie
// (web) of het Keychain/Keystore-refresh-token via de X-Refresh-Token-header (native schil,
// fase 4 — de SameSite-cookie werkt niet in de Capacitor-webview).
import { bewaarNatiefRefreshToken, haalNatiefRefreshToken, natieveSessieBeschikbaar } from './nativeSessie'

let accessToken: string | null = null
let sessieVerlopenHandler: (() => void) | null = null

/** Native schil (fase 4): alle paden zijn root-relatief; in de app-bundel wijst
 * VITE_API_BASE naar het productiedomein (capacitor://localhost heeft geen backend).
 * Web/dev: leeg → ongewijzigd gedrag (dev-proxy/zelfde origin). */
const API_BASE: string = (import.meta.env?.VITE_API_BASE as string | undefined) ?? ''

function apiUrl(pad: string): string {
  return API_BASE ? `${API_BASE}${pad}` : pad
}

/** Native aankondiging + het header-refresh-token voor de vernieuwen-familie (het pad-prefix
 * spiegelt bewust het cookie-path van de backend). Web: no-op. */
async function metNatieveAuthHeaders(pad: string, headers: Headers): Promise<void> {
  if (!natieveSessieBeschikbaar()) return
  headers.set('X-Native-Client', '1')
  if (pad.startsWith('/auth/token/vernieuwen')) {
    const token = await haalNatiefRefreshToken()
    if (token) headers.set('X-Refresh-Token', token)
  }
}

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

/** Maar: onze eigen backend gebruikt 502 óók als bewuste applicatiefout mét JSON-detail
 * (RLZ-fout in sync/bank/omzet/doorbelasting). Een échte gateway-fout (LB, dev-proxy) heeft
 * nooit zo'n body — alleen dán is "backend niet bereikbaar" de juiste melding (bewijs-push-
 * kliktest 2026-08-17: een detail-dragende 502 verscheen als onbereikbaar-melding en
 * verstopte de echte reden). */
async function gooiAlsBackendOnbereikbaar(resp: Response): Promise<void> {
  if (!isBackendOnbereikbaarStatus(resp.status)) return
  try {
    const body: unknown = await resp.clone().json()
    if (body && typeof body === 'object' && 'detail' in body) return
  } catch {
    // geen JSON-body → gateway
  }
  throw new BackendOnbereikbaarError()
}

/** Netwerkfout (bv. backend echt plat, geen proxy-response) én de 502/503/504-gatewaystatus delen
 * dezelfde gebruikersmelding — het onderscheid tussen "geen verbinding" en "verbinding maar geen
 * backend erachter" is voor de eindgebruiker niet relevant. */
export class BackendOnbereikbaarError extends ApiError {
  constructor() {
    super(0, BACKEND_ONBEREIKBAAR_MELDING)
  }
}

/** Géén request mag eeuwig hangen (kliktest 2026-08-12: oneindig "Bezig…" op de activatie
 * doordat de backend niet antwoordde) — de refresh-timeout van 2026-08-07 geldt daarom voor
 * álle requests. Eigen AbortController + setTimeout i.p.v. AbortSignal.timeout(), zodat tests
 * met fake timers kunnen sturen. */
export const REQUEST_TIMEOUT_MS = 10_000

async function fetchMetTimeout(pad: string, init: RequestInit): Promise<Response> {
  try {
    if (init.signal) return await fetch(apiUrl(pad), init)
    // clearTimeout ná de response-headers: de timeout bewaakt "server antwoordt niet", niet
    // het daarna binnenstromen van een grote body (PDF-blob) — die zou anders halverwege
    // afgebroken worden.
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
    try {
      return await fetch(apiUrl(pad), { ...init, signal: controller.signal })
    } finally {
      clearTimeout(timer)
    }
  } catch {
    // fetch() gooit alleen bij een echte netwerkfout of de abort hierboven (geen enkele
    // HTTP-response) — een 502 van de dev-proxy komt hier niet binnen, dat is een gewone
    // (niet-ok) Response.
    throw new BackendOnbereikbaarError()
  }
}

async function ruweFetch(pad: string, init: RequestInit): Promise<Response> {
  const headers = new Headers(init.headers)
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
  // Alleen awaiten in de native schil: op het webpad start fetch in dezelfde tick (het
  // single-flight-contract van verversSessie leunt daarop — zie client.test.ts).
  if (natieveSessieBeschikbaar()) await metNatieveAuthHeaders(pad, headers)
  return fetchMetTimeout(pad, { ...init, headers, credentials: 'include' })
}

/** Voor auth-endpoints buiten de access-token-flow (accordeur: setup-token in een eigen
 * Authorization-header, of alleen de refresh-cookie): zelfde timeout- en onbereikbaar-
 * vertaling als apiFetch, maar zonder het in-memory access-token (dat zou een meegegeven
 * setup-token overschrijven) en zonder 401-refresh-retry. */
export async function kaleAuthFetch(pad: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers)
  if (natieveSessieBeschikbaar()) await metNatieveAuthHeaders(pad, headers)
  const resp = await fetchMetTimeout(pad, { ...init, headers, credentials: 'include' })
  await gooiAlsBackendOnbereikbaar(resp)
  return resp
}

async function voerVerversUit(): Promise<boolean> {
  let resp = await ruweFetch('/auth/token/vernieuwen', { method: 'POST' })
  if (resp.status === 409) {
    // Rotatie-botsing (backend hield de rij-lock vast voor een parallelle vernieuwing, bv. een
    // tweede tab): geen uitlog-signaal — kort wachten en precies één keer opnieuw proberen.
    await new Promise((resolve) => setTimeout(resolve, 300))
    resp = await ruweFetch('/auth/token/vernieuwen', { method: 'POST' })
  }
  await gooiAlsBackendOnbereikbaar(resp)
  if (!resp.ok) return false
  const body = (await resp.json()) as { access_token: string; refresh_token?: string }
  accessToken = body.access_token
  // Native (fase 4): de rotatie levert het nieuwe refresh-token in de body — meteen naar de
  // Keychain/Keystore, anders is de sessie na de volgende app-start alsnog weg.
  if (body.refresh_token) await bewaarNatiefRefreshToken(body.refresh_token)
  return true
}

let refreshInFlight: Promise<boolean> | null = null

/** Stille refresh via de httpOnly-cookie — geen TOTP nodig zolang de cookie geldig is. Gooit
 * BackendOnbereikbaarError door (in plaats van 'm als gewone mislukte refresh te behandelen) zodat
 * de aanroeper (AuthContext, bij het laden van de app) dat kan onderscheiden van "gewoon niet
 * ingelogd" en een nette melding kan tonen i.p.v. stil op het login-scherm te belanden.
 *
 * Single-flight (browserreview 2026-08-07): één pageload kan meerdere aanroepers tegelijk hebben
 * (dubbel React-effect onder StrictMode, 401-retries van parallelle fetches). Twee parallelle
 * POSTs met dezelfde cookie raken server-side de hergebruik-detectie — daarom delen alle
 * gelijktijdige aanroepers hier één in-flight promise; er loopt nooit meer dan één
 * vernieuwen-request tegelijk vanuit dit tabblad. */
export function verversSessie(): Promise<boolean> {
  refreshInFlight ??= voerVerversUit().finally(() => {
    refreshInFlight = null
  })
  return refreshInFlight
}

const GEEN_RETRY_PADEN = new Set(['/auth/login', '/auth/token/vernieuwen', '/auth/token/vernieuwen/logout'])

/** Eén automatische refresh-poging bij een 401 — daarna geeft de aanroeper het zelf op. */
export async function apiFetch(pad: string, init: RequestInit = {}): Promise<Response> {
  let resp = await ruweFetch(pad, init)
  await gooiAlsBackendOnbereikbaar(resp)
  if (resp.status === 401 && !GEEN_RETRY_PADEN.has(pad)) {
    const ververst = await verversSessie()
    if (ververst) {
      resp = await ruweFetch(pad, init)
      await gooiAlsBackendOnbereikbaar(resp)
    } else {
      accessToken = null
      sessieVerlopenHandler?.()
    }
  }
  return resp
}

/** FastAPI/pydantic geeft bij een 422 geen platte `detail`-string maar een lijst
 * `[{loc: [...], msg: "...", type: "..."}, ...]` — zonder dit uit te pakken viel de generieke
 * foutafhandeling terug op de kale statustekst ("Unprocessable Entity"), precies de "nooit alleen
 * 'Controleren mislukt'"-klacht uit de kliktest. `loc` bevat het veldpad (met een 'body'-prefix
 * die niet nuttig is om te tonen). */
function pydanticValidatiefoutenNaarTekst(detail: unknown): string | null {
  if (!Array.isArray(detail)) return null
  const regels = detail
    .map((fout) => {
      if (!fout || typeof fout !== 'object' || !('msg' in fout)) return null
      const loc =
        'loc' in fout && Array.isArray(fout.loc)
          ? (fout.loc as unknown[]).filter((l) => l !== 'body').join('.')
          : null
      const msg = String((fout as { msg: unknown }).msg)
      return loc ? `${loc}: ${msg}` : msg
    })
    .filter((regel): regel is string => regel !== null)
  return regels.length > 0 ? regels.join('; ') : null
}

async function foutmelding(resp: Response): Promise<string> {
  try {
    const body: unknown = await resp.json()
    if (body && typeof body === 'object' && 'detail' in body) {
      const detail = (body as { detail: unknown }).detail
      if (typeof detail === 'string') return detail
      const validatiefouten = pydanticValidatiefoutenNaarTekst(detail)
      if (validatiefouten) return validatiefouten
    }
  } catch {
    // geen JSON-body — val terug op de statustekst
  }
  return resp.statusText || `Fout (${resp.status})`
}

export const GEEN_JSON_MELDING =
  'De server gaf een onverwacht antwoord. Probeer het opnieuw; blijft dit gebeuren, neem dan contact op met de ' +
  'beheerder.'

export async function apiJson<T>(pad: string, init: RequestInit = {}): Promise<T> {
  const resp = await apiFetch(pad, init)
  if (!resp.ok) throw new ApiError(resp.status, await foutmelding(resp))
  if (resp.status === 204) return undefined as T
  // Vangnet op de proxy-bugklasse (browserreview 2026-08-07, derde herhaling): een pad dat
  // buiten de dev-proxy valt krijgt Vite's SPA-fallback — index.html met status 200. Zonder deze
  // check lekt dat als rauwe parserfout ("Unexpected token '<'") naar de UI; nu wordt het een
  // nette ApiError. De guard-test src/api/proxyDekking.test.ts hoort dit al in CI te vangen.
  const contentType = resp.headers.get('content-type') ?? ''
  if (!contentType.includes('json')) throw new ApiError(resp.status, GEEN_JSON_MELDING)
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
