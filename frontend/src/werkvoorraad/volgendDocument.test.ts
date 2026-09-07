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

// ————— Besluit Peter 07-09: positie in de GETOONDE lijstvolgorde wint altijd, de soort-
// voorkeur van 25-08 vervalt (ook zonder lijstcontext). —————

describe('kiesVolgendDocument (besluit Peter 07-09 — positioneel, geen soort-voorkeur)', () => {
  it('zonder context, 1 en 2 open, bezig met 3 → 4 (gaat niet terug naar eerdere open documenten)', () => {
    const items = [
      doc('1', 'inkoopfactuur', 'te_controleren'),
      doc('2', 'inkoopfactuur', 'te_controleren'),
      doc('3', 'inkoopfactuur', 'te_controleren'),
      doc('4', 'inkoopfactuur', 'te_controleren'),
    ]
    expect(kiesVolgendDocument(items, '3')?.id).toBe('4')
  })

  it('laatste in de lijst → cyclisch terug naar het eerste dat nog verwerkbaar is', () => {
    const items = [
      doc('1', 'inkoopfactuur', 'te_controleren'),
      doc('2', 'inkoopfactuur', 'te_controleren'),
      doc('3', 'inkoopfactuur', 'te_controleren'),
    ]
    expect(kiesVolgendDocument(items, '3')?.id).toBe('1')
  })

  it('alleen het huidige document is verwerkbaar → null (het huidige zelf telt nooit mee)', () => {
    const items = [
      doc('1', 'inkoopfactuur', 'geboekt'),
      doc('2', 'inkoopfactuur', 'afgewezen'),
      doc('huidig', 'inkoopfactuur', 'te_controleren'),
    ]
    expect(kiesVolgendDocument(items, 'huidig')).toBeNull()
  })

  it('positie wint ook over een andere soort: het eerstvolgende document, ongeacht soort', () => {
    const items = [
      doc('huidig', 'inkoopfactuur', 'te_controleren'),
      doc('v1', 'verkoopfactuur', 'te_controleren'),
      doc('i1', 'inkoopfactuur', 'klaar_om_te_boeken'),
    ]
    // v1 staat direct ná 'huidig' in de lijst — dat wint, ook al is i1 dezelfde soort.
    expect(kiesVolgendDocument(items, 'huidig')?.id).toBe('v1')
  })

  it('sluit het huidige document zelf uit, ook als het nog een verwerkbare status heeft', () => {
    const items = [doc('huidig', 'inkoopfactuur', 'te_controleren')]
    expect(kiesVolgendDocument(items, 'huidig')).toBeNull()
  })

  it('negeert ter_accordering, afgewezen, vraag_open, geboekt, verwijderd en extractie_bezig', () => {
    const items = [
      doc('a', 'inkoopfactuur', 'ter_accordering'),
      doc('b', 'inkoopfactuur', 'afgewezen'),
      doc('c', 'inkoopfactuur', 'geboekt'),
      doc('d', 'inkoopfactuur', 'vraag_open'),
      doc('e', 'inkoopfactuur', 'verwijderd'),
      doc('f', 'inkoopfactuur', 'extractie_bezig'),
    ]
    expect(kiesVolgendDocument(items, 'huidig')).toBeNull()
    expect(kiesVolgendDocument([...items, doc('g', 'inkoopfactuur', 'boeken_mislukt')], 'huidig')?.id).toBe('g')
  })

  it('lege lijst → null', () => {
    expect(kiesVolgendDocument([], 'huidig')).toBeNull()
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
    expect(kiesVolgendDocument(lijst, 'k1', klaarFilter)?.id).toBe('k2')
    expect(kiesVolgendDocument(lijst, 'k2', klaarFilter)?.id).toBe('k3')
  })

  it('ná het laatste in de lijst: cyclisch terug naar het eerste dat nog verwerkbaar is', () => {
    expect(kiesVolgendDocument(lijst, 'k3', klaarFilter)?.id).toBe('k1')
  })

  it('filter zonder verwerkbare kandidaten (bv. "Bij klant") → null → terug naar de lijst', () => {
    const bijKlant = [item('a1', 'ter_accordering'), item('a2', 'ter_accordering')]
    expect(kiesVolgendDocument(bijKlant, 'a1', { soort: null, status: 'ter_accordering', zoekterm: '' })).toBeNull()
    // Het net geboekte document staat niet meer in het filter — de rest wél.
    const naBoeken = [item('k1', 'geboekt'), item('k2', 'klaar_om_te_boeken')]
    expect(kiesVolgendDocument(naBoeken, 'k1', klaarFilter)?.id).toBe('k2')
    expect(kiesVolgendDocument([item('k1', 'geboekt')], 'k1', klaarFilter)).toBeNull()
  })

  it('soort-tab zonder status-filter blijft binnen de tab; zonder context het bestaande gedrag', () => {
    const tab = { soort: 'inkoopfactuur', status: 'alle', zoekterm: '' }
    expect(kiesVolgendDocument(lijst, 'k3', tab)?.id).toBe('k1')
    expect(kiesVolgendDocument([item('k1', 'geboekt'), item('v1', 'te_controleren', 'verkoopfactuur')], 'k1', tab)).toBeNull()
    expect(kiesVolgendDocument([item('k1', 'geboekt'), item('v1', 'te_controleren', 'verkoopfactuur')], 'k1', null)?.id).toBe('v1')
  })
})
