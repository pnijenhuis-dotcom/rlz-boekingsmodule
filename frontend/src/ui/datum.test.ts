import { describe, expect, it } from 'vitest'
import {
  binnenGrenzen,
  dateNaarIso,
  isoNaarWeergave,
  maskeerDatumInvoer,
  weergaveNaarIso,
} from './datum'

describe('maskeerDatumInvoer', () => {
  it('maskeert cijfers naar dd-mm-jjjj tijdens het typen', () => {
    expect(maskeerDatumInvoer('7')).toBe('7')
    expect(maskeerDatumInvoer('0708')).toBe('07-08')
    expect(maskeerDatumInvoer('07082026')).toBe('07-08-2026')
  })

  it('negeert niet-cijfers en knipt af op 8 cijfers', () => {
    expect(maskeerDatumInvoer('07/08/2026!!')).toBe('07-08-2026')
    expect(maskeerDatumInvoer('070820269999')).toBe('07-08-2026')
  })
})

describe('weergaveNaarIso', () => {
  it('vertaalt geldige weergave naar ISO', () => {
    expect(weergaveNaarIso('07-08-2026')).toBe('2026-08-07')
  })

  it('weigert niet-bestaande kalenderdagen', () => {
    expect(weergaveNaarIso('31-02-2026')).toBeNull()
    expect(weergaveNaarIso('00-01-2026')).toBeNull()
  })

  it('weigert halve invoer', () => {
    expect(weergaveNaarIso('07-08-26')).toBeNull()
    expect(weergaveNaarIso('')).toBeNull()
  })
})

describe('isoNaarWeergave', () => {
  it('vertaalt ISO naar dd-mm-jjjj en null/rommel naar leeg', () => {
    expect(isoNaarWeergave('2026-08-07')).toBe('07-08-2026')
    expect(isoNaarWeergave(null)).toBe('')
    expect(isoNaarWeergave('geen-datum')).toBe('')
  })
})

describe('binnenGrenzen', () => {
  it('toetst lexicografisch (correct voor jjjj-mm-dd)', () => {
    expect(binnenGrenzen('2026-08-07', '2026-01-01', '2026-12-31')).toBe(true)
    expect(binnenGrenzen('2025-12-31', '2026-01-01', undefined)).toBe(false)
    expect(binnenGrenzen('2027-01-01', undefined, '2026-12-31')).toBe(false)
  })
})

describe('dateNaarIso', () => {
  it('gebruikt lokale datum, geen UTC-verschuiving', () => {
    expect(dateNaarIso(new Date(2026, 7, 7))).toBe('2026-08-07')
    expect(dateNaarIso(new Date(2026, 0, 1))).toBe('2026-01-01')
  })
})
