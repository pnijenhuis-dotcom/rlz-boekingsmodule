import { describe, expect, it } from 'vitest'
import { isMiniVoorraadNotitie, miniVoorraadMelding, miniVoorraadTijdlijnTekst } from './miniVoorraadTijdlijn'

// Mini-voorraad (06-09), mockup blok 1: de melding ná boeken benoemt het aantal regels én de nieuwe producten;
// de tijdlijnregel herkent de notitie-sleutels die instroom.py schrijft en valt fail-closed terug.
describe('miniVoorraadMelding', () => {
  it('benoemt regels en nieuwe producten', () => {
    expect(miniVoorraadMelding({ regels: 3, nieuwe_producten: ['Kanaalplaatvork speciaal'] })).toBe(
      'Mini-voorraad bijgewerkt — 3 regels · nieuw — controleer naam: Kanaalplaatvork speciaal',
    )
  })

  it('enkelvoud, zonder nieuwe producten, overgeslagen geteld', () => {
    expect(miniVoorraadMelding({ regels: 1, nieuwe_producten: [] })).toBe('Mini-voorraad bijgewerkt — 1 regel')
    expect(miniVoorraadMelding({ regels: 2, nieuwe_producten: [], overgeslagen: ['regel 3: geen aantal'] })).toBe('Mini-voorraad bijgewerkt — 2 regels · 1 overgeslagen')
  })
})

describe('tijdlijn-notities mini_voorraad_bijgewerkt / mini_voorraad_teruggedraaid', () => {
  it('herkent de gebouwde vorm (sleutel mét blok), de contract-varianten en de storno; ander detail = geen regel', () => {
    expect(isMiniVoorraadNotitie({ mini_voorraad_bijgewerkt: { regels: 2, nieuwe_producten: [], tekst: 'x' } })).toBe(true)
    expect(isMiniVoorraadNotitie({ mini_voorraad_teruggedraaid: { regels: 2, producten: [], tekst: 'x' } })).toBe(true)
    expect(isMiniVoorraadNotitie({ soort: 'mini_voorraad_bijgewerkt', regels: 2, nieuwe_producten: [] })).toBe(true)
    expect(isMiniVoorraadNotitie({ notitie: 'mini_voorraad_bijgewerkt' })).toBe(true)
    expect(isMiniVoorraadNotitie({ extractie_wachtrij: 'groot_document' })).toBe(false)
    expect(isMiniVoorraadNotitie({ reden: 'iets anders' })).toBe(false)
  })

  it('instroom: de servertekst in het blok wint, overgeslagen redenen worden benoemd; zonder tekst opgebouwd uit het blok', () => {
    expect(
      miniVoorraadTijdlijnTekst({
        mini_voorraad_bijgewerkt: { regels: 3, nieuwe_producten: ['X'], bestaande: 2, overgeslagen: ['regel 4: geen aantal'], boek_cyclus: 1, tekst: 'Mini-voorraad bijgewerkt — 3 regels · nieuw: X' },
      }),
    ).toBe('Mini-voorraad bijgewerkt — 3 regels · nieuw: X · overgeslagen: regel 4: geen aantal')
    expect(miniVoorraadTijdlijnTekst({ soort: 'mini_voorraad_bijgewerkt', regels: 2, nieuwe_producten: ['A', 'B'] })).toBe(
      'Mini-voorraad bijgewerkt — 2 regels · nieuw — controleer naam: A, B',
    )
    expect(miniVoorraadTijdlijnTekst({ mini_voorraad_bijgewerkt: { regels: 1, nieuwe_producten: [] } })).toBe('Mini-voorraad bijgewerkt — 1 regel')
    expect(miniVoorraadTijdlijnTekst({ notitie: 'mini_voorraad_bijgewerkt' })).toBe('Mini-voorraad bijgewerkt')
  })

  it('storno (tegenboeken): tekst + de teruggedraaide producten', () => {
    expect(
      miniVoorraadTijdlijnTekst({
        mini_voorraad_teruggedraaid: { regels: 2, producten: ['Stapelbok 1,25x0,85', 'AR-40 gaffel'], boek_cyclus: 1, reden: 'dubbel', tekst: 'Mini-voorraad teruggedraaid — 2 regels' },
      }),
    ).toBe('Mini-voorraad teruggedraaid — 2 regels · Stapelbok 1,25x0,85, AR-40 gaffel')
    expect(miniVoorraadTijdlijnTekst({ mini_voorraad_teruggedraaid: { regels: 1 } })).toBe('Mini-voorraad teruggedraaid — 1 regel')
  })
})
