import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

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
    // Stub die, net als echte fetch, pas faalt wanneer het AbortSignal afgaat.
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_url: string, init?: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            init?.signal?.addEventListener('abort', () => reject(new DOMException('afgebroken', 'AbortError')))
          }),
      ),
    )

    const belofte = client.verversSessie()
    const verwachting = expect(belofte).rejects.toBeInstanceOf(client.BackendOnbereikbaarError)
    await vi.advanceTimersByTimeAsync(client.REFRESH_TIMEOUT_MS + 100)
    await verwachting
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
