// Factuurbeeld-prefetchcache (snelheidslaag 2026-08-17): fetch-deduplicatie tussen prefetch
// en weergave, opruimen buiten het venster (revoke) en het niet-cachen van mislukkingen.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FactuurCache } from './pdfCache'

describe('FactuurCache', () => {
  const revoke = vi.fn()

  beforeEach(() => {
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: () => 'blob:test', revokeObjectURL: revoke }))
    revoke.mockClear()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('deelt één fetch tussen prefetch en weergave (dedupe per document)', async () => {
    const fetcher = vi.fn(() => Promise.resolve('blob:d1'))
    const cache = new FactuurCache(fetcher)
    const [a, b] = await Promise.all([cache.haal('a1', 'd1'), cache.haal('a1', 'd1')])
    expect(a).toBe('blob:d1')
    expect(b).toBe('blob:d1')
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('snoeit alles buiten het venster (revoke) en fetcht daarna opnieuw', async () => {
    const fetcher = vi.fn((_a: string, documentId: string) => Promise.resolve(`blob:${documentId}`))
    const cache = new FactuurCache(fetcher)
    await cache.haal('a1', 'd1')
    await cache.haal('a1', 'd2')
    cache.snoei(['d2'])
    expect(revoke).toHaveBeenCalledWith('blob:d1')
    await cache.haal('a1', 'd2')
    expect(fetcher).toHaveBeenCalledTimes(2) // d2 bleef gecachet
    await cache.haal('a1', 'd1')
    expect(fetcher).toHaveBeenCalledTimes(3) // d1 was gesnoeid → verse fetch
  })

  it('revoket een blob die pas ná het snoeien binnenkomt (geen lek bij een trage fetch)', async () => {
    let geefVrij: (url: string) => void = () => {}
    const fetcher = vi.fn(() => new Promise<string>((resolve) => (geefVrij = resolve)))
    const cache = new FactuurCache(fetcher)
    const belofte = cache.haal('a1', 'd1')
    cache.snoei([])
    geefVrij('blob:laat')
    await belofte
    expect(revoke).toHaveBeenCalledWith('blob:laat')
  })

  it('cachet mislukkingen niet — opnieuw openen probeert opnieuw', async () => {
    const fetcher = vi
      .fn()
      .mockRejectedValueOnce(new Error('netwerk stuk'))
      .mockResolvedValueOnce('blob:d1')
    const cache = new FactuurCache(fetcher)
    await expect(cache.haal('a1', 'd1')).rejects.toThrow('netwerk stuk')
    await expect(cache.haal('a1', 'd1')).resolves.toBe('blob:d1')
    expect(fetcher).toHaveBeenCalledTimes(2)
  })
})
