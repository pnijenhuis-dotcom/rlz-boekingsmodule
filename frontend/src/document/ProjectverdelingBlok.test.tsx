import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ProjectverdelingDto } from '../api/types'
import { ProjectverdelingBlok, defaultPeriode } from './ProjectverdelingBlok'

const ADM = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOC = 'bbbbbbbb-0000-0000-0000-000000000002'
const EINDHOVEN = 'cccccccc-0000-0000-0000-000000000011'
const TILBURG = 'cccccccc-0000-0000-0000-000000000012'
const VENLO = 'cccccccc-0000-0000-0000-000000000013'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const PREFILL: ProjectverdelingDto = {
  document_id: DOC,
  status: 'voorstel',
  opgeslagen: false,
  prefill: true,
  basisbedrag: '2000.00',
  vaste_regels: [],
  pro_rato: true,
  pro_rato_periode: '2026-07-01',
  pro_rato_periode_label: 'juli 2026',
  pro_rato_bedrag: '2000.00',
  delen: [
    { project_id: EINDHOVEN, project_naam: '26120 Eindhoven (BAM)', wijze: 'pro_rato', bedrag: '1200.00', aandeel: '0.600000', omzet: '6000.00' },
    { project_id: TILBURG, project_naam: '26127 Tilburg (Heijmans)', wijze: 'pro_rato', bedrag: '500.00', aandeel: '0.250000', omzet: '2500.00' },
    { project_id: VENLO, project_naam: '26131 Venlo (Dura)', wijze: 'pro_rato', bedrag: '300.00', aandeel: '0.150000', omzet: '1500.00' },
  ],
  omzetstanden: [],
  aantal_projecten_met_omzet: 3,
  omzet_cache_leeg: false,
  compleet: true,
  blokkade: null,
  boek_cyclus: 0,
  hercontrole: null,
}

const MET_VAST: ProjectverdelingDto = {
  ...PREFILL,
  opgeslagen: true,
  prefill: false,
  vaste_regels: [{ project_id: TILBURG, bedrag: '600.00', hint: 'rechtstreeks steigerbouwen', project_naam: '26127 Tilburg (Heijmans)' }],
  pro_rato_bedrag: '1400.00',
  delen: [
    { project_id: TILBURG, project_naam: '26127 Tilburg (Heijmans)', wijze: 'vast', bedrag: '600.00' },
    { project_id: EINDHOVEN, project_naam: '26120 Eindhoven (BAM)', wijze: 'pro_rato', bedrag: '840.00', aandeel: '0.600000', omzet: '6000.00' },
    { project_id: TILBURG, project_naam: '26127 Tilburg (Heijmans)', wijze: 'pro_rato', bedrag: '350.00', aandeel: '0.250000', omzet: '2500.00' },
    { project_id: VENLO, project_naam: '26131 Venlo (Dura)', wijze: 'pro_rato', bedrag: '210.00', aandeel: '0.150000', omzet: '1500.00' },
  ],
}

const TE_VEEL_VAST: ProjectverdelingDto = {
  ...MET_VAST,
  vaste_regels: [{ project_id: TILBURG, bedrag: '2500.00', project_naam: '26127 Tilburg (Heijmans)' }],
  pro_rato_bedrag: '-500.00',
  delen: [{ project_id: TILBURG, project_naam: '26127 Tilburg (Heijmans)', wijze: 'vast', bedrag: '2500.00' }],
  compleet: false,
  blokkade: '€ 500.00 meer vast verdeeld dan het bedrag excl. — verlaag een vaste regel',
}

const GEBOEKT_MET_SIGNAAL: ProjectverdelingDto = {
  ...MET_VAST,
  status: 'geboekt',
  hercontrole: {
    op: '2026-09-02T07:00:00Z',
    afwijking_pct: '7.73',
    drempel_pct: '5.00',
    periode: '2026-07-01',
    signaal: true,
    nieuwe_verdeling: [
      { project_id: TILBURG, project_naam: '26127 Tilburg (Heijmans)', wijze: 'vast', bedrag: '600.00' },
      { project_id: EINDHOVEN, project_naam: '26120 Eindhoven (BAM)', wijze: 'pro_rato', bedrag: '763.64', aandeel: '0.545455', omzet: '6000.00' },
      { project_id: TILBURG, project_naam: '26127 Tilburg (Heijmans)', wijze: 'pro_rato', bedrag: '318.18', aandeel: '0.227273', omzet: '2500.00' },
      { project_id: VENLO, project_naam: '26131 Venlo (Dura)', wijze: 'pro_rato', bedrag: '318.18', aandeel: '0.227273', omzet: '2500.00' },
    ],
  },
}

