import { describe, expect, it } from 'vitest'
import {
  bewaarHerkomstStand,
  chipSoort,
  chipZichtbaar,
  leesHerkomstStand,
  periodeIsAanname,
} from './herkomstZichtbaarheid'

describe('herkomstZichtbaarheid (punt 2 "groen = niets tonen", Peter 02-10)', () => {
  it('oranje/rood/vraag = afwijking, altijd zichtbaar', () => {
    for (const k of ['chip afwijking', 'afwijking', 'chip blokkerend', 'blokkerend', 'chip vraag']) {
      expect(chipSoort(k)).toBe('afwijking')
      expect(chipZichtbaar(k, false)).toBe(true)
      expect(chipZichtbaar(k, true)).toBe(true)
    }
  })

  it('groen/grijs/geheugen/stil/neutraal = herkomst, alleen onder "Herkomst tonen"', () => {
    for (const k of ['chip ok', 'ok', 'chip handmatig', 'chip geheugen', 'chip stil', 'chip', '', null, undefined]) {
      expect(chipSoort(k)).toBe('herkomst')
      expect(chipZichtbaar(k, false)).toBe(false)
      expect(chipZichtbaar(k, true)).toBe(true)
    }
  })

  it('altijdTonen maakt een rustige klasse tóch een afwijking (aanname-periode, btw in kosten, samenvoegen niet mogelijk)', () => {
    expect(chipSoort('chip geheugen', true)).toBe('afwijking')
    expect(chipZichtbaar('chip stil', false, true)).toBe(true)
    expect(chipZichtbaar('chip handmatig', false, true)).toBe(true)
  })

  it('periode: alleen de terugval op de factuurdatum is een aanname', () => {
    expect(periodeIsAanname('afgeleid_van_factuurdatum')).toBe(true)
    expect(periodeIsAanname('factuur')).toBe(false)
    expect(periodeIsAanname('factuur_maand')).toBe(false)
    expect(periodeIsAanname('mens')).toBe(false)
    expect(periodeIsAanname(null)).toBe(false)
  })

  it('stand per blok: default dicht, bewaard per browsersessie, weigerende opslag = dicht zonder fout', () => {
    const geheugen = new Map<string, string>()
    const opslag = {
      getItem: (k: string) => geheugen.get(k) ?? null,
      setItem: (k: string, v: string) => void geheugen.set(k, v),
      removeItem: (k: string) => void geheugen.delete(k),
    }
    expect(leesHerkomstStand('crediteur', opslag)).toBe(false)
    bewaarHerkomstStand('crediteur', true, opslag)
    expect(leesHerkomstStand('crediteur', opslag)).toBe(true)
    expect(leesHerkomstStand('regels', opslag)).toBe(false)
    bewaarHerkomstStand('crediteur', false, opslag)
    expect(leesHerkomstStand('crediteur', opslag)).toBe(false)

    const kapot = {
      getItem: () => {
        throw new Error('opslag geblokkeerd')
      },
      setItem: () => {
        throw new Error('opslag geblokkeerd')
      },
      removeItem: () => {
        throw new Error('opslag geblokkeerd')
      },
    }
    expect(leesHerkomstStand('kopgegevens', kapot)).toBe(false)
    expect(() => bewaarHerkomstStand('kopgegevens', true, kapot)).not.toThrow()
  })
})
