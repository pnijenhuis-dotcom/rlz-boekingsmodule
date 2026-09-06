// Koude-start-meting (blok D1 06-09): marks zijn éénmalig per app-run, Server-Timing wordt geparsed
// en het overzicht splitst client-duur in netwerk + server. Puur lokaal — geen fetch, geen server.

import { afterEach, describe, expect, it } from 'vitest'
import { markeer, noteerServerTiming, overzicht, parseServerTiming, resetVoorTests } from './koudeStart'

afterEach(() => resetVoorTests())

describe('parseServerTiming', () => {
  it('leest dur-metrics uit één of meer entries; rommel wordt genegeerd', () => {
    expect(parseServerTiming('wachtrij;dur=12.3')).toEqual([{ naam: 'wachtrij', duurMs: 12.3 }])
    expect(parseServerTiming('db;dur=4, wachtrij;dur=31;desc="x"')).toEqual([
      { naam: 'db', duurMs: 4 },
      { naam: 'wachtrij', duurMs: 31 },
    ])
    expect(parseServerTiming('cache;hit')).toEqual([])
    expect(parseServerTiming(null)).toEqual([])
    expect(parseServerTiming('')).toEqual([])
  })
})

describe('markeer + overzicht', () => {
  it('registreert stappen als ms sinds navigatiestart en zet performance-marks', () => {
    markeer('app-render')
    markeer('wachtrij-start')
    markeer('wachtrij-klaar')
    const o = overzicht()
    expect(o.stappen['app-render']).toBeTypeOf('number')
    expect(o.afgeleid.wachtrijClientMs).toBeGreaterThanOrEqual(0)
    expect(performance.getEntriesByName('acc:app-render', 'mark')).toHaveLength(1)
  })

  it('een tweede markering van dezelfde stap telt niet (een verversing is geen koude start)', () => {
    markeer('wachtrij-start')
    const eerste = overzicht().stappen['wachtrij-start']
    markeer('wachtrij-start')
    expect(overzicht().stappen['wachtrij-start']).toBe(eerste)
    expect(performance.getEntriesByName('acc:wachtrij-start', 'mark')).toHaveLength(1)
  })

  it('splitst de wachtrij-duur in server (header) en netwerk (rest), nooit negatief', () => {
    markeer('wachtrij-start')
    markeer('wachtrij-klaar')
    noteerServerTiming('wachtrij', 'wachtrij;dur=0.5')
    const o = overzicht()
    expect(o.server.wachtrij).toBe(0.5)
    expect(o.afgeleid.wachtrijNetwerkMs).toBeGreaterThanOrEqual(0)
    // Alleen de eigen route telt; een tweede header overschrijft niet.
    noteerServerTiming('wachtrij', 'wachtrij;dur=99')
    expect(overzicht().server.wachtrij).toBe(0.5)
    noteerServerTiming('vragen', 'wachtrij;dur=99')
    expect(overzicht().server.vragen).toBeUndefined()
  })

  it('kaarten-render sluit de meting af mét performance.measure en window.__koudeStart (dev)', () => {
    markeer('app-render')
    markeer('sessie')
    markeer('kaarten-render')
    expect(performance.getEntriesByName('acc:app-render→sessie', 'measure')).toHaveLength(1)
    const w = window as { __koudeStart?: { stappen: Record<string, number> } }
    expect(w.__koudeStart?.stappen['kaarten-render']).toBeTypeOf('number')
  })
})
