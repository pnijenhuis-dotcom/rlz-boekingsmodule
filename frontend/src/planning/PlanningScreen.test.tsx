/** Planning personeel v3 "dag-eerst" (akkoord Peter 18-09, mockup planning-v3-dag-eerst.html): dagkolommen mét
 * projectkaarten (ploeg-initialen, aantal, laagste urenstatus, werkopdracht, conflict-chip, gereserveerd), projectbalk
 * (alle actieve projecten, zoeken, gepland eerst, "+ N", tegel → dag = reservering), conflictenbalk, vulhandvat (kaart +
 * ploeg over de week → één bulk-call + toast + ongedaan maken), ploeg-paneel (vinkjes + beschikbaarheid → één bulk-call,
 * bevestiging bij verwijderen mét uren), toggle Per project (lezen), pool mét vrij/afwezig + filter, week in de URL,
 * einddatum-signaal, controle-meldingen + dubbele-dag-teller, 403/409. Eén request — geen per-rij-calls (68 projecten).
 * Herschreven 18-09 t.o.v. het rij-grid (22/23-08): de gedragsdekking (plannen, verwijderen, dagdeel, 403/409, urenstatus,
 * filters, één request) blijft, de selectors volgen de nieuwe weergave. */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PlanningScreen } from './PlanningScreen'

const ADMINISTRATIE_ID = 'dddddddd-0000-0000-0000-00000000000d'
const PROJECT_ID = 'aaaaaaaa-0000-0000-0000-00000000000a'
const COMPACT_PROJECT_ID = 'ffffffff-0000-0000-0000-00000000000f'
const ZZP_ID = 'bbbbbbbb-0000-0000-0000-00000000000b'
const UITV_ID = 'cccccccc-0000-0000-0000-00000000000c'
const SANNE_ID = '99999999-0000-0000-0000-000000000009'
const KAART_MA = `${PROJECT_ID}|2026-08-24`

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
            {
              gebruiker_id: ZZP_ID, naam: 'Milan K.', rol: 'zzper', dagdeel: 'heel',
              // 15-09: urenstatus uit de weekstaat (stip + tekst + tooltip) — gekeurd, 8 u · 42 m².
              uren_status: 'gekeurd', uren: '8.00', m2: '42.00', uren_detail: '8 u · 42 m² · gekeurd door Ben v. Dijk op 26-08 17:42',
              weekstaat_id: 'eeeeeeee-0000-0000-0000-00000000000e', achteraf: true,
            },
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
        week_uren: { ingevuld_uren: '8', gekeurd_uren: '8', open_aantal: 0, zonder_uren_aantal: 1 },
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
      { gebruiker_id: UITV_ID, naam: 'Ben v. Dijk', rol: 'uitvoerder', geplande_dagen: '0.5' },
      // V3: een vrije persoon (0 dg) voor het ploeg-paneel en de "alleen vrij"-filter.
      { gebruiker_id: SANNE_ID, naam: 'Sanne V.', rol: 'zzper', geplande_dagen: '0' },
    ],
    reserveringen: [],
    afwezigheid: [],
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
  bulk?: (body: Record<string, unknown>) => Response
}

