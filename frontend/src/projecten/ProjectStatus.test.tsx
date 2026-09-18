import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { NieuwProjectModal } from './NieuwProjectModal'
import { ProjectDetailScreen } from './ProjectDetailScreen'
import { ProjectenKantoorbreedScreen } from './ProjectenKantoorbreedScreen'
import { ProjectenScreen } from './ProjectenScreen'

/** Blok 3 18-09 (Peter): projectstatus lopend/afgesloten + projectnummer uniek — kantoorkant.
 * Detail: "Afsluiten…" opent een dialoog (reden + datum optioneel) → POST afsluiten; afgesloten = chip + "Heropenen".
 * Lijst per administratie: afgesloten standaard weg, toggle "Toon afgesloten (N)" = alleen_actief=false, rij grijs mét chip.
 * Kantoorbreed: chip "kandidaat afsluiten" (teller + rij), toggle in de URL (`?afgesloten=1`).
 * Nieuw project: 409 "nummer bestaat al" = melding mét het bestaande project + "Openen" (nooit stil een tweede). */

const ADM = 'dddddddd-0000-0000-0000-00000000000d'
const PID = 'aaaaaaaa-0000-0000-0000-00000000000a'
const PID2 = 'bbbbbbbb-0000-0000-0000-00000000000b'

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function detail(status: 'lopend' | 'afgesloten' = 'lopend') {
  return {
    project_id: PID,
    naam: '26127 Tilburg (Heijmans)',
    is_actief: status === 'lopend',
    specificatie: null,
    documenten: [],
    staffels: [],
    werknummers: [],
    ontleding: [],
    gebouwd_m2: '0',
    prijsafspraken: [],
    veldwerkers: [],
    status,
    afgesloten_op: status === 'afgesloten' ? '2026-09-15T00:00:00Z' : null,
    afgesloten_door: null,
    afsluit_reden: status === 'afgesloten' ? 'Werk opgeleverd' : null,
  }
}

function lijstRij(id: string, naam: string, status: 'lopend' | 'afgesloten' = 'lopend') {
  return {
    project_id: id,
    naam,
    is_actief: status === 'lopend',
    opdrachtgever: 'Heijmans',
    werknummer_opdrachtgever: null,
    specs_status: 'geen',
    documenten: {},
    staffels: 0,
    gebouwd_m2: '0',
    contract_m2: null,
    doorlopende_huur: false,
    heeft_activiteit: false,
    status,
    afgesloten_op: status === 'afgesloten' ? '2026-09-15T00:00:00Z' : null,
    afsluit_reden: null,
  }
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('ProjectDetailScreen — afsluiten / heropenen', () => {
  it('Afsluiten… opent de dialoog, bevestigen POST reden+datum en toont daarna chip + Heropenen', async () => {
    const state = { detail: detail('lopend'), posts: [] as Array<{ url: string; body: unknown }> }
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url.includes('/auth/administraties')) return Promise.resolve(json({ administraties: [{ id: ADM, naam: 'Universal' }] }))
        if (url.endsWith('/afsluiten') && init?.method === 'POST') {
          state.posts.push({ url, body: JSON.parse(String(init.body)) })
          state.detail = detail('afgesloten')
          return Promise.resolve(json({ ...detail('afgesloten') }))
        }
        if (url.endsWith('/heropenen') && init?.method === 'POST') {
          state.posts.push({ url, body: {} })
          state.detail = detail('lopend')
          return Promise.resolve(json({ ...detail('lopend') }))
        }
        if (url.includes(`/projecten/${ADM}/${PID}`)) return Promise.resolve(json(state.detail))
        if (url.includes('/materiaal/')) return Promise.resolve(json({ detail: 'uit' }, 409))
        if (url.includes('/crediteuren')) return Promise.resolve(json({ vendors: [] }))
        return Promise.resolve(json({ detail: `onverwacht: ${url}` }, 500))
      }),
    )
    render(
      <MemoryRouter initialEntries={[`/projecten/${ADM}/${PID}`]}>
        <Routes>
          <Route path="/projecten/:administratieId/:projectId" element={<ProjectDetailScreen />} />
        </Routes>
      </MemoryRouter>,
    )
    await userEvent.click(await screen.findByTestId('knop-afsluiten'))
    const dialoog = await screen.findByRole('dialog')
    await userEvent.type(within(dialoog).getByLabelText('Reden'), 'Werk opgeleverd')
    await userEvent.type(within(dialoog).getByLabelText('Afgesloten per'), '2026-09-15')
    await userEvent.click(within(dialoog).getByTestId('bevestig-afsluiten'))
    await waitFor(() => expect(state.posts).toHaveLength(1))
    expect(state.posts[0].url).toBe(`/projecten/${ADM}/${PID}/afsluiten`)
    expect(state.posts[0].body).toEqual({ reden: 'Werk opgeleverd', datum: '2026-09-15' })
    expect(await screen.findByTestId('status-afgesloten')).toHaveTextContent('afgesloten op 15-9-2026')
    expect(screen.getByText(/Project afgesloten — het staat niet meer in de keuzelijsten/)).toBeInTheDocument()
    await userEvent.click(screen.getByTestId('knop-heropenen'))
    await waitFor(() => expect(state.posts).toHaveLength(2))
    expect(await screen.findByTestId('knop-afsluiten')).toBeInTheDocument()
  })
})

