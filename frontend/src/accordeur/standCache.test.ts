// Cache-first stand (blok D2 06-09): per gebruiker gescheiden, nooit zonder gebruikers-id, oud of
// afwijkend formaat = genegeerd, lokale verzend_fout reist niet mee, wissen bij sessie-einde.

import { afterEach, beforeAll, describe, expect, it } from 'vitest'
import type { WachtrijItemDto } from './accordeurApi'
import { bewaarStand, leesStand, MAX_LEEFTIJD_MS, verversTekst, wisAlleStanden, wisStand } from './standCache'

// Node 22+ schaduwt window.localStorage in de jsdom-testomgeving met zijn eigen (lege) experimental
// global — in-memory vervanger, zelfde patroon als AccordeurApp.test.tsx.
function inMemoryOpslag(): Storage {
  const opslag = new Map<string, string>()
  return {
    getItem: (sleutel: string) => opslag.get(sleutel) ?? null,
    setItem: (sleutel: string, waarde: string) => void opslag.set(sleutel, String(waarde)),
    removeItem: (sleutel: string) => void opslag.delete(sleutel),
    clear: () => opslag.clear(),
    key: (i: number) => [...opslag.keys()][i] ?? null,
    get length() {
      return opslag.size
    },
  }
}

beforeAll(() => {
  Object.defineProperty(window, 'localStorage', { configurable: true, value: inMemoryOpslag() })
})

const ITEM: WachtrijItemDto = {
  document_id: 'd1',
  administratie_id: 'a1',
  administratie_naam: 'BLOW B.V.',
  leverancier_naam: 'Essent Zakelijk',
  referentie: 'E-1',
  factuurdatum: '2026-07-01',
  totaalbedrag: '847.00',
  aangeboden_op: '2026-07-02T09:00:00Z',
  laag_volgnummer: 1,
  boeking_omschrijving: 'Energie',
  staande_regel_kandidaat: false,
}

afterEach(() => localStorage.clear())

describe('standCache', () => {
  it('bewaart en leest per gebruiker; een andere gebruiker ziet niets (nooit cross-user)', () => {
    const t = bewaarStand('u-1', [ITEM], [], new Date('2026-09-06T08:15:00Z'))
    expect(t).toBe('2026-09-06T08:15:00.000Z')
    const stand = leesStand('u-1', new Date('2026-09-06T09:00:00Z'))
    expect(stand?.items).toEqual([ITEM])
    expect(stand?.tijdstip).toBe(t)
    expect(leesStand('u-2', new Date('2026-09-06T09:00:00Z'))).toBeNull()
  })

  it('zonder gebruikers-id wordt er niets bewaard of gelezen', () => {
    expect(bewaarStand(null, [ITEM], [])).toBeNull()
    expect(localStorage.length).toBe(0)
    expect(leesStand(null)).toBeNull()
  })

  it('stript een lokale verzend_fout (weergavestaat) vóór het bewaren', () => {
    bewaarStand('u-1', [{ ...ITEM, verzend_fout: 'niet verzonden' } as WachtrijItemDto], [])
    const stand = leesStand('u-1')
    expect(stand?.items[0]).not.toHaveProperty('verzend_fout')
  })

  it('negeert een te oude stand en een afwijkend formaat (nooit een halve kaart)', () => {
    const oud = new Date('2026-08-01T08:00:00Z')
    bewaarStand('u-1', [ITEM], [], oud)
    expect(leesStand('u-1', new Date(oud.getTime() + MAX_LEEFTIJD_MS + 1))).toBeNull()
    expect(leesStand('u-1', new Date(oud.getTime() + 1000))).not.toBeNull()
    localStorage.setItem('accordeur-stand:u-3', JSON.stringify({ v: 99, items: [], vragen: [], tijdstip: oud.toISOString() }))
    expect(leesStand('u-3', oud)).toBeNull()
    localStorage.setItem('accordeur-stand:u-4', 'geen json')
    expect(leesStand('u-4')).toBeNull()
  })

  it('wisStand wist gericht, wisAlleStanden wist alle standen maar laat andere sleutels staan', () => {
    bewaarStand('u-1', [ITEM], [])
    bewaarStand('u-2', [ITEM], [])
    localStorage.setItem('accordeur-thema', 'licht')
    wisStand('u-1')
    expect(leesStand('u-1')).toBeNull()
    expect(leesStand('u-2')).not.toBeNull()
    wisAlleStanden()
    expect(leesStand('u-2')).toBeNull()
    expect(localStorage.getItem('accordeur-thema')).toBe('licht')
  })

  it('verversTekst: vandaag alleen de tijd, anders mét datum; onbekend = "nog niet ververst"', () => {
    const nu = new Date(2026, 8, 6, 9, 30)
    expect(verversTekst(new Date(2026, 8, 6, 8, 5).toISOString(), nu)).toBe('laatst ververst 08:05')
    expect(verversTekst(new Date(2026, 8, 5, 17, 45).toISOString(), nu)).toBe('laatst ververst 05-09 17:45')
    expect(verversTekst(null, nu)).toBe('nog niet ververst')
    expect(verversTekst('kapot', nu)).toBe('nog niet ververst')
  })
})
