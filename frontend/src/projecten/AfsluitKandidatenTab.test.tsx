import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AfsluitKandidatenTab } from './AfsluitKandidatenTab'
import { ProjectenIngang } from './ProjectenIngang'
import { magAfsluitenBedienen, type AfsluitKandidaatDto, type AfsluitKandidatenDto } from './projectenApi'

// Opdracht Peter 19-09: tab "Afsluiten? (N)" — kandidaten uit de server-motor (redenen, laatste activiteit, open posten),
// vinkjes + "Afsluiten (N)" = bulk mét uitkomst per rij, "Niet afsluiten…" mét verplichte reden, filter op reden + zoekveld,
// deeplink `?tab=afsluiten` op de kantoorbrede én de per-administratie-lijst. De client formatteert; de server beslist.

const ADMIN_A = 'aaaaaaaa-0000-0000-0000-000000000001'
const P1 = '11111111-0000-0000-0000-000000000001'
const P2 = '22222222-0000-0000-0000-000000000002'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const RIJ_NAAM: AfsluitKandidaatDto = {
  administratie_id: ADMIN_A,
  administratie_naam: 'Universal Steigerbouw B.V.',
  project_id: P1,
  naam: 'Afgesloten 26012 Tilburg (van Kasteren)',
  redenen: ['naam_afgesloten'],
  reden_tekst: 'naam zegt afgesloten, status actief',
  laatste_activiteit: { soort: 'inkoop', datum: '2026-09-02', bedrag: '500.00', boekstuk: 'IF-77' },
  stil_dagen: 17,
  stil_maanden: 6,
  open_posten: { inkoop_niet_geboekt: 0, inkoop_niet_geboekt_bedrag: '0', verplichting_open: 0, uren_niet_gekeurd: 0, let_op: false },
  looptijd_tot: null,
  uitstel: null,
}
const RIJ_STIL: AfsluitKandidaatDto = {
  administratie_id: ADMIN_A,
  administratie_naam: 'Universal Steigerbouw B.V.',
  project_id: P2,
  naam: '25157 Harderwijk (Wessels)',
  redenen: ['stil', 'eindfactuur'],
  reden_tekst: 'geen activiteit sinds 2026-03-30 (173 dagen, venster 6 mnd) · eindfactuur geboekt (VF-301)',
  laatste_activiteit: { soort: 'verkoop', datum: '2026-03-30', bedrag: '3120.00', boekstuk: 'VF-301' },
  stil_dagen: 173,
  stil_maanden: 6,
  open_posten: { inkoop_niet_geboekt: 1, inkoop_niet_geboekt_bedrag: '150.00', verplichting_open: 0, uren_niet_gekeurd: 2, let_op: true },
  looptijd_tot: '2026-06-30',
  uitstel: null,
}

function lijst(rijen: AfsluitKandidaatDto[] = [RIJ_NAAM, RIJ_STIL], extra: Partial<AfsluitKandidatenDto> = {}): AfsluitKandidatenDto {
  return {
    rijen,
    totaal: rijen.length,
    pagina: 1,
    per_pagina: 50,
    tellers: { kandidaten: rijen.length, uitgesteld: 0, administraties: 1, per_reden: { stil: 1, eindfactuur: 1, naam_afgesloten: 1, looptijd_verstreken: 0 }, let_op: 1 },
    redenen: ['stil', 'eindfactuur', 'naam_afgesloten', 'looptijd_verstreken'],
    reden_labels: { stil: 'geen activiteit', eindfactuur: 'eindfactuur geboekt', naam_afgesloten: 'naam zegt afgesloten', looptijd_verstreken: 'looptijd verstreken' },
    stil_maanden: null,
    ...extra,
  }
}

type Handler = (url: string, init?: RequestInit) => Response | null

function stubFetch(kandidaten: (url: string) => AfsluitKandidatenDto, extra: Handler = () => null) {
  const aanroepen: { url: string; init?: RequestInit }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      aanroepen.push({ url, init })
      const e = extra(url, init)
      if (e) return Promise.resolve(e)
      if (url === '/auth/administraties') return Promise.resolve(jsonResponse({ administraties: [{ id: ADMIN_A, naam: 'Universal Steigerbouw B.V.' }] }))
      if (url.startsWith('/projecten/afsluit-kandidaten')) return Promise.resolve(jsonResponse(kandidaten(url)))
      if (url.startsWith('/projecten/kantoorbreed?')) {
        return Promise.resolve(
          jsonResponse({
            rijen: [],
            totaal: 0,
            pagina: 1,
            per_pagina: 25,
            administraties_in_selectie: 0,
            tellers: { projecten: 0, administraties: 0, met_signaal: 0, verplichting_overschreden: 0, marge_negatief: 0, weekstaat_ontbreekt: 0, te_keuren: 0, kandidaat_afsluiten: 2, afgesloten: 0 },
            facetten: { status: {}, administraties: [] },
          }),
        )
      }
      if (url.startsWith(`/projecten/${ADMIN_A}?`)) return Promise.resolve(jsonResponse({ projecten: [], zonder_specs: 0, aantal_afgesloten: 0 }))
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
  return aanroepen
}

