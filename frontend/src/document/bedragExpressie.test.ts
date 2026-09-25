import { describe, expect, it } from 'vitest'
import { evalueerBedragExpressie, formatBedragInvoer, isExpressie } from './bedragExpressie'

describe('bedragExpressie (FV-08 — rekenen in bedragvelden, eigen parser, geen eval)', () => {
  it.each([
    ['20+30', 50],
    ['20 + 30', 50],
    ['1.250,50*2', 2501],
    ['100/3', 33.33],
    ['(10+5)*2', 30],
    ['10+5*2', 20],
    ['-5+10', 5],
    ['2*(3+4)-1', 13],
    ['12,5+7,5', 20],
    ['0,1+0,2', 0.3],
    ['1234.56+1', 1235.56],
    ['10/4', 2.5],
    ['2,005*1', 2.01],
  ])('%s → %s', (invoer, verwacht) => {
    expect(evalueerBedragExpressie(invoer)).toBe(verwacht)
  })

  it.each(['abc', '20+', '+', '(20+30', '20+30)', '10/0', '', '20 30', '1.2.3+1'])('ongeldig: %s → null', (invoer) => {
    expect(evalueerBedragExpressie(invoer)).toBeNull()
  })

  it('kaal getal is geen expressie', () => {
    expect(isExpressie('1234,56')).toBe(false)
    expect(isExpressie('1.234,56')).toBe(false)
    expect(isExpressie('1234.56')).toBe(false)
    expect(isExpressie('')).toBe(false)
    expect(isExpressie('20+30')).toBe(true)
    expect(isExpressie('(10+5)*2')).toBe(true)
  })

  it('formatteert NL', () => {
    expect(formatBedragInvoer(2501)).toBe('2501,00')
    expect(formatBedragInvoer(33.33)).toBe('33,33')
  })
})
