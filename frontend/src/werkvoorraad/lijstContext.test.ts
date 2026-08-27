import { describe, expect, it } from 'vitest'
import type { DocumentListItemDto } from '../api/types'
import {
  STATUSFILTER_ALLE,
  STATUSFILTER_AUTOMATISCH,
  STATUSFILTER_DUPLICAAT,
  STATUSFILTER_URENMATCH,
  filterDocumenten,
  kiesTabVoorStatus,
  lijstContextNaarParams,
  lijstContextUitParams,
  lijstPositie,
  lijstRoute,
} from './lijstContext'
import { documentRoute } from './format'

function doc(overrides: Partial<DocumentListItemDto> & { id: string }): DocumentListItemDto {
  return {
    bestandsnaam: `${overrides.id}.pdf`,
    status: 'te_controleren',
    bron: 'upload',
    soort: 'inkoopfactuur',
    mogelijk_duplicaat_van: null,
    toegewezen_aan: null,
    aangemaakt_op: '2026-08-27T10:00:00Z',
    laatst_gewijzigd_op: '2026-08-27T10:00:00Z',
    afwijzing: null,
    leverancier: null,
    totaalbedrag: null,
    factuurdatum: null,
    automatisch_geboekt: false,
    ...overrides,
  }
}

const LIJST = [
  doc({ id: 'a', status: 'klaar_om_te_boeken', leverancier: 'Eneco' }),
  doc({ id: 'b', status: 'te_controleren', leverancier: 'Technische Unie' }),
  doc({ id: 'c', status: 'klaar_om_te_boeken', leverancier: 'Bouwmaat' }),
  doc({ id: 'd', soort: 'verkoopfactuur', status: 'afgewezen' }),
  doc({ id: 'e', status: 'geboekt', automatisch_geboekt: true }),
  doc({ id: 'f', status: 'te_controleren', duplicaatsignaal: { uitkomst: 'mogelijk_duplicaat', aantal_treffers: 1, berekend_op: '2026-08-27T10:00:00Z' } }),
  doc({ id: 'g', status: 'te_controleren', factuurmatch: { uitkomst: 'afwijking', verschil_bedrag: '10.00', tarief_ontbreekt: false } as never }),
]

describe('lijstContext — filterDocumenten (één bron voor lijst én controlescherm)', () => {
  it('soort-scope + status-filter + zoekterm, in lijstvolgorde', () => {
    expect(filterDocumenten(LIJST, { soort: 'inkoopfactuur', status: 'klaar_om_te_boeken', zoekterm: '' }).map((d) => d.id)).toEqual(['a', 'c'])
    expect(filterDocumenten(LIJST, { soort: null, status: 'afgewezen', zoekterm: '' }).map((d) => d.id)).toEqual(['d'])
    expect(filterDocumenten(LIJST, { soort: 'inkoopfactuur', status: STATUSFILTER_ALLE, zoekterm: 'bouw' }).map((d) => d.id)).toEqual(['c'])
    // Zoeken op bestandsnaam blijft werken (metaregel, punt 3a).
    expect(filterDocumenten(LIJST, { soort: null, status: STATUSFILTER_ALLE, zoekterm: 'b.pdf' }).map((d) => d.id)).toEqual(['b'])
  })

  it('sentinels: automatisch geboekt, mogelijk duplicaat, urenmatch-afwijking', () => {
    expect(filterDocumenten(LIJST, { soort: null, status: STATUSFILTER_AUTOMATISCH, zoekterm: '' }).map((d) => d.id)).toEqual(['e'])
    expect(filterDocumenten(LIJST, { soort: null, status: STATUSFILTER_DUPLICAAT, zoekterm: '' }).map((d) => d.id)).toEqual(['f'])
    expect(filterDocumenten(LIJST, { soort: null, status: STATUSFILTER_URENMATCH, zoekterm: '' }).map((d) => d.id)).toEqual(['g'])
  })
})

describe('lijstContext — URL-params heen en terug', () => {
  it('serialiseert soort altijd, status/zoekterm alleen als gezet; leest terug', () => {
    const ctx = { soort: 'inkoopfactuur', status: 'klaar_om_te_boeken', zoekterm: 'eneco' }
    const q = lijstContextNaarParams(ctx)
    expect(q).toBe('soort=inkoopfactuur&status=klaar_om_te_boeken&q=eneco')
    expect(lijstContextUitParams(new URLSearchParams(q))).toEqual(ctx)
    expect(lijstContextNaarParams({ soort: null, status: STATUSFILTER_ALLE, zoekterm: '  ' })).toBe('soort=alle')
    expect(lijstContextUitParams(new URLSearchParams('soort=alle'))).toEqual({ soort: null, status: STATUSFILTER_ALLE, zoekterm: '' })
    expect(lijstContextUitParams(new URLSearchParams(''))).toBeNull()
    expect(lijstContextNaarParams(null)).toBe('')
  })

  it('documentRoute draagt de context alleen op het inkoop-controlescherm; lijstRoute is de terugweg', () => {
    const ctx = { soort: 'inkoopfactuur', status: 'klaar_om_te_boeken', zoekterm: '' }
    expect(documentRoute('A', LIJST[0], ctx)).toBe('/documenten/A/a?soort=inkoopfactuur&status=klaar_om_te_boeken')
    expect(documentRoute('A', LIJST[0])).toBe('/documenten/A/a')
    expect(documentRoute('A', LIJST[3], ctx)).toBe('/verkoop/A/d')
    expect(lijstRoute('A', ctx)).toBe('/?administratie=A&soort=inkoopfactuur&status=klaar_om_te_boeken')
    expect(lijstRoute('A', null)).toBe('/?administratie=A')
  })
})

describe('lijstContext — lijstPositie + kiesTabVoorStatus', () => {
  it('positie "n van m" mét buren binnen het filter; buiten de lijst = index -1', () => {
    const ctx = { soort: 'inkoopfactuur', status: 'klaar_om_te_boeken', zoekterm: '' }
    const pos = lijstPositie(LIJST, ctx, 'c')
    expect(pos.index).toBe(1)
    expect(pos.totaal).toBe(2)
    expect(pos.vorige?.id).toBe('a')
    expect(pos.volgende).toBeNull()
    expect(lijstPositie(LIJST, ctx, 'b').index).toBe(-1)
  })

  it('kiest de tab waarin het status-filter iets oplevert (kolom-teller "Afgewezen" op een verkoopfactuur)', () => {
    const tabs = ['inkoopfactuur', 'verkoopfactuur']
    expect(kiesTabVoorStatus(LIJST, tabs, 'afgewezen')).toBe('verkoopfactuur')
    expect(kiesTabVoorStatus(LIJST, tabs, 'klaar_om_te_boeken')).toBe('inkoopfactuur')
    expect(kiesTabVoorStatus(LIJST, tabs, STATUSFILTER_ALLE)).toBe('inkoopfactuur')
    expect(kiesTabVoorStatus(LIJST, tabs, 'ter_accordering')).toBeNull()
  })
})