function renderTab(administratieId: string | null = null) {
  return render(
    <MemoryRouter>
      <AfsluitKandidatenTab administratieId={administratieId} />
    </MemoryRouter>,
  )
}

describe('AfsluitKandidatenTab', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('toont per rij redenen, laatste activiteit en open posten; zoekterm en redenfilter gaan naar de server', async () => {
    const aanroepen = stubFetch(() => lijst())
    renderTab()
    const tabel = await screen.findByTestId('afsluit-tabel')
    const rijen = within(tabel).getAllByTestId('afsluit-rij')
    expect(rijen).toHaveLength(2)
    expect(within(rijen[0]).getByText('Afgesloten 26012 Tilburg (van Kasteren)')).toBeInTheDocument()
    expect(within(rijen[0]).getByTestId('reden-chips')).toHaveTextContent('naam zegt afgesloten')
    expect(within(rijen[0]).getByTestId('laatste-activiteit')).toHaveTextContent('inkoop · 2-9-2026')
    expect(within(rijen[0]).getByTestId('laatste-activiteit')).toHaveTextContent('IF-77')
    expect(within(rijen[0]).getByText('—')).toBeInTheDocument()
    expect(within(rijen[1]).getByTestId('reden-chips')).toHaveTextContent('geen activiteit')
    expect(within(rijen[1]).getByTestId('reden-chips')).toHaveTextContent('eindfactuur geboekt')
    expect(within(rijen[1]).getByTestId('open-posten')).toHaveTextContent('let op')
    expect(within(rijen[1]).getByTestId('open-posten')).toHaveTextContent('1 inkoop niet geboekt')
    expect(within(rijen[1]).getByTestId('open-posten')).toHaveTextContent('2 weekstaat niet gekeurd')
    expect(within(rijen[1]).getByText('looptijd tot 30-6-2026')).toBeInTheDocument()
    expect(screen.getByTestId('chip-let-op')).toHaveTextContent('1 met open posten')
    expect(screen.getByTestId('afsluit-voet')).toHaveTextContent('2 kandidaten over 1 administratie')
    expect(screen.getByTestId('afsluit-voet')).toHaveTextContent('nooit automatisch')
    // Kantoorbreed: administratie-link = deeplink naar de tab per administratie.
    expect(within(rijen[0]).getByRole('link', { name: 'Universal Steigerbouw B.V.' })).toHaveAttribute('href', `/projecten?administratie=${ADMIN_A}&tab=afsluiten`)

    const user = userEvent.setup()
    await user.selectOptions(screen.getByLabelText('Filter op reden'), 'stil')
    await waitFor(() => expect(aanroepen.some((a) => a.url === '/projecten/afsluit-kandidaten?reden=stil')).toBe(true))
    await user.type(screen.getByLabelText('Zoek kandidaat'), 'kudo')
    await waitFor(() => expect(aanroepen.some((a) => a.url === '/projecten/afsluit-kandidaten?q=kudo&reden=stil')).toBe(true))
  })

  it('vinkjes + "Afsluiten (N)" → bevestiging → bulk-aanroep; uitkomst per rij zichtbaar (gelukt / bron weigerde)', async () => {
    let keer = 0
    const aanroepen = stubFetch(
      () => {
        keer += 1
        // Ná de bulk herlaadt de tab: de gelukte rij is weg, de geweigerde blijft.
        return keer === 1 ? lijst() : lijst([RIJ_STIL])
      },
      (url, init) => {
        if (url === '/projecten/afsluiten-bulk' && init?.method === 'POST') {
          return jsonResponse({
            uitkomsten: [
              { administratie_id: ADMIN_A, project_id: P1, naam: RIJ_NAAM.naam, uitkomst: 'gelukt', detail: null },
              { administratie_id: ADMIN_A, project_id: P2, naam: RIJ_STIL.naam, uitkomst: 'bron_weigert', detail: 'RLZ bevestigde IsActive=false niet bij teruglezen — RLZ wint, status ongewijzigd' },
            ],
            gelukt: 1,
            mislukt: 1,
          })
        }
        return null
      },
    )
    renderTab()
    await screen.findByTestId('afsluit-tabel')
    const knop = screen.getByTestId('knop-bulk-afsluiten')
    expect(knop).toBeDisabled()
    expect(knop).toHaveTextContent('Afsluiten (0)')
    const user = userEvent.setup()
    await user.click(screen.getByLabelText('Alles op deze pagina kiezen'))
    expect(knop).toHaveTextContent('Afsluiten (2)')
    await user.click(knop)
    expect(await screen.findByRole('dialog', { name: /projecten afsluiten/i })).toBeInTheDocument()
    await user.type(screen.getByLabelText('Reden afsluiten'), 'Opgeleverd')
    await user.click(screen.getByTestId('bevestig-bulk'))
    await waitFor(() => expect(aanroepen.some((a) => a.url === '/projecten/afsluiten-bulk')).toBe(true))
    const bulk = aanroepen.find((a) => a.url === '/projecten/afsluiten-bulk')!
    expect(JSON.parse(String(bulk.init?.body))).toEqual({
      items: [
        { administratie_id: ADMIN_A, project_id: P1 },
        { administratie_id: ADMIN_A, project_id: P2 },
      ],
      reden: 'Opgeleverd',
      datum: null,
    })
    // Uitkomst per rij: de geweigerde rij toont de reden op de rij; het overzicht toont beide (niets verdwijnt stil).
    const overzicht = await screen.findByTestId('uitkomst-overzicht')
    expect(overzicht).toHaveTextContent('Afgesloten 26012 Tilburg (van Kasteren)')
    expect(overzicht).toHaveTextContent('afgesloten')
    expect(overzicht).toHaveTextContent('bron weigerde: RLZ bevestigde IsActive=false niet bij teruglezen')
    await waitFor(() => expect(screen.getAllByTestId('afsluit-rij')).toHaveLength(1))
    expect(within(screen.getAllByTestId('afsluit-rij')[0]).getByTestId('uitkomst')).toHaveTextContent('bron weigerde')
  })

  it('"Niet afsluiten…" vraagt een verplichte reden en stuurt die naar de server; "Toon uitgesteld" toont de reden', async () => {
    let uitgesteld = false
    const aanroepen = stubFetch(
      (url) => {
        if (url.includes('toon_uitgesteld=true')) {
          return lijst([{ ...RIJ_STIL, uitstel: { reden: 'Garantiewerk in oktober', door: 'x', op: '2026-09-19T10:00:00Z', laatste_activiteit: '2026-03-30' } }], {
            tellers: { kandidaten: 1, uitgesteld: 1, administraties: 1, per_reden: { stil: 0, eindfactuur: 0, naam_afgesloten: 1, looptijd_verstreken: 0 }, let_op: 0 },
          })
        }
        return uitgesteld
          ? lijst([RIJ_NAAM], { tellers: { kandidaten: 1, uitgesteld: 1, administraties: 1, per_reden: { stil: 0, eindfactuur: 0, naam_afgesloten: 1, looptijd_verstreken: 0 }, let_op: 0 } })
          : lijst()
      },
      (url, init) => {
        if (url === `/projecten/${ADMIN_A}/${P2}/niet-afsluiten` && init?.method === 'POST') {
          uitgesteld = true
          return jsonResponse({ reden: 'Garantiewerk in oktober', door: 'x', op: '2026-09-19T10:00:00Z', laatste_activiteit: '2026-03-30' })
        }
        return null
      },
    )
    renderTab()
    await screen.findByTestId('afsluit-tabel')
    const user = userEvent.setup()
    await user.click(within(screen.getAllByTestId('afsluit-rij')[1]).getByTestId('knop-niet-afsluiten'))
    const dialoog = await screen.findByRole('dialog', { name: 'Niet afsluiten' })
    expect(within(dialoog).getByTestId('bevestig-niet-afsluiten')).toBeDisabled() // reden verplicht
    await user.type(within(dialoog).getByLabelText('Reden niet afsluiten'), 'Garantiewerk in oktober')
    await user.click(within(dialoog).getByTestId('bevestig-niet-afsluiten'))
    await waitFor(() => expect(aanroepen.some((a) => a.url === `/projecten/${ADMIN_A}/${P2}/niet-afsluiten`)).toBe(true))
    expect(JSON.parse(String(aanroepen.find((a) => a.url.endsWith('/niet-afsluiten'))!.init?.body))).toEqual({ reden: 'Garantiewerk in oktober' })
    await waitFor(() => expect(screen.getAllByTestId('afsluit-rij')).toHaveLength(1))
    const toggle = await screen.findByTestId('toggle-uitgesteld')
    expect(toggle).toHaveTextContent('Toon uitgesteld (1)')
    await user.click(toggle)
    await waitFor(() => expect(screen.getByTestId('uitstel')).toHaveTextContent('Garantiewerk in oktober'))
    // Uitgestelde rijen zijn lezen: geen vinkjes, geen "Niet afsluiten…", geen bulk-knop.
    expect(screen.queryByTestId('knop-bulk-afsluiten')).toBeNull()
    expect(screen.queryByTestId('knop-niet-afsluiten')).toBeNull()
  })

  it('per administratie: geen administratiekolom, stil-venster zichtbaar en wijzigbaar (PUT), lege stand is een zin', async () => {
    let maanden = 6
    const aanroepen = stubFetch(
      () => lijst([], { stil_maanden: maanden, tellers: { kandidaten: 0, uitgesteld: 0, administraties: 0, per_reden: { stil: 0, eindfactuur: 0, naam_afgesloten: 0, looptijd_verstreken: 0 }, let_op: 0 } }),
      (url, init) => {
        if (url === `/projecten/${ADMIN_A}/afsluit-instelling` && init?.method === 'PUT') {
          maanden = (JSON.parse(String(init.body)) as { stil_maanden: number }).stil_maanden
          return jsonResponse({ stil_maanden: maanden })
        }
        return null
      },
    )
    renderTab(ADMIN_A)
    expect(await screen.findByTestId('afsluit-leeg')).toHaveTextContent('Geen projecten die klaar lijken om af te sluiten')
    expect(aanroepen[0].url).toBe(`/projecten/afsluit-kandidaten?administratie_id=${ADMIN_A}`)
    expect(screen.getByTestId('stil-venster')).toHaveTextContent('Stil-venster: 6 maanden')
    const user = userEvent.setup()
    await user.click(screen.getByTestId('stil-venster-wijzig'))
    const veld = screen.getByLabelText('Stil-venster in maanden')
    await user.clear(veld)
    await user.type(veld, '3')
    await user.click(screen.getByRole('button', { name: 'Opslaan' }))
    await waitFor(() => expect(screen.getByTestId('stil-venster')).toHaveTextContent('Stil-venster: 3 maanden'))
    expect(aanroepen.some((a) => a.url === `/projecten/${ADMIN_A}/afsluit-instelling` && a.init?.method === 'PUT')).toBe(true)
  })

  it('rechten: Beheerder en Boekhouding+Projecten bedienen, Boekhouding leest alleen; zonder context = tonen (server beslist)', () => {
    expect(magAfsluitenBedienen('beheerder')).toBe(true)
    expect(magAfsluitenBedienen('boekhouding_projecten')).toBe(true)
    expect(magAfsluitenBedienen('boekhouding')).toBe(false)
    expect(magAfsluitenBedienen('klant_accordeur')).toBe(false)
    expect(magAfsluitenBedienen(null)).toBe(true)
  })
})

