// Koude-start-meting (blok D1 06-09): marks zijn éénmalig per app-run, Server-Timing wordt geparsed
// en het overzicht splitst client-duur in netwerk + server. Puur lokaal — geen fetch, geen server.

import { afterEach, beforeAll, describe, expect, it } from 'vitest'
import { markeer, noteerServerTiming, overzicht, parseServerTiming, resetVoorTests } from './koudeStart'

// Node 22+ schaduwt window.localStorage in de jsdom-testomgeving met zijn eigen (lege) experimental
// global — in-memory vervanger, zelfde patroon als standCache.test.ts (nodig voor de 12a-opslag).
beforeAll(() => {
  const opslag = new Map<string, string>()
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: {
      getItem: (k: string) => opslag.get(k) ?? null,
      setItem: (k: string, v: string) => void opslag.set(k, String(v)),
      removeItem: (k: string) => void opslag.delete(k),
      clear: () => opslag.clear(),
      key: (i: number) => [...opslag.keys()][i] ?? null,
      get length() {
        return opslag.size
      },
    } as Storage,
  })
})

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

// Blok 12a (07-09): de afgeronde meting wordt lokaal bewaard (geen PII, nooit naar de server) en
// de diagnoseregel is één leesbare, kopieerbare regel mét bundelversie.
import { KOUDE_START_OPSLAG_SLEUTEL, WEB_BUILD_ID, diagnoseRegel, leesLaatsteKoudeStart, type BewaardeKoudeStart } from './koudeStart'
import { APP_MARKETING_VERSIE } from './appVersie'

describe('laatste koude start bewaren + diagnoseregel (12a)', () => {
  it('kaarten-render bewaart de meting in localStorage; leesLaatsteKoudeStart geeft haar terug', () => {
    expect(leesLaatsteKoudeStart()).toBeNull()
    markeer('app-render')
    markeer('sessie')
    markeer('wachtrij-start')
    markeer('wachtrij-klaar')
    noteerServerTiming('wachtrij', 'wachtrij;dur=12')
    markeer('kaarten-render')
    const bewaard = leesLaatsteKoudeStart()
    expect(bewaard).not.toBeNull()
    expect(bewaard?.versie).toBe(1)
    expect(bewaard?.build).toBe(WEB_BUILD_ID)
    expect(bewaard?.overzicht.stappen['kaarten-render']).toBeTypeOf('number')
    expect(bewaard?.overzicht.server.wachtrij).toBe(12)
    // Geen gebruikers- of documentgegevens in de opslag — alleen tijden/versie.
    const ruw = localStorage.getItem(KOUDE_START_OPSLAG_SLEUTEL) ?? ''
    expect(Object.keys(JSON.parse(ruw) as object).sort()).toEqual(['build', 'overzicht', 'tijdstip', 'versie'])
  })

  it('een onleesbaar of verouderd record telt als "geen meting"', () => {
    localStorage.setItem(KOUDE_START_OPSLAG_SLEUTEL, '{rommel')
    expect(leesLaatsteKoudeStart()).toBeNull()
    localStorage.setItem(KOUDE_START_OPSLAG_SLEUTEL, JSON.stringify({ versie: 0, tijdstip: 'x', overzicht: { stappen: {} } }))
    expect(leesLaatsteKoudeStart()).toBeNull()
  })

  it('diagnoseRegel: boot / sessie / server / netwerk / totaal in ms + build + tijdstip; ontbrekend = "–"', () => {
    const meting: BewaardeKoudeStart = {
      versie: 1,
      tijdstip: '2026-09-07T13:05:00',
      build: 'abc1234-20260907-1500',
      overzicht: {
        stappen: { 'app-render': 410, sessie: 2240, 'wachtrij-start': 2250, 'wachtrij-klaar': 2800, 'kaarten-render': 2900 },
        server: { wachtrij: 240 },
        afgeleid: { wachtrijClientMs: 550, wachtrijNetwerkMs: 310, totTotEersteKaartenMs: 2900 },
      },
    }
    expect(diagnoseRegel(meting, '1.0 (45)')).toBe(
      'web abc1234-20260907-1500 · app 1.0 (45) · boot 410 ms · sessie 1830 ms · server 240 ms · netwerk 310 ms · totaal 2900 ms · 07-09 13:05',
    )
    // Zonder native build (PWA/browser): marketingversie uit appVersie.ts als "app 1.1 (web)" (mini-run 09-09);
    // zonder server-header "–" waar de meting ontbreekt.
    const kaal: BewaardeKoudeStart = { ...meting, overzicht: { stappen: { 'app-render': 300 }, server: {}, afgeleid: {} } }
    expect(diagnoseRegel(kaal)).toBe(
      `web abc1234-20260907-1500 · app ${APP_MARKETING_VERSIE} (web) · boot 300 ms · sessie – · server – · netwerk – · totaal – · 07-09 13:05`,
    )
    expect(diagnoseRegel(null)).toBe(`web ${WEB_BUILD_ID} · app ${APP_MARKETING_VERSIE} (web) · nog geen koude start gemeten`)
  })
})

// Blok 2b (08-09): laatste verbindingsfout van het slot lokaal bewaard en als staart in de diagnoseregel.
describe('laatste verbindingsfout (blok 2b 08-09)', () => {
  it('bewaren → lezen → staart in de diagnoseregel (oorzaak, ruwe melding, tijdstip); zonder fout geen staart', async () => {
    const { bewaarLaatsteVerbindingsfout, leesLaatsteVerbindingsfout, diagnoseRegel: regel, resetVoorTests } = await import('./koudeStart')
    resetVoorTests()
    expect(leesLaatsteVerbindingsfout()).toBeNull()
    expect(regel(null)).not.toContain('verbindingsfout')
    bewaarLaatsteVerbindingsfout({ oorzaak: 'netwerk', technisch: 'TypeError: Load failed', pad: '/auth/token/vernieuwen' })
    const fout = leesLaatsteVerbindingsfout()
    expect(fout?.oorzaak).toBe('netwerk')
    expect(fout?.pad).toBe('/auth/token/vernieuwen')
    expect(fout?.technisch).toBe('TypeError: Load failed')
    const tekst = regel(null, '1.0 (89)', { ...fout!, tijdstip: '2026-09-08T10:12:00' })
    expect(tekst).toBe(`web ${WEB_BUILD_ID} · app 1.0 (89) · nog geen koude start gemeten · laatste verbindingsfout: netwerk (TypeError: Load failed) 08-09 10:12`)
    // Onleesbaar record = geen fout.
    localStorage.setItem('accordeur-laatste-verbindingsfout', '{"versie":2}')
    expect(leesLaatsteVerbindingsfout()).toBeNull()
  })
})
