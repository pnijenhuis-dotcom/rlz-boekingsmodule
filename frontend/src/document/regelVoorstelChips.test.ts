import { describe, expect, it } from 'vitest'
import {
  bepaalBtwStandaardChip,
  bepaalGbChip,
  bepaalOverstapChip,
  bepaalProjectFactuurChip,
  btwBronUitDto,
  gbBronUitDto,
  overstapVertalingUitDto,
  projectBronUitDto,
} from './regelVoorstelChips'

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
    // blok 6 herstelrun 08-09: de herkomst van de verlegd-keuze reist mee in de chip
    expect(bepaalBtwStandaardChip('factuur_verlegd', 'btw-1', false, 'meest gebruikt in RLZ-historie (12×)')).toMatchObject({
      klasse: 'afwijking',
      tekst: 'uit factuur: btw verlegd — meest gebruikt in RLZ-historie (12×)',
    })
    expect(bepaalBtwStandaardChip('factuur_verlegd', 'btw-1', false)).toMatchObject({ tekst: 'uit factuur: btw verlegd' })
    expect(bepaalBtwStandaardChip('factuur_verlegd', 'btw-1', true, 'voorkeur beheerder')).toBeNull()
  })

  it('btw-bron uit de DTO alleen mét een taxrate in het veld', () => {
    expect(btwBronUitDto('standaard', 'btw-1')).toBe('standaard')
    expect(btwBronUitDto('factuur', 'btw-1')).toBe('factuur')
    expect(btwBronUitDto('standaard', null)).toBeNull()
    expect(btwBronUitDto('geheugen', 'btw-1')).toBeNull()
  })
})

describe('regelVoorstelChips — overstap-vertaling van een open voorstel (Odoo-slotstuk 04-09, C1 hervertaling)', () => {
  const VERTAALD = { van_id: 'rlz-4304', van_code: '4304', van_naam: 'Brandstof auto', naar_id: 'odoo-430400', naar_code: '430400', naar_naam: 'Brandstof' }
  const LEEG = { van_id: 'rlz-7000', van_code: '7000', van_naam: 'Inkoop onderaanneming', naar_id: null, reden: 'geen Odoo-tegenhanger in de mapping bij de overstap' }

  it('vertaald én veld draagt nog de Odoo-waarde = oranje "vertaald bij overstap" mét RLZ → Odoo in de tooltip', () => {
    const chip = bepaalOverstapChip(VERTAALD, 'grootboek', 'odoo-430400', false)
    expect(chip).toMatchObject({ klasse: 'afwijking', tekst: 'vertaald bij overstap' })
    expect(chip?.titel).toContain('Reeleezee 4304 Brandstof auto → Odoo 430400 Brandstof')
    expect(chip?.titel).toContain('controleer en boek')
  })

  it('niet vertaalbaar én veld leeg = rode "niet vertaalbaar bij overstap — kies" mét de serverreden als tooltip', () => {
    const chip = bepaalOverstapChip(LEEG, 'btw', null, false)
    expect(chip).toMatchObject({ klasse: 'blokkerend', tekst: 'niet vertaalbaar bij overstap — kies' })
    expect(chip?.titel).toContain('geen Odoo-tegenhanger in de mapping bij de overstap')
    expect(chip?.titel).toContain('btw-tarief')
  })

  it('geen chip zonder spoor, zodra de mens het veld aanraakte, of als er iets anders in het veld staat dan de vertaling', () => {
    expect(bepaalOverstapChip(null, 'grootboek', 'odoo-430400', false)).toBeNull()
    expect(bepaalOverstapChip(undefined, 'project', null, false)).toBeNull()
    expect(bepaalOverstapChip(VERTAALD, 'grootboek', 'odoo-430400', true)).toBeNull()
    expect(bepaalOverstapChip(VERTAALD, 'grootboek', 'odoo-ander', false)).toBeNull()
    expect(bepaalOverstapChip(VERTAALD, 'grootboek', null, false)).toBeNull()
    // Onvertaalbaar maar de mens (of het geheugen) heeft al iets gekozen: niets meer te melden.
    expect(bepaalOverstapChip(LEEG, 'btw', 'odoo-21', false)).toBeNull()
    expect(bepaalOverstapChip(LEEG, 'btw', null, true)).toBeNull()
  })

  it('overstapVertalingUitDto valideert de server-JSON per veld; rommel of leeg = geen spoor', () => {
    const spoor = overstapVertalingUitDto({ op: '2026-09-04T20:00:00Z', grootboek: VERTAALD, btw: LEEG, project: null })
    expect(spoor?.grootboek).toMatchObject({ van_code: '4304', naar_id: 'odoo-430400' })
    expect(spoor?.btw).toMatchObject({ naar_id: null, reden: LEEG.reden })
    expect(spoor?.project).toBeUndefined()
    expect(spoor?.op).toBe('2026-09-04T20:00:00Z')
    expect(overstapVertalingUitDto(null)).toBeNull()
    expect(overstapVertalingUitDto(undefined)).toBeNull()
    expect(overstapVertalingUitDto('tekst')).toBeNull()
    expect(overstapVertalingUitDto({ op: 'x' })).toBeNull()
    expect(overstapVertalingUitDto({ grootboek: 'geen object' })).toBeNull()
  })
})

