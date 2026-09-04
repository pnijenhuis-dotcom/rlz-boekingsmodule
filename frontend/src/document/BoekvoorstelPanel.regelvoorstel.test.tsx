import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BoekvoorstelPanel } from './BoekvoorstelPanel'

/** Regel-niveau voorstel-chips op het controlescherm (medewerker-wensen 04-09, mockup
 * projectverdeling-en-regelvoorstellen.html blok 2 + 3): grootboek per regel uit het regel-geheugen (groen)
 * of de AI-classificatie (oranje, bevestigen) én de btw-default van de administratie (grijs). Eigen
 * testbestand náást BoekvoorstelPanel.test.tsx (gedeeld bestand, parallelle bouwrun). */

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const GB_4110 = 'cccccccc-0000-0000-0000-000000004110'
const GB_4112 = 'cccccccc-0000-0000-0000-000000004112'
const TAXRATE_HOOG = 'dddddddd-0000-0000-0000-000000000021'
const TAXRATE_VERLEGD = 'dddddddd-0000-0000-0000-000000000009'
const VENDOR_ID = 'eeeeeeee-0000-0000-0000-000000000005'
const PROJECT_ODOO = 'ffffffff-0000-0000-0000-000000026127'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function regel(overrides: Record<string, unknown>) {
  return {
    id: null,
    ledger_id: null,
    taxrate_id: null,
    project_id: null,
    netto_bedrag: '82.40',
    btw_bedrag: '17.30',
    omschrijving: 'Regel',
    btw_bron: null,
    gb_bron: null,
    gb_voorstel_detail: null,
    ...overrides,
  }
}

