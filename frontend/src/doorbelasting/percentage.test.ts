import { describe, expect, it } from 'vitest'
import {
  bedragNaarPercentage,
  formatPct,
  parsePercentage,
  percentageNaarBedrag,
  percentageVoorBackend,
  restPercentage,
  restantStand,
  somPercentages,
} from './percentage'

describe('parsePercentage (bugfix 02-09: 0–100, max 2 decimalen, komma óf punt)', () => {
  it('accepteert gehele en decimale percentages met komma of punt', () => {
    expect(parsePercentage('60')).toEqual({ waarde: 60, fout: null })
    expect(parsePercentage('33,33')).toEqual({ waarde: 33.33, fout: null })
    expect(parsePercentage('33.3')).toEqual({ waarde: 33.3, fout: null })
    expect(parsePercentage(' 100 ')).toEqual({ waarde: 100, fout: null })
    expect(parsePercentage('0')).toEqual({ waarde: 0, fout: null })
  })

  it('leeg = geen waarde en geen fout', () => {
    expect(parsePercentage('')).toEqual({ waarde: null, fout: null })
    expect(parsePercentage('   ')).toEqual({ waarde: null, fout: null })
  })

  it('weigert de parse-bug-invoer ("1110000", geplakt "11.100,00") mét uitleg — nooit doorgerekend', () => {
    expect(parsePercentage('1110000').fout).toMatch(/geen geldig percentage/)
    expect(parsePercentage('11.100,00').fout).toMatch(/geen geldig percentage/)
    expect(parsePercentage('11.100,00').waarde).toBeNull()
    expect(parsePercentage('1,234').fout).toMatch(/hooguit 2 decimalen/)
    expect(parsePercentage('abc').waarde).toBeNull()
    expect(parsePercentage('-5').waarde).toBeNull()
  })

  it('weigert boven 100', () => {
    expect(parsePercentage('101').fout).toMatch(/buiten 0–100/)
    expect(parsePercentage('100,01').fout).toMatch(/buiten 0–100/)
  })

  it('levert een punt-decimale string voor de backend', () => {
    expect(percentageVoorBackend('33,33')).toBe('33.33')
    expect(percentageVoorBackend('50')).toBe('50')
    expect(percentageVoorBackend('1110000')).toBeNull()
  })
})

describe('sommen en rest (floating-point-ruis verdwijnt)', () => {
  it('rest van 88,9 is exact 11,1 — niet 11,099999999999994 (de oorspronkelijke bug)', () => {
    expect(restPercentage(['88,9'])).toBe(11.1)
    expect(formatPct(restPercentage(['88,9']))).toBe('11,1')
    expect(String(100 - 88.9)).not.toBe('11.1') // de ruwe berekening die de bug veroorzaakte
  })

  it('somt met 2 decimalen en telt ongeldige invoer als 0', () => {
    expect(somPercentages(['33,33', '33,33', '33.34'])).toBe(100)
    expect(somPercentages(['60', 'abc', ''])).toBe(60)
    expect(restPercentage(['60'])).toBe(40)
    expect(restPercentage(['60', '60'])).toBe(0) // 120 % → niets meer te verdelen, balk toont 'te veel'
  })

  it('restantStand kent drie standen', () => {
    expect(restantStand(100)).toBe('compleet')
    expect(restantStand(60)).toBe('open')
    expect(restantStand(110)).toBe('te_veel')
  })
})

describe('% ↔ bedrag (live gekoppeld, indicatief — centen bindend server-side)', () => {
  it('percentage naar bedrag rondt op centen', () => {
    expect(percentageNaarBedrag(691, 60)).toBe(414.6)
    expect(percentageNaarBedrag(691, 33.33)).toBe(230.31)
  })

  it('bedrag naar percentage met komma of punt; leeg regelbedrag = null', () => {
    expect(bedragNaarPercentage(691, '414,60')).toBe(60)
    expect(bedragNaarPercentage(691, '414.6')).toBe(60)
    expect(bedragNaarPercentage(691, '760,10')).toBe(110)
    expect(bedragNaarPercentage(0, '10')).toBeNull()
    expect(bedragNaarPercentage(691, '')).toBeNull()
    expect(bedragNaarPercentage(691, '1.234,56')).toBeNull()
  })
})
