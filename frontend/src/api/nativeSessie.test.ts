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
