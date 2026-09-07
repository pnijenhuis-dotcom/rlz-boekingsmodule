import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ProjectenIngang } from './ProjectenIngang'
import { ProjectenKantoorbreedScreen } from './ProjectenKantoorbreedScreen'
import type { ProjectKantoorbreedRijDto, ProjectenKantoorbreedDto } from './projectenApi'

// Inzicht › Projecten KANTOORBREED (fixrun 07-09 blok C5, mockup inzicht-kantoorbreed ①②⑨): één lijst over
// alle administraties (server sorteert/pagineert), tellers + facetten + zoekveld gaan naar de server, per rij
// vier status-chips en de klik naar het bestaande projectdetail. De client formatteert alleen.

const ADMIN_A = 'aaaaaaaa-0000-0000-0000-000000000001'
const ADMIN_B = 'bbbbbbbb-0000-0000-0000-000000000002'
const P1 = '11111111-0000-0000-0000-000000000001'
const P2 = '22222222-0000-0000-0000-000000000002'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const RIJ_SIGNAAL: ProjectKantoorbreedRijDto = {
  administratie_id: ADMIN_A,
  administratie_naam: 'Universal Steigerbouw B.V.',
  project_id: P1,
  naam: '26014 Breda (Moeskops)',
  opdrachtgever: 'Moeskops Bouw',
  werknummer_opdrachtgever: 'MB-88412',
  looptijd_tot: null,
  resultaat: { baten: '10000.00', kosten: '12360.00', marge: '-2360.00', marge_pct: '-23.6', onbepaalbaar_uren: '4', heeft_cijfers: true },
  verplichtingen: { aantal: 1, goedgekeurd_excl: '5000.00', verbruikt_excl: '6000.00', percentage: 120, overschreden: 1 },
  weekstaten: { van_toepassing: true, ontbrekend: 2, oudste_ontbrekende_jaar: 2026, oudste_ontbrekende_week: 35, te_keuren: 1, concept: 0 },
  m2: { gebouwd_m2: '1000.00', contract_m2: '4000', percentage: 25, doorlopende_huur: false },
  signalen: ['verplichting_overschreden', 'marge_negatief', 'weekstaat_ontbreekt', 'te_keuren'],
  urgentie: 15,
}
const RIJ_SCHOON: ProjectKantoorbreedRijDto = {
  administratie_id: ADMIN_B,
  administratie_naam: 'Andere BV',
  project_id: P2,
  naam: 'Kantoorpand Eindhoven',
  opdrachtgever: null,
  werknummer_opdrachtgever: null,
  looptijd_tot: null,
  resultaat: { baten: '0', kosten: '0', marge: '0', marge_pct: null, onbepaalbaar_uren: '0', heeft_cijfers: false },
  verplichtingen: { aantal: 0, goedgekeurd_excl: '0', verbruikt_excl: '0', percentage: null, overschreden: 0 },
  weekstaten: { van_toepassing: false, ontbrekend: 0, oudste_ontbrekende_jaar: null, oudste_ontbrekende_week: null, te_keuren: 0, concept: 0 },
  m2: { gebouwd_m2: '0', contract_m2: null, percentage: null, doorlopende_huur: false },
  signalen: [],
  urgentie: 0,
}

function lijst(rijen: ProjectKantoorbreedRijDto[] = [RIJ_SIGNAAL, RIJ_SCHOON], extra: Partial<ProjectenKantoorbreedDto> = {}): ProjectenKantoorbreedDto {
  return {
    rijen,
    totaal: rijen.length,
    pagina: 1,
    per_pagina: 25,
    administraties_in_selectie: 2,
    tellers: { projecten: 2, administraties: 2, met_signaal: 1, verplichting_overschreden: 1, marge_negatief: 1, weekstaat_ontbreekt: 1, te_keuren: 1 },
    facetten: {
      status: { alle: 2, signaal: 1, verplichting_overschreden: 1, marge_negatief: 1, weekstaat_ontbreekt: 1, te_keuren: 1, op_schema: 1 },
      administraties: [
        { administratie_id: ADMIN_A, naam: 'Universal Steigerbouw B.V.', aantal: 1 },
        { administratie_id: ADMIN_B, naam: 'Andere BV', aantal: 1 },
      ],
    },
    ...extra,
  }
}

function stubFetch(antwoord: ProjectenKantoorbreedDto = lijst()) {
  const aangeroepen: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      aangeroepen.push(url)
      if (url === '/auth/administraties') {
        return Promise.resolve(
          jsonResponse({ administraties: [{ id: ADMIN_A, naam: 'Universal Steigerbouw B.V.' }, { id: ADMIN_B, naam: 'Andere BV' }] }),
        )
      }
      if (url.startsWith('/projecten/kantoorbreed?')) return Promise.resolve(jsonResponse(antwoord))
      if (url.startsWith(`/projecten/${ADMIN_A}?`)) return Promise.resolve(jsonResponse({ projecten: [], zonder_specs: 0 }))
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
  return aangeroepen
}