describe('Projecten — tab "Afsluiten? (N)" via ?tab=afsluiten', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('kantoorbreed: de tab landt op de kandidaten en zet de teller in de tabkop; de chip springt naar de tab', async () => {
    stubFetch(() => lijst())
    render(
      <MemoryRouter initialEntries={['/projecten?tab=afsluiten']}>
        <Routes>
          <Route path="/projecten" element={<ProjectenIngang />} />
        </Routes>
      </MemoryRouter>,
    )
    expect(await screen.findByTestId('afsluit-tabel')).toBeInTheDocument()
    expect(screen.getByTestId('tab-afsluiten')).toHaveAttribute('aria-selected', 'true')
    await waitFor(() => expect(screen.getByTestId('tab-afsluiten')).toHaveTextContent('Afsluiten? (2)'))
    expect(screen.getByTestId('projecten-paneel')).not.toBeVisible()
    const user = userEvent.setup()
    await user.click(screen.getByTestId('tab-projecten'))
    await waitFor(() => expect(screen.getByTestId('projecten-paneel')).toBeVisible())
    await user.click(await screen.findByTestId('chip-kandidaat'))
    await waitFor(() => expect(screen.getByTestId('tab-afsluiten')).toHaveAttribute('aria-selected', 'true'))
  })

  it('per administratie: ?administratie=…&tab=afsluiten opent de tab van díe administratie', async () => {
    const aanroepen = stubFetch(() => lijst([RIJ_NAAM], { stil_maanden: 6 }))
    render(
      <MemoryRouter initialEntries={[`/projecten?administratie=${ADMIN_A}&tab=afsluiten`]}>
        <Routes>
          <Route path="/projecten" element={<ProjectenIngang />} />
        </Routes>
      </MemoryRouter>,
    )
    expect(await screen.findByTestId('afsluit-tabel')).toBeInTheDocument()
    expect(aanroepen.some((a) => a.url === `/projecten/afsluit-kandidaten?administratie_id=${ADMIN_A}`)).toBe(true)
    expect(screen.getByTestId('tab-afsluiten')).toHaveAttribute('aria-selected', 'true')
    expect(screen.queryByRole('columnheader', { name: 'Administratie' })).toBeNull()
    expect(screen.getByTestId('stil-venster')).toHaveTextContent('Stil-venster: 6 maanden')
  })
})
