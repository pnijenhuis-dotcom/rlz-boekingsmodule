/** Planning-agenda steigerbouw (akkoord Peter 22-08 + jaaragenda-besluiten 22-08): weekgrid
 * met alléén projecten mét planning, "+ project toevoegen"-zoekrij, klik-alternatief voor
 * drag-and-drop, week in de URL (?week=2026-W41), einddatum-signaal, pool met geplande-
 * dagen-teller (> 5 = zacht signaal, besluit C), controle-meldingen + dubbele-dag-teller
 * (kantoor-only) en de 403-module-recht-melding. */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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

interface MockOpties {
  planning?: () => Response
  zoek?: () => Response
  post?: () => Response
}

function installMock(opties: MockOpties = {}) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/auth/administraties'))
      return Promise.resolve(jsonResponse({ administraties: [{ id: ADMINISTRATIE_ID, naam: 'Universal Steigerbouw' }] }))
    if (url.includes('/uren/kantoor/planning/projecten'))
      return Promise.resolve((opties.zoek ?? (() => jsonResponse([])))())
    if (url.includes('/uren/kantoor/planning') && init?.method === 'POST') {
      // Spiegel de echte backend: vereis_administratie_scope leest administratie_id als
      // QUERY-parameter, óók op POST — zonder die parameter is de cloud-response een 422
      // (kliktest 23-08). De mock dwingt dat hier net zo hard af, anders vangt de suite
      // deze klasse bug nooit.
      if (!url.includes(`administratie_id=${ADMINISTRATIE_ID}`))
        return Promise.resolve(
          jsonResponse({ detail: [{ loc: ['query', 'administratie_id'], msg: 'Field required' }] }, 422),
        )
      return Promise.resolve((opties.post ?? (() => new Response(null, { status: 204 })))())
    }
    if (url.includes('/uren/kantoor/planning'))
      return Promise.resolve((opties.planning ?? (() => jsonResponse(planningWeek())))())
    return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderScherm(zoekdeel = `?administratie=${ADMINISTRATIE_ID}`) {
  return render(
    <MemoryRouter initialEntries={[`/planning${zoekdeel}`]}>
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
    installMock()
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

  it('leest de week uit de URL (?week=2026-W41) en vraagt die week op', async () => {
    const fetchMock = installMock({ planning: () => jsonResponse(planningWeek({ weeknummer: 41 })) })
    renderScherm(`?administratie=${ADMINISTRATIE_ID}&week=2026-W41`)
    await waitFor(() => expect(screen.getByText('144 Breda (Moeskops)')).toBeInTheDocument())
    const planningCall = fetchMock.mock.calls
      .map((c) => String(c[0]))
      .find((u) => u.includes('/uren/kantoor/planning?'))
    expect(planningCall).toContain('jaar=2026')
    expect(planningCall).toContain('weeknummer=41')
    // De weekkiezer staat op dezelfde waarde als de URL.
    expect(screen.getByLabelText('Weekkiezer')).toHaveValue('2026-W41')
  })

  it('voegt via de zoekrij een leeg project toe aan het grid', async () => {
    installMock({
      planning: () => jsonResponse(planningWeek({ projecten: [] })),
      zoek: () =>
        jsonResponse([
          {
            project_id: 'eeeeeeee-0000-0000-0000-00000000000e',
            naam: '25016 Groesbeek (Janssen)',
            opdrachtgever: 'Janssen-Groesbeek',
            soort_werk: null,
            looptijd_tot: null,
          },
        ]),
    })
    renderScherm()
    await waitFor(() => expect(screen.getByText(/Nog niets gepland in deze week/)).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('Zoek een actief project'), { target: { value: 'groesbeek' } })
    const resultaat = await screen.findByText(/25016 Groesbeek \(Janssen\) · Janssen-Groesbeek/)
    fireEvent.click(resultaat)
    // Het project staat nu als (lege) rij in het grid, klaar om op te plannen.
    await waitFor(() => expect(screen.getByText('25016 Groesbeek (Janssen)')).toBeInTheDocument())
  })

  it('plant via het klik-alternatief: cel aanklikken → persoon kiezen', async () => {
    let gepost: unknown = null
    installMock({
      post: () => new Response(null, { status: 204 }),
    })
    const fetchMock = vi.mocked(fetch)
    renderScherm(`?administratie=${ADMINISTRATIE_ID}&week=2026-W35`)
    await waitFor(() => expect(screen.getByText('144 Breda (Moeskops)')).toBeInTheDocument())
    // Dinsdag 25-08 is leeg — klik de cel aan en kies Ben v. Dijk uit de pool-lijst.
    fireEvent.click(screen.getByTestId(`cel-${PROJECT_ID}|2026-08-25`))
    const keuze = await screen.findByRole('button', { name: 'Ben v. Dijk · uitv.' })
    fireEvent.click(keuze)
    let postUrl = ''
    await waitFor(() => {
      const postCall = fetchMock.mock.calls.find((c) => (c[1] as RequestInit | undefined)?.method === 'POST')
      expect(postCall).toBeDefined()
      postUrl = String(postCall![0])
      gepost = JSON.parse(String((postCall![1] as RequestInit).body))
    })
    // De scope-check leest administratie_id uit de QUERY — zonder deze parameter is de echte
    // response een 422 (kliktest 23-08); de body alleen is niet genoeg.
    expect(postUrl).toContain(`administratie_id=${ADMINISTRATIE_ID}`)
    expect(gepost).toMatchObject({
      administratie_id: ADMINISTRATIE_ID,
      gebruiker_id: 'cccccccc-0000-0000-0000-00000000000c',
      project_id: PROJECT_ID,
      datum: '2026-08-25',
    })
  })

  it('verwijdert een kaartje mét administratie_id als query-parameter', async () => {
    const fetchMock = installMock()
    renderScherm(`?administratie=${ADMINISTRATIE_ID}&week=2026-W35`)
    await waitFor(() => expect(screen.getByText('144 Breda (Moeskops)')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Milan K. uit de planning halen' }))
    let postUrl = ''
    await waitFor(() => {
      const postCall = fetchMock.mock.calls.find((c) => (c[1] as RequestInit | undefined)?.method === 'POST')
      expect(postCall).toBeDefined()
      postUrl = String(postCall![0])
    })
    expect(postUrl).toContain('/uren/kantoor/planning/verwijderen')
    expect(postUrl).toContain(`administratie_id=${ADMINISTRATIE_ID}`)
    // De mock antwoordt 422 als de query-parameter ontbreekt — dan verschijnt hier een actie-fout.
    await waitFor(() => expect(screen.queryByText(/Actie mislukt|Field required/)).not.toBeInTheDocument())
  })

  it('wijzigt het dagdeel mét administratie_id als query-parameter', async () => {
    const fetchMock = installMock()
    renderScherm(`?administratie=${ADMINISTRATIE_ID}&week=2026-W35`)
    await waitFor(() => expect(screen.getByText('144 Breda (Moeskops)')).toBeInTheDocument())
    fireEvent.click(screen.getByTitle('Hele dag — maak ½ dag'))
    let postUrl = ''
    await waitFor(() => {
      const postCall = fetchMock.mock.calls.find((c) => (c[1] as RequestInit | undefined)?.method === 'POST')
      expect(postCall).toBeDefined()
      postUrl = String(postCall![0])
    })
    expect(postUrl).toContain('/uren/kantoor/planning/dagdeel')
    expect(postUrl).toContain(`administratie_id=${ADMINISTRATIE_ID}`)
  })

  it('markeert kaartjes ná de projecteinddatum als zacht oranje signaal', async () => {
    installMock({
      planning: () =>
        jsonResponse(
          planningWeek({
            projecten: [
              {
                project_id: PROJECT_ID,
                project_naam: '144 Breda (Moeskops)',
                opdrachtgever: 'Moeskops',
                soort_werk: 'montage',
                looptijd_tot: '2026-08-20', // vóór de getoonde week
                week_man: 1,
                per_datum: {
                  '2026-08-24': [{ gebruiker_id: ZZP_ID, naam: 'Milan K.', rol: 'zzper', dagdeel: 'heel' }],
                },
              },
            ],
          }),
        ),
    })
    renderScherm(`?administratie=${ADMINISTRATIE_ID}&week=2026-W35`)
    await waitFor(() => expect(screen.getByText('144 Breda (Moeskops)')).toBeInTheDocument())
    expect(
      screen.getByTitle('Gepland ná de einddatum van het project (zacht signaal, geen blokkade)'),
    ).toBeInTheDocument()
    expect(screen.getByText(/deze week valt ná de einddatum/)).toBeInTheDocument()
  })

  it('meldt netjes dat het module-recht ontbreekt (403 — fail-closed)', async () => {
    installMock({ planning: () => jsonResponse({ detail: 'geen recht' }, 403) })
    renderScherm()
    await waitFor(() =>
      expect(screen.getByText(/module-recht "Meerwerk & urenstaten"/)).toBeInTheDocument(),
    )
  })

  it('meldt de opt-in-uitschakeling (409) zonder grid', async () => {
    installMock({ planning: () => jsonResponse({ detail: 'module uit' }, 409) })
    renderScherm()
    await waitFor(() =>
      expect(screen.getByText(/niet ingeschakeld voor deze administratie/)).toBeInTheDocument(),
    )
  })
})
