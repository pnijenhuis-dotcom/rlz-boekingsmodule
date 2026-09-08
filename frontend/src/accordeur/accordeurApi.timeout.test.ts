// Blok 1 (08-09): de wachtrij-/vragen-leesroutes wachten tot LEES_TIMEOUT_MS (30 s) op de server —
// niet de generieke REQUEST_TIMEOUT_MS (10 s) die live de wachtrij van 9,8–11,5 s afbrak. Geld-
// besluiten (akkoord/afwijzen) blijven op de standaard-timeout.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as client from '../api/client'
import { haalWachtrij, LEES_TIMEOUT_MS } from './accordeurApi'

function hangendeFetch() {
  const gezien: { signal: AbortSignal | null | undefined }[] = []
  const mock = vi.fn((_invoer: RequestInfo | URL, init?: RequestInit) => {
    gezien.push({ signal: init?.signal })
    return new Promise<Response>((_r, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
    })
  })
  vi.stubGlobal('fetch', mock)
  return { mock, gezien }
}

describe('accordeurApi — lees-timeout', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    client.setAccessToken('t')
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    client.setAccessToken(null)
  })

  it('de wachtrij-fetch breekt NIET af op de generieke 10 s, wél op LEES_TIMEOUT_MS', async () => {
    expect(LEES_TIMEOUT_MS).toBeGreaterThan(client.REQUEST_TIMEOUT_MS)
    const { gezien } = hangendeFetch()
    const belofte = haalWachtrij()
    const verwachting = expect(belofte).rejects.toBeInstanceOf(client.BackendOnbereikbaarError)
    await vi.advanceTimersByTimeAsync(client.REQUEST_TIMEOUT_MS + 500)
    expect(gezien[0]?.signal?.aborted).toBe(false)
    await vi.advanceTimersByTimeAsync(LEES_TIMEOUT_MS)
    expect(gezien[0]?.signal?.aborted).toBe(true)
    await verwachting
  })

  it('een geldbesluit houdt de standaard-timeout van REQUEST_TIMEOUT_MS', async () => {
    const { gezien } = hangendeFetch()
    const belofte = client.apiFetch('/administraties/a/accordering/documenten/d/akkoord', { method: 'POST' })
    const verwachting = expect(belofte).rejects.toBeInstanceOf(client.BackendOnbereikbaarError)
    await vi.advanceTimersByTimeAsync(client.REQUEST_TIMEOUT_MS + 100)
    expect(gezien[0]?.signal?.aborted).toBe(true)
    await verwachting
  })
})