function renderScherm(pad = '/projecten') {
  return render(
    <MemoryRouter initialEntries={[pad]}>
      <Routes>
        <Route path="/projecten" element={<ProjectenIngang />} />
        <Route path="/projecten/:administratieId/:projectId" element={<div data-testid="detail-doel">detail</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('ProjectenKantoorbreedScreen', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('toont tellers, per rij de vier chips en de voet; facet en zoekterm gaan naar de server', async () => {
    const aangeroepen = stubFetch()
    renderScherm()
    const tabel = await screen.findByTestId('projecten-tabel')
    expect(screen.getByTestId('chip-signaal')).toHaveTextContent('1 met signaal')
    expect(screen.getByTestId('chip-overschreden')).toHaveTextContent('1 offerte overschreden')
    expect(screen.getByTestId('chip-ontbreekt')).toHaveTextContent('1 weekstaat ontbreekt')
    expect(aangeroepen.find((u) => u.startsWith('/projecten/kantoorbreed?'))).toBe('/projecten/kantoorbreed?pagina=1&status=alle')
    const rijen = within(tabel).getAllByTestId('projecten-rij')
    expect(rijen).toHaveLength(2)
    // Signaalrij: administratie-link naar de lijst per administratie, project + opdrachtgever + werknummer, chips.
    expect(within(rijen[0]).getByRole('link', { name: 'Universal Steigerbouw B.V.' })).toHaveAttribute('href', `/projecten?administratie=${ADMIN_A}`)
    expect(within(rijen[0]).getByText('26014 Breda (Moeskops)')).toBeInTheDocument()
    expect(within(rijen[0]).getByText(/Moeskops Bouw · werknr MB-88412/)).toBeInTheDocument()
    expect(within(rijen[0]).getByTestId('chip-resultaat')).toHaveTextContent('marge -23,6 %')
    expect(within(rijen[0]).getByTestId('chip-resultaat')).toHaveTextContent('4 u zonder tarief')
    expect(within(rijen[0]).getByTestId('chip-verplichtingen')).toHaveTextContent('offerte overschreden')
    expect(within(rijen[0]).getByTestId('chip-weekstaten')).toHaveTextContent('wk 35 ontbreekt (+1)')
    expect(within(rijen[0]).getByTestId('chip-weekstaten')).toHaveTextContent('1 te keuren')
    expect(within(rijen[0]).getByTestId('chip-m2')).toHaveTextContent('1.000 / 4.000 m²')
    expect(within(rijen[0]).getByRole('link', { name: /Open project 26014/ })).toHaveAttribute('href', `/projecten/${ADMIN_A}/${P1}`)
    // Schone rij: geen cijfers, geen offertes, weekstaten n.v.t., geen contract-m².
    expect(within(rijen[1]).getByText('geen cijfers')).toBeInTheDocument()
    expect(within(rijen[1]).getByText('n.v.t.')).toBeInTheDocument()
    expect(within(rijen[1]).getByText('geen contract-m²')).toBeInTheDocument()
    expect(screen.getByTestId('projecten-voet')).toHaveTextContent(/2 projecten over 2 administraties/)
    // Status-facet → server-side filter; zoekterm → q.
    await userEvent.selectOptions(screen.getByLabelText('Status'), 'signaal')
    await waitFor(() => expect(aangeroepen).toContain('/projecten/kantoorbreed?pagina=1&status=signaal'))
    await userEvent.type(screen.getByLabelText('Zoek project'), 'breda')
    await waitFor(() => expect(aangeroepen).toContain('/projecten/kantoorbreed?pagina=1&status=signaal&q=breda'))
  })

  it('klik op een rij navigeert naar het bestaande projectdetail', async () => {
    stubFetch()
    renderScherm()
    const tabel = await screen.findByTestId('projecten-tabel')
    await userEvent.click(within(tabel).getByText('26014 Breda (Moeskops)'))
    expect(await screen.findByTestId('detail-doel')).toBeInTheDocument()
  })

  it('toont de lege stand met facet-uitleg', async () => {
    stubFetch(lijst([], { totaal: 0, administraties_in_selectie: 0 }))
    renderScherm('/projecten?status=op_schema')
    expect(await screen.findByTestId('projecten-leeg')).toHaveTextContent('Geen projecten met status "op schema".')
  })

  it('/projecten mét ?administratie= blijft de bestaande lijst per administratie (deeplink)', async () => {
    const aangeroepen = stubFetch()
    renderScherm(`/projecten?administratie=${ADMIN_A}`)
    await waitFor(() => expect(aangeroepen.some((u) => u.startsWith(`/projecten/${ADMIN_A}?`))).toBe(true))
    expect(aangeroepen.some((u) => u.startsWith('/projecten/kantoorbreed'))).toBe(false)
    expect(screen.queryByTestId('projecten-paneel')).toBeNull()
  })

  it('rendert los ook zonder router-ingang (directe component)', async () => {
    stubFetch()
    render(
      <MemoryRouter initialEntries={['/projecten']}>
        <ProjectenKantoorbreedScreen />
      </MemoryRouter>,
    )
    expect(await screen.findByTestId('projecten-paneel')).toBeInTheDocument()
  })
})
