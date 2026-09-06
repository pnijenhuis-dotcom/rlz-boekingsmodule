import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PlanningSignalenScreen } from './PlanningSignalenScreen'
import type { PlanningSignaalDto, PlanningSignalenLijstDto } from './planningSignaalApi'

// Weekstaten ontbreken — KANTOORBREED (mini-run 06-09 blok A, inzicht-kantoorbreed ①②⑨): één lijst over alle
// administraties mét uren-opt-in (server sorteert/pagineert), chips + administratie-facet + filter, één
// handeling per rij (herinneren / afmelden mét verplichte reden / toch tonen) en de deep-link naar de planning.

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const ADMIN_A = 'aaaaaaaa-0000-0000-0000-000000000001'
const ADMIN_B = 'bbbbbbbb-0000-0000-0000-000000000002'

const OPEN: PlanningSignaalDto = {
  administratie_id: ADMIN_A,
  administratie_naam: 'Universal Steigerbouw B.V.',
  gebruiker_id: 'zzp-1',
  gebruiker_naam: 'Milan K.',
  gebruiker_actief: true,
  project_id: 'proj-1',
  project_naam: '26014 Eindhoven (BAM)',
  jaar: 2026,
  weeknummer: 27,
  maandag: '2026-06-29',
  zondag: '2026-07-05',
  geplande_dagen: '2.5',
  soort: 'geen_staat',
  weekstaat_status: null,
  status: 'open',
  herinneringen: 0,
  laatste_herinnering: null,
  herinnerd_vandaag: false,
  afmelding: null,
}
const CONCEPT_HERINNERD: PlanningSignaalDto = {
  ...OPEN,
  administratie_id: ADMIN_B,
  administratie_naam: 'Bradwolff Constructie B.V.',
  gebruiker_id: 'zzp-2',
  gebruiker_naam: 'Ben v. Dijk',
  project_id: 'proj-2',
  project_naam: '26021 Tilburg (Heijmans)',
  weeknummer: 28,
  maandag: '2026-07-06',
  zondag: '2026-07-12',
  geplande_dagen: '1',
  soort: 'concept',
  weekstaat_status: 'concept',
  herinneringen: 2,
  laatste_herinnering: { op: '2026-09-06T08:00:00Z', kanaal: 'push', door_naam: 'Rob T.' },
  herinnerd_vandaag: true,
}
const AFGEMELD: PlanningSignaalDto = {
  ...OPEN,
  gebruiker_id: 'zzp-3',
  gebruiker_naam: 'Karin S.',
  weeknummer: 26,
  maandag: '2026-06-22',
  zondag: '2026-06-28',
  status: 'afgemeld',
  afmelding: { reden: 'ziek gemeld die week', op: '2026-09-05T10:00:00Z', door_naam: 'Rob T.' },
}

function lijst(rijen: PlanningSignaalDto[], extra: Partial<PlanningSignalenLijstDto> = {}): PlanningSignalenLijstDto {
  return {
    rijen,
    totaal: rijen.length,
    pagina: 1,
    per_pagina: 25,
    administraties_in_selectie: 2,
    tellers: { open: 2, afgemeld: 1, administraties: 2 },
    facet_administraties: [
      { administratie_id: ADMIN_A, naam: 'Universal Steigerbouw B.V.', aantal: 1 },
      { administratie_id: ADMIN_B, naam: 'Bradwolff Constructie B.V.', aantal: 1 },
    ],
    venster_weken: 6,
    ...extra,
  }
}

