import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BoekvoorstelPanel } from './BoekvoorstelPanel'
import { toonHerkomst } from './testHerkomst'

/** Blok 10 07-09 — project uit de factuur (casus Spot Services: óns projectnummer staat op de factuur): chip
 * "uit factuur" (groen) / "uit factuur, nog niet bevestigd" (oranje) / uitleg-chip bij meerduidig op het projectveld;
 * weg zodra de mens het veld aanraakt; het kop-niveau-geheugen zwijgt op project zolang de chip staat. Eigen
 * testbestand náást de andere BoekvoorstelPanel-tests (gedeeld bestand, parallelle bouwrun). */

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const GB_4110 = 'cccccccc-0000-0000-0000-000000004110'
const TAXRATE_HOOG = 'dddddddd-0000-0000-0000-000000000021'
const VENDOR_ID = 'eeeeeeee-0000-0000-0000-000000000005'
const PROJECT_KONING = 'ffffffff-0000-0000-0000-000000026140'
const PROJECT_TILBURG = 'ffffffff-0000-0000-0000-000000026127'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function regel(overrides: Record<string, unknown>) {
  return {
    id: null,
    ledger_id: GB_4110,
    taxrate_id: TAXRATE_HOOG,
    project_id: null,
    netto_bedrag: '1000.00',
    btw_bedrag: '210.00',
    omschrijving: 'Steigerhuur week 34',
    btw_bron: null,
    gb_bron: null,
    gb_voorstel_detail: null,
    project_bron: null,
    project_bron_detail: null,
    ...overrides,
  }
}

function installFetchMock(regels: unknown[], geheugenVoorstel?: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/boekingsgeheugen/voorstel') && init?.method === 'POST') {
        if (geheugenVoorstel === undefined) return Promise.resolve(new Response(null, { status: 404 }))
        return Promise.resolve(jsonResponse(geheugenVoorstel))
      }
      if (url.endsWith('/grootboek')) {
        return Promise.resolve(jsonResponse({ rekeningen: [{ ledger_id: GB_4110, code: '4110', naam: 'Steigerhuur', soort: 2 }] }))
      }
      if (url.endsWith('/btw-codes')) {
        return Promise.resolve(jsonResponse({ btw_codes: [{ id: TAXRATE_HOOG, naam: 'NL, Hoog Tarief', percentage: 0.21 }] }))
      }
      if (url.endsWith('/crediteuren')) return Promise.resolve(jsonResponse({ crediteuren: [{ id: VENDOR_ID, naam: 'Spot Services' }] }))
      if (url.endsWith('/projecten')) {
        return Promise.resolve(
          jsonResponse({
            projecten: [
              { id: PROJECT_KONING, naam: '26140 Koningstraat (Confide)' },
              { id: PROJECT_TILBURG, naam: '26127 Tilburg (Heijmans)' },
            ],
          }),
        )
      }
      if (url.endsWith('/project-instelling')) return Promise.resolve(jsonResponse({ verplicht: true }))
      if (url.endsWith('/boekvoorstel') && (!init || init.method === undefined)) {
        return Promise.resolve(
          jsonResponse({
            document_id: DOCUMENT_ID,
            vendor_id: VENDOR_ID,
            referentie: 'SS-2026-0812',
            factuurdatum: '2026-08-28',
            totaalbedrag: '1210.00',
            rlz_boekstuknummer: null,
            opgeslagen: true,
            prefill_automatisch: true,
            regels,
            regels_samenvoegen: false,
            samenvoegen_toegestaan: false,
            samengevoegde_regel: null,
          }),
        )
      }
      if (url.endsWith('/boekvoorstel') && init?.method === 'PUT') return Promise.resolve(jsonResponse({}))
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

function renderPanel() {
  return render(
    <BoekvoorstelPanel
      administratieId={ADMINISTRATIE_ID}
      documentId={DOCUMENT_ID}
      status="te_controleren"
      onGeboekt={() => {}}
      onHersteld={() => {}}
    />,
  )
}

