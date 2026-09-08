import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

/** client.ts houdt module-state bij (access-token, in-flight refresh-promise) — elke test krijgt
 * daarom een verse module-instantie via resetModules + dynamic import. */
async function verseClient() {
  vi.resetModules()
  return import('./client')
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('verversSessie — single-flight (browserreview 2026-08-07)', () => {
  it('deelt één in-flight request over parallelle aanroepers', async () => {
    const client = await verseClient()
    let laatLos: (r: Response) => void = () => {}
    const fetchMock = vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          laatLos = resolve
        }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const eerste = client.verversSessie()
    const tweede = client.verversSessie()
    expect(fetchMock).toHaveBeenCalledTimes(1)

    laatLos(jsonResponse({ access_token: 'tok-1' }))
    await expect(eerste).resolves.toBe(true)
    await expect(tweede).resolves.toBe(true)
    expect(client.getAccessToken()).toBe('tok-1')
  })

  it('start ná afronding wél een nieuw request (geen permanente cache)', async () => {
    const client = await verseClient()
    const fetchMock = vi.fn(() => Promise.resolve(jsonResponse({ access_token: 'tok' })))
    vi.stubGlobal('fetch', fetchMock)

    await client.verversSessie()
    await client.verversSessie()
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('probeert bij een 409 (rotatie bezet) na een korte wachttijd precies één keer opnieuw', async () => {
    const client = await verseClient()
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(null, { status: 409 }))
      .mockResolvedValueOnce(jsonResponse({ access_token: 'tok-na-retry' }))
    vi.stubGlobal('fetch', fetchMock)

    const belofte = client.verversSessie()
    await vi.advanceTimersByTimeAsync(400)
    await expect(belofte).resolves.toBe(true)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(client.getAccessToken()).toBe('tok-na-retry')
  })

  it('geeft false bij 401 — de aanroeper handelt de nette redirect naar /login af', async () => {
    const client = await verseClient()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 401 })))
    await expect(client.verversSessie()).resolves.toBe(false)
  })

  it('hangt nooit eeuwig: na de timeout wordt het een BackendOnbereikbaarError', async () => {
    const client = await verseClient()
    stubHangendeFetch()

    const belofte = client.verversSessie()
    const verwachting = expect(belofte).rejects.toBeInstanceOf(client.BackendOnbereikbaarError)
    await vi.advanceTimersByTimeAsync(client.REQUEST_TIMEOUT_MS + 100)
    await verwachting
  })
})

/** Stub die, net als echte fetch, nooit resolvet en pas faalt wanneer het AbortSignal afgaat. */
function stubHangendeFetch() {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      (_url: string, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(new DOMException('afgebroken', 'AbortError')))
        }),
    ),
  )
}

describe('timeout op álle requests (kliktest 2026-08-12: oneindig "Bezig…" bij dode backend)', () => {
  it.each([
    ['/auth/uitnodigingen/accepteren'],
    ['/auth/login'],
    ['/auth/totp/bevestigen'],
  ])('%s hangt nooit eeuwig — na de timeout een nette onbereikbaar-melding', async (pad) => {
    const client = await verseClient()
    stubHangendeFetch()

    const belofte = client.apiPostJson(pad, { veld: 'x' })
    const verwachting = expect(belofte).rejects.toThrow(client.BACKEND_ONBEREIKBAAR_MELDING)
    await vi.advanceTimersByTimeAsync(client.REQUEST_TIMEOUT_MS + 100)
    await verwachting
  })

  it('kaleAuthFetch (setup-token/cookie-pad) krijgt dezelfde timeout', async () => {
    const client = await verseClient()
    stubHangendeFetch()

    const belofte = client.kaleAuthFetch('/auth/webauthn/login/voltooien', { method: 'POST' })
    const verwachting = expect(belofte).rejects.toBeInstanceOf(client.BackendOnbereikbaarError)
    await vi.advanceTimersByTimeAsync(client.REQUEST_TIMEOUT_MS + 100)
    await verwachting
  })

  it('kaleAuthFetch vertaalt een 502/503/504 van de proxy naar BackendOnbereikbaarError', async () => {
    const client = await verseClient()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 503 })))
    await expect(client.kaleAuthFetch('/auth/token/vernieuwen/ontgrendelen')).rejects.toBeInstanceOf(
      client.BackendOnbereikbaarError,
    )
  })
})

