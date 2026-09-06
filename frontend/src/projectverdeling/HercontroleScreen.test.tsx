import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ProjectverdelingSignaalLijstDto, ProjectverdelingSignaalRijDto } from '../api/types'
import { HercontroleScreen, verschuivingen } from './HercontroleScreen'

// Inzicht › Projectverdeling KANTOORBREED (opdracht 06-09 blok B, mockup inzicht-kantoorbreed ①②⑨): één lijst
// over alle administraties (server sorteert/pagineert/telt), chips + administratie-facet + zoekterm in de URL,
// per rij de BESTAANDE actie "Herverdelen…" (zelfde dialoog + POST als het controlescherm) en de deep-link naar
// het document. De client formatteert alleen.

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const ADMIN_A = 'aaaaaaaa-0000-0000-0000-000000000001'
const ADMIN_B = 'bbbbbbbb-0000-0000-0000-000000000002'
const DOC_1 = 'dddddddd-0000-0000-0000-000000000001'
const DOC_2 = 'dddddddd-0000-0000-0000-000000000002'
const EINDHOVEN = 'cccccccc-0000-0000-0000-000000000011'
const TILBURG = 'cccccccc-0000-0000-0000-000000000012'
const VENLO = 'cccccccc-0000-0000-0000-000000000013'

const FLOORBEHEER: ProjectverdelingSignaalRijDto = {
  administratie_id: ADMIN_A,
  administratie_naam: 'Universal Steigerbouw B.V.',
  document_id: DOC_1,
  bestandsnaam: 'floorbeheer-2026-07.pdf',
  leverancier: 'Floorbeheer B.V.',
  referentie: 'FB-2026-0731',
  pro_rato_periode: '2026-07-01',
  pro_rato_bedrag: '1400.00',
  afwijking_pct: '7.73',
  drempel_pct: '5.00',
  hercontrole_op: '2026-09-02T04:10:00Z',
  totaalbedrag: '2420.00',
  geboekt_op: '2026-08-12T09:30:00Z',
  delen_oud: [
    { project_id: TILBURG, project_naam: '26127 Tilburg (Heijmans)', wijze: 'vast', bedrag: '600.00' },
    { project_id: EINDHOVEN, project_naam: '26120 Eindhoven (BAM)', wijze: 'pro_rato', bedrag: '840.00' },
    { project_id: TILBURG, project_naam: '26127 Tilburg (Heijmans)', wijze: 'pro_rato', bedrag: '350.00' },
    { project_id: VENLO, project_naam: '26131 Venlo (Dura)', wijze: 'pro_rato', bedrag: '210.00' },
  ],
  delen_nieuw: [
    { project_id: TILBURG, project_naam: '26127 Tilburg (Heijmans)', wijze: 'vast', bedrag: '600.00' },
    { project_id: EINDHOVEN, project_naam: '26120 Eindhoven (BAM)', wijze: 'pro_rato', bedrag: '763.64' },
    { project_id: TILBURG, project_naam: '26127 Tilburg (Heijmans)', wijze: 'pro_rato', bedrag: '318.18' },
    { project_id: VENLO, project_naam: '26131 Venlo (Dura)', wijze: 'pro_rato', bedrag: '318.18' },
  ],
}
const DERKS: ProjectverdelingSignaalRijDto = {
  ...FLOORBEHEER,
  administratie_id: ADMIN_B,
  administratie_naam: 'Kempen Facilities B.V.',
  document_id: DOC_2,
  bestandsnaam: 'derks-0812.pdf',
  leverancier: 'Derks Management',
  referentie: 'DM-812',
  afwijking_pct: '5.20',
  totaalbedrag: '1210.00',
}

function lijst(rijen: ProjectverdelingSignaalRijDto[] = [FLOORBEHEER, DERKS], extra: Partial<ProjectverdelingSignaalLijstDto> = {}): ProjectverdelingSignaalLijstDto {
  return {
    rijen,
    totaal: rijen.length,
    pagina: 1,
    per_pagina: 25,
    administraties: new Set(rijen.map((r) => r.administratie_id)).size,
    tellers: { signalen: 2, administraties: 2 },
    ...extra,
  }
}

