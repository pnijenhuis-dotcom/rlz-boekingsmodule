// Optimistische besluit-verzender (snelheidslaag 2026-08-17): retry-classificatie (alleen
// netwerk/5xx), begrensde backoff, FIFO-volgorde, dubbelklik-dedupe en de
// definitief-mislukt-terugmelding (nooit stil verloren).

import { describe, expect, it, vi } from 'vitest'
import { ApiError, BackendOnbereikbaarError } from '../api/client'
import type { WachtrijItemDto } from './accordeurApi'
import { BACKOFF_MS, BesluitVerzender, MAX_POGINGEN, type BesluitOpdracht } from './besluitQueue'

function item(documentId: string): WachtrijItemDto {
  return {
    document_id: documentId,
    administratie_id: 'a1',
    administratie_naam: 'BLOW B.V.',
    leverancier_naam: 'Essent Zakelijk',
    referentie: 'E-1',
    factuurdatum: '2026-07-01',
    totaalbedrag: '847.00',
    aangeboden_op: '2026-07-02T09:00:00Z',
    laag_volgnummer: 1,
    boeking_omschrijving: null,
    staande_regel_kandidaat: false,
  }
}

function opdracht(documentId: string, soort: 'akkoord' | 'afwijzen' = 'akkoord'): BesluitOpdracht {
  return { item: item(documentId), soort, staandeRegelAanmaken: false, reden: soort === 'afwijzen' ? 'te vroeg' : null }
}

/** Verzender met stub-API's en instant-backoff; geeft de callbacks + spies terug. */
function maakVerzender(overrides: { geefAkkoord?: ReturnType<typeof vi.fn>; wijsAf?: ReturnType<typeof vi.fn> } = {}) {
  const geefAkkoord = overrides.geefAkkoord ?? vi.fn(() => Promise.resolve({}))
  const wijsAf = overrides.wijsAf ?? vi.fn(() => Promise.resolve({}))
  const wachtAanroepen: number[] = []
  const wacht = vi.fn((ms: number) => {
    wachtAanroepen.push(ms)
    return Promise.resolve()
  })
  const verzender = new BesluitVerzender({
    geefAkkoord: geefAkkoord as never,
    wijsAf: wijsAf as never,
    wacht,
  })
  const mislukt: { opdracht: BesluitOpdracht; voorwaardenNodig: boolean }[] = []
  const aantallen: number[] = []
  verzender.zetLuisteraar({
    onDefinitiefMislukt: (o, v) => mislukt.push({ opdracht: o, voorwaardenNodig: v }),
    onAantalOnderwegGewijzigd: (n) => aantallen.push(n),
  })
  return { verzender, geefAkkoord, wijsAf, wacht, wachtAanroepen, mislukt, aantallen }
}

async function laatRijLeeglopen(verzender: BesluitVerzender): Promise<void> {
  // De verzendrij draait op microtasks (wacht = instant resolve) — een paar ticks volstaan.
  for (let i = 0; i < 50 && verzender.aantalOnderweg() > 0; i++) {
    await Promise.resolve()
  }
}