function installFetchMock(regels: unknown[], geheugenVoorstel?: unknown, opties: { projectVerplicht?: boolean } = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/boekingsgeheugen/voorstel') && init?.method === 'POST') {
        if (geheugenVoorstel === undefined) return Promise.resolve(new Response(null, { status: 404 }))
        return Promise.resolve(jsonResponse(geheugenVoorstel))
      }
      if (url.endsWith('/grootboek')) {
        return Promise.resolve(
          jsonResponse({
            rekeningen: [
              { ledger_id: GB_4110, code: '4110', naam: 'Automatisering', soort: 2 },
              { ledger_id: GB_4112, code: '4112', naam: 'Software-abonnementen', soort: 2 },
            ],
          }),
        )
      }
      if (url.endsWith('/btw-codes')) {
        return Promise.resolve(
          jsonResponse({
            btw_codes: [
              { id: TAXRATE_HOOG, naam: 'NL, Hoog Tarief', percentage: 0.21 },
              { id: TAXRATE_VERLEGD, naam: 'NL, BTW verlegd (hoog)', percentage: 0 },
            ],
          }),
        )
      }
      if (url.endsWith('/crediteuren')) return Promise.resolve(jsonResponse({ crediteuren: [{ id: VENDOR_ID, naam: 'Derks Automatisering B.V.' }] }))
      if (url.endsWith('/projecten')) return Promise.resolve(jsonResponse({ projecten: [{ id: PROJECT_ODOO, naam: '[26127] Tilburg (Heijmans)' }] }))
      if (url.endsWith('/project-instelling')) return Promise.resolve(jsonResponse({ verplicht: opties.projectVerplicht ?? false }))
      if (url.endsWith('/boekvoorstel') && (!init || init.method === undefined)) {
        return Promise.resolve(
          jsonResponse({
            document_id: DOCUMENT_ID,
            vendor_id: VENDOR_ID,
            referentie: 'D-2026-0901',
            factuurdatum: '2026-09-01',
            totaalbedrag: '135.41',
            rlz_boekstuknummer: null,
            opgeslagen: false,
            regels,
            regels_samenvoegen: false,
            samenvoegen_toegestaan: true,
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
    <BoekvoorstelPanel administratieId={ADMINISTRATIE_ID} documentId={DOCUMENT_ID} status="te_controleren" onGeboekt={() => {}} onHersteld={() => {}} />,
  )
}

describe('BoekvoorstelPanel — regel-GB-voorstel (blok D 04-09, Derks-casus)', () => {
  beforeEach(() => {
    vi.stubGlobal('crypto', { ...globalThis.crypto, randomUUID: () => `local-${Math.random()}` })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('geheugen-treffer = groen "uit geheugen", AI-classificatie = oranje "AI-voorstel — bevestig", leeg = geen chip', async () => {
    installFetchMock([
      regel({ omschrijving: 'Microsoft 365 Business Premium (YR-MTH)', ledger_id: GB_4110, gb_bron: 'geheugen', gb_voorstel_detail: '3× bevestigd, laatst 12-08-2026' }),
      regel({ omschrijving: 'Copilot Business Premium (YR-MTH)', ledger_id: GB_4112, gb_bron: 'ai', gb_voorstel_detail: 'AI koos uit 2 grootboeken van deze leverancier — bevestig of corrigeer', netto_bedrag: '29.51', btw_bedrag: '6.20' }),
      regel({ omschrijving: 'Onbekende dienst', netto_bedrag: '10.00', btw_bedrag: '2.10' }),
    ])
    renderPanel()
    const gbVelden = await screen.findAllByLabelText('Grootboek', { exact: false })
    await waitFor(() => expect(gbVelden[0]).toHaveValue('4110 · Automatisering'))
    expect(gbVelden[1]).toHaveValue('4112 · Software-abonnementen')
    expect(gbVelden[2]).toHaveValue('')

    const chips = screen.getAllByTestId('regel-gb-chip')
    expect(chips).toHaveLength(2)
    expect(chips[0]).toHaveTextContent('uit geheugen')
    expect(chips[0]).toHaveClass('chip', 'ok')
    expect(chips[0]).toHaveAttribute('title', expect.stringContaining('3× bevestigd, laatst 12-08-2026'))
    expect(chips[1]).toHaveTextContent('AI-voorstel — bevestig')
    expect(chips[1]).toHaveClass('chip', 'afwijking')
  })

  it('historie-only = oranje "uit historie, nog niet bevestigd"', async () => {
    installFetchMock([regel({ ledger_id: GB_4110, gb_bron: 'geheugen_seed', gb_voorstel_detail: 'uit historie (2×), nog niet bevestigd' })])
    renderPanel()
    const chip = await screen.findByTestId('regel-gb-chip')
    expect(chip).toHaveTextContent('uit historie, nog niet bevestigd')
    expect(chip).toHaveClass('chip', 'afwijking')
  })

  it('de chip verdwijnt zodra de mens het grootboek-veld aanraakt (zelfde regel als de btw-chip)', async () => {
    installFetchMock([regel({ ledger_id: GB_4112, gb_bron: 'ai', gb_voorstel_detail: 'AI koos uit 2 grootboeken' })])
    const gebruiker = userEvent.setup()
    renderPanel()
    expect(await screen.findByTestId('regel-gb-chip')).toHaveTextContent('AI-voorstel — bevestig')
    const veld = screen.getAllByLabelText('Grootboek', { exact: false })[0]
    await gebruiker.click(veld)
    await gebruiker.click(await screen.findByRole('option', { name: /4110.*Automatisering/ }))
    await waitFor(() => expect(screen.queryByTestId('regel-gb-chip')).toBeNull())
  })

  it('het kop-niveau-geheugen zwijgt op het grootboek zolang de regel-chip staat, maar blijft op btw praten', async () => {
    installFetchMock([regel({ ledger_id: GB_4110, gb_bron: 'geheugen', gb_voorstel_detail: '3× bevestigd' })], {
      gb: { waarde: GB_4112, confidence: 0.6, telling: 3, oranje: true, reden: 'gesplitste stem', app_bevestigd: true },
      btw: { waarde: TAXRATE_HOOG, confidence: 0.95, telling: 3, oranje: false, reden: null, app_bevestigd: true },
      project: { waarde: null, confidence: 0, telling: 0, oranje: true, reden: 'geen observaties', app_bevestigd: false },
    })
    renderPanel()
    expect(await screen.findByTestId('regel-gb-chip')).toHaveTextContent('uit geheugen')
    // btw: engine vult 'm mét geheugen-chip; grootboek: géén "Geheugen: 4112"-afwijkingschip naast de regel-chip.
    await waitFor(() => expect(screen.getAllByLabelText('Btw-code', { exact: false })[0]).toHaveValue('21% · NL, Hoog Tarief'))
    expect(screen.getByText(/Geheugen 95%/)).toBeInTheDocument()
    expect(screen.queryByText(/Geheugen: 4112/)).toBeNull()
  })
})

describe('BoekvoorstelPanel — btw-default administratie (blok E 04-09, mockup blok 3)', () => {
  beforeEach(() => {
    vi.stubGlobal('crypto', { ...globalThis.crypto, randomUUID: () => `local-${Math.random()}` })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('"standaard administratie" = neutrale grijze chip; factuur-regel houdt "uit factuur (21%)"', async () => {
    installFetchMock([
      regel({ omschrijving: 'AR-40 staander 2,0m m.p. (huur)', taxrate_id: TAXRATE_VERLEGD, btw_bron: 'standaard', netto_bedrag: '1000.00', btw_bedrag: '0.00' }),
      regel({ omschrijving: 'Diesel heftruck', taxrate_id: TAXRATE_HOOG, btw_bron: 'factuur', netto_bedrag: '100.00', btw_bedrag: '21.00' }),
    ])
    renderPanel()
    const btwVelden = await screen.findAllByLabelText('Btw-code', { exact: false })
    await waitFor(() => expect(btwVelden[0]).toHaveValue('0% · NL, BTW verlegd (hoog)'))
    expect(btwVelden[1]).toHaveValue('21% · NL, Hoog Tarief')
    const chip = screen.getByTestId('regel-btw-standaard-chip')
    expect(chip).toHaveTextContent('standaard administratie')
    expect(chip).toHaveClass('chip', 'handmatig')
    expect(screen.getByText('uit factuur (21%)')).toHaveClass('chip', 'ok')
  })

  it('de chip verdwijnt zodra de mens de btw-code zelf kiest', async () => {
    installFetchMock([regel({ taxrate_id: TAXRATE_VERLEGD, btw_bron: 'standaard', netto_bedrag: '1000.00', btw_bedrag: '0.00' })])
    const gebruiker = userEvent.setup()
    renderPanel()
    expect(await screen.findByTestId('regel-btw-standaard-chip')).toBeInTheDocument()
    await gebruiker.click(screen.getAllByLabelText('Btw-code', { exact: false })[0])
    await gebruiker.click(await screen.findByRole('option', { name: /NL, Hoog Tarief/ }))
    await waitFor(() => expect(screen.queryByTestId('regel-btw-standaard-chip')).toBeNull())
  })
})

describe('BoekvoorstelPanel — overstap-vertaling van een open voorstel (Odoo-slotstuk 04-09, C1 hervertaling)', () => {
  beforeEach(() => {
    vi.stubGlobal('crypto', { ...globalThis.crypto, randomUUID: () => `local-${Math.random()}` })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  const GB_VERTAALD = { van_id: 'rlz-4304', van_code: '4304', van_naam: 'Brandstof auto', naar_id: GB_4110, naar_code: '4110', naar_naam: 'Automatisering' }
  const BTW_LEEG = { van_id: 'rlz-btw-x', van_code: null, van_naam: 'NL, BTW verlegd (hoog)', naar_id: null, reden: 'geen Odoo-tegenhanger in de mapping bij de overstap' }
  const PROJECT_VERTAALD = { van_id: 'rlz-pr-26127', van_code: '26127', van_naam: '26127 Tilburg (Heijmans)', naar_id: PROJECT_ODOO, naar_code: '26127', naar_naam: '[26127] Tilburg (Heijmans)' }

  it('grootboek vertaald = oranje "vertaald bij overstap"; btw niet vertaalbaar en leeg = rode "kies"; project vertaald = oranje in de projectkolom', async () => {
    installFetchMock(
      [
        regel({
          omschrijving: 'Diesel',
          ledger_id: GB_4110,
          taxrate_id: null,
          project_id: PROJECT_ODOO,
          overstap_vertaling: { op: '2026-09-04T20:00:00Z', grootboek: GB_VERTAALD, btw: BTW_LEEG, project: PROJECT_VERTAALD },
        }),
      ],
      undefined,
      { projectVerplicht: true },
    )
    renderPanel()
    const gb = await screen.findByTestId('regel-overstap-chip-grootboek')
    expect(gb).toHaveTextContent('vertaald bij overstap')
    expect(gb).toHaveClass('chip', 'afwijking')
    expect(gb).toHaveAttribute('title', expect.stringContaining('Reeleezee 4304 Brandstof auto → Odoo 4110 Automatisering'))
    const btw = screen.getByTestId('regel-overstap-chip-btw')
    expect(btw).toHaveTextContent('niet vertaalbaar bij overstap — kies')
    expect(btw).toHaveClass('chip', 'blokkerend')
    expect(btw).toHaveAttribute('title', expect.stringContaining('geen Odoo-tegenhanger in de mapping bij de overstap'))
    const project = screen.getByTestId('regel-overstap-chip-project')
    expect(project).toHaveTextContent('vertaald bij overstap')
    expect(project).toHaveClass('chip', 'afwijking')
  })

  it('de chip verdwijnt zodra de mens het veld aanraakt — ook de rode "kies" ná een keuze', async () => {
    installFetchMock([regel({ ledger_id: GB_4110, taxrate_id: null, overstap_vertaling: { grootboek: GB_VERTAALD, btw: BTW_LEEG } })])
    const gebruiker = userEvent.setup()
    renderPanel()
    expect(await screen.findByTestId('regel-overstap-chip-grootboek')).toBeInTheDocument()
    expect(screen.getByTestId('regel-overstap-chip-btw')).toBeInTheDocument()
    await gebruiker.click(screen.getAllByLabelText('Grootboek', { exact: false })[0])
    await gebruiker.click(await screen.findByRole('option', { name: /4112.*Software-abonnementen/ }))
    await waitFor(() => expect(screen.queryByTestId('regel-overstap-chip-grootboek')).toBeNull())
    await gebruiker.click(screen.getAllByLabelText('Btw-code', { exact: false })[0])
    await gebruiker.click(await screen.findByRole('option', { name: /NL, Hoog Tarief/ }))
    await waitFor(() => expect(screen.queryByTestId('regel-overstap-chip-btw')).toBeNull())
  })

  it('zonder spoor (RLZ-administratie of gewoon voorstel) geen overstap-chips', async () => {
    installFetchMock([regel({ ledger_id: GB_4110, gb_bron: 'geheugen', gb_voorstel_detail: '3× bevestigd' })])
    renderPanel()
    expect(await screen.findByTestId('regel-gb-chip')).toBeInTheDocument()
    expect(screen.queryByTestId('regel-overstap-chip-grootboek')).toBeNull()
    expect(screen.queryByTestId('regel-overstap-chip-btw')).toBeNull()
  })
})
