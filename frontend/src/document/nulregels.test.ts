import { describe, expect, it } from 'vitest'
import type { AiVoorstel } from './aiVoorstel'
import { aantalTariefstaffels, boekbareAiRegels, isTariefstaffelRegel } from './nulregels'
import { bepaalBtwHerkomstChip, bepaalBtwStandaardChip, btwBronUitDto } from './regelVoorstelChips'

/** Blok 4 (08-09, Spot Services 2026-608): tariefstaffel-regels zijn geen boekingsregel; btw-verlegd-chip. */

function regel(o: Record<string, unknown>) {
  return { omschrijving: 'r', netto_bedrag: '0.00', btw_bedrag: '0.00', hoeveelheid: '0', taxrate_id: null, ...o }
}

describe('nulregels — tariefstaffels (blok 4a)', () => {
  it('server-vlag wint; zonder vlag hetzelfde predicaat (aantal 0/leeg, netto 0, btw 0/leeg)', () => {
    expect(isTariefstaffelRegel(regel({ tariefstaffel: true, netto_bedrag: '10.00' }))).toBe(true)
    expect(isTariefstaffelRegel(regel({ tariefstaffel: false }))).toBe(false)
    expect(isTariefstaffelRegel(regel({}))).toBe(true)
    expect(isTariefstaffelRegel(regel({ hoeveelheid: '0,00', btw_bedrag: null }))).toBe(true)
    expect(isTariefstaffelRegel(regel({ hoeveelheid: '' }))).toBe(true)
  })

  it('negatieve regels, gratis leveringen en regels zonder gelezen netto blijven', () => {
    expect(isTariefstaffelRegel(regel({ netto_bedrag: '-56.44' }))).toBe(false)
    expect(isTariefstaffelRegel(regel({ hoeveelheid: '1' }))).toBe(false)
    expect(isTariefstaffelRegel(regel({ netto_bedrag: null }))).toBe(false)
  })

  it('boekbare regels houden hun eigen zekerheid; louter nulregels blijven staan', () => {
    const ai = {
      bron: 'ai',
      regels: [regel({ omschrijving: 'echt', netto_bedrag: '100.00', hoeveelheid: '2' }), regel({}), regel({ omschrijving: 'echt 2', netto_bedrag: '50.00', hoeveelheid: '1' })],
      regel_zekerheid: [0.9, 0.5, 0.7],
    } as unknown as AiVoorstel
    const boekbaar = boekbareAiRegels(ai)
    expect(boekbaar.map((x) => x.regel.omschrijving)).toEqual(['echt', 'echt 2'])
    expect(boekbaar.map((x) => x.zekerheid)).toEqual([0.9, 0.7])
    expect(aantalTariefstaffels(ai)).toBe(1)
    const alleenNul = { bron: 'ai', regels: [regel({}), regel({})], regel_zekerheid: [0.9, 0.9] } as unknown as AiVoorstel
    expect(boekbareAiRegels(alleenNul)).toHaveLength(2)
  })
})

describe('regelVoorstelChips — btw verlegd uit de factuur (blok 4c)', () => {
  it('factuur_verlegd = oranje chip "uit factuur: btw verlegd", weg zodra de mens het veld aanraakt', () => {
    expect(btwBronUitDto('factuur_verlegd', 'tr-9')).toBe('factuur_verlegd')
    expect(btwBronUitDto('factuur_verlegd', null)).toBeNull()
    const chip = bepaalBtwHerkomstChip('factuur_verlegd', 'tr-9', false)
    expect(chip).toMatchObject({ klasse: 'afwijking', tekst: 'uit factuur: btw verlegd' })
    expect(chip?.titel).toContain('verlegd')
    expect(bepaalBtwHerkomstChip('factuur_verlegd', 'tr-9', true)).toBeNull()
    expect(bepaalBtwHerkomstChip('factuur_verlegd', null, false)).toBeNull()
  })

  it('standaard blijft de grijze chip (compat-naam werkt); berekend-factuur geeft hier geen chip', () => {
    expect(bepaalBtwStandaardChip('standaard', 'tr-1', false)).toMatchObject({ klasse: 'handmatig', tekst: 'standaard administratie' })
    expect(bepaalBtwHerkomstChip('factuur', 'tr-1', false)).toBeNull()
  })
})
