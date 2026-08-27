import { describe, expect, it } from 'vitest'
import type { DocumentListItemDto } from '../api/types'
import { kiesVolgendDocument } from './volgendDocument'

function doc(id: string, soort: string, status: string): DocumentListItemDto {
  return {
    id,
    bestandsnaam: `${id}.pdf`,
    status,
    bron: 'upload',
    soort,
    mogelijk_duplicaat_van: null,
    toegewezen_aan: null,
    aangemaakt_op: '2026-08-25T10:00:00Z',
    laatst_gewijzigd_op: '2026-08-25T10:00:00Z',
    afwijzing: null,
    leverancier: null,
    totaalbedrag: null,
    factuurdatum: null,
    automatisch_geboekt: false,
  }
}

describe('kiesVolgendDocument (deel 4 punt 1 — doorloop ná boeken/afwijzen)', () => {
  it('kiest het eerste te verwerken document van dezelfde soort, in lijstvolgorde', () => {
    const items = [
      doc('huidig', 'inkoopfactuur', 'te_controleren'),
      doc('v1', 'verkoopfactuur', 'te_controleren'),
      doc('i1', 'inkoopfactuur', 'klaar_om_te_boeken'),
      doc('i2', 'inkoopfactuur', 'te_controleren'),
    ]
    expect(kiesVolgendDocument(items, 'huidig', 'inkoopfactuur')?.id).toBe('i1')
  })

  it('sluit het huidige document zelf uit, ook als het nog een verwerkbare status heeft', () => {
    const items = [doc('huidig', 'inkoopfactuur', 'te_controleren')]
    expect(kiesVolgendDocument(items, 'huidig', 'inkoopfactuur')).toBeNull()
  })

  it('valt terug op de volgende soort in SOORT_VOLGORDE als er niets van dezelfde soort open staat', () => {
    const items = [
      doc('huidig', 'inkoopfactuur', 'te_controleren'),
      doc('w1', 'waarborg', 'te_controleren'),
      doc('k1', 'kassarapport', 'te_controleren'),
      doc('v1', 'verkoopfactuur', 'handmatig_afmaken'),
    ]
    expect(kiesVolgendDocument(items, 'huidig', 'inkoopfactuur')?.id).toBe('v1')
    // Vanuit een verkoopfactuur is kassarapport de volgende soort, niet inkoop.
    expect(
      kiesVolgendDocument([doc('i9', 'inkoopfactuur', 'te_controleren'), doc('k1', 'kassarapport', 'te_controleren')], 'x', 'verkoopfactuur')?.id,
    ).toBe('k1')
    // Cyclisch: vanuit waarborg komt inkoop weer vóór een onbekende soort.
    expect(
      kiesVolgendDocument([doc('o1', 'onbekend', 'te_controleren'), doc('i1', 'inkoopfactuur', 'te_controleren')], 'x', 'waarborg')?.id,
    ).toBe('i1')
  })

  it('negeert ter_accordering, afgewezen, vraag_open, geboekt en verwijderd', () => {
    const items = [
      doc('a', 'inkoopfactuur', 'ter_accordering'),
      doc('b', 'inkoopfactuur', 'afgewezen'),
      doc('c', 'inkoopfactuur', 'geboekt'),
      doc('d', 'inkoopfactuur', 'vraag_open'),
      doc('e', 'inkoopfactuur', 'verwijderd'),
      doc('f', 'inkoopfactuur', 'extractie_bezig'),
    ]
    expect(kiesVolgendDocument(items, 'huidig', 'inkoopfactuur')).toBeNull()
    expect(kiesVolgendDocument([...items, doc('g', 'inkoopfactuur', 'boeken_mislukt')], 'huidig', 'inkoopfactuur')?.id).toBe('g')
  })

  it('lege lijst → null', () => {
    expect(kiesVolgendDocument([], 'huidig', 'inkoopfactuur')).toBeNull()
  })
})

// ————— Werkstroom-run 27/28-08 punt 1b: doorloop BINNEN het actieve lijstfilter —————

describe('kiesVolgendDocument mét lijstcontext (punt 1b)', () => {
  const item = (id: string, status: string, soort = 'inkoopfactuur') =>
    ({
      id,
      bestandsnaam: `${id}.pdf`,
      status,
      bron: 'upload',
      soort,
      mogelijk_duplicaat_van: null,
      toegewezen_aan: null,
      aangemaakt_op: '2026-08-27T10:00:00Z',
      laatst_gewijzigd_op: '2026-08-27T10:00:00Z',
      afwijzing: null,
      leverancier: null,
      totaalbedrag: null,
      factuurdatum: null,
      automatisch_geboekt: false,
    }) as never

  const lijst = [
    item('k1', 'klaar_om_te_boeken'),
    item('t1', 'te_controleren'),
    item('k2', 'klaar_om_te_boeken'),
    item('k3', 'klaar_om_te_boeken'),
    item('v1', 'te_controleren', 'verkoopfactuur'),
  ]
  const klaarFilter = { soort: 'inkoopfactuur', status: 'klaar_om_te_boeken', zoekterm: '' }

  it('vanuit "Klaar om te boeken" → het volgende klaar-om-te-boeken-document, nooit een te-controleren', () => {
    expect(kiesVolgendDocument(lijst, 'k1', 'inkoopfactuur', klaarFilter)?.id).toBe('k2')
    expect(kiesVolgendDocument(lijst, 'k2', 'inkoopfactuur', klaarFilter)?.id).toBe('k3')
  })

  it('ná het laatste in de lijst: cyclisch terug naar het eerste dat nog verwerkbaar is', () => {
    expect(kiesVolgendDocument(lijst, 'k3', 'inkoopfactuur', klaarFilter)?.id).toBe('k1')
  })

  it('filter zonder verwerkbare kandidaten (bv. "Bij klant") → null → terug naar de lijst', () => {
    const bijKlant = [item('a1', 'ter_accordering'), item('a2', 'ter_accordering')]
    expect(kiesVolgendDocument(bijKlant, 'a1', 'inkoopfactuur', { soort: null, status: 'ter_accordering', zoekterm: '' })).toBeNull()
    // Het net geboekte document staat niet meer in het filter — de rest wél.
    const naBoeken = [item('k1', 'geboekt'), item('k2', 'klaar_om_te_boeken')]
    expect(kiesVolgendDocument(naBoeken, 'k1', 'inkoopfactuur', klaarFilter)?.id).toBe('k2')
    expect(kiesVolgendDocument([item('k1', 'geboekt')], 'k1', 'inkoopfactuur', klaarFilter)).toBeNull()
  })

  it('soort-tab zonder status-filter blijft binnen de tab; zonder context het bestaande gedrag', () => {
    const tab = { soort: 'inkoopfactuur', status: 'alle', zoekterm: '' }
    expect(kiesVolgendDocument(lijst, 'k3', 'inkoopfactuur', tab)?.id).toBe('k1')
    expect(kiesVolgendDocument([item('k1', 'geboekt'), item('v1', 'te_controleren', 'verkoopfactuur')], 'k1', 'inkoopfactuur', tab)).toBeNull()
    expect(kiesVolgendDocument([item('k1', 'geboekt'), item('v1', 'te_controleren', 'verkoopfactuur')], 'k1', 'inkoopfactuur', null)?.id).toBe('v1')
  })
})
