import { describe, expect, it } from 'vitest'
import { PROJECTKLEUR_AANTAL, projectKleurIndex, projectKleurSleutel, projectKleurVar, splitsProjectnummer } from './projectKleur'

/** Run B punt 25 (Peter 02-10): stabiele projectkleur per rij — hash(projectnummer) → palet van 8. */
describe('projectKleur — deterministische accentkleur per project', () => {
  it('splitst het projectnummer van de naam (ook ná "Afgesloten"), zonder nummer blijft de naam heel', () => {
    expect(splitsProjectnummer('25147 Hoofddorp (Grunsven)')).toEqual({ voorvoegsel: '', nummer: '25147', rest: ' Hoofddorp (Grunsven)' })
    expect(splitsProjectnummer('Afgesloten 25147 Hoofddorp')).toEqual({ voorvoegsel: 'Afgesloten ', nummer: '25147', rest: ' Hoofddorp' })
    expect(splitsProjectnummer('144 Breda (Moeskops)')).toEqual({ voorvoegsel: '', nummer: '144', rest: ' Breda (Moeskops)' })
    expect(splitsProjectnummer('Kantoor algemeen')).toEqual({ voorvoegsel: '', nummer: null, rest: 'Kantoor algemeen' })
    expect(splitsProjectnummer(null)).toEqual({ voorvoegsel: '', nummer: null, rest: '' })
  })

  it('sleutel = nummer (naam-suffix en afsluit-voorvoegsel doen er niet toe), anders de genormaliseerde naam', () => {
    expect(projectKleurSleutel('25147 Hoofddorp')).toBe('25147')
    expect(projectKleurSleutel('Afgesloten 25147 Hoofddorp — fase 2')).toBe('25147')
    expect(projectKleurSleutel('  Kantoor   Algemeen ')).toBe('kantoor algemeen')
  })

  it('is stabiel: zelfde nummer = zelfde index, ongeacht de rest van de naam; index altijd binnen het palet', () => {
    const a = projectKleurIndex('25147 Hoofddorp (Grunsven)')
    expect(projectKleurIndex('25147 Hoofddorp — nieuwe naam')).toBe(a)
    expect(projectKleurIndex('Afgesloten 25147 Hoofddorp')).toBe(a)
    expect(a).toBeGreaterThanOrEqual(0)
    expect(a).toBeLessThan(PROJECTKLEUR_AANTAL)
    expect(projectKleurVar('25147 Hoofddorp')).toBe(`var(--projectkleur-${a})`)
  })

  it('verdeelt opeenvolgende projectnummers over álle acht tinten (geen dode kleuren) en buren verschillen meestal', () => {
    const gezien = new Set<number>()
    for (let n = 26100; n < 26200; n++) gezien.add(projectKleurIndex(`${n} Project ${n}`))
    expect(gezien.size).toBe(PROJECTKLEUR_AANTAL)
    let verschillend = 0
    for (let n = 26100; n < 26199; n++) if (projectKleurIndex(`${n}`) !== projectKleurIndex(`${n + 1}`)) verschillend++
    expect(verschillend).toBeGreaterThanOrEqual(80)
  })
})
