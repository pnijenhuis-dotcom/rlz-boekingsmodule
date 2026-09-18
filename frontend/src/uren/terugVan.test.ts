/** SPOED 18-09 — Android-terugknop: één scherm terug binnen de uren-flow, nooit de app uit. */
import { describe, expect, it } from 'vitest'
import { terugVan } from './UrenFlow'

const WEEK = { jaar: 2026, weeknummer: 38, maandag: '2026-09-14', zondag: '2026-09-20', is_huidige: true, geplande_projecten: 0, te_doen: 0, status: 'open' as const, totaal_uren: '0', totaal_m2: '0' }
const KAART = { administratie_id: 'a', project_id: 'p', project_naam: 'X' } as never

describe('terugVan', () => {
  it('schermen mét terug gebruiken die; de rest volgt de vaste ouder', () => {
    expect(terugVan({ s: 'daginvoer', ctx: {} as never, datum: 'd', dagNaam: 'ma', bestaand: null, doorfacturerenStandaard: true, chips: [], contractM2: null, terug: { s: 'weekProjecten', week: WEEK } }, 'zzper')).toEqual({ s: 'weekProjecten', week: WEEK })
    expect(terugVan({ s: 'weekProjecten', week: WEEK }, 'zzper')).toEqual({ s: 'zzpWeken' })
    expect(terugVan({ s: 'projectToevoegen', week: WEEK }, 'zzper')).toEqual({ s: 'weekProjecten', week: WEEK })
    expect(terugVan({ s: 'projectdetail', kaart: KAART }, 'uitvoerder')).toEqual({ s: 'uitvProjecten' })
    expect(terugVan({ s: 'keurafwijs', item: {} as never, staat: {} as never }, 'uitvoerder')).toEqual({ s: 'keurdetail', item: {} })
  })
  it('een beginscherm blijft staan (null) — de uitvoerder landt vanuit Mijn uren op Projecten, de ZZP\'er blijft op weken', () => {
    expect(terugVan({ s: 'uitvProjecten' }, 'uitvoerder')).toBeNull()
    expect(terugVan({ s: 'zzpWeken' }, 'zzper')).toBeNull()
    expect(terugVan({ s: 'zzpWeken' }, 'uitvoerder')).toEqual({ s: 'uitvProjecten' })
    expect(terugVan({ s: 'zzpWeken' }, 'detacheerder')).toEqual({ s: 'detaZzpers' })
  })
})
