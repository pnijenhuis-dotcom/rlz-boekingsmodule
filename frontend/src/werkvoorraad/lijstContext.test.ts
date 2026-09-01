import { describe, expect, it } from 'vitest'
import type { DocumentListItemDto } from '../api/types'
import {
  STATUSFILTER_ALLE,
  STATUSFILTER_AUTOMATISCH,
  STATUSFILTER_DUPLICAAT,
  STATUSFILTER_URENMATCH,
  STATUS_TE_CONTROLEREN,
  defaultStatusFilter,
  filterDocumenten,
  kiesTabVoorStatus,
  lijstContextNaarParams,
  lijstContextUitParams,
  lijstPositie,
  lijstRoute,
  sorteerDocumenten,
  volgendeSortering,
  type LijstContext,
  type Sortering,
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

describe('lijstContext — defaultStatusFilter (blok D 01-09: binnenkomst = eerst het werk)', () => {
  it('kiest "Te controleren" zodra er te-controleren-werk is', () => {
    expect(defaultStatusFilter(LIJST)).toBe(STATUS_TE_CONTROLEREN)
  })

  it('valt terug op "Alle" zonder te-controleren-werk — nooit een leeg eerste beeld', () => {
    expect(defaultStatusFilter(LIJST.filter((d) => d.status !== STATUS_TE_CONTROLEREN))).toBe(STATUSFILTER_ALLE)
    expect(defaultStatusFilter([])).toBe(STATUSFILTER_ALLE)
  })
})

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
    expect(lijstContextUitParams(new URLSearchParams(q))).toEqual({ ...ctx, sortering: null })
    expect(lijstContextNaarParams({ soort: null, status: STATUSFILTER_ALLE, zoekterm: '  ' })).toBe('soort=alle')
    expect(lijstContextUitParams(new URLSearchParams('soort=alle'))).toEqual({ soort: null, status: STATUSFILTER_ALLE, zoekterm: '', sortering: null })
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

describe('lijstContext — kolomsortering (punt 21, opruimrun 28-08)', () => {
  const RIJEN = [
    doc({ id: 'a', leverancier: 'Eneco', totaalbedrag: '121.00', factuurdatum: '2026-07-03', status: 'klaar_om_te_boeken' }),
    doc({ id: 'b', leverancier: 'bouwmaat', totaalbedrag: '9.50', factuurdatum: '2026-07-01', status: 'te_controleren' }),
    doc({ id: 'c', leverancier: null, totaalbedrag: null, factuurdatum: null, status: 'afgewezen' }),
    doc({ id: 'd', leverancier: 'Technische Unie', totaalbedrag: '1000.00', factuurdatum: '2026-07-02', status: 'geboekt' }),
  ]

  it('sorteert oplopend/aflopend per kolom; ontbrekende waarden altijd achteraan', () => {
    const ids = (s: Sortering | null) => sorteerDocumenten(RIJEN, s).map((d) => d.id)
    expect(ids(null)).toEqual(['a', 'b', 'c', 'd'])
    // leverancier: hoofdletter-ongevoelig; 'c' heeft geen leverancier → bestandsnaam 'c.pdf'
    expect(ids({ kolom: 'leverancier', richting: 'asc' })).toEqual(['b', 'c', 'a', 'd'])
    expect(ids({ kolom: 'leverancier', richting: 'desc' })).toEqual(['d', 'a', 'c', 'b'])
    // bedrag numeriek (niet als tekst: 9.50 < 121 < 1000), null achteraan in beide richtingen
    expect(ids({ kolom: 'bedrag', richting: 'asc' })).toEqual(['b', 'a', 'd', 'c'])
    expect(ids({ kolom: 'bedrag', richting: 'desc' })).toEqual(['d', 'a', 'b', 'c'])
    expect(ids({ kolom: 'factuurdatum', richting: 'asc' })).toEqual(['b', 'd', 'a', 'c'])
    expect(ids({ kolom: 'factuurdatum', richting: 'desc' })).toEqual(['a', 'd', 'b', 'c'])
  })

  it('status sorteert op het label; toegewezen gebruikt de naam-resolver en zet boekfouten vooraan', () => {
    const rijen = [
      doc({ id: 'x', toegewezen_aan: 'u-2' }),
      doc({ id: 'y', toegewezen_aan: 'u-1' }),
      doc({ id: 'z', toegewezen_aan: null, accordering_boek_fout: 'Boeken staat uit' }),
    ]
    const namen: Record<string, string> = { 'u-1': 'Zoë', 'u-2': 'Anna' }
    const ids = sorteerDocumenten(rijen, { kolom: 'toegewezen', richting: 'asc' }, { naamVoor: (id) => namen[id] }).map(
      (d) => d.id,
    )
    expect(ids).toEqual(['z', 'x', 'y'])
    const statusIds = sorteerDocumenten(RIJEN, { kolom: 'status', richting: 'asc' }).map((d) => d.id)
    expect(statusIds[0]).toBe('c') // "Afgewezen" komt alfabetisch vóór "Geboekt"/"Klaar…"/"Te controleren"
  })

  it('klik-cyclus oplopend → aflopend → uit; andere kolom begint weer oplopend', () => {
    const s1 = volgendeSortering(null, 'bedrag')
    expect(s1).toEqual({ kolom: 'bedrag', richting: 'asc' })
    const s2 = volgendeSortering(s1, 'bedrag')
    expect(s2).toEqual({ kolom: 'bedrag', richting: 'desc' })
    expect(volgendeSortering(s2, 'bedrag')).toBeNull()
    expect(volgendeSortering(s2, 'status')).toEqual({ kolom: 'status', richting: 'asc' })
  })

  it('reist mee in de URL (sort=<kolom>:<richting>) en stuurt filterDocumenten + lijstPositie', () => {
    const ctx: LijstContext = { soort: null, status: STATUSFILTER_ALLE, zoekterm: '', sortering: { kolom: 'bedrag', richting: 'desc' } }
    const q = lijstContextNaarParams(ctx)
    expect(q).toBe('soort=alle&sort=bedrag%3Adesc')
    const terug = lijstContextUitParams(new URLSearchParams(q))
    expect(terug?.sortering).toEqual({ kolom: 'bedrag', richting: 'desc' })
    // Alleen een sortering (geen filter) is óók context.
    expect(lijstContextUitParams(new URLSearchParams('sort=status:asc'))?.sortering).toEqual({ kolom: 'status', richting: 'asc' })
    expect(lijstContextUitParams(new URLSearchParams('sort=onzin:asc'))?.sortering).toBeNull()
    expect(filterDocumenten(RIJEN, ctx).map((d) => d.id)).toEqual(['d', 'a', 'b', 'c'])
    const positie = lijstPositie(RIJEN, ctx, 'a')
    expect(positie.index).toBe(1)
    expect(positie.vorige?.id).toBe('d')
    expect(positie.volgende?.id).toBe('b')
  })
})