describe('BesluitVerzender', () => {
  it('verstuurt een akkoord en meldt het aantal onderweg 1 → 0', async () => {
    const { verzender, geefAkkoord, mislukt, aantallen } = maakVerzender()
    verzender.verstuur(opdracht('d1'))
    expect(verzender.isOnderweg('d1')).toBe(true)
    await laatRijLeeglopen(verzender)
    expect(geefAkkoord).toHaveBeenCalledWith('a1', 'd1', false)
    expect(mislukt).toEqual([])
    expect(aantallen).toEqual([1, 0])
  })

  it('verstuurt een afwijzing mét reden', async () => {
    const { verzender, wijsAf } = maakVerzender()
    verzender.verstuur(opdracht('d1', 'afwijzen'))
    await laatRijLeeglopen(verzender)
    expect(wijsAf).toHaveBeenCalledWith('a1', 'd1', 'te vroeg')
  })

  it('herprobeert bij een netwerkfout en slaagt daarna zonder mislukt-melding', async () => {
    const geefAkkoord = vi
      .fn()
      .mockRejectedValueOnce(new BackendOnbereikbaarError())
      .mockResolvedValueOnce({})
    const { verzender, mislukt, wachtAanroepen } = maakVerzender({ geefAkkoord })
    verzender.verstuur(opdracht('d1'))
    await laatRijLeeglopen(verzender)
    expect(geefAkkoord).toHaveBeenCalledTimes(2)
    expect(wachtAanroepen).toEqual([BACKOFF_MS[0]])
    expect(mislukt).toEqual([])
  })

  it('herprobeert óók bij een 5xx (server had het besluit mogelijk niet verwerkt)', async () => {
    const geefAkkoord = vi.fn().mockRejectedValueOnce(new ApiError(500, 'stuk')).mockResolvedValueOnce({})
    const { verzender, mislukt } = maakVerzender({ geefAkkoord })
    verzender.verstuur(opdracht('d1'))
    await laatRijLeeglopen(verzender)
    expect(geefAkkoord).toHaveBeenCalledTimes(2)
    expect(mislukt).toEqual([])
  })

  it('een 4xx is definitief: geen retry, direct de mislukt-melding', async () => {
    const geefAkkoord = vi.fn().mockRejectedValue(new ApiError(409, 'al besloten door een ander'))
    const { verzender, mislukt, wachtAanroepen } = maakVerzender({ geefAkkoord })
    verzender.verstuur(opdracht('d1'))
    await laatRijLeeglopen(verzender)
    expect(geefAkkoord).toHaveBeenCalledTimes(1)
    expect(wachtAanroepen).toEqual([])
    expect(mislukt).toHaveLength(1)
    expect(mislukt[0].opdracht.item.document_id).toBe('d1')
    expect(mislukt[0].voorwaardenNodig).toBe(false)
  })

  it('herkent de voorwaarden-403 in de mislukt-melding', async () => {
    const geefAkkoord = vi.fn().mockRejectedValue(new ApiError(403, 'voorwaarden_akkoord_vereist'))
    const { verzender, mislukt } = maakVerzender({ geefAkkoord })
    verzender.verstuur(opdracht('d1'))
    await laatRijLeeglopen(verzender)
    expect(mislukt).toHaveLength(1)
    expect(mislukt[0].voorwaardenNodig).toBe(true)
  })

  it('geeft na MAX_POGINGEN tijdelijke fouten alsnog definitief op (begrensd, nooit eeuwig)', async () => {
    const geefAkkoord = vi.fn().mockRejectedValue(new BackendOnbereikbaarError())
    const { verzender, mislukt, wachtAanroepen } = maakVerzender({ geefAkkoord })
    verzender.verstuur(opdracht('d1'))
    await laatRijLeeglopen(verzender)
    expect(geefAkkoord).toHaveBeenCalledTimes(MAX_POGINGEN)
    expect(wachtAanroepen).toEqual([...BACKOFF_MS])
    expect(mislukt).toHaveLength(1)
  })

  it('verwerkt besluiten sequentieel in klik-volgorde (FIFO)', async () => {
    const volgorde: string[] = []
    const geefAkkoord = vi.fn((_a: string, documentId: string) => {
      volgorde.push(documentId)
      return Promise.resolve({})
    })
    const { verzender } = maakVerzender({ geefAkkoord })
    verzender.verstuur(opdracht('d1'))
    verzender.verstuur(opdracht('d2'))
    verzender.verstuur(opdracht('d3'))
    expect(verzender.aantalOnderweg()).toBe(3)
    await laatRijLeeglopen(verzender)
    expect(volgorde).toEqual(['d1', 'd2', 'd3'])
  })

  it('negeert een tweede besluit voor hetzelfde document zolang het eerste onderweg is', async () => {
    const { verzender, geefAkkoord } = maakVerzender()
    verzender.verstuur(opdracht('d1'))
    verzender.verstuur(opdracht('d1'))
    await laatRijLeeglopen(verzender)
    expect(geefAkkoord).toHaveBeenCalledTimes(1)
  })
})
