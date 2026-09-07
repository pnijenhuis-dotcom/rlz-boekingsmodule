// Native sessie-opslag (store-app fase 4): fail-closed plugin-detectie, en het
// header-token-pad in de refresh-flow — in de schil reist het refresh-token als
// X-Refresh-Token (Keychain/Keystore) en wordt het geroteerde token uit de body bewaard.

import { afterEach, describe, expect, it, vi } from 'vitest'
import { setAccessToken, verversSessie } from './client'
import { haalNatiefRefreshToken, natieveSessieBeschikbaar } from './nativeSessie'

function maakOpslagFake(begin: Record<string, string> = {}) {
  const data = new Map(Object.entries(begin))
  return {
    zet: vi.fn(({ sleutel, waarde }: { sleutel: string; waarde: string }) => {
      data.set(sleutel, waarde)
      return Promise.resolve()
    }),
    haal: vi.fn(({ sleutel }: { sleutel: string }) => Promise.resolve({ waarde: data.get(sleutel) ?? null })),
    verwijder: vi.fn(({ sleutel }: { sleutel: string }) => {
      data.delete(sleutel)
      return Promise.resolve()
    }),
    _data: data,
  }
}

function stubCapacitor(plugin: unknown) {
  vi.stubGlobal('Capacitor', { isNativePlatform: () => true, Plugins: { VeiligeOpslag: plugin } })
}

afterEach(() => {
  vi.unstubAllGlobals()
  setAccessToken(null)
})

describe('natieveSessieBeschikbaar — detectie', () => {
  it('false buiten de schil en bij een half plugin-oppervlak (fail-closed)', () => {
    expect(natieveSessieBeschikbaar()).toBe(false)
    stubCapacitor({ zet: () => Promise.resolve() })
    expect(natieveSessieBeschikbaar()).toBe(false)
  })

  it('true met het volledige plugin-oppervlak', () => {
    stubCapacitor(maakOpslagFake())
    expect(natieveSessieBeschikbaar()).toBe(true)
  })
})

describe('refresh-flow in de native schil', () => {
  it('verversSessie stuurt het Keychain-token als header en bewaart het geroteerde token', async () => {
    const opslag = maakOpslagFake({ refresh_token: 'oud-token' })
    stubCapacitor(opslag)
    let gezienHeaders: Headers | null = null
    vi.stubGlobal(
      'fetch',
      vi.fn((invoer: RequestInfo | URL, init?: RequestInit) => {
        expect(String(invoer)).toBe('/auth/token/vernieuwen')
        gezienHeaders = new Headers(init?.headers)
        return Promise.resolve(
          new Response(JSON.stringify({ access_token: 'acc-1', refresh_token: 'nieuw-token' }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }),
        )
      }),
    )

    await expect(verversSessie()).resolves.toBe(true)
    expect(gezienHeaders!.get('X-Native-Client')).toBe('1')
    expect(gezienHeaders!.get('X-Refresh-Token')).toBe('oud-token')
    // Rotatie bewaard — anders is de sessie na de volgende app-start weg.
    await expect(haalNatiefRefreshToken()).resolves.toBe('nieuw-token')
  })

  it('web-pad ongewijzigd: geen native headers zonder schil', async () => {
    let gezienHeaders: Headers | null = null
    vi.stubGlobal(
      'fetch',
      vi.fn((_invoer: RequestInfo | URL, init?: RequestInit) => {
        gezienHeaders = new Headers(init?.headers)
        return Promise.resolve(new Response(null, { status: 401 }))
      }),
    )
    await expect(verversSessie()).resolves.toBe(false)
    expect(gezienHeaders!.has('X-Native-Client')).toBe(false)
    expect(gezienHeaders!.has('X-Refresh-Token')).toBe(false)
  })
})

// Blok 12b (07-09, beslispunt 3 "KOUDE START ACCORDEUR-APP"): in de native schil zonder leesbaar
// refresh-token (gesloten slot / verse installatie) doet de stille refresh GEEN netwerkrondje meer —
// de uitkomst is dezelfde als bij een 401 (false). Web blijft onverkort het cookie-pad.
describe('boot-refresh native zonder leesbaar token (12b)', () => {
  it('native + geen token → false zónder fetch; native + token → wél de POST', async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify({ access_token: 'acc-2' }), { status: 200, headers: { 'Content-Type': 'application/json' } }),
      ),
    )
    vi.stubGlobal('fetch', fetchMock)
    const opslag = maakOpslagFake()
    stubCapacitor(opslag)

    await expect(verversSessie()).resolves.toBe(false)
    expect(fetchMock).not.toHaveBeenCalled()
    expect(opslag.haal).toHaveBeenCalledWith({ sleutel: 'refresh_token' })

    opslag._data.set('refresh_token', 'tok')
    await expect(verversSessie()).resolves.toBe(true)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('web (geen schil): de POST gaat altijd — ook zonder enig token (cookie-pad, ongewijzigd)', async () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response(null, { status: 401 })))
    vi.stubGlobal('fetch', fetchMock)
    await expect(verversSessie()).resolves.toBe(false)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(String((fetchMock.mock.calls[0] as unknown as [RequestInfo])[0])).toBe('/auth/token/vernieuwen')
  })

  it('apiFetch-401-pad: native zonder token → sessie-verlopen-handler, precies als ná een mislukte refresh', async () => {
    const { apiFetch, setSessieVerlopenHandler } = await import('./client')
    const fetchMock = vi.fn(() => Promise.resolve(new Response(null, { status: 401 })))
    vi.stubGlobal('fetch', fetchMock)
    stubCapacitor(maakOpslagFake())
    const handler = vi.fn()
    setSessieVerlopenHandler(handler)
    try {
      const resp = await apiFetch('/accordering/wachtrij')
      expect(resp.status).toBe(401)
      // Eén request (de 401), géén vernieuwen-POST erachteraan.
      expect(fetchMock).toHaveBeenCalledTimes(1)
      expect(handler).toHaveBeenCalledTimes(1)
    } finally {
      setSessieVerlopenHandler(null)
    }
  })
})
