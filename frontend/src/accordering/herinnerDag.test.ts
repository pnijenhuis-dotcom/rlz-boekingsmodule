/** Dagrem-spiegel voor de herinner-knop: dezelfde Europe/Amsterdam-kalenderdag als de
 * server (herinnering.py::_vandaag) — inclusief het randgeval waar de UTC-dag verschilt
 * van de Amsterdamse dag. */

import { describe, expect, it } from 'vitest'

import { herinnerTijdLabel, isVandaagHerinnerd } from './herinnerDag'

describe('isVandaagHerinnerd', () => {
  const nu = new Date('2026-08-18T06:00:00Z') // 18-08 08:00 in Amsterdam

  it('zelfde Amsterdamse kalenderdag = vandaag', () => {
    expect(isVandaagHerinnerd('2026-08-18T04:12:00Z', nu)).toBe(true)
  })

  it('UTC-gisteren maar Amsterdam-vandaag telt als vandaag (23:30 UTC = 01:30 CEST)', () => {
    expect(isVandaagHerinnerd('2026-08-17T23:30:00Z', nu)).toBe(true)
  })

  it('Amsterdam-gisteren (21:59 UTC = 23:59 CEST) telt niet als vandaag', () => {
    expect(isVandaagHerinnerd('2026-08-17T21:59:00Z', nu)).toBe(false)
  })

  it('leeg of onleesbaar = niet herinnerd (knop actief)', () => {
    expect(isVandaagHerinnerd(null, nu)).toBe(false)
    expect(isVandaagHerinnerd(undefined, nu)).toBe(false)
    expect(isVandaagHerinnerd('geen-datum', nu)).toBe(false)
  })
})

describe('herinnerTijdLabel', () => {
  it('toont het Amsterdamse tijdstip (CEST = UTC+2)', () => {
    expect(herinnerTijdLabel('2026-08-18T12:05:00Z')).toBe('14:05')
  })
})