describe('ProjectenScreen — toggle Toon afgesloten', () => {
  it('standaard alleen lopende; toggle vraagt alleen_actief=false en toont de afgesloten rij grijs mét chip', async () => {
    const urls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        urls.push(url)
        if (url.includes('/auth/administraties')) return Promise.resolve(json({ administraties: [{ id: ADM, naam: 'Universal' }] }))
        if (url.includes('/volgend-nummer')) return Promise.resolve(json({ projectnummer: '26128' }))
        if (url.includes(`/projecten/${ADM}?`)) {
          const alles = url.includes('alleen_actief=false')
          return Promise.resolve(
            json({
              projecten: alles
                ? [lijstRij(PID, '26127 Tilburg (Heijmans)'), lijstRij(PID2, '26100 Oud werk (X)', 'afgesloten')]
                : [lijstRij(PID, '26127 Tilburg (Heijmans)')],
              zonder_specs: 0,
              aantal_afgesloten: 1,
            }),
          )
        }
        return Promise.resolve(json({ detail: `onverwacht: ${url}` }, 500))
      }),
    )
    render(
      <MemoryRouter initialEntries={[`/projecten?administratie=${ADM}`]}>
        <Routes>
          <Route path="/projecten" element={<ProjectenScreen />} />
        </Routes>
      </MemoryRouter>,
    )
    expect(await screen.findByText('26127 Tilburg (Heijmans)')).toBeInTheDocument()
    expect(screen.queryByText('26100 Oud werk (X)')).not.toBeInTheDocument()
    const toggle = screen.getByTestId('toggle-afgesloten')
    expect(toggle).toHaveTextContent('Toon afgesloten (1)')
    await userEvent.click(toggle)
    expect(await screen.findByText('26100 Oud werk (X)')).toBeInTheDocument()
    expect(screen.getByText(/^afgesloten/)).toBeInTheDocument()
    expect(urls.some((u) => u.includes('alleen_actief=false'))).toBe(true)
    expect(screen.getByTestId('toggle-afgesloten')).toHaveTextContent('Verberg afgesloten')
  })
})