describe('eigen 502 met JSON-detail ≠ gateway-fout (bewijs-push-kliktest 2026-08-17)', () => {
  it('apiJson toont het detail van een backend-502 in plaats van de onbereikbaar-melding', async () => {
    // De backend gebruikt 502 bewust als applicatiefout mét reden (RLZ-fout in sync/bank/
    // omzet/doorbelasting) — die reden mag nooit achter "backend niet bereikbaar" verdwijnen.
    const client = await verseClient()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ detail: 'RLZ weigerde de boeking (409/xyz)' }, 502)),
    )
    const belofte = client.apiJson('/administraties/x/sync')
    await expect(belofte).rejects.toThrow('RLZ weigerde de boeking (409/xyz)')
    await expect(belofte).rejects.not.toBeInstanceOf(client.BackendOnbereikbaarError)
  })

  it('een kale gateway-502 (HTML/lege body) blijft wél BackendOnbereikbaarError', async () => {
    const client = await verseClient()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('<html>Bad Gateway</html>', { status: 502 })),
    )
    await expect(client.apiJson('/werkvoorraad/overzicht')).rejects.toBeInstanceOf(
      client.BackendOnbereikbaarError,
    )
  })

  it('de timeout breekt een al binnengekomen response niet meer af (grote body, bv. PDF-blob)', async () => {
    const client = await verseClient()
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      init?.signal?.addEventListener('abort', () => {
        throw new Error('abort had geannuleerd moeten zijn na de response')
      })
      return Promise.resolve(jsonResponse({ ok: true }))
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(client.apiJson('/documenten/x/bestand')).resolves.toEqual({ ok: true })
    // Ver voorbij de timeout: de abort-timer is bij de response al opgeruimd.
    await vi.advanceTimersByTimeAsync(client.REQUEST_TIMEOUT_MS * 2)
  })
})

describe('apiJson — niet-JSON-vangnet (proxy-bugklasse)', () => {
  it('vertaalt een HTML-antwoord (SPA-fallback) naar een nette ApiError i.p.v. een parserfout', async () => {
    const client = await verseClient()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response('<!doctype html><html></html>', {
          status: 200,
          headers: { 'Content-Type': 'text/html' },
        }),
      ),
    )
    await expect(client.apiJson('/bank/overzicht')).rejects.toThrow(client.GEEN_JSON_MELDING)
  })
})

// Blok 2b (08-09): incident "Geen verbinding met de server" op het code-slot zonder request bij de server —
// de foutklasse draagt nu de oorzaak (timeout / netwerk / server) + de ruwe browsermelding, zodat slot en
// diagnoseregel kunnen zeggen wát er misging.
describe('BackendOnbereikbaarError.oorzaak (blok 2b 08-09)', () => {
  it('eigen 10 s-timer → oorzaak "timeout" mét de AbortError als technische melding', async () => {
    const client = await verseClient()
    stubHangendeFetch()
    const belofte = client.kaleAuthFetch('/auth/token/vernieuwen', { method: 'POST' })
    const verwachting = belofte.catch((err: unknown) => err)
    await vi.advanceTimersByTimeAsync(client.REQUEST_TIMEOUT_MS + 100)
    const err = (await verwachting) as InstanceType<typeof client.BackendOnbereikbaarError>
    expect(err).toBeInstanceOf(client.BackendOnbereikbaarError)
    expect(err.oorzaak).toBe('timeout')
    expect(err.technisch).toContain('AbortError')
  })

  it('fetch gooit vóór een response (offline/CORS/webview "Load failed") → oorzaak "netwerk" + ruwe melding', async () => {
    const client = await verseClient()
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Load failed')))
    const err = (await client.kaleAuthFetch('/auth/token/vernieuwen', { method: 'POST' }).catch((e: unknown) => e)) as InstanceType<
      typeof client.BackendOnbereikbaarError
    >
    expect(err).toBeInstanceOf(client.BackendOnbereikbaarError)
    expect(err.oorzaak).toBe('netwerk')
    expect(err.technisch).toBe('TypeError: Load failed')
    expect(err.message).toBe(client.BACKEND_ONBEREIKBAAR_MELDING)
  })

  it('kale 502/503/504 → oorzaak "server" mét de status', async () => {
    const client = await verseClient()
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 503 })))
    const err = (await client.kaleAuthFetch('/auth/token/vernieuwen', { method: 'POST' }).catch((e: unknown) => e)) as InstanceType<
      typeof client.BackendOnbereikbaarError
    >
    expect(err.oorzaak).toBe('server')
    expect(err.technisch).toBe('HTTP 503')
  })
})