function stubFetch(opties: { lijstVoor?: (url: string) => PlanningSignalenLijstDto; actieStatus?: number; actieDetail?: string } = {}) {
  const aangeroepen: { pad: string; method: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      aangeroepen.push({ pad: url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined })
      if (url === '/auth/administraties') {
        return Promise.resolve(
          jsonResponse({
            administraties: [
              { id: ADMIN_A, naam: 'Universal Steigerbouw B.V.' },
              { id: ADMIN_B, naam: 'Bradwolff Constructie B.V.' },
            ],
          }),
        )
      }
      if (url.startsWith('/uren/kantoor/planning-signalen?')) {
        return Promise.resolve(jsonResponse(opties.lijstVoor ? opties.lijstVoor(url) : lijst([OPEN, CONCEPT_HERINNERD])))
      }
      if (url.startsWith('/uren/kantoor/planning-signalen/')) {
        if (opties.actieStatus) return Promise.resolve(jsonResponse({ detail: opties.actieDetail ?? 'Mislukt' }, opties.actieStatus))
        if (url.endsWith('/herinneren')) {
          return Promise.resolve(jsonResponse({ gebruiker_id: 'zzp-1', kanaal: 'push', verzonden_op: '2026-09-06T09:00:00Z', herinneringen: 1 }))
        }
        return Promise.resolve(jsonResponse({ id: 'afh-1' }))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
  return aangeroepen
}

function renderScherm(pad = '/meerwerk/planning-signalen') {
  return render(
    <MemoryRouter initialEntries={[pad]}>
      <PlanningSignalenScreen />
    </MemoryRouter>,
  )
}

describe('PlanningSignalenScreen (kantoorbreed)', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('toont chips, één rij per signaal mét week/administratie/veldwerker/project/stand en de voet; filter gaat naar de server', async () => {
    const aangeroepen = stubFetch()
    renderScherm()
    const tabel = await screen.findByTestId('planning-signalen-tabel')
    expect(screen.getByTestId('chip-open')).toHaveTextContent('2 open')
    expect(screen.getByTestId('chip-afgemeld')).toHaveTextContent('1 afgemeld')
    expect(aangeroepen.find((a) => a.pad.startsWith('/uren/kantoor/planning-signalen?'))!.pad).toBe(
      '/uren/kantoor/planning-signalen?pagina=1&filter=open',
    )
    const rijen = within(tabel).getAllByTestId('planning-signaal-rij')
    expect(rijen).toHaveLength(2)
    // Geen weekstaat: week, administratie-link, veldwerker, project, geplande dagen als "2,5 dagen", rode stand-chip.
    expect(within(rijen[0]).getByText('wk 27')).toBeInTheDocument()
    expect(within(rijen[0]).getByRole('link', { name: 'Universal Steigerbouw B.V.' })).toHaveAttribute('href', `/?administratie=${ADMIN_A}`)
    expect(within(rijen[0]).getByText('Milan K.')).toBeInTheDocument()
    expect(within(rijen[0]).getByText('26014 Eindhoven (BAM)')).toBeInTheDocument()
    expect(within(rijen[0]).getByText('2,5 dagen')).toBeInTheDocument()
    expect(within(rijen[0]).getByTestId('chip-status')).toHaveTextContent('geen weekstaat')
    expect(within(rijen[0]).getByRole('button', { name: /Herinnering sturen aan Milan K\./ })).toBeEnabled()
    expect(within(rijen[0]).getByRole('link', { name: /Naar de planning van week 27/ })).toHaveAttribute(
      'href',
      `/planning?administratie=${ADMIN_A}&week=2026-W27`,
    )
    // Concept + vandaag herinnerd: oranje chip, herinner-regel "2×", knop uit met de tekst "Herinnerd vandaag".
    expect(within(rijen[1]).getByTestId('chip-status')).toHaveTextContent('concept, niet ingediend')
    expect(within(rijen[1]).getByText(/herinnerd .* · 2× · push/)).toBeInTheDocument()
    const herinnerd = within(rijen[1]).getByRole('button', { name: /Herinnering sturen aan Ben v\. Dijk/ })
    expect(herinnerd).toBeDisabled()
    expect(herinnerd).toHaveTextContent('Herinnerd vandaag')
    expect(screen.getByTestId('planning-signalen-voet')).toHaveTextContent(/2 signalen over 2 administraties/)
    // Filter "afgemeld" → server-side parameter.
    await userEvent.click(screen.getByRole('button', { name: /^afgemeld/ }))
    await waitFor(() =>
      expect(aangeroepen.some((a) => a.pad === '/uren/kantoor/planning-signalen?pagina=1&filter=afgemeld')).toBe(true),
    )
  })

  it('administratie in de URL is een filter en gaat als administratie_id naar de server', async () => {
    const aangeroepen = stubFetch()
    renderScherm(`/meerwerk/planning-signalen?administratie_id=${ADMIN_B}`)
    await screen.findByTestId('planning-signalen-tabel')
    expect(aangeroepen.find((a) => a.pad.startsWith('/uren/kantoor/planning-signalen?'))!.pad).toBe(
      `/uren/kantoor/planning-signalen?pagina=1&filter=open&administratie_id=${ADMIN_B}`,
    )
  })

  it('"Herinnering sturen" post de sleutel en herlaadt; een 409 (vandaag al herinnerd) is zichtbaar en blokkeert niets', async () => {
    const aangeroepen = stubFetch()
    renderScherm()
    const tabel = await screen.findByTestId('planning-signalen-tabel')
    await userEvent.click(within(tabel).getAllByRole('button', { name: /Herinnering sturen aan Milan K\./ })[0])
    await waitFor(() => expect(aangeroepen.some((a) => a.pad === '/uren/kantoor/planning-signalen/herinneren')).toBe(true))
    const post = aangeroepen.find((a) => a.pad === '/uren/kantoor/planning-signalen/herinneren')!
    expect(post.method).toBe('POST')
    expect(post.body).toEqual({ administratie_id: ADMIN_A, gebruiker_id: 'zzp-1', project_id: 'proj-1', jaar: 2026, weeknummer: 27 })
    // Ná de actie wordt de lijst opnieuw opgehaald.
    await waitFor(() => expect(aangeroepen.filter((a) => a.pad.startsWith('/uren/kantoor/planning-signalen?')).length).toBe(2))
    cleanup()
    vi.unstubAllGlobals()

    stubFetch({ actieStatus: 409, actieDetail: 'Vandaag is er al een herinnering voor deze week aan deze veldwerker verstuurd' })
    renderScherm()
    const tabel2 = await screen.findByTestId('planning-signalen-tabel')
    await userEvent.click(within(tabel2).getAllByRole('button', { name: /Herinnering sturen aan Milan K\./ })[0])
    expect(await screen.findByText(/Vandaag is er al een herinnering/)).toBeInTheDocument()
    expect(screen.getByTestId('planning-signalen-tabel')).toBeInTheDocument()
  })

  it('"Afmelden…" eist een inhoudelijke reden (≥ 5 tekens) en post sleutel + reden', async () => {
    const aangeroepen = stubFetch()
    renderScherm()
    const tabel = await screen.findByTestId('planning-signalen-tabel')
    await userEvent.click(within(tabel).getByRole('button', { name: /Afmelden: week 27 van Milan K\./ }))
    const dialoog = await screen.findByTestId('afmeld-dialoog')
    expect(within(dialoog).getByText(/Week 27 · Milan K\. · 26014 Eindhoven \(BAM\)/)).toBeInTheDocument()
    const bevestig = within(dialoog).getByRole('button', { name: 'Afmelden' })
    expect(bevestig).toBeDisabled()
    await userEvent.type(within(dialoog).getByLabelText('Reden'), 'ziek')
    expect(bevestig).toBeDisabled()
    expect(within(dialoog).getByText(/minimaal 5 tekens/)).toBeInTheDocument()
    await userEvent.type(within(dialoog).getByLabelText('Reden'), ' gemeld die week')
    expect(bevestig).toBeEnabled()
    await userEvent.click(bevestig)
    await waitFor(() => expect(aangeroepen.some((a) => a.pad === '/uren/kantoor/planning-signalen/afmelden')).toBe(true))
    const post = aangeroepen.find((a) => a.pad === '/uren/kantoor/planning-signalen/afmelden')!
    expect(post.body).toEqual({
      administratie_id: ADMIN_A,
      gebruiker_id: 'zzp-1',
      project_id: 'proj-1',
      jaar: 2026,
      weeknummer: 27,
      reden: 'ziek gemeld die week',
    })
    await waitFor(() => expect(screen.queryByTestId('afmeld-dialoog')).toBeNull())
  })

  it('een afgemeld signaal toont de reden en "Toch tonen" trekt de afmelding in', async () => {
    const aangeroepen = stubFetch({ lijstVoor: () => lijst([AFGEMELD], { tellers: { open: 0, afgemeld: 1, administraties: 0 } }) })
    renderScherm('/meerwerk/planning-signalen?filter=afgemeld')
    const tabel = await screen.findByTestId('planning-signalen-tabel')
    const rij = within(tabel).getAllByTestId('planning-signaal-rij')[0]
    expect(within(rij).getByTestId('chip-status')).toHaveTextContent('afgemeld')
    expect(within(rij).getByText(/afgemeld: ziek gemeld die week · Rob T\./)).toBeInTheDocument()
    expect(within(rij).queryByRole('button', { name: /Herinnering sturen/ })).toBeNull()
    await userEvent.click(within(rij).getByRole('button', { name: /Toch tonen: week 26 van Karin S\./ }))
    await waitFor(() => expect(aangeroepen.some((a) => a.pad === '/uren/kantoor/planning-signalen/afmelden-intrekken')).toBe(true))
    expect(aangeroepen.find((a) => a.pad === '/uren/kantoor/planning-signalen/afmelden-intrekken')!.body).toEqual({
      administratie_id: ADMIN_A,
      gebruiker_id: 'zzp-3',
      project_id: 'proj-1',
      jaar: 2026,
      weeknummer: 26,
    })
  })

  it('lege stand en 403 zonder module-recht zijn leesbaar', async () => {
    stubFetch({ lijstVoor: () => lijst([], { totaal: 0, administraties_in_selectie: 0, tellers: { open: 0, afgemeld: 0, administraties: 0 } }) })
    renderScherm()
    expect(await screen.findByTestId('planning-signalen-leeg')).toHaveTextContent(/alles is ingediend of afgemeld/)
    cleanup()
    vi.unstubAllGlobals()

    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url === '/auth/administraties') return Promise.resolve(jsonResponse({ administraties: [] }))
        return Promise.resolve(jsonResponse({ detail: "Vereist het module-recht 'Meerwerk & urenstaten'" }, 403))
      }),
    )
    renderScherm()
    expect(await screen.findByText(/vereist een module-recht/)).toBeInTheDocument()
  })
})
