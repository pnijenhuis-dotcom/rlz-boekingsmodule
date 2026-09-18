/** Run B punt 5 — offline-wachtrij (puur, fake IndexedDB): bewaren/vervangen/verwijderen, versleuteld op het slot-anker (mock),
 * verzenden: geslaagd = weg, geen verbinding = stoppen, 409 bevroren = conflict (één keer "nieuw"), andere fout = zichtbaar;
 * mengen in de weekkaarten (bolletjes per kaart/dag). */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, BackendOnbereikbaarError } from '../api/client'
import { installeerFakeIndexedDb } from '../api/fakeIndexedDb.testhulp'

const slot = vi.hoisted(() => ({ anker: true }))
vi.mock('../api/appSlot', () => ({
  versleutelAlsSlotActief: (t: string) => Promise.resolve(slot.anker ? `slot.v1.${btoa(unescape(encodeURIComponent(t)))}` : null),
  ontsleutelSlotWaarde: (w: string) => Promise.resolve(w.startsWith('slot.v1.') ? decodeURIComponent(escape(atob(w.slice(8)))) : null),
}))

import {
  bevrorenConflict,
  bewaarInWachtrij,
  isGeenVerbinding,
  leesWachtrij,
  OFFLINE_DB_NAAM,
  OFFLINE_STORE_NAAM,
  pasWachtrijToe,
  verwijderUitWachtrij,
  verzendWachtrij,
  wisWachtrij,
  type ZetDagPayload,
} from './urenOffline'

const ADM = 'aaaaaaaa-0000-0000-0000-000000000001'
const P1 = 'cccccccc-0000-0000-0000-000000000001'
function payload(over: Partial<ZetDagPayload> = {}): ZetDagPayload {
  return { administratie_id: ADM, project_id: P1, jaar: 2026, weeknummer: 38, datum: '2026-09-15', uren: '8', m2: null, doorfactureren: true, opmerking: 'opbouwen', namens_zzper_id: null, ...over }
}

let fake: ReturnType<typeof installeerFakeIndexedDb>
beforeEach(() => {
  fake = installeerFakeIndexedDb()
  slot.anker = true
})
afterEach(() => fake.herstel())

describe('urenOffline — opslag', () => {
  it('bewaart versleuteld op het slot-anker, vervangt dezelfde dag, verwijdert', async () => {
    await bewaarInWachtrij(payload(), new Date('2026-09-15T16:00:00Z'))
    const rij = await bewaarInWachtrij(payload({ datum: '2026-09-16', uren: '6' }), new Date('2026-09-16T16:00:00Z'))
    expect(rij.map((r) => r.payload.datum)).toEqual(['2026-09-15', '2026-09-16'])
    const ruw = fake.data.get(OFFLINE_DB_NAAM)!.get(OFFLINE_STORE_NAAM)!
    const waarden = [...ruw.entries()].filter(([k]) => k !== '__index__').map(([, v]) => v)
    expect(waarden.every((v) => v.startsWith('slot.v1.'))).toBe(true)
    expect(waarden.some((v) => v.includes('opbouwen'))).toBe(false)
    // Zelfde dag opnieuw = vervangen, geen tweede regel.
    const na = await bewaarInWachtrij(payload({ uren: '4' }))
    expect(na.length).toBe(2)
    expect(na.find((r) => r.payload.datum === '2026-09-15')?.payload.uren).toBe('4')
    const rest = await verwijderUitWachtrij(na[0].sleutel)
    expect(rest.length).toBe(1)
    await wisWachtrij()
    expect(await leesWachtrij()).toEqual([])
  })
  it('zonder actief slot valt de opslag terug op een leesbare plain-waarde (dev), lezen werkt gelijk', async () => {
    slot.anker = false
    await bewaarInWachtrij(payload())
    const ruw = fake.data.get(OFFLINE_DB_NAAM)!.get(OFFLINE_STORE_NAAM)!
    expect([...ruw.values()].some((v) => v.startsWith('plain:'))).toBe(true)
    expect((await leesWachtrij())[0].payload.uren).toBe('8')
  })
})

