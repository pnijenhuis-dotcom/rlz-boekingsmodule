import { afterEach, describe, expect, it, vi } from 'vitest'
import { bevestigTransport, maakTransportDefinitief, schatM2, verschuifTransport, wijzigMateriaallijst, type ProductDto } from './transportApi'

/* m²-schatting client-side (weergave tijdens het typen; de server rekent bindend met dezelfde
 * formule Σ(aantal × lengte) / 4,6 uit Peters bestellijst): het voorbeeld #262651 geeft 331,09 m². */
function product(id: string, lengte: string | null): ProductDto {
  return { id, leverancier_id: 'l', categorie_id: 'c', categorie_naam: 'Tubelock', bundel: 'steiger', naam: id, verpakking: null, eenheid: 'stuks', m2_lengte: lengte, volgorde: 0, actief: true, nummer: '1.1' }
}

describe('schatM2', () => {
  it('rekent Peters voorbeeld na en negeert producten zonder lengte', () => {
    const producten = new Map<string, ProductDto>([
      ['b2', product('b2', '2')],
      ['b28', product('b28', '2.8')],
      ['b3', product('b3', '3')],
      ['b4', product('b4', '4')],
      ['uk', product('uk', '1.4')],
      ['us', product('us', '2')],
      ['anker', product('anker', '1')],
      ['kruis', product('kruis', null)],
    ])
    expect(schatM2({ b2: 50, b28: 0, b3: 150, b4: 150, uk: 45, us: 150, anker: 10, kruis: 1000 }, producten)).toBe(331.09)
    expect(schatM2({}, producten)).toBe(0)
    expect(schatM2({ b4: 115 }, producten)).toBe(100)
  })
})

/* Transport-statusflow-endpoints (31-08): bevestigen (voertuig), definitief (regels + planner),
 * materiaallijst wijzigen (delta) en dag verschuiven — URL, methode en body geverifieerd. */
function stubFetch() {
  const fn = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify({ id: 't1' }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
  vi.stubGlobal('fetch', fn)
  return fn
}

function laatsteCall(fn: ReturnType<typeof stubFetch>): { url: string; method: string | undefined; body: unknown } {
  const [input, init] = fn.mock.calls[fn.mock.calls.length - 1]
  return { url: String(input), method: init?.method, body: JSON.parse(String(init?.body)) }
}

afterEach(() => vi.unstubAllGlobals())

describe('transport-statusflow-api', () => {
  it('bevestigTransport post het toegezegde voertuig naar /bevestigen', async () => {
    const fn = stubFetch()
    await bevestigTransport('a1', 't1', 'voorwagen')
    const { url, method, body } = laatsteCall(fn)
    expect(url).toContain('/materiaal/a1/transport/t1/bevestigen')
    expect(method).toBe('POST')
    expect(body).toEqual({ voertuig: 'voorwagen' })
  })

  it('maakTransportDefinitief post regels + transportplanner naar /definitief', async () => {
    const fn = stubFetch()
    await maakTransportDefinitief('a1', 't1', { p1: 120, p2: 36 }, 'De Jong Transport')
    const { url, method, body } = laatsteCall(fn)
    expect(url).toContain('/materiaal/a1/transport/t1/definitief')
    expect(method).toBe('POST')
    expect(body).toEqual({ regels: { p1: 120, p2: 36 }, transportplanner: 'De Jong Transport' })
  })

  it('wijzigMateriaallijst post naar /materiaallijst — planner optioneel (null)', async () => {
    const fn = stubFetch()
    await wijzigMateriaallijst('a1', 't1', { p1: 90 })
    const { url, method, body } = laatsteCall(fn)
    expect(url).toContain('/materiaal/a1/transport/t1/materiaallijst')
    expect(method).toBe('POST')
    expect(body).toEqual({ regels: { p1: 90 }, transportplanner: null })
    await wijzigMateriaallijst('a1', 't1', { p1: 90 }, 'Eigen wagen')
    expect(laatsteCall(fn).body).toEqual({ regels: { p1: 90 }, transportplanner: 'Eigen wagen' })
  })

  it('verschuifTransport post de nieuwe datum naar /verschuiven', async () => {
    const fn = stubFetch()
    await verschuifTransport('a1', 't1', '2026-08-27')
    const { url, method, body } = laatsteCall(fn)
    expect(url).toContain('/materiaal/a1/transport/t1/verschuiven')
    expect(method).toBe('POST')
    expect(body).toEqual({ datum: '2026-08-27' })
  })
})