function bulkResultaat(body: Record<string, unknown>, extra: Partial<Record<string, unknown>> = {}) {
  const items = (body.items as Record<string, unknown>[]) ?? []
  return {
    correlatie_id: 'corr-1',
    aangemaakt: body.verwijderen ? [] : items,
    resultaten: items.map((i) => ({ ...i, dagdeel: 'heel', uitkomst: 'gedaan', reden: null, conflict: null, conflict_projectnaam: null })),
    ...extra,
  }
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
      const body = JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown>
      if (url.includes('/planning/bulk')) return Promise.resolve((opties.bulk ?? ((b: Record<string, unknown>) => jsonResponse(bulkResultaat(b))))(body))
      if (url.includes('/planning/reservering') && !url.includes('/verwijderen'))
        return Promise.resolve(jsonResponse({ id: 'res-1', project_id: body.project_id, projectnaam: 'x', datum: body.datum }, 201))
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

function posts(fetchMock: ReturnType<typeof installMock>, pad: string) {
  return fetchMock.mock.calls
    .filter((c) => (c[1] as RequestInit | undefined)?.method === 'POST' && String(c[0]).includes(pad))
    .map((c) => ({ url: String(c[0]), body: JSON.parse(String((c[1] as RequestInit).body)) as Record<string, unknown> }))
}

async function wachtOpGrid() {
  await waitFor(() => expect(screen.getByTestId(`kaart-${KAART_MA}`)).toBeInTheDocument())
}

describe('PlanningScreen — dag-eerst (v3, Peter 18-09)', () => {
  afterEach(() => {
    try {
      window.localStorage?.clear()
    } catch {
      /* geen opslag in deze testomgeving */
    }
  })

  it('toont dagkoppen mét dagtotaal, één projectkaart per project × dag mét ploeg-initialen en aantal, de projectbalk en de kantoor-signalen', async () => {
    installMock()
    renderScherm(`?administratie=${ADMINISTRATIE_ID}&week=2026-W35`)
    await wachtOpGrid()
    expect(screen.getByTestId('dagtotaal-2026-08-24')).toHaveTextContent('2 man · 1 project')
    expect(screen.getByTestId('dagtotaal-2026-08-25')).toHaveTextContent('—')
    const kaart = screen.getByTestId(`kaart-${KAART_MA}`)
    expect(within(kaart).getByTestId(`initiaal-${ZZP_ID}`)).toHaveTextContent('MK')
    expect(within(kaart).getByTestId(`initiaal-${UITV_ID}`)).toHaveTextContent('BV')
    expect(within(kaart).getByTestId(`initiaal-${UITV_ID}`).className).toContain(' u') // uitvoerder = groene rand (status)
    expect(within(kaart).getByTestId('kaart-aantal')).toHaveTextContent('2')
    expect(within(kaart).getByText(/Montage fase 1 — zuidgevel eerst/)).toBeInTheDocument() // werkopdracht op de kaart
    // Projectbalk: álle actieve projecten, gepland eerst, ongepland mét chip; telling zoals v3 23-08.
    expect(screen.getByTestId('projectbalk-telling')).toHaveTextContent('2 actieve projecten · 1 mét planning deze week')
    const tegels = screen.getAllByRole('listitem', { name: undefined }).filter((el) => el.className.includes('plan-ptegel'))
    expect(tegels[0]).toHaveTextContent('144 Breda (Moeskops)')
    expect(screen.getByTestId(`projecttegel-${COMPACT_PROJECT_ID}`)).toHaveTextContent('niet gepland')
    // Besluit C: > 5 geplande dagen kleurt als zacht signaal; vrije persoon toont "vrij".
    expect(screen.getByTitle('Meer dan 5 geplande dagen deze week (zacht signaal)')).toBeInTheDocument()
    expect(screen.getByTestId(`pool-${SANNE_ID}`)).toHaveTextContent('0 dg · vrij')
    // Kantoor-signalen ongewijzigd: buiten planning + dubbele dag + 30-dagen-teller.
    expect(screen.getByText(/uren buiten planning/)).toBeInTheDocument()
    expect(screen.getByText(/dubbele dag/)).toBeInTheDocument()
    expect(screen.getByText('3× / 30 dgn')).toBeInTheDocument()
    expect(screen.getByText('+ Project aanmaken')).toBeInTheDocument()
    expect(screen.getByText("+ ZZP'er")).toBeInTheDocument()
  })

  it('leest de week uit de URL (?week=2026-W41) en vraagt die week op', async () => {
    const fetchMock = installMock({ planning: () => jsonResponse(planningWeek({ weeknummer: 41 })) })
    renderScherm(`?administratie=${ADMINISTRATIE_ID}&week=2026-W41`)
    await waitFor(() => expect(screen.getByTestId('projectbalk')).toBeInTheDocument())
    const planningCall = fetchMock.mock.calls.map((c) => String(c[0])).find((u) => u.includes('/uren/kantoor/planning?'))
    expect(planningCall).toContain('jaar=2026')
    expect(planningCall).toContain('weeknummer=41')
    expect(screen.getByLabelText('Weekkiezer')).toHaveValue('2026-W41')
  })

  it('klik-alternatief voor slepen: projecttegel kiezen → dag aanklikken = reservering (het project zonder planning is direct beplanbaar)', async () => {
    const fetchMock = installMock()
    renderScherm(`?administratie=${ADMINISTRATIE_ID}&week=2026-W35`)
    await wachtOpGrid()
    fireEvent.click(screen.getByTestId(`projecttegel-${COMPACT_PROJECT_ID}`))
    expect(screen.getByTestId(`projecttegel-${COMPACT_PROJECT_ID}`)).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(screen.getByTestId('dag-2026-08-24'))
    await waitFor(() => expect(posts(fetchMock, '/planning/reservering')).toHaveLength(1))
    const [res] = posts(fetchMock, '/planning/reservering')
    expect(res.url).toContain(`administratie_id=${ADMINISTRATIE_ID}`) // scope-query (422-les 23-08)
    expect(res.body).toMatchObject({ administratie_id: ADMINISTRATIE_ID, project_id: COMPACT_PROJECT_ID, datum: '2026-08-24' })
    await waitFor(() => expect(screen.queryByText(/Actie mislukt|Field required/)).not.toBeInTheDocument())
  })

  it('toont een reservering als grijze "gereserveerd"-kaart en telt 0 man', async () => {
    installMock({
      planning: () => jsonResponse(planningWeek({ reserveringen: [{ id: 'r-1', project_id: COMPACT_PROJECT_ID, projectnaam: '25036 Arnhem', datum: '2026-08-26' }] })),
    })
    renderScherm(`?administratie=${ADMINISTRATIE_ID}&week=2026-W35`)
    await wachtOpGrid()
    const kaart = screen.getByTestId(`kaart-${COMPACT_PROJECT_ID}|2026-08-26`)
    expect(kaart.className).toContain('leeg')
    expect(kaart).toHaveTextContent('gereserveerd · nog geen ploeg')
    expect(screen.getByTestId('dagtotaal-2026-08-26')).toHaveTextContent('0 man · 1 project')
  })

  it('projectbalk zoekt live (diakriet-loos) en meldt een lege uitkomst netjes; de telling blijft over alles', async () => {
    installMock()
    renderScherm(`?administratie=${ADMINISTRATIE_ID}&week=2026-W35`)
    await wachtOpGrid()
    fireEvent.change(screen.getByLabelText('Zoek project'), { target: { value: 'confíde' } })
    expect(screen.getByTestId(`projecttegel-${COMPACT_PROJECT_ID}`)).toBeInTheDocument()
    expect(screen.queryByTestId(`projecttegel-${PROJECT_ID}`)).not.toBeInTheDocument()
    expect(screen.getByTestId('projectbalk-telling')).toHaveTextContent('1 actieve projecten · 0 mét planning deze week')
    fireEvent.change(screen.getByLabelText('Zoek project'), { target: { value: 'bestaat-niet' } })
    expect(screen.getByText(/Geen project past bij "bestaat-niet"/)).toBeInTheDocument()
  })

  it('blijft één request bij realistische aantallen (68 actieve projecten) — de balk toont 12 + "+ 56"', async () => {
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
    await waitFor(() => expect(screen.getByTestId('projectbalk-telling')).toHaveTextContent('68 actieve projecten · 1 mét planning deze week'))
    expect(screen.getByText('26100 Plaats 0')).toBeInTheDocument()
    expect(screen.queryByText('26166 Plaats 66')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '+ 56' }))
    expect(screen.getByText('26166 Plaats 66')).toBeInTheDocument()
    const planningCalls = fetchMock.mock.calls.filter((c) => String(c[0]).includes('/uren/kantoor/planning'))
    expect(planningCalls).toHaveLength(1)
  })

  it('ploeg kiezen: klik op de kaart → paneel rechts mét beschikbaarheid → vinkje → Opslaan = één bulk-call; toast + Ongedaan maken', async () => {
    const fetchMock = installMock()
    renderScherm(`?administratie=${ADMINISTRATIE_ID}&week=2026-W35`)
    await wachtOpGrid()
    fireEvent.click(screen.getByTestId(`kaart-${KAART_MA}`))
    const paneel = await screen.findByTestId('ploeg-paneel')
    expect(paneel).toHaveTextContent('144 Breda (Moeskops)')
    expect(paneel).toHaveTextContent('2 gekozen · beschikbaarheid voor ma 24-8')
    expect(within(paneel).getByTestId(`paneel-persoon-${SANNE_ID}`)).toHaveTextContent('vrij')
    expect(within(paneel).getByTestId('ploeg-opslaan')).toBeDisabled() // geen diff
    fireEvent.click(within(paneel).getByRole('checkbox', { name: 'Sanne V.' }))
    expect(within(paneel).getByTestId('ploeg-opslaan')).toHaveTextContent('Opslaan (3)')
    fireEvent.click(within(paneel).getByTestId('ploeg-opslaan'))
    await waitFor(() => expect(posts(fetchMock, '/planning/bulk')).toHaveLength(1))
    const [bulk] = posts(fetchMock, '/planning/bulk')
    expect(bulk.url).toContain(`administratie_id=${ADMINISTRATIE_ID}`)
    expect(bulk.body).toMatchObject({ administratie_id: ADMINISTRATIE_ID, bron: 'ploeg', items: [{ gebruiker_id: SANNE_ID, project_id: PROJECT_ID, datum: '2026-08-24', dagdeel: 'heel' }] })
    // Toast met de server-uitkomst + ongedaan maken = dezelfde set terug mét verwijderen: true en de correlatie-id.
    const toast = await screen.findByTestId('bulk-toast')
    expect(toast).toHaveTextContent('Ploeg opgeslagen · 1 toegevoegd')
    fireEvent.click(within(toast).getByTestId('ongedaan-maken'))
    await waitFor(() => expect(posts(fetchMock, '/planning/bulk')).toHaveLength(2))
    expect(posts(fetchMock, '/planning/bulk')[1].body).toMatchObject({ bron: 'ongedaan', verwijderen: true, correlatie_id: 'corr-1', items: [{ gebruiker_id: SANNE_ID, project_id: PROJECT_ID, datum: '2026-08-24' }] })
  })

  it('ploeg-paneel: iemand mét ingevulde uren van de planning halen vraagt bevestiging mét de urenstand (nee = niets gepost)', async () => {
    const fetchMock = installMock()
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    renderScherm(`?administratie=${ADMINISTRATIE_ID}&week=2026-W35`)
    await wachtOpGrid()
    fireEvent.click(screen.getByTestId(`kaart-${KAART_MA}`))
    const paneel = await screen.findByTestId('ploeg-paneel')
    fireEvent.click(within(paneel).getByRole('checkbox', { name: 'Milan K.' })) // gekeurd, 8 u
    fireEvent.click(within(paneel).getByTestId('ploeg-opslaan'))
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('Milan K. heeft 8 u ingevuld op deze dag — toch van de planning halen? De uren blijven staan.'))
    expect(posts(fetchMock, '/planning/bulk')).toHaveLength(0)
    confirm.mockRestore()
  })

  it('vulhandvat: kaart selecteren → handvat slepen over di–wo → ghost-kaarten → loslaten = één bulk-call (bron vulhandvat) + toast "Gekopieerd naar di–wo"', async () => {
    const fetchMock = installMock()
    renderScherm(`?administratie=${ADMINISTRATIE_ID}&week=2026-W35`)
    await wachtOpGrid()
    fireEvent.click(screen.getByTestId(`kaart-${KAART_MA}`))
    const handvat = await screen.findByTestId('handvat')
    fireEvent.pointerDown(handvat)
    fireEvent.pointerEnter(screen.getByTestId('dag-2026-08-25'))
    fireEvent.pointerEnter(screen.getByTestId('dag-2026-08-26'))
    expect(screen.getByTestId('ghost-2026-08-25')).toHaveTextContent('kopie · zelfde ploeg')
    expect(screen.getByTestId('ghost-2026-08-26')).toBeInTheDocument()
    fireEvent.pointerUp(window)
    await waitFor(() => expect(posts(fetchMock, '/planning/bulk')).toHaveLength(1))
    const [bulk] = posts(fetchMock, '/planning/bulk')
    expect(bulk.body.bron).toBe('vulhandvat')
    expect(bulk.body.items).toHaveLength(4) // 2 personen × di, wo — ma (bron) niet
    expect((bulk.body.items as { datum: string }[]).map((i) => i.datum).sort()).toEqual(['2026-08-25', '2026-08-25', '2026-08-26', '2026-08-26'])
    expect(await screen.findByTestId('bulk-toast')).toHaveTextContent('Gekopieerd naar di–wo · 4 persoon-dagen')
  })

  it('vulhandvat slaat een doeldag mét een bestaande kaart van hetzelfde project over en stopt bij vrijdag (nooit over de weekgrens)', async () => {
    const week = planningWeek()
    const rij = (week.projecten as Record<string, unknown>[])[0]
    ;(rij.per_datum as Record<string, unknown>)['2026-08-26'] = [{ gebruiker_id: SANNE_ID, naam: 'Sanne V.', rol: 'zzper', dagdeel: 'heel' }]
    const fetchMock = installMock({ planning: () => jsonResponse(week) })
    renderScherm(`?administratie=${ADMINISTRATIE_ID}&week=2026-W35`)
    await wachtOpGrid()
    fireEvent.click(screen.getByTestId(`kaart-${KAART_MA}`))
    fireEvent.pointerDown(await screen.findByTestId('handvat'))
    fireEvent.pointerEnter(screen.getByTestId('dag-2026-08-28')) // vrijdag
    expect(screen.getByTestId('ghost-overgeslagen-2026-08-26')).toHaveTextContent('overgeslagen — staat hier al')
    fireEvent.pointerUp(window)
    await waitFor(() => expect(posts(fetchMock, '/planning/bulk')).toHaveLength(1))
    const datums = (posts(fetchMock, '/planning/bulk')[0].body.items as { datum: string }[]).map((i) => i.datum)
    expect(new Set(datums)).toEqual(new Set(['2026-08-25', '2026-08-27', '2026-08-28']))
    expect(datums).toHaveLength(6)
  })

  it('conflictenbalk: dubbel gepland op één dag = klikbaar item → springt naar de kaart (oplichten + paneel)', async () => {
    const week = planningWeek()
    const compact = (week.projecten as Record<string, unknown>[])[1]
    ;(compact.per_datum as Record<string, unknown>)['2026-08-24'] = [{ gebruiker_id: ZZP_ID, naam: 'Milan K.', rol: 'zzper', dagdeel: 'heel' }]
    installMock({ planning: () => jsonResponse(week) })
    renderScherm(`?administratie=${ADMINISTRATIE_ID}&week=2026-W35`)
    await wachtOpGrid()
    const balk = screen.getByTestId('conflictenbalk')
    expect(balk).toHaveTextContent('1 conflict deze week')
    expect(balk).toHaveTextContent('ma 24-8: Milan K. op 144 Breda (Moeskops) én 25036 Arnhem')
    // Beide kaarten dragen de conflict-chip; Milans initiaal oranje omrand.
    expect(within(screen.getByTestId(`kaart-${KAART_MA}`)).getByTestId('kaart-conflict')).toBeInTheDocument()
    expect(within(screen.getByTestId(`kaart-${KAART_MA}`)).getByTestId(`initiaal-${ZZP_ID}`).className).toContain(' c')
    fireEvent.click(within(balk).getByRole('button', { name: /Milan K. op/ }))
    await waitFor(() => expect(screen.getByTestId(`kaart-${KAART_MA}`).className).toContain('oplichten'))
    expect(screen.getByTestId('ploeg-paneel')).toBeInTheDocument()
  })

  it('afwezigheid: pool toont "afwezig t/m", filter "alleen vrij" verbergt geplande en afwezige, paneel schakelt de afwezige uit; gepland op zo\'n dag = conflict', async () => {
    const week = planningWeek({ afwezigheid: [{ id: 'a-1', gebruiker_id: UITV_ID, van: '2026-08-24', tot: '2026-08-25', reden: 'verlof' }] })
    installMock({ planning: () => jsonResponse(week) })
    renderScherm(`?administratie=${ADMINISTRATIE_ID}&week=2026-W35`)
    await wachtOpGrid()
    expect(screen.getByTestId(`pool-${UITV_ID}`)).toHaveTextContent('afwezig t/m 25-8')
    expect(screen.getByTestId('conflictenbalk')).toHaveTextContent('Ben v. Dijk afwezig (verlof) maar gepland op 144 Breda')
    fireEvent.click(screen.getByTestId('pool-alleen-vrij'))
    expect(screen.queryByTestId(`pool-${UITV_ID}`)).not.toBeInTheDocument()
    expect(screen.queryByTestId(`pool-${ZZP_ID}`)).not.toBeInTheDocument()
    expect(screen.getByTestId(`pool-${SANNE_ID}`)).toBeInTheDocument()
    fireEvent.click(screen.getByTestId(`kaart-${KAART_MA}`))
    const paneel = await screen.findByTestId('ploeg-paneel')
    expect(within(paneel).getByTestId(`paneel-persoon-${UITV_ID}`)).toHaveTextContent('afwezig t/m 25-8')
  })

  it('verwijdert een persoon van de kaart (kaart geselecteerd → ✕) mét administratie_id als query-parameter', async () => {
    const fetchMock = installMock()
    renderScherm(`?administratie=${ADMINISTRATIE_ID}&week=2026-W35`)
    await wachtOpGrid()
    fireEvent.click(screen.getByTestId(`kaart-${KAART_MA}`))
    fireEvent.click(screen.getByRole('button', { name: 'Milan K. uit de planning halen' }))
    await waitFor(() => expect(posts(fetchMock, '/planning/verwijderen')).toHaveLength(1))
    const [post] = posts(fetchMock, '/planning/verwijderen')
    expect(post.url).toContain(`administratie_id=${ADMINISTRATIE_ID}`)
    expect(post.body).toMatchObject({ gebruiker_id: ZZP_ID, project_id: PROJECT_ID, datum: '2026-08-24' })
    await waitFor(() => expect(screen.queryByText(/Actie mislukt|Field required/)).not.toBeInTheDocument())
  })

  it('wijzigt het dagdeel mét administratie_id als query-parameter', async () => {
    const fetchMock = installMock()
    renderScherm(`?administratie=${ADMINISTRATIE_ID}&week=2026-W35`)
    await wachtOpGrid()
    fireEvent.click(screen.getByTestId(`kaart-${KAART_MA}`))
    fireEvent.click(screen.getByTitle('Hele dag — maak ½ dag'))
    await waitFor(() => expect(posts(fetchMock, '/planning/dagdeel')).toHaveLength(1))
    const [post] = posts(fetchMock, '/planning/dagdeel')
    expect(post.url).toContain(`administratie_id=${ADMINISTRATIE_ID}`)
    expect(post.body).toMatchObject({ gebruiker_id: ZZP_ID, dagdeel: 'half' })
  })

  it('markeert een kaart ná de projecteinddatum als zacht oranje signaal (geen blokkade)', async () => {
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
                looptijd_tot: '2026-08-20',
                is_actief: true,
                week_man: 1,
                per_datum: { '2026-08-24': [{ gebruiker_id: ZZP_ID, naam: 'Milan K.', rol: 'zzper', dagdeel: 'heel' }] },
              },
            ],
          }),
        ),
    })
    renderScherm(`?administratie=${ADMINISTRATIE_ID}&week=2026-W35`)
    await wachtOpGrid()
    const kaart = screen.getByTestId(`kaart-${KAART_MA}`)
    expect(kaart).toHaveAttribute('title', 'Gepland ná de einddatum van het project (zacht signaal, geen blokkade)')
    expect(kaart.className).toContain('na-einddatum')
  })

  it('meldt netjes dat het module-recht ontbreekt (403 — fail-closed)', async () => {
    installMock({ planning: () => jsonResponse({ detail: 'geen recht' }, 403) })
    renderScherm()
    await waitFor(() => expect(screen.getByText(/module-recht "Meerwerk & urenstaten"/)).toBeInTheDocument())
  })

  it('meldt de opt-in-uitschakeling (409) zonder grid', async () => {
    installMock({ planning: () => jsonResponse({ detail: 'module uit' }, 409) })
    renderScherm()
    await waitFor(() => expect(screen.getByText(/niet ingeschakeld voor deze administratie/)).toBeInTheDocument())
  })

  it('werkopdracht: 📋 op een kaart mét lopende opdracht opent de dag-override-dialoog; het paneel biedt "wijzigen"', async () => {
    installMock()
    renderScherm(`?administratie=${ADMINISTRATIE_ID}&week=2026-W35`)
    await wachtOpGrid()
    fireEvent.click(screen.getByLabelText('Werkopdracht 144 Breda (Moeskops) ma 24-8'))
    await waitFor(() => expect(screen.getByText(/Afwijkende opdracht — 144 Breda/)).toBeInTheDocument())
  })

  it('toggle "Per project": leesweergave mét rij per project, cel = aantal + status; klik op een cel = terug naar Per dag mét die kaart; stand in localStorage', async () => {
    // De testomgeving heeft geen localStorage — een minimale stub volstaat voor de "stand onthouden"-toets.
    const opslag = new Map<string, string>()
    vi.stubGlobal('localStorage', { getItem: (k: string) => opslag.get(k) ?? null, setItem: (k: string, v: string) => void opslag.set(k, v), removeItem: (k: string) => void opslag.delete(k), clear: () => opslag.clear() })
    installMock()
    renderScherm(`?administratie=${ADMINISTRATIE_ID}&week=2026-W35`)
    await wachtOpGrid()
    fireEvent.click(screen.getByTestId('weergave-project'))
    const tabel = await screen.findByTestId('per-project')
    expect(window.localStorage.getItem('planning-weergave')).toBe('project')
    const rij = within(tabel).getByTestId(`pp-rij-${PROJECT_ID}`)
    expect(rij).toHaveTextContent('2 mandagen · uren 1/2')
    expect(within(rij).getByTestId('week-uren-chip')).toHaveTextContent('8 u ingevuld · 8 u gekeurd · 1 zonder uren')
    expect(tabel).toHaveTextContent('1 actieve projecten zonder planning deze week')
    expect(screen.queryByTestId('handvat')).not.toBeInTheDocument() // geen bewerkacties in lezen
    fireEvent.click(within(rij).getByRole('button', { name: '144 Breda (Moeskops) ma 24-8: 2 man' }))
    await waitFor(() => expect(screen.getByTestId(`kaart-${KAART_MA}`)).toBeInTheDocument())
    expect(screen.getByTestId('ploeg-paneel')).toBeInTheDocument()
    expect(window.localStorage.getItem('planning-weergave')).toBe('dag')
  })

  it('deeplink ?kaart=<project>|<datum> (signalen) landt op de kaart mét paneel', async () => {
    installMock()
    renderScherm(`?administratie=${ADMINISTRATIE_ID}&week=2026-W35&kaart=${encodeURIComponent(KAART_MA)}`)
    await wachtOpGrid()
    await waitFor(() => expect(screen.getByTestId(`kaart-${KAART_MA}`)).toHaveAttribute('aria-pressed', 'true'))
    expect(screen.getByTestId('ploeg-paneel')).toBeInTheDocument()
  })
})