interface Opties {
  get: ProjectverdelingDto
  puts?: unknown[]
  putAntwoord?: ProjectverdelingDto
  posts?: { url: string; body: unknown }[]
  postStatus?: number
}

function installFetchMock({ get, puts, putAntwoord, posts, postStatus = 200 }: Opties) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      if (url.endsWith(`/administraties/${ADM}/projecten`)) {
        return Promise.resolve(
          jsonResponse({
            projecten: [
              { id: EINDHOVEN, naam: '26120 Eindhoven (BAM)' },
              { id: TILBURG, naam: '26127 Tilburg (Heijmans)' },
              { id: VENLO, naam: '26131 Venlo (Dura)' },
            ],
          }),
        )
      }
      if (url.endsWith('/projectverdeling/herverdelen') && method === 'POST') {
        posts?.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null })
        if (postStatus !== 200) return Promise.resolve(jsonResponse({ detail: 'Herverdelen via tegenboeken kan alleen als storno geblokkeerd is' }, postStatus))
        return Promise.resolve(jsonResponse({ document_id: DOC, status: 'te_controleren', rlz_tegenboeking_id: 'x', rlz_boekstuknummer: 'TB-1' }))
      }
      if (url.endsWith('/projectverdeling') && method === 'PUT') {
        puts?.push(init?.body ? JSON.parse(String(init.body)) : null)
        return Promise.resolve(jsonResponse(putAntwoord ?? MET_VAST))
      }
      if (url.endsWith('/projectverdeling')) return Promise.resolve(jsonResponse(get))
      return Promise.resolve(jsonResponse({ detail: `onbekend pad ${url}` }, 404))
    }),
  )
}

