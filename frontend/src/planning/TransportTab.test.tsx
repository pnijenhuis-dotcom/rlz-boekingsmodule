import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TransportTab } from './TransportTab'

/* Transport-tab (steigerbouw-run D1/D5): weekgrid met twee blokken, kaartje met status,
 * wachtrisico-paneel + rode markering, bestellingen-paneel. Fetch gemockt op de /materiaal-routes. */

const WEEK = {
  jaar: 2026,
  weeknummer: 35,
  maandag: '2026-08-24',
  zondag: '2026-08-30',
  projecten: [
    {
      project_id: 'p1',
      project_naam: '144 Breda (Moeskops)',
      opdrachtgever: 'Moeskops',
      is_actief: true,
      week_transporten: 1,
      ploeg_label: 'ploeg di (1 man)',
      per_datum: {
        '2026-08-25': [
          {
            id: 't1', project_id: 'p1', project_naam: '144 Breda (Moeskops)', leverancier_id: 'l1', leverancier_naam: 'Universal Nederland B.V.',
            bestelling_id: null, bestelling_nummer: null, soort: 'levering', datum: '2026-08-25', tijdstip: '07:00:00', status: 'gepland', status_bron: 'kantoor',
            status_reden: null, regels: [], samenvatting: 'Levering steiger 100.00 m²', m2: '100.00', omschrijving: null,
          },
        ],
      },
    },
    { project_id: 'p2', project_naam: '25016 Groesbeek', opdrachtgever: 'Janssen', is_actief: true, week_transporten: 0, ploeg_label: null, per_datum: {} },
  ],
  wachtrisico: [{ project_id: 'p1', project_naam: '144 Breda (Moeskops)', datum: '2026-08-25', aantal_personen: 1, transport_id: 't1', leverancier_naam: 'Universal Nederland B.V.', samenvatting: 'Levering steiger 100.00 m²' }],
  aantal_transporten: 1,
  bestellingen_concept: 1,
  bestellingen_met_wijzigingen: 0,
  materiaalmatch_open: 0,
}

function stub() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
      if (url.includes('/materiaal/a1/transport')) return json(WEEK)
      if (url.includes('/materiaal/a1/bestellingen')) return json({ items: [], totaal: 0, pagina: 1, per_pagina: 10 })
      if (url.includes('/materiaal/a1/leveranciers')) return json([])
      if (url.includes('/materiaal/a1/stand/')) return json({ project_id: 'p1', project_naam: '144 Breda', tot_en_met: '2026-08-25', regels: [], m2_op_locatie: '0.00', totaal_items: 0, leveranciers: [] })
      return json({})
    }),
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('TransportTab', () => {
  it('toont grid met kaartje, overige-projecten-scheider en het wachtrisico-paneel', async () => {
    stub()
    const dagen = ['2026-08-24', '2026-08-25', '2026-08-26', '2026-08-27', '2026-08-28', '2026-08-29', '2026-08-30'].map((d, i) => ({ datum: d, naam: ['ma', 'di', 'wo', 'do', 'vr', 'za', 'zo'][i] }))
    render(<TransportTab administratieId="a1" week={{ jaar: 2026, weeknummer: 35 }} dagen={dagen} filterTerm="" setFilterTerm={() => {}} />)
    await waitFor(() => expect(screen.getByText('Levering steiger 100.00 m²')).toBeInTheDocument())
    expect(screen.getByText(/transporten deze week: 1 · 1 wachtrisico/)).toBeInTheDocument()
    expect(screen.getByText('Overige actieve projecten — geen transport deze week')).toBeInTheDocument()
    expect(screen.getByText('25016 Groesbeek')).toBeInTheDocument()
    expect(screen.getByText(/NIET bevestigd · ⚠ ploeg staat gepland/)).toBeInTheDocument()
    expect(screen.getByText(/Wachtrisico/)).toBeInTheDocument()
    expect(screen.getByText(/ploeg gepland \(1 man\)/)).toBeInTheDocument()
  })
})