describe('BoekvoorstelPanel — project uit de factuur (blok 10 07-09, Spot Services)', () => {
  beforeEach(() => {
    vi.stubGlobal('crypto', { ...globalThis.crypto, randomUUID: () => `local-${Math.random()}` })
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('exacte projectcode = groen "uit factuur" op het projectveld, mét detail in de tooltip', async () => {
    installFetchMock([
      regel({ project_id: PROJECT_KONING, project_bron: 'factuur', project_bron_detail: 'Factuur vermeldt "26140" = projectcode van 26140 Koningstraat (Confide)' }),
    ])
    renderPanel()
    await waitFor(() => expect(screen.getAllByLabelText('Project', { exact: false })[0]).toHaveValue('26140 Koningstraat (Confide)'))
    await toonHerkomst() // 02-10: herkomst-chips staan achter "Herkomst tonen"
    const chip = screen.getByTestId('regel-project-factuur-chip')
    expect(chip).toHaveTextContent('uit factuur')
    expect(chip).toHaveClass('chip', 'ok')
    expect(chip).toHaveAttribute('title', expect.stringContaining('projectcode van 26140 Koningstraat'))
  })

  it('eerste keer werknummer = oranje "uit factuur, nog niet bevestigd"; regel zonder bron = geen chip', async () => {
    installFetchMock([
      regel({ project_id: PROJECT_KONING, project_bron: 'factuur_onbevestigd', project_bron_detail: 'Werknummer "SPOT-4711" … (nog niet bevestigd)' }),
      regel({ omschrijving: 'Transport', project_id: PROJECT_TILBURG, netto_bedrag: '150.00', btw_bedrag: '31.50' }),
    ])
    renderPanel()
    const chip = await screen.findByTestId('regel-project-factuur-chip')
    expect(chip).toHaveTextContent('uit factuur, nog niet bevestigd')
    expect(chip).toHaveClass('chip', 'afwijking')
    expect(screen.getAllByTestId('regel-project-factuur-chip')).toHaveLength(1)
  })

  it('meerduidig = niets ingevuld + uitleg-chip met de kandidaten', async () => {
    installFetchMock([
      regel({ project_id: null, project_bron: 'factuur_meerduidig', project_bron_detail: 'Factuur vermeldt "26140" — meerdere projecten passen: A, B. Kies zelf.' }),
    ])
    renderPanel()
    const chip = await screen.findByTestId('regel-project-factuur-chip')
    expect(chip).toHaveTextContent('meerdere passen, kies')
    expect(chip).toHaveAttribute('title', expect.stringContaining('A, B'))
    expect(screen.getAllByLabelText('Project', { exact: false })[0]).toHaveValue('')
  })

  it('run D 02-10 blok B: plaats + opdrachtgever = oranje chip "op plaats + opdrachtgever" op álle regels (één project per document)', async () => {
    const detail = 'Factuur noemt plaats + opdrachtgever "hoogvliet" + "weboma" — past op 26140 Koningstraat (Confide); controleer en bevestig'
    installFetchMock([
      regel({ project_id: PROJECT_KONING, project_bron: 'factuur_plaats_opdrachtgever', project_bron_detail: detail }),
      regel({ omschrijving: 'Transport', project_id: PROJECT_KONING, project_bron: 'factuur_plaats_opdrachtgever', project_bron_detail: detail, netto_bedrag: '150.00', btw_bedrag: '31.50' }),
    ])
    renderPanel()
    const chips = await screen.findAllByTestId('regel-project-factuur-chip')
    expect(chips).toHaveLength(2)
    for (const chip of chips) {
      expect(chip).toHaveTextContent('op plaats + opdrachtgever')
      expect(chip).toHaveClass('chip', 'afwijking')
      expect(chip).toHaveAttribute('title', expect.stringContaining('hoogvliet'))
    }
    // Bij ≥ 2 regels staat óók het kopveld "Project voor alle regels" (FV-07) in de lijst — toets de regelvelden.
    await waitFor(() => {
      const waarden = screen.getAllByLabelText('Project', { exact: false }).map((el) => (el as HTMLInputElement).value)
      expect(waarden.filter((w) => w === '26140 Koningstraat (Confide)')).toHaveLength(2)
    })
  })

  it('run D 02-10 blok B: meerduidig toont de kandidaten als keuze; één klik kiest het project en de chip verdwijnt', async () => {
    installFetchMock([
      regel({
        project_id: null,
        project_bron: 'factuur_meerduidig',
        project_bron_detail: 'Factuur noemt plaats + opdrachtgever — meerdere projecten passen: 26140 Koningstraat (Confide), 26127 Tilburg (Heijmans). Kies zelf.',
        project_kandidaten: [
          { id: PROJECT_KONING, naam: '26140 Koningstraat (Confide)' },
          { id: PROJECT_TILBURG, naam: '26127 Tilburg (Heijmans)' },
        ],
      }),
    ])
    const gebruiker = userEvent.setup()
    renderPanel()
    const chip = await screen.findByTestId('regel-project-factuur-chip')
    expect(chip).toHaveTextContent('meerdere passen, kies')
    const kandidaten = screen.getByTestId('regel-project-kandidaten')
    expect(kandidaten).toHaveTextContent('Kies 26140 Koningstraat (Confide)')
    expect(kandidaten).toHaveTextContent('Kies 26127 Tilburg (Heijmans)')
    await gebruiker.click(screen.getByRole('button', { name: 'Kies 26127 Tilburg (Heijmans)' }))
    await waitFor(() => expect(screen.getAllByLabelText('Project', { exact: false })[0]).toHaveValue('26127 Tilburg (Heijmans)'))
    await waitFor(() => expect(screen.queryByTestId('regel-project-kandidaten')).toBeNull())
    expect(screen.queryByTestId('regel-project-factuur-chip')).toBeNull()
  })

  it('de chip verdwijnt zodra de mens het project zelf kiest (mens wint)', async () => {
    installFetchMock([regel({ project_id: PROJECT_KONING, project_bron: 'factuur' })])
    const gebruiker = userEvent.setup()
    renderPanel()
    await toonHerkomst() // 02-10: herkomst-chips staan achter "Herkomst tonen"
    expect(await screen.findByTestId('regel-project-factuur-chip')).toHaveTextContent('uit factuur')
    await gebruiker.click(screen.getAllByLabelText('Project', { exact: false })[0])
    await gebruiker.click(await screen.findByRole('option', { name: /26127.*Tilburg/ }))
    await waitFor(() => expect(screen.queryByTestId('regel-project-factuur-chip')).toBeNull())
  })

  it('het kop-niveau-geheugen zwijgt op project zolang de factuur-chip staat', async () => {
    installFetchMock([regel({ project_id: PROJECT_KONING, project_bron: 'factuur' })], {
      gb: { waarde: GB_4110, confidence: 0.95, telling: 3, oranje: false, reden: null, app_bevestigd: true },
      btw: { waarde: TAXRATE_HOOG, confidence: 0.95, telling: 3, oranje: false, reden: null, app_bevestigd: true },
      project: { waarde: PROJECT_TILBURG, confidence: 0.9, telling: 3, oranje: false, reden: null, app_bevestigd: true },
    })
    renderPanel()
    await toonHerkomst() // 02-10: herkomst-chips staan achter "Herkomst tonen"
    expect(await screen.findByTestId('regel-project-factuur-chip')).toHaveTextContent('uit factuur')
    await waitFor(() => expect(screen.getAllByText(/Geheugen 95%/).length).toBeGreaterThan(0))
    // Geen "Geheugen: 26127 …"-afwijkingschip naast de factuur-chip; het veld houdt het factuur-project.
    expect(screen.queryByText(/Geheugen: 26127/)).toBeNull()
    expect(screen.getAllByLabelText('Project', { exact: false })[0]).toHaveValue('26140 Koningstraat (Confide)')
  })
})
