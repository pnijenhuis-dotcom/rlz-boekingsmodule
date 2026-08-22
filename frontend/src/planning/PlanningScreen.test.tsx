/** Planning-agenda steigerbouw (akkoord Peter 22-08): weekgrid met actieve projecten als
 * rijen en kaartjes per dag, pool met geplande-dagen-teller (> 5 = zacht signaal, besluit C),
 * controle-meldingen + dubbele-dag-teller (kantoor-only) en de 403-module-recht-melding. */
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PlanningScreen } from './PlanningScreen'

const ADMINISTRATIE_ID = 'dddddddd-0000-0000-0000-00000000000d'
const PROJECT_ID = 'aaaaaaaa-0000-0000-0000-00000000000a'
const ZZP_ID = 'bbbbbbbb-0000-0000-0000-00000000000b'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function planningWeek(overrides: Record<string, unknown> = {}) {
  return {
    jaar: 2026,
    weeknummer: 35,
    maandag: '2026-08-24',
    zondag: '2026-08-30',
    projecten: [
      {
        project_id: PROJECT_ID,
        project_naam: '144 Breda (Moeskops)',
        opdrachtgever: 'Moeskops',
        soort_werk: 'montage',
        looptijd_tot: null,
        week_man: 2,
        per_datum: {
          '2026-08-24': [
            { gebruiker_id: ZZP_ID, naam: 'Milan K.', rol: 'zzper', dagdeel: 'heel' },
            { gebruiker_id: 'cccccccc-0000-0000-0000-00000000000c', naam: 'Ben v. Dijk', rol: 'uitvoerder', dagdeel: 'half' },
          ],
        },
      },
    ],
    pool: [
      { gebruiker_id: ZZP_ID, naam: 'Milan K.', rol: 'zzper', geplande_dagen: '6' },
      { gebruiker_id: 'cccccccc-0000-0000-0000-00000000000c', naam: 'Ben v. Dijk', rol: 'uitvoerder', geplande_dagen: '0.5' },
    ],
    buiten_planning: [
      { gebruiker_id: ZZP_ID, naam: 'Milan K.', datum: '2026-08-26', project_naam: '25013 Deurne', uren: '4' },
    ],
    dubbele_dagen: [
      {
        gebruiker_id: ZZP_ID,
        naam: 'Stefan B.',
        datum: '2026-08-25',
        project_namen: ['144 Breda', '25011 Zwolle'],
        ongedekte_project_namen: ['25011 Zwolle'],
      },
    ],
    dubbele_dag_tellers: [{ gebruiker_id: ZZP_ID, naam: 'Stefan B.', aantal: 3 }],
    ...overrides,
  }
}

function installMock(planning: () => Response) {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/auth/administraties'))
        return Promise.resolve(jsonResponse({ administraties: [{ id: ADMINISTRATIE_ID, naam: 'Universal Steigerbouw' }] }))
      if (url.includes('/uren/kantoor/planning')) return Promise.resolve(planning())
      return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
    }),
  )
}

function renderScherm() {
  return render(
    <MemoryRouter initialEntries={[`/planning?administratie=${ADMINISTRATIE_ID}`]}>
      <Routes>
        <Route path="/planning" element={<PlanningScreen />} />
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('PlanningScreen', () => {
  it('toont het weekgrid met kaartjes, tellers en de kantoor-signalen', async () => {
    installMock(() => jsonResponse(planningWeek()))
    renderScherm()
    await waitFor(() => expect(screen.getByText('144 Breda (Moeskops)')).toBeInTheDocument())
    // Kaartjes in de cel — de uitvoerder draagt het uitv.-label, de projectrij de man-teller.
    expect(screen.getAllByText('Milan K.').length).toBeGreaterThan(0)
    expect(screen.getByText('deze week: 2 man')).toBeInTheDocument()
    expect(screen.getAllByText('uitv.').length).toBeGreaterThan(0)
    // Besluit C: > 5 geplande dagen kleurt als zacht signaal (title-attribuut aanwezig).
    expect(screen.getByTitle('Meer dan 5 geplande dagen deze week (zacht signaal)')).toBeInTheDocument()
    // Kantoor-signalen: buiten planning (oranje) + dubbele dag + 30-dagen-teller.
    expect(screen.getByText(/uren buiten planning/)).toBeInTheDocument()
    expect(screen.getByText(/dubbele dag/)).toBeInTheDocument()
    expect(screen.getByText('3× / 30 dgn')).toBeInTheDocument()
  })

  it('meldt netjes dat het module-recht ontbreekt (403 — fail-closed)', async () => {
    installMock(() => jsonResponse({ detail: 'geen recht' }, 403))
    renderScherm()
    await waitFor(() =>
      expect(screen.getByText(/module-recht "Meerwerk & urenstaten"/)).toBeInTheDocument(),
    )
  })

  it('meldt de opt-in-uitschakeling (409) zonder grid', async () => {
    installMock(() => jsonResponse({ detail: 'module uit' }, 409))
    renderScherm()
    await waitFor(() =>
      expect(screen.getByText(/niet ingeschakeld voor deze administratie/)).toBeInTheDocument(),
    )
  })
})