function stubFetch(opties: { lijstAntwoord?: ProjectverdelingSignaalLijstDto; postStatus?: number; postDetail?: string } = {}) {
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
              { id: ADMIN_B, naam: 'Kempen Facilities B.V.' },
            ],
          }),
        )
      }
      if (url.startsWith('/projectverdeling/hercontrole-signalen?')) return Promise.resolve(jsonResponse(opties.lijstAntwoord ?? lijst()))
      if (url.endsWith('/projectverdeling/herverdelen') && method === 'POST') {
        if (opties.postStatus && opties.postStatus !== 200) {
          return Promise.resolve(jsonResponse({ detail: opties.postDetail ?? 'Mislukt' }, opties.postStatus))
        }
        return Promise.resolve(
          jsonResponse({ document_id: DOC_1, status: 'te_controleren', rlz_tegenboeking_id: 'eeeeeeee-0000-0000-0000-000000000001', rlz_boekstuknummer: 'IF-2026-0912' }),
        )
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
  return aangeroepen
}

function renderScherm(pad = '/projectverdeling') {
  return render(
    <MemoryRouter initialEntries={[pad]}>
      <Routes>
        <Route path="/projectverdeling" element={<HercontroleScreen />} />
        <Route path="/" element={<div>Documentenlijst</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('HercontroleScreen (Inzicht › Projectverdeling, kantoorbreed)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('toont chips, één rij per signaal (leverancier vet + subregel, administratie-link, afwijking-chip, oud → nieuw, deep-link) en de voet', async () => {
    const aangeroepen = stubFetch()
    renderScherm()
    const tabel = await screen.findByTestId('hercontrole-tabel')
    expect(screen.getByTestId('chip-signalen')).toHaveTextContent('2 signalen')
    expect(screen.getByTestId('chip-administraties')).toHaveTextContent('over 2 administraties')
    // Eerste lijst-call: pagina 1, geen facet, geen zoekterm — de server sorteert (zwaarste eerst).
    expect(aangeroepen.find((a) => a.pad.startsWith('/projectverdeling/hercontrole-signalen?'))!.pad).toBe(
      '/projectverdeling/hercontrole-signalen?pagina=1',
    )
    const rijen = within(tabel).getAllByTestId('hercontrole-rij')
    expect(rijen).toHaveLength(2)
    expect(within(rijen[0]).getByText('Floorbeheer B.V.')).toBeInTheDocument()
    expect(rijen[0]).toHaveTextContent(/FB-2026-0731 · € 2\.420,00 · geboekt 12-08/)
    expect(within(rijen[0]).getByRole('link', { name: 'Universal Steigerbouw B.V.' })).toHaveAttribute('href', `/?administratie=${ADMIN_A}`)
    expect(within(rijen[0]).getByTestId('chip-afwijking')).toHaveTextContent('7,73 % afwijking')
    expect(rijen[0]).toHaveTextContent(/drempel 5 % · omzet juli 2026/)
    // Compact oud → nieuw: alleen verschoven projecten (de vaste Tilburg-regel van € 600 telt op en verschuift óók).
    expect(rijen[0]).toHaveTextContent(/26131 Venlo \(Dura\): € 210,00 → € 318,18/)
    expect(rijen[0]).toHaveTextContent(/26120 Eindhoven \(BAM\): € 840,00 → € 763,64/)
    expect(within(rijen[0]).getByRole('link', { name: /Naar het document van Floorbeheer/ })).toHaveAttribute('href', `/?administratie=${ADMIN_A}&document=${DOC_1}`)
    expect(screen.getByTestId('hercontrole-voet')).toHaveTextContent(/1 van 1/)
    expect(screen.getByTestId('hercontrole-voet')).toHaveTextContent(/2 signalen over 2 administraties/)
  })

  it('facet en zoekterm leven in de URL en gaan server-side mee; deep-link ?administratie=X vult het facet voor', async () => {
    const aangeroepen = stubFetch()
    renderScherm(`/projectverdeling?administratie=${ADMIN_A}`)
    await screen.findByTestId('hercontrole-tabel')
    expect(aangeroepen.find((a) => a.pad.startsWith('/projectverdeling/hercontrole-signalen?'))!.pad).toBe(
      `/projectverdeling/hercontrole-signalen?pagina=1&administratie_id=${ADMIN_A}`,
    )
    await userEvent.type(screen.getByLabelText('Zoek leverancier of referentie'), 'derks')
    await waitFor(() =>
      expect(aangeroepen.some((a) => a.pad === `/projectverdeling/hercontrole-signalen?pagina=1&administratie_id=${ADMIN_A}&q=derks`)).toBe(true),
    )
  })

  it('Herverdelen… opent de BESTAANDE dialoog (oud vs nieuw) en POST naar de herverdelen-route van dát document; daarna herlaadt de lijst', async () => {
    const aangeroepen = stubFetch()
    renderScherm()
    const tabel = await screen.findByTestId('hercontrole-tabel')
    const lijstCallsVoor = aangeroepen.filter((a) => a.pad.startsWith('/projectverdeling/hercontrole-signalen?')).length
    await userEvent.click(within(tabel).getByRole('button', { name: /^Herverdelen: Floorbeheer/ }))
    const dialoog = await screen.findByTestId('pv-herverdeel-dialoog')
    expect(dialoog).toHaveTextContent('26131 Venlo (Dura)')
    expect(dialoog).toHaveTextContent('€ 210,00')
    expect(dialoog).toHaveTextContent('€ 318,18')
    await userEvent.type(within(dialoog).getByLabelText('Reden herverdelen'), 'nagekomen factuur Venlo')
    await userEvent.click(within(dialoog).getByRole('button', { name: 'Tegenboeken en herverdelen' }))
    await waitFor(() => expect(aangeroepen.some((a) => a.method === 'POST')).toBe(true))
    const post = aangeroepen.find((a) => a.method === 'POST')!
    expect(post.pad).toBe(`/administraties/${ADMIN_A}/documenten/${DOC_1}/projectverdeling/herverdelen`)
    expect(post.body).toEqual({ reden: 'nagekomen factuur Venlo' })
    await waitFor(() => expect(screen.queryByTestId('pv-herverdeel-dialoog')).toBeNull())
    await waitFor(() => expect(aangeroepen.filter((a) => a.pad.startsWith('/projectverdeling/hercontrole-signalen?')).length).toBeGreaterThan(lijstCallsVoor))
  })

  it('een 409 (aangifte-poort niet blokkerend → storno is de route) blijft leesbaar in de dialoog, niets stil', async () => {
    stubFetch({ postStatus: 409, postDetail: 'Herverdelen via tegenboeken kan alleen als storno geblokkeerd is' })
    renderScherm()
    await userEvent.click(within(await screen.findByTestId('hercontrole-tabel')).getByRole('button', { name: /^Herverdelen: Derks/ }))
    const dialoog = await screen.findByTestId('pv-herverdeel-dialoog')
    await userEvent.click(within(dialoog).getByRole('button', { name: 'Tegenboeken en herverdelen' }))
    expect(await within(dialoog).findByText(/Herverdelen via tegenboeken kan alleen/)).toBeInTheDocument()
  })

  it('lege stand zonder filter benoemt de cadans; mét filter zegt hij dat het filter leeg is', async () => {
    stubFetch({ lijstAntwoord: lijst([], { totaal: 0, administraties: 0, tellers: { signalen: 0, administraties: 0 } }) })
    renderScherm()
    expect(await screen.findByTestId('hercontrole-leeg')).toHaveTextContent(
      'Geen afwijkingen — de maandelijkse hercontrole draait mee in de dagelijkse sync.',
    )
    expect(screen.getByTestId('chip-signalen')).toHaveTextContent('0 signalen')
    cleanup()
    vi.unstubAllGlobals()
    stubFetch({ lijstAntwoord: lijst([], { totaal: 0, administraties: 0, tellers: { signalen: 2, administraties: 2 } }) })
    renderScherm('/projectverdeling?q=bestaat-niet')
    expect(await screen.findByTestId('hercontrole-leeg')).toHaveTextContent('Geen afwijkingen binnen dit filter.')
    // De kopchips blijven de kantoorbrede stand tonen, ook als het filter niets oplevert.
    expect(screen.getByTestId('chip-signalen')).toHaveTextContent('2 signalen')
  })

  it('verschuivingen(): alleen projecten waarvan het deel verschuift, gesommeerd per project, grootste nieuwe deel eerst', () => {
    const rijen = verschuivingen(FLOORBEHEER.delen_oud ?? [], FLOORBEHEER.delen_nieuw ?? [])
    expect(rijen.map((r) => [r.naam, r.oud, r.nieuw])).toEqual([
      ['26127 Tilburg (Heijmans)', '950.00', '918.18'],
      ['26120 Eindhoven (BAM)', '840.00', '763.64'],
      ['26131 Venlo (Dura)', '210.00', '318.18'],
    ])
  })
})