// App-auth zonder passkey (contract §5a, 08-09): de PWA-slotmodus stuurt X-App-Slot: 1 (+ X-Refresh-Token
// op de vernieuwen-familie) — en de kantoor-web merkt daar NIETS van: buiten /accordeur zonder slot-vlag
// zijn de headers byte-identiek aan vóór 08-09.
describe('slot-headers alleen in de slotmodus (§5a) — kantoor-pad byte-identiek', () => {
  // Node 22+ schaduwt window.localStorage in de jsdom-testomgeving — in-memory vervanger.
  beforeAll(() => {
    const opslag = new Map<string, string>()
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        getItem: (k: string) => opslag.get(k) ?? null,
        setItem: (k: string, v: string) => void opslag.set(k, String(v)),
        removeItem: (k: string) => void opslag.delete(k),
        clear: () => opslag.clear(),
        key: (i: number) => [...opslag.keys()][i] ?? null,
        get length() {
          return opslag.size
        },
      } as Storage,
    })
  })
  afterEach(() => {
    window.history.pushState({}, '', '/')
    localStorage.removeItem('accordeur-slot-modus')
  })

  it('kantoor-pad: alleen Authorization, credentials include, géén X-App-Slot/X-Native-Client/X-Refresh-Token', async () => {
    const client = await verseClient()
    client.setAccessToken('tok-k')
    let gezien: { headers: Headers; init: RequestInit } | null = null
    vi.stubGlobal(
      'fetch',
      vi.fn((_u: RequestInfo | URL, init?: RequestInit) => {
        gezien = { headers: new Headers(init?.headers), init: init ?? {} }
        return Promise.resolve(jsonResponse({ ok: true }))
      }),
    )
    await client.apiJson('/werkvoorraad/overzicht')
    expect([...gezien!.headers.entries()]).toEqual([['authorization', 'Bearer tok-k']])
    expect(gezien!.init.credentials).toBe('include')
    // Ook de vernieuwen-familie: cookie-pad, geen header-token.
    await client.verversSessie()
    expect(gezien!.headers.has('X-App-Slot')).toBe(false)
    expect(gezien!.headers.has('X-Refresh-Token')).toBe(false)
  })

  it('PWA-slotmodus (/accordeur + IndexedDB + WebCrypto): X-App-Slot: 1 op elke request, X-Refresh-Token op vernieuwen, nooit X-Native-Client', async () => {
    const { installeerFakeIndexedDb } = await import('./fakeIndexedDb.testhulp')
    const { webcrypto } = await import('node:crypto')
    if (!globalThis.crypto?.subtle) Object.defineProperty(globalThis, 'crypto', { value: webcrypto, configurable: true })
    const idb = installeerFakeIndexedDb()
    try {
      window.history.pushState({}, '', '/accordeur')
      const client = await verseClient()
      const { webVeiligeOpslag } = await import('./webVeiligeOpslag')
      await webVeiligeOpslag().zet({ sleutel: 'refresh_token', waarde: 'rt-web' })
      const gezien: Headers[] = []
      vi.stubGlobal(
        'fetch',
        vi.fn((_u: RequestInfo | URL, init?: RequestInit) => {
          gezien.push(new Headers(init?.headers))
          return Promise.resolve(jsonResponse({ access_token: 'acc-web', refresh_token: 'rt-web-2' }))
        }),
      )
      await expect(client.verversSessie()).resolves.toBe(true)
      expect(gezien[0].get('X-App-Slot')).toBe('1')
      expect(gezien[0].get('X-Refresh-Token')).toBe('rt-web')
      expect(gezien[0].has('X-Native-Client')).toBe(false)
      await client.apiJson('/accordering/wachtrij')
      expect(gezien[1].get('X-App-Slot')).toBe('1')
      expect(gezien[1].has('X-Refresh-Token')).toBe(false)
      expect(gezien[1].get('Authorization')).toBe('Bearer acc-web')
      // Rotatie: het nieuwe token staat in de web-opslag (slot niet ingesteld → plain, zoals native legacy).
      expect(idb.data.get('accordeur-slot')?.get('kv')?.get('refresh_token')).toBe('rt-web-2')
    } finally {
      idb.herstel()
    }
  })
})
