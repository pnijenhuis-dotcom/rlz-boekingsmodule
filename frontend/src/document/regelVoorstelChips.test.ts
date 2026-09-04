import { describe, expect, it } from 'vitest'
import { bepaalBtwStandaardChip, bepaalGbChip, btwBronUitDto, gbBronUitDto } from './regelVoorstelChips'

describe('regelVoorstelChips — grootboek per regel (blok D 04-09, mockup blok 2)', () => {
  it('geheugen = groene chip "uit geheugen" mét detail in de tooltip', () => {
    const chip = bepaalGbChip('geheugen', '3× bevestigd, laatst 12-08-2026', 'gb-1', false)
    expect(chip).toMatchObject({ klasse: 'ok', tekst: 'uit geheugen' })
    expect(chip?.titel).toContain('3× bevestigd, laatst 12-08-2026')
  })

  it('historie/conflict/AI = oranje chips (bevestigen), deterministisch wint in de tekst van AI', () => {
    expect(bepaalGbChip('geheugen_seed', null, 'gb-1', false)).toMatchObject({ klasse: 'afwijking', tekst: 'uit historie, nog niet bevestigd' })
    expect(bepaalGbChip('geheugen_conflict', null, 'gb-1', false)).toMatchObject({ klasse: 'afwijking', tekst: 'geheugen wisselend — controleer' })
    expect(bepaalGbChip('ai', 'AI koos uit 4 GB', 'gb-1', false)).toMatchObject({ klasse: 'afwijking', tekst: 'AI-voorstel — bevestig' })
  })

  it('geen chip zonder bron, zonder waarde in het veld, of zodra de mens het veld aanraakte', () => {
    expect(bepaalGbChip(null, null, 'gb-1', false)).toBeNull()
    expect(bepaalGbChip('geheugen', null, null, false)).toBeNull()
    expect(bepaalGbChip('ai', null, 'gb-1', true)).toBeNull()
  })

  it('server-waarden worden gevalideerd — onbekend = geen voorstel', () => {
    expect(gbBronUitDto('geheugen')).toBe('geheugen')
    expect(gbBronUitDto('ai')).toBe('ai')
    expect(gbBronUitDto('iets')).toBeNull()
    expect(gbBronUitDto(null)).toBeNull()
    expect(gbBronUitDto(undefined)).toBeNull()
  })
})

describe('regelVoorstelChips — btw-default administratie (blok E 04-09, mockup blok 3)', () => {
  it('standaard = neutrale grijze chip "standaard administratie"', () => {
    expect(bepaalBtwStandaardChip('standaard', 'btw-1', false)).toMatchObject({ klasse: 'handmatig', tekst: 'standaard administratie' })
  })

  it('factuur-bron of aangeraakt veld geeft hier geen chip', () => {
    expect(bepaalBtwStandaardChip('factuur', 'btw-1', false)).toBeNull()
    expect(bepaalBtwStandaardChip('standaard', 'btw-1', true)).toBeNull()
    expect(bepaalBtwStandaardChip('standaard', null, false)).toBeNull()
    expect(bepaalBtwStandaardChip(null, 'btw-1', false)).toBeNull()
  })

  it('btw-bron uit de DTO alleen mét een taxrate in het veld', () => {
    expect(btwBronUitDto('standaard', 'btw-1')).toBe('standaard')
    expect(btwBronUitDto('factuur', 'btw-1')).toBe('factuur')
    expect(btwBronUitDto('standaard', null)).toBeNull()
    expect(btwBronUitDto('geheugen', 'btw-1')).toBeNull()
  })
})