function renderBlok(status = 'te_controleren', onGewijzigd?: () => void) {
  return render(
    <ProjectverdelingBlok administratieId={ADM} documentId={DOC} status={status} soort="inkoopfactuur" boekvoorstelVersie={0} onGewijzigd={onGewijzigd} />,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('ProjectverdelingBlok', () => {
  it('toont de prefill (opt-in per leverancier): restant pro rato, 3 projecten mét omzet, 100 %-stand', async () => {
    installFetchMock({ get: PREFILL })
    renderBlok()
    expect(await screen.findByText(/Restant — pro rato omzet juli 2026/)).toBeInTheDocument()
    expect(screen.getByText(/3 projecten mét omzet · omzetloos telt niet mee · OVH uitgesloten/)).toBeInTheDocument()
    expect(screen.getByText(/voorstel — pro rato per leverancier aan/)).toBeInTheDocument()
    expect(screen.getByTestId('pv-restant-balk')).toHaveTextContent('verdeeld 100% ✓')
    expect(screen.queryByText('omzetstanden vastgelegd')).not.toBeInTheDocument()
    expect(screen.queryByTestId('pv-vaste-regel')).not.toBeInTheDocument()
  })

  it('"Verdeling tonen ▸" klapt de pro-rato-preview uit met percentages, bedragen en de som-regel', async () => {
    installFetchMock({ get: MET_VAST })
    renderBlok()
    await screen.findByText(/Restant — pro rato omzet juli 2026/)
    await userEvent.click(screen.getByRole('button', { name: 'Verdeling tonen ▸' }))
    const preview = screen.getByTestId('pv-preview')
    expect(preview).toHaveTextContent('26120 Eindhoven (BAM) 60,0% · € 840,00')
    expect(preview).toHaveTextContent('grootste-rest-centen, som exact € 1.400,00')
    expect(screen.getAllByTestId('pv-vaste-regel')).toHaveLength(1)
    expect(screen.getByText('vast')).toBeInTheDocument()
  })

  it('een vaste regel + restant: auto-opslaan (600 ms) stuurt vaste regels én omzetmaand naar de server', async () => {
    const puts: unknown[] = []
    installFetchMock({ get: PREFILL, puts })
    renderBlok()
    await screen.findByText(/Restant — pro rato omzet juli 2026/)
    await userEvent.click(screen.getByRole('button', { name: '+ Regel toevoegen (vast)' }))
    const combobox = screen.getByRole('combobox', { name: /Project \(vast\)/ })
    await userEvent.click(combobox)
    await userEvent.type(combobox, 'Tilburg')
    await userEvent.click(await screen.findByRole('option', { name: /26127 Tilburg/ }))
    await userEvent.type(screen.getByLabelText('Bedrag excl. (vast)'), '600,00')
    await waitFor(() => expect(puts.length).toBeGreaterThan(0), { timeout: 3000 })
    const laatste = puts[puts.length - 1] as { vaste_regels: { project_id: string; bedrag: string }[]; pro_rato_periode: string }
    expect(laatste.vaste_regels).toEqual([{ project_id: TILBURG, bedrag: '600.00', hint: null }])
    expect(laatste.pro_rato_periode).toBe('2026-07-01')
    // Serverantwoord (MET_VAST) wordt de getoonde stand: restant € 1.400.
    expect(await screen.findByText('€ 1.400,00')).toBeInTheDocument()
  })

  it('te veel vast verdeeld = blokkeer-reden in één zin en een rode restant-balk', async () => {
    installFetchMock({ get: TE_VEEL_VAST })
    renderBlok()
    expect(await screen.findByTestId('pv-blokkade')).toHaveTextContent('€ 500.00 meer vast verdeeld dan het bedrag excl.')
    expect(screen.getByTestId('pv-restant-balk')).toHaveClass('te-veel')
    expect(screen.getByTestId('pv-restant-balk')).toHaveTextContent('te veel vast')
  })

  it('lege omzetstand = actie: knop naar de projectcijfers-sync', async () => {
    installFetchMock({
      get: { ...PREFILL, compleet: false, delen: [], aantal_projecten_met_omzet: 0, omzet_cache_leeg: true, blokkade: 'Geen omzetcijfers bekend voor juli 2026 — ververs de projectcijfers (⟳) of vul vaste regels in' },
    })
    renderBlok()
    expect(await screen.findByRole('button', { name: /Projectcijfers verversen/ })).toBeInTheDocument()
  })

  it('B1: geen projectplicht én geen actieve projecten (beschikbaar=false) = geen blok', async () => {
    installFetchMock({ get: { document_id: DOC, status: 'geen', opgeslagen: false, beschikbaar: false } })
    renderBlok()
    await waitFor(() => expect((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThan(0))
    await new Promise((r) => setTimeout(r, 20))
    expect(screen.queryByTestId('projectverdeling-blok')).not.toBeInTheDocument()
  })

  it('B1: openVerzoek vanuit de lege project-kolom opent het blok als voorstel pro rato (zelfde actie als de tekstknop)', async () => {
    const puts: unknown[] = []
    installFetchMock({ get: { document_id: DOC, status: 'geen', opgeslagen: false, beschikbaar: true }, puts, putAntwoord: PREFILL })
    const { rerender } = render(
      <ProjectverdelingBlok administratieId={ADM} documentId={DOC} status="te_controleren" soort="inkoopfactuur" boekvoorstelVersie={0} openVerzoek={0} />,
    )
    await screen.findByRole('button', { name: 'Verdelen over projecten…' })
    rerender(
      <ProjectverdelingBlok administratieId={ADM} documentId={DOC} status="te_controleren" soort="inkoopfactuur" boekvoorstelVersie={0} openVerzoek={1} />,
    )
    await waitFor(() => expect(puts.length).toBe(1), { timeout: 3000 })
    expect(puts[0]).toEqual({ vaste_regels: [], pro_rato_periode: defaultPeriode() })
    expect(await screen.findByText(/Restant — pro rato omzet/)).toBeInTheDocument()
  })

  it('zonder opt-in: alleen de tekstknop "Verdelen over projecten…"; klik = voorstel pro rato (vorige maand) opgeslagen', async () => {
    const puts: unknown[] = []
    installFetchMock({ get: { document_id: DOC, status: 'geen', opgeslagen: false }, puts, putAntwoord: PREFILL })
    renderBlok()
    const knop = await screen.findByRole('button', { name: 'Verdelen over projecten…' })
    expect(knop).toHaveClass('linkbtn')
    await userEvent.click(knop)
    await waitFor(() => expect(puts.length).toBe(1), { timeout: 3000 })
    expect(puts[0]).toEqual({ vaste_regels: [], pro_rato_periode: defaultPeriode() })
    // De maandkeuze is de lokale default (vorige maand); het serverantwoord levert de 100 %-stand.
    expect(await screen.findByText(/Restant — pro rato omzet/)).toBeInTheDocument()
    expect(screen.getByTestId('pv-restant-balk')).toHaveTextContent('verdeeld 100% ✓')
  })

  it('geboekt: alleen-lezen, chip "omzetstanden vastgelegd", hercontrole-signaal mét Herverdelen… → dialoog oud vs nieuw → POST', async () => {
    const posts: { url: string; body: unknown }[] = []
    const onGewijzigd = vi.fn()
    installFetchMock({ get: GEBOEKT_MET_SIGNAAL, posts })
    renderBlok('geboekt', onGewijzigd)
    expect(await screen.findByText('omzetstanden vastgelegd')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '+ Regel toevoegen (vast)' })).not.toBeInTheDocument()
    const signaal = screen.getByTestId('pv-signaal')
    expect(signaal).toHaveTextContent('omzet juli 2026 is ná het boeken gewijzigd')
    expect(signaal).toHaveTextContent('wijkt nu 7,73% af')
    await userEvent.click(screen.getByRole('button', { name: 'Herverdelen…' }))
    const dialoog = await screen.findByTestId('pv-herverdeel-dialoog')
    expect(dialoog).toHaveTextContent('26131 Venlo (Dura)')
    expect(dialoog).toHaveTextContent('€ 210,00')
    expect(dialoog).toHaveTextContent('€ 318,18')
    fireEvent.change(screen.getByLabelText('Reden herverdelen'), { target: { value: 'nagekomen factuur Venlo' } })
    await userEvent.click(screen.getByRole('button', { name: 'Tegenboeken en herverdelen' }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].body).toEqual({ reden: 'nagekomen factuur Venlo' })
    await waitFor(() => expect(onGewijzigd).toHaveBeenCalled())
  })

  it('herverdelen geblokkeerd (409, aangifte-poort niet blokkerend) = leesbare fout in de dialoog, niets stil', async () => {
    const posts: { url: string; body: unknown }[] = []
    installFetchMock({ get: GEBOEKT_MET_SIGNAAL, posts, postStatus: 409 })
    renderBlok('geboekt')
    await userEvent.click(await screen.findByRole('button', { name: 'Herverdelen…' }))
    await screen.findByTestId('pv-herverdeel-dialoog')
    await userEvent.click(screen.getByRole('button', { name: 'Tegenboeken en herverdelen' }))
    expect(await screen.findByText(/Herverdelen via tegenboeken kan alleen/)).toBeInTheDocument()
    // Lege reden → de vooringevulde standaardtekst ging mee (verplicht veld, nooit leeg).
    expect((posts[0].body as { reden: string }).reden).toMatch(/omzet juli 2026 gewijzigd/)
  })

  it('B3-dekking (bugfix 04-09): ná een geslaagde opslag vuurt onOpgeslagen en meldt onStand dekt=true (compleet) resp. false (blokkade)', async () => {
    const puts: unknown[] = []
    const opgeslagen = vi.fn()
    const standen: { dekt: boolean }[] = []
    installFetchMock({ get: { document_id: DOC, status: 'geen', opgeslagen: false, beschikbaar: true }, puts, putAntwoord: MET_VAST })
    render(
      <ProjectverdelingBlok
        administratieId={ADM}
        documentId={DOC}
        status="te_controleren"
        soort="inkoopfactuur"
        boekvoorstelVersie={0}
        onOpgeslagen={opgeslagen}
        onStand={(stand) => standen.push(stand)}
      />,
    )
    const knop = await screen.findByRole('button', { name: 'Verdelen over projecten…' })
    // Lege stand ('geen') = niets gedekt.
    await waitFor(() => expect(standen.at(-1)).toEqual({ dekt: false }))
    await userEvent.click(knop)
    await waitFor(() => expect(puts.length).toBe(1), { timeout: 3000 })
    await waitFor(() => expect(opgeslagen).toHaveBeenCalledTimes(1))
    // Het serverantwoord is compleet → de regels zonder kolom-project zijn gedekt.
    await waitFor(() => expect(standen.at(-1)).toEqual({ dekt: true }))
  })

  it('B3-dekking: een onvolledige verdeling (blokkade) meldt dekt=false', async () => {
    const standen: { dekt: boolean }[] = []
    installFetchMock({ get: TE_VEEL_VAST })
    render(
      <ProjectverdelingBlok administratieId={ADM} documentId={DOC} status="te_controleren" soort="inkoopfactuur" boekvoorstelVersie={0} onStand={(stand) => standen.push(stand)} />,
    )
    await screen.findByText(/meer vast verdeeld/)
    await waitFor(() => expect(standen.at(-1)).toEqual({ dekt: false }))
  })

  it('geen inkoopfactuur = geen blok', () => {
    installFetchMock({ get: PREFILL })
    const { container } = render(
      <ProjectverdelingBlok administratieId={ADM} documentId={DOC} status="te_controleren" soort="kassarapport" boekvoorstelVersie={0} />,
    )
    expect(container).toBeEmptyDOMElement()
  })
})