describe('urenstatus op de kaart (Peter/Haci 15-09, in v3 op kaartniveau)', () => {
  it('kaartstatus = laagste van de ploeg mét tooltip per persoon, tekst "uren N/M", achteraf-chip; klik opent de weekstaat', async () => {
    installMock()
    renderScherm(`?administratie=${ADMINISTRATIE_ID}&week=2026-W35`)
    await wachtOpGrid()
    const kaart = screen.getByTestId(`kaart-${KAART_MA}`)
    const stip = within(kaart).getByTestId('uren-status')
    expect(stip).toHaveAttribute('data-status', 'geen') // Ben heeft nog geen uren → laagste
    expect(stip).toHaveTextContent('geen uren')
    expect(stip.getAttribute('title')).toContain('Milan K.: 8 u · 42 m² · gekeurd door Ben v. Dijk op 26-08 17:42')
    expect(within(kaart).getByTestId('achteraf-chip')).toBeInTheDocument()
  })

  it('filter "alleen zonder uren" werkt als kaartfilter: alleen ploegleden zonder uren blijven, en staat in de URL', async () => {
    installMock()
    renderScherm(`?administratie=${ADMINISTRATIE_ID}&week=2026-W35&uren=zonder`)
    await wachtOpGrid()
    await waitFor(() => expect(screen.getByTestId('uren-filter-zonder')).toHaveAttribute('aria-pressed', 'true'))
    const kaart = screen.getByTestId(`kaart-${KAART_MA}`)
    expect(within(kaart).queryByTestId(`initiaal-${ZZP_ID}`)).not.toBeInTheDocument() // gekeurd → verborgen
    expect(within(kaart).getByTestId(`initiaal-${UITV_ID}`)).toBeInTheDocument() // geen uren → zichtbaar
    expect(within(kaart).getByTestId('kaart-aantal')).toHaveTextContent('1')
  })
})
