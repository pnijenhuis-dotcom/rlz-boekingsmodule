import { describe, expect, it } from 'vitest'
import { isKopDoorgezetNotitie, kopDoorgezetTijdlijnTekst } from './kopDoorgezetTijdlijn'

describe('kopDoorgezetTijdlijn (FV-07, 25-09)', () => {
  it('herkent de notitie en leest project + btw', () => {
    const detail = { kop_doorgezet: { project: 3, project_naam: '26127 Tilburg (Heijmans)', btw: 3, btw_code: '21% · NL Hoog' } }
    expect(isKopDoorgezetNotitie(detail)).toBe(true)
    expect(kopDoorgezetTijdlijnTekst(detail)).toBe('Kop → regels: project ‹26127 Tilburg (Heijmans)› op 3 regels · btw ‹21% · NL Hoog› op 3 regels')
  })
  it('alleen btw, zonder code', () => {
    expect(kopDoorgezetTijdlijnTekst({ kop_doorgezet: { btw: 1 } })).toBe('Kop → regels: btw op 1 regel')
    expect(isKopDoorgezetNotitie({ kop_omschrijving: {} })).toBe(false)
  })
})
