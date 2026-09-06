// Parallel laden + voorlader (blok D3 06-09): wachtrij en vragen starten tegelijk, een vragen-fout
// blokkeert nooit, de voorlader is idempotent en éénmalig over te nemen (30 s vers).

import { afterEach, describe, expect, it, vi } from 'vitest'
import { setAccessToken } from '../api/client'
import { laadVerseStand, neemVoorgeladenStand, resetVoorladerVoorTests, voorlaadStand } from './voorlader'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

afterEach(() => {
  vi.unstubAllGlobals()
  resetVoorladerVoorTests()
  setAccessToken(null)
})

describe('laadVerseStand', () => {
  it('start de vragen-fetch vóór het wachtrij-antwoord binnen is (parallel, niet serieel)', async () => {
    setAccessToken('t')
    const volgorde: string[] = []
    let geefWachtrij: (r: Response) => void = () => {}
    vi.stubGlobal(
      'fetch',
      vi.fn((invoer: RequestInfo | URL) => {
        const pad = String(invoer).split('?')[0]
        volgorde.push(`start ${pad}`)
        if (pad === '/accordering/wachtrij') return new Promise<Response>((r) => (geefWachtrij = r))
        return Promise.resolve(jsonResponse({ items: [{ id: 'v1' }] }))
      }),
    )
    const belofte = laadVerseStand()
    await Promise.resolve()
    expect(volgorde).toEqual(['start /accordering/vragen', 'start /accordering/wachtrij'])
    geefWachtrij(jsonResponse({ items: [{ document_id: 'd1' }] }))
    const stand = await belofte
    expect(stand.items).toEqual([{ document_id: 'd1' }])
    expect(stand.vragen).toEqual([{ id: 'v1' }])
  })

  it('een vragen-fout wordt null; een wachtrij-fout (403 voorwaarden) gooit door mét de detail-tekst', async () => {
    setAccessToken('t')
    vi.stubGlobal(
      'fetch',
      vi.fn((invoer: RequestInfo | URL) => {
        const pad = String(invoer).split('?')[0]
        if (pad === '/accordering/vragen') return Promise.resolve(new Response(null, { status: 500 }))
        return Promise.resolve(jsonResponse({ items: [] }))
      }),
    )
    expect((await laadVerseStand()).vragen).toBeNull()

    vi.stubGlobal(
      'fetch',
      vi.fn((invoer: RequestInfo | URL) => {
        const pad = String(invoer).split('?')[0]
        if (pad === '/accordering/wachtrij') return Promise.resolve(jsonResponse({ detail: 'voorwaarden_akkoord_vereist' }, 403))
        return Promise.resolve(jsonResponse({ items: [] }))
      }),
    )
    await expect(laadVerseStand()).rejects.toMatchObject({ status: 403, message: 'voorwaarden_akkoord_vereist' })
  })
})

describe('voorlader', () => {
  it('is idempotent binnen het venster en éénmalig over te nemen; te oud = niet overnemen', async () => {
    setAccessToken('t')
    const mock = vi.fn(() => Promise.resolve(jsonResponse({ items: [] })))
    vi.stubGlobal('fetch', mock)
    voorlaadStand(1_000)
    voorlaadStand(2_000)
    expect(mock).toHaveBeenCalledTimes(2) // wachtrij + vragen, niet nog eens twee
    const belofte = neemVoorgeladenStand(3_000)
    expect(belofte).not.toBeNull()
    expect(neemVoorgeladenStand(3_000)).toBeNull()
    await belofte

    voorlaadStand(10_000)
    expect(neemVoorgeladenStand(10_000 + 31_000)).toBeNull()
  })

  it('zonder afnemer verdwijnt een fout stil (optimalisatie, geen bron van waarheid)', async () => {
    setAccessToken('t')
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(null, { status: 500 }))))
    voorlaadStand()
    await new Promise((r) => setTimeout(r, 0))
    // Geen unhandled rejection — de test slaagt als we hier komen; de belofte is wél overneembaar.
    await expect(neemVoorgeladenStand()!).rejects.toBeTruthy()
  })
})
