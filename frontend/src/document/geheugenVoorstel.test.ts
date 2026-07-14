import { describe, expect, it } from 'vitest'
import type { GeheugenVeldVoorstelDto, GeheugenVoorstelDto } from '../api/types'
import { bepaalGeheugenChip, bepaalPrefill, korteReden, omschrijvingSleutel } from './geheugenVoorstel'

const GB = 'aaaaaaaa-0000-0000-0000-00000000000a'
const BTW = 'bbbbbbbb-0000-0000-0000-00000000000b'
const PROJECT = 'cccccccc-0000-0000-0000-00000000000c'
const ANDER = 'dddddddd-0000-0000-0000-00000000000d'

function veld(waarde: string | null, extra: Partial<GeheugenVeldVoorstelDto> = {}): GeheugenVeldVoorstelDto {
  return { waarde, confidence: 0.9, telling: 3, oranje: false, reden: null, app_bevestigd: true, ...extra }
}

function voorstel(overrides: Partial<GeheugenVoorstelDto> = {}): GeheugenVoorstelDto {
  return { gb: veld(GB), btw: veld(BTW), project: veld(PROJECT), ...overrides }
}

const GEEN_HANDMATIG = { ledgerId: false, taxrateId: false, projectId: false }

function regel(overrides: Partial<Parameters<typeof bepaalPrefill>[0]> = {}) {
  return { ledgerId: null, taxrateId: null, projectId: null, handmatigeVelden: GEEN_HANDMATIG, ...overrides }
}

describe('omschrijvingSleutel', () => {
  it('trimt en maakt van een lege omschrijving null (leverancier-niveau)', () => {
    expect(omschrijvingSleutel('  Steigerhuur wk 23  ')).toBe('Steigerhuur wk 23')
    expect(omschrijvingSleutel('')).toBeNull()
    expect(omschrijvingSleutel('   ')).toBeNull()
  })
})

describe('bepaalPrefill', () => {
  it('vult alleen lege, niet-handmatige velden (project alleen bij projectplicht)', () => {
    expect(bepaalPrefill(regel(), voorstel(), true)).toEqual({ ledgerId: GB, taxrateId: BTW, projectId: PROJECT })
    expect(bepaalPrefill(regel(), voorstel(), false)).toEqual({ ledgerId: GB, taxrateId: BTW })
  })

  it('overschrijft nooit een al gevuld veld', () => {
    expect(bepaalPrefill(regel({ ledgerId: ANDER, taxrateId: ANDER }), voorstel(), false)).toEqual({})
  })

  it('vult een handmatig aangeraakt veld niet, ook niet als het leeg is', () => {
    const aangeraakt = regel({ handmatigeVelden: { ledgerId: true, taxrateId: false, projectId: true } })
    expect(bepaalPrefill(aangeraakt, voorstel(), true)).toEqual({ taxrateId: BTW })
  })

  it('vult niets zonder geheugen-waarde', () => {
    expect(bepaalPrefill(regel(), voorstel({ gb: veld(null), btw: veld(null), project: veld(null) }), true)).toEqual({})
  })
})

describe('bepaalGeheugenChip', () => {
  it('geen chip zonder geheugen-waarde', () => {
    expect(bepaalGeheugenChip(veld(null), null, false)).toBeNull()
  })

  it('bevestigd (rustig) als de huidige waarde het geheugen volgt, met de oranje-vlag van de backend', () => {
    expect(bepaalGeheugenChip(veld(GB), GB, false)).toEqual({
      soort: 'bevestigd',
      oranje: false,
      telling: 3,
      confidence: 0.9,
      reden: null,
    })
    const oranje = veld(GB, { oranje: true, reden: 'gesplitste stem', telling: 1, confidence: 0.55 })
    expect(bepaalGeheugenChip(oranje, GB, true)).toMatchObject({ soort: 'bevestigd', oranje: true, reden: 'gesplitste stem' })
  })

  it('afwijkend (oranje markeren, niet overnemen) als extractie/opgeslagen waarde afwijkt', () => {
    expect(bepaalGeheugenChip(veld(GB), ANDER, false)).toEqual({
      soort: 'afwijkend',
      waarde: GB,
      telling: 3,
      confidence: 0.9,
    })
  })

  it('geen chip als de gebruiker het veld zelf anders koos — handmatige keuze wordt nooit genagd', () => {
    expect(bepaalGeheugenChip(veld(GB), ANDER, true)).toBeNull()
    expect(bepaalGeheugenChip(veld(GB), null, true)).toBeNull()
  })
})

describe('korteReden', () => {
  it('compacteert de lange engine-redenen tot chip-hints', () => {
    expect(korteReden('alleen rlz-historie, nog geen app-bevestiging')).toBe('uit historie, nog niet bevestigd')
    expect(korteReden('leverancier-fallback; gesplitste stem')).toBe('btw via leverancier-niveau; gesplitste stem')
    expect(korteReden(null)).toBeNull()
  })
})
