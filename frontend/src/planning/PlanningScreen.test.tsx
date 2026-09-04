/** Planning-agenda steigerbouw (akkoord Peter 22-08 + v3-grid-besluit 23-08): weekgrid met
 * ÁLLE actieve projecten in twee blokken (mét planning bovenaan, de rest compact onder de
 * scheidingskop — direct beplanbaar, precies het gat van v2), live filterveld + telling,
 * klik-alternatief voor drag-and-drop, week in de URL (?week=2026-W41), einddatum-signaal,
 * pool met geplande-dagen-teller (> 5 = zacht signaal, besluit C), controle-meldingen +
 * dubbele-dag-teller (kantoor-only) en de 403-module-recht-melding. Eén request — geen
 * per-rij-calls (Universal = 68 actieve projecten). */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PlanningScreen } from './PlanningScreen'

const ADMINISTRATIE_ID = 'dddddddd-0000-0000-0000-00000000000d'
const PROJECT_ID = 'aaaaaaaa-0000-0000-0000-00000000000a'
const COMPACT_PROJECT_ID = 'ffffffff-0000-0000-0000-00000000000f'
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
        is_actief: true,
        week_man: 2,
        per_datum: {
          '2026-08-24': [
            { gebruiker_id: ZZP_ID, naam: 'Milan K.', rol: 'zzper', dagdeel: 'heel' },
            { gebruiker_id: 'cccccccc-0000-0000-0000-00000000000c', naam: 'Ben v. Dijk', rol: 'uitvoerder', dagdeel: 'half' },
          ],
        },
        // Werkopdrachten (31-08): chip in de rijkop + dag-override in de dagcel.
        werkopdrachten: [
          { groep_id: 'dddddddd-0000-0000-0000-00000000000d', van: '2026-08-22', tot_en_met: '2026-09-29', tekst: 'Montage fase 1 — zuidgevel eerst' },
        ],
        werkopdracht_overrides: {
          '2026-08-25': [{ groep_id: 'dddddddd-0000-0000-0000-00000000000d', tekst: 'extra werk — traptoren bijplaatsen', afwijkend: true }],
        },
      },
      // V3: de leesroute levert óók de actieve projecten zónder planning (compacte blok).
      {
        project_id: COMPACT_PROJECT_ID,
        project_naam: '25036 Arnhem',
        opdrachtgever: 'Confide Bouw',
        soort_werk: 'montage',
        looptijd_tot: null,
        is_actief: true,
        week_man: 0,
        per_datum: {},
        werkopdrachten: [],
        werkopdracht_overrides: {},
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
  post?: () => Response
}