describe('ProjectenKantoorbreedScreen — kandidaat afsluiten + toggle', () => {
  const rij = (id: string, extra: Record<string, unknown>) => ({
    administratie_id: ADM,
    administratie_naam: 'Universal',
    project_id: id,
    naam: id === PID ? '26127 Tilburg (Heijmans)' : '26100 Oud werk (X)',
    opdrachtgever: null,
    werknummer_opdrachtgever: null,
    looptijd_tot: null,
    resultaat: { baten: '0', kosten: '0', marge: '0', marge_pct: null, onbepaalbaar_uren: '0', heeft_cijfers: false },
    verplichtingen: { aantal: 0, goedgekeurd_excl: '0', verbruikt_excl: '0', percentage: null, overschreden: 0 },
    weekstaten: { van_toepassing: false, ontbrekend: 0, oudste_ontbrekende_jaar: null, oudste_ontbrekende_week: null, te_keuren: 0, concept: 0 },
    m2: { gebouwd_m2: '400', contract_m2: '400', percentage: 100, doorlopende_huur: false },
    signalen: [],
    urgentie: 0,
    ...extra,
  })
  it('toont de teller-chip en de rij-chip "kandidaat afsluiten"; de toggle zet ?afgesloten=1 en vraagt toon_afgesloten', async () => {
    const urls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        urls.push(url)
        if (url === '/auth/administraties') return Promise.resolve(json({ administraties: [{ id: ADM, naam: 'Universal' }] }))
        if (url.startsWith('/projecten/kantoorbreed?')) {
          const toon = url.includes('toon_afgesloten=true')
          const rijen = [rij(PID, { kandidaat_afsluiten: true, kandidaat_reden: 'geen activiteit sinds 2026-05-01 (140 dagen) · contract-m² bereikt' })]
          if (toon) rijen.push(rij(PID2, { status: 'afgesloten', afgesloten_op: '2026-09-15T00:00:00Z' }))
          return Promise.resolve(
            json({
              rijen,
              totaal: rijen.length,
              pagina: 1,
              per_pagina: 25,
              administraties_in_selectie: 1,
              tellers: { projecten: 1, administraties: 1, met_signaal: 0, verplichting_overschreden: 0, marge_negatief: 0, weekstaat_ontbreekt: 0, te_keuren: 0, kandidaat_afsluiten: 1, afgesloten: 1 },
              facetten: { status: { alle: 1 }, administraties: [] },
            }),
          )
        }
        return Promise.resolve(new Response(null, { status: 404 }))
      }),
    )
    render(
      <MemoryRouter initialEntries={['/projecten']}>
        <Routes>
          <Route path="/projecten" element={<ProjectenKantoorbreedScreen />} />
        </Routes>
      </MemoryRouter>,
    )
    expect(await screen.findByTestId('chip-kandidaat')).toHaveTextContent('1 kandidaat afsluiten')
    expect(screen.getByTestId('chip-kandidaat-rij')).toHaveAttribute('title', expect.stringContaining('140 dagen'))
    await userEvent.click(screen.getByTestId('toggle-afgesloten'))
    expect(await screen.findByTestId('chip-afgesloten')).toHaveTextContent('afgesloten 15-9-2026')
    expect(urls.some((u) => u.includes('toon_afgesloten=true'))).toBe(true)
  })
})

describe('NieuwProjectModal — projectnummer bestaat al (409)', () => {
  it('toont het bestaande project mét status en "Openen" kiest dat project; niets aangemaakt', async () => {
    const posts: unknown[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url.includes('/volgend-nummer')) return Promise.resolve(json({ projectnummer: '26127' }))
        if (url === `/projecten/${ADM}` && init?.method === 'POST') {
          posts.push(JSON.parse(String(init.body)))
          return Promise.resolve(
            json(
              {
                detail: {
                  code: 'projectnummer_bestaat_al',
                  melding: '26127 bestaat al: 26127 Tilburg (Heijmans), lopend — openen?',
                  nummer: '26127',
                  bestaand_project_id: PID,
                  bestaand_naam: '26127 Tilburg (Heijmans)',
                  status: 'lopend',
                  bron: 'cache',
                },
              },
              409,
            ),
          )
        }
        return Promise.resolve(json({ detail: `onverwacht: ${url}` }, 500))
      }),
    )
    const gekozen: string[] = []
    render(<NieuwProjectModal administratieId={ADM} onKlaar={(id) => gekozen.push(id)} onAnnuleren={() => {}} />)
    const dialoog = await screen.findByRole('dialog')
    await waitFor(() => expect((within(dialoog).getByPlaceholderText('26xxx') as HTMLInputElement).value).toBe('26127'))
    await userEvent.type(within(dialoog).getByPlaceholderText('bijv. Tilburg'), 'Breda')
    await userEvent.type(within(dialoog).getByPlaceholderText('bijv. Heijmans'), 'Moeskops')
    await userEvent.click(within(dialoog).getByRole('button', { name: 'Aanmaken in RLZ' }))
    const melding = await screen.findByTestId('nummer-bestaat-al')
    expect(melding).toHaveTextContent('26127')
    expect(melding).toHaveTextContent('26127 Tilburg (Heijmans)')
    expect(melding).toHaveTextContent('(lopend)')
    expect(posts).toHaveLength(1)
    await userEvent.click(within(melding).getByRole('button', { name: 'Openen' }))
    expect(gekozen).toEqual([PID])
  })
})