describe('regelVoorstelChips — project uit de factuur (blok 10 07-09, casus Spot Services)', () => {
  it('exacte code / bevestigd werknummer = groen "uit factuur" mét detail', () => {
    const chip = bepaalProjectFactuurChip('factuur', 'Factuur vermeldt "26140" = projectcode van 26140 Koningstraat', 'p-1', false)
    expect(chip).toMatchObject({ klasse: 'ok', tekst: 'uit factuur' })
    expect(chip?.titel).toContain('projectcode van 26140 Koningstraat')
  })

  it('onbevestigd werknummer of fuzzy = oranje "uit factuur, nog niet bevestigd"', () => {
    expect(bepaalProjectFactuurChip('factuur_onbevestigd', null, 'p-1', false)).toMatchObject({
      klasse: 'afwijking',
      tekst: 'uit factuur, nog niet bevestigd',
    })
  })

  it('meerduidig = uitleg-chip zolang het veld leeg is, weg zodra er iets gekozen is', () => {
    const chip = bepaalProjectFactuurChip('factuur_meerduidig', 'meerdere projecten passen: A, B', null, false)
    expect(chip).toMatchObject({ klasse: 'afwijking', tekst: 'factuur noemt een project — meerdere passen, kies' })
    expect(chip?.titel).toContain('A, B')
    expect(bepaalProjectFactuurChip('factuur_meerduidig', null, 'p-1', false)).toBeNull()
  })

  it('geen chip zonder bron, zonder waarde in het veld (gevulde bronnen) of zodra de mens het veld aanraakte', () => {
    expect(bepaalProjectFactuurChip(null, null, 'p-1', false)).toBeNull()
    expect(bepaalProjectFactuurChip('factuur', null, null, false)).toBeNull()
    expect(bepaalProjectFactuurChip('factuur', null, 'p-1', true)).toBeNull()
    expect(bepaalProjectFactuurChip('factuur_meerduidig', null, null, true)).toBeNull()
  })

  it('server-waarden worden gevalideerd', () => {
    expect(projectBronUitDto('factuur')).toBe('factuur')
    expect(projectBronUitDto('factuur_onbevestigd')).toBe('factuur_onbevestigd')
    expect(projectBronUitDto('factuur_meerduidig')).toBe('factuur_meerduidig')
    expect(projectBronUitDto('geheugen')).toBeNull()
    expect(projectBronUitDto(null)).toBeNull()
    expect(projectBronUitDto(undefined)).toBeNull()
  })
})