function installMock(opties: MockOpties = {}) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/auth/administraties'))
      return Promise.resolve(jsonResponse({ administraties: [{ id: ADMINISTRATIE_ID, naam: 'Universal Steigerbouw' }] }))
    if (url.includes('/uren/kantoor/mijn-toegang'))
      return Promise.resolve(
        jsonResponse({
          heeft_meerwerk_recht: true,
          administraties_met_opt_in: [ADMINISTRATIE_ID],
          aantal_administraties_in_scope: 1,
          is_beheerder: true,
          heeft_veldwerkerbeheer_recht: true,
          is_beheerder_of_bp: true,
          mag_project_aanmaken: true,
        }),
      )
    if (url.includes('/uren/kantoor/werkopdrachten'))
      return Promise.resolve(jsonResponse([]))
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
    // V3: álle actieve projecten in twee blokken — het project zonder planning staat compact
    // onder de scheidingskop; de telling naast het filterveld telt beide.
    expect(screen.getByText('Overige actieve projecten — nog niemand gepland deze week')).toBeInTheDocument()
    expect(screen.getByText('25036 Arnhem')).toBeInTheDocument()
    expect(screen.getByText('2 actieve projecten · 1 mét planning deze week')).toBeInTheDocument()
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

  it('plant direct vanaf het compacte blok op een project zónder bestaande planning (het v2-gat)', async () => {
    // Precies het gat van v2: een project zonder planning stond niet in het grid en was dus
    // niet beplanbaar zonder eerst te zoeken. In v3 is de compacte rij direct beplanbaar.
    const fetchMock = installMock()
    renderScherm(`?administratie=${ADMINISTRATIE_ID}&week=2026-W35`)
    await waitFor(() => expect(screen.getByText('25036 Arnhem')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId(`cel-${COMPACT_PROJECT_ID}|2026-08-24`))
    fireEvent.click(await screen.findByRole('button', { name: 'Milan K.' }))
    let postUrl = ''
    let gepost: unknown = null
    await waitFor(() => {
      const postCall = fetchMock.mock.calls.find((c) => (c[1] as RequestInit | undefined)?.method === 'POST')
      expect(postCall).toBeDefined()
      postUrl = String(postCall![0])
      gepost = JSON.parse(String((postCall![1] as RequestInit).body))
    })
    // Query-parameter-assertie van de 422-fix (23-08) blijft onverkort staan.
    expect(postUrl).toContain(`administratie_id=${ADMINISTRATIE_ID}`)
    expect(gepost).toMatchObject({
      administratie_id: ADMINISTRATIE_ID,
      gebruiker_id: ZZP_ID,
      project_id: COMPACT_PROJECT_ID,
      datum: '2026-08-24',
    })
    await waitFor(() => expect(screen.queryByText(/Actie mislukt|Field required/)).not.toBeInTheDocument())
  })

  it('filtert beide blokken live en meldt een lege uitkomst netjes', async () => {
    installMock()
    renderScherm(`?administratie=${ADMINISTRATIE_ID}&week=2026-W35`)
    await waitFor(() => expect(screen.getByText('144 Breda (Moeskops)')).toBeInTheDocument())
    // Filter op opdrachtgever van het compacte project: het bovenblok-project verdwijnt.
    fireEvent.change(screen.getByLabelText('Filter projecten'), { target: { value: 'confide' } })
    expect(screen.getByText('25036 Arnhem')).toBeInTheDocument()
    expect(screen.queryByText('144 Breda (Moeskops)')).not.toBeInTheDocument()
    // De telling blijft over de ongefilterde stand gaan.
    expect(screen.getByText('2 actieve projecten · 1 mét planning deze week')).toBeInTheDocument()
    // Lege uitkomst = nette leegmelding, geen kaal grid.
    fireEvent.change(screen.getByLabelText('Filter projecten'), { target: { value: 'bestaat-niet' } })
    expect(screen.getByText(/Geen project past bij "bestaat-niet"/)).toBeInTheDocument()
  })

  it('blijft één request bij realistische aantallen (68 actieve projecten)', async () => {
    const projecten = [
      ...(planningWeek().projecten as Record<string, unknown>[]).slice(0, 1),
      ...Array.from({ length: 67 }, (_, i) => ({
        project_id: `00000000-0000-0000-0000-${String(100 + i).padStart(12, '0')}`,
        project_naam: `26${String(100 + i).padStart(3, '0')} Plaats ${i}`,
        opdrachtgever: 'Opdrachtgever',
        soort_werk: null,
        looptijd_tot: null,
        is_actief: true,
        week_man: 0,
        per_datum: {},
      })),
    ]
    const fetchMock = installMock({ planning: () => jsonResponse(planningWeek({ projecten })) })
    renderScherm(`?administratie=${ADMINISTRATIE_ID}&week=2026-W35`)
    await waitFor(() => expect(screen.getByText('68 actieve projecten · 1 mét planning deze week')).toBeInTheDocument())
    expect(screen.getByText('26100 Plaats 0')).toBeInTheDocument()
    expect(screen.getByText('26166 Plaats 66')).toBeInTheDocument()
    // Eén planning-request voor het hele grid — geen per-rij-calls (de batch-les van 22-08).
    const planningCalls = fetchMock.mock.calls.filter((c) => String(c[0]).includes('/uren/kantoor/planning'))
    expect(planningCalls).toHaveLength(1)
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
                is_actief: true,
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

  it('toont de werkopdracht-chip, dag-override en de 31-08-knoppen (+ Project, + ZZP\'er)', async () => {
    installMock()
    // Week vastpinnen op de fixture-week (35): de dag-override hangt aan di 25-08.
    renderScherm(`?administratie=${ADMINISTRATIE_ID}&week=2026-W35`)
    await waitFor(() => expect(screen.getByText('144 Breda (Moeskops)')).toBeInTheDocument())
    // Chip in de rijkop (actuele opdracht die de week raakt) + ⊕ op élke rij.
    expect(screen.getByText('Montage fase 1 — zuidgevel eerst')).toBeInTheDocument()
    expect(screen.getByLabelText('Werkopdracht toevoegen voor 25036 Arnhem')).toBeInTheDocument()
    // Dag-override in de dagcel: alleen die dag wijkt af (mockup "di afwijkend: …").
    const override = screen.getByTitle('Alleen deze dag wijkt de werkopdracht af — klik om te wijzigen')
    expect(override.textContent).toContain('di afwijkend:')
    expect(override.textContent).toContain('extra werk — traptoren bijplaatsen')
    // Blok C (31-08): "+ Project aanmaken" (B+P) en "+ ZZP'er" (veldwerkerbeheer-recht).
    expect(screen.getByText('+ Project aanmaken')).toBeInTheDocument()
    expect(screen.getByText("+ ZZP'er")).toBeInTheDocument()
    // Chip-klik opent de werkopdracht-popup (periode + tekst + historie).
    fireEvent.click(screen.getByLabelText('Werkopdracht 144 Breda (Moeskops)'))
    await waitFor(() => expect(screen.getByText(/Werkopdracht — 144 Breda/)).toBeInTheDocument())
  })

  it('meldt de opt-in-uitschakeling (409) zonder grid', async () => {
    installMock({ planning: () => jsonResponse({ detail: 'module uit' }, 409) })
    renderScherm()
    await waitFor(() =>
      expect(screen.getByText(/niet ingeschakeld voor deze administratie/)).toBeInTheDocument(),
    )
  })
})