describe('urenOffline — verzenden', () => {
  it('geen verbinding = TypeError of BackendOnbereikbaar; 409 zonder code is géén bevroren-conflict', () => {
    expect(isGeenVerbinding(new TypeError('Failed to fetch'))).toBe(true)
    expect(isGeenVerbinding(new BackendOnbereikbaarError('netwerk'))).toBe(true)
    expect(isGeenVerbinding(new ApiError(422, 'ongeldig'))).toBe(false)
    expect(bevrorenConflict(new ApiError(409, 'x', { code: 'anders' }))).toBeNull()
    expect(bevrorenConflict(new ApiError(409, 'x', { detail: 'De week is ingediend.', code: 'weekstaat_bevroren', status: 'ingediend', server_regel: null }))?.status).toBe('ingediend')
    // Contract-afwijking 1 (5B): bedragen als strings ("8.00"/"40.00"), tekst nogmaals als `detail`.
    const c = bevrorenConflict(new ApiError(409, 'x', { detail: 'De week is goedgekeurd.', code: 'weekstaat_bevroren', status: 'goedgekeurd', server_regel: { uren: '8.00', m2: '40.00', opmerking: null, doorfactureren: true } }))
    expect(c?.server_regel?.m2).toBe('40.00')
    expect(c?.detail).toBe('De week is goedgekeurd.')
  })
  it('geslaagd = weg; geen verbinding = stoppen mét de rest open', async () => {
    await bewaarInWachtrij(payload({ datum: '2026-09-15' }), new Date('2026-09-15T10:00:00Z'))
    await bewaarInWachtrij(payload({ datum: '2026-09-16' }), new Date('2026-09-16T10:00:00Z'))
    let n = 0
    const uitkomst = await verzendWachtrij(() => {
      n += 1
      return n === 1 ? Promise.resolve({}) : Promise.reject(new TypeError('Failed to fetch'))
    })
    expect(uitkomst.verzonden.map((r) => r.payload.datum)).toEqual(['2026-09-15'])
    expect(uitkomst.geenVerbinding).toBe(true)
    expect(uitkomst.open.map((r) => r.payload.datum)).toEqual(['2026-09-16'])
  })
  it('409 weekstaat_bevroren = conflict mét beide standen, blijft staan, is maar één keer "nieuw"; andere fout blijft zichtbaar', async () => {
    await bewaarInWachtrij(payload({ datum: '2026-09-15' }), new Date('2026-09-15T10:00:00Z'))
    await bewaarInWachtrij(payload({ datum: '2026-09-16' }), new Date('2026-09-16T10:00:00Z'))
    const zend = (p: ZetDagPayload) =>
      p.datum === '2026-09-15'
        ? Promise.reject(new ApiError(409, 'bevroren', { code: 'weekstaat_bevroren', status: 'ingediend', server_regel: { uren: '6', m2: null, opmerking: 'ombouwen', doorfactureren: true } }))
        : Promise.reject(new ApiError(422, 'Uren moeten tussen 0 en 24 liggen.'))
    const eerste = await verzendWachtrij(zend)
    expect(eerste.nieuweConflicten.length).toBe(1)
    expect(eerste.nieuweConflicten[0].conflict?.server_regel?.uren).toBe('6')
    expect(eerste.open.length).toBe(2)
    expect(eerste.open.find((r) => r.payload.datum === '2026-09-16')?.fout).toBe('Uren moeten tussen 0 en 24 liggen.')
    const tweede = await verzendWachtrij(zend)
    expect(tweede.nieuweConflicten.length).toBe(0)
    expect(tweede.open.find((r) => r.payload.datum === '2026-09-15')?.conflict?.status).toBe('ingediend')
  })
})

describe('urenOffline — weergave', () => {
  it('mengt alleen regels van deze week in de kaarten: dag_uren, bolletje per kaart en per dag', async () => {
    const regels = [
      { sleutel: 'a', payload: payload({ datum: '2026-09-15', uren: '8' }), bewaard_op: '1', conflict: null, fout: null },
      { sleutel: 'b', payload: payload({ datum: '2026-09-22', weeknummer: 39, uren: '2' }), bewaard_op: '2', conflict: null, fout: null },
    ]
    const kaart = { administratie_id: ADM, project_id: P1, dag_uren: { '2026-09-14': '8' } } as never
    const uit = pasWachtrijToe([kaart], regels, { jaar: 2026, weeknummer: 38 })
    expect(uit.kaarten[0].dag_uren).toEqual({ '2026-09-14': '8', '2026-09-15': '8' })
    expect(uit.perKaart[`${ADM}|${P1}`]).toEqual(['2026-09-15'])
    expect([...uit.datums]).toEqual(['2026-09-15'])
    expect(uit.regels.length).toBe(1)
  })
})
