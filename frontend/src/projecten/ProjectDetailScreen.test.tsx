/** Projectdetail — contract-ontleding AUTO-FIRST (D6 07-09, besluit Peter 06-09): specs en staffels
 * dragen een herkomst-chip "uit contract" / "handmatig"; het leesspoor toont "niet in contract
 * aangetroffen" als expliciete uitkomst en heeft géén bevestig-knoppen meer; een inline correctie
 * van een contract-staffel gaat via de bestaande wijzig-route en de chip wordt daarna "handmatig". */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ProjectDetailScreen } from './ProjectDetailScreen'

const ADMINISTRATIE_ID = 'dddddddd-0000-0000-0000-00000000000d'
const PROJECT_ID = 'aaaaaaaa-0000-0000-0000-00000000000a'
const DOCUMENT_ID = 'cccccccc-0000-0000-0000-00000000000c'
const STAFFEL_CONTRACT = 'bbbbbbbb-0000-0000-0000-000000000001'
const STAFFEL_LEGACY = 'bbbbbbbb-0000-0000-0000-000000000002'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function detail(overrides: { trapHerkomst?: string | null; trapPrijs?: string } = {}) {
  return {
    project_id: PROJECT_ID,
    naam: '26031 Tilburg (Heijmans)',
    is_actief: true,
    specificatie: {
      opdrachtgever: 'BAM Wonen',
      werknummer_opdrachtgever: null,
      soort_werk: 'gevelsteiger t.b.v. renovatie',
      contract_m2: '4350.00',
      looptijd_van: '2026-06-02',
      looptijd_tot: '2026-11-30',
      huurtijd_omschrijving: null,
      doorlopende_huur_omschrijving: '€ 150 per week vanaf week 10 (afgeleid uit staffel: §5 "€ 150/week uitgaande van 9 weken")',
      veld_herkomst: {
        opdrachtgever: 'contract',
        soort_werk: 'contract',
        contract_m2: 'mens',
        looptijd_van: 'contract',
        looptijd_tot: 'contract',
        doorlopende_huur_omschrijving: 'contract',
      },
    },
    documenten: [
      { id: DOCUMENT_ID, soort: 'contract', titel: 'OB 26031', versie_omschrijving: null, bestandsnaam: 'ob.pdf',
        aangemaakt_op: '2026-09-07T08:00:00Z', ontleed: true },
    ],
    staffels: [
      { id: STAFFEL_CONTRACT, omschrijving: 'Trapsteiger', eenheid: 'm2', prijs_per_eenheid: overrides.trapPrijs ?? '9.20',
        verrekenbaar: true, bron: '§4.2 "€ 9,20 per m²"', aangemaakt_op: '2026-09-07T08:00:00Z',
        herkomst: overrides.trapHerkomst === undefined ? 'contract' : overrides.trapHerkomst,
        herkomst_document_id: DOCUMENT_ID },
      { id: STAFFEL_LEGACY, omschrijving: 'Netten', eenheid: 'm2', prijs_per_eenheid: '1.10', verrekenbaar: true,
        bron: 'handmatig', aangemaakt_op: '2026-08-22T08:00:00Z', herkomst: null, herkomst_document_id: null },
    ],
    werknummers: [],
    ontleding: [
      { id: 'e1', project_document_id: DOCUMENT_ID, soort: 'soort_werk', omschrijving: 'Soort werk',
        citaat: 'p.1 "gevelsteiger t.b.v. renovatie"', waarde: { waarde: 'gevelsteiger t.b.v. renovatie' },
        zekerheid: null, status: 'overgenomen' },
      { id: 'e2', project_document_id: DOCUMENT_ID, soort: 'contract_m2', omschrijving: 'Contract-m²',
        citaat: 'p.1 "4.200 m²"', waarde: { waarde: '4200' }, zekerheid: null, status: 'mens_behouden' },
      { id: 'e3', project_document_id: DOCUMENT_ID, soort: 'huurtijd', omschrijving: 'Huurtijd inbegrepen',
        citaat: null, waarde: null, zekerheid: null, status: 'niet_aangetroffen' },
      { id: 'e4', project_document_id: DOCUMENT_ID, soort: 'staffel', omschrijving: 'Huur doorlopend',
        citaat: '§5 "€ 150/week uitgaande van 9 weken"',
        waarde: { waarde: '150', eenheid: 'week', reden: "eenheid 'week' niet herkend (m²/m¹/stuks/manuren) — voeg de staffel handmatig toe" },
        zekerheid: '0.900', status: 'ongeldig' },
    ],
    gebouwd_m2: '0',
    prijsafspraken: [],
    veldwerkers: [],
  }
}

function installMock(state: { detail: ReturnType<typeof detail>; puts: Array<{ url: string; body: unknown }> }) {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/auth/administraties'))
        return Promise.resolve(jsonResponse({ administraties: [{ id: ADMINISTRATIE_ID, naam: 'Universal Steigerbouw' }] }))
      if (url.includes(`/projecten/${ADMINISTRATIE_ID}/staffels/`) && init?.method === 'PUT') {
        state.puts.push({ url, body: JSON.parse(String(init.body)) })
        state.detail = detail({ trapHerkomst: 'mens', trapPrijs: '9.50' })
        return Promise.resolve(new Response(null, { status: 204 }))
      }
      if (url.includes(`/projecten/${ADMINISTRATIE_ID}/${PROJECT_ID}`)) return Promise.resolve(jsonResponse(state.detail))
      if (url.includes('/materiaal/')) return Promise.resolve(jsonResponse({ detail: 'uit' }, 409))
      if (url.includes('/crediteuren')) return Promise.resolve(jsonResponse({ vendors: [] }))
      return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
    }),
  )
}

function renderDetail() {
  return render(
    <MemoryRouter initialEntries={[`/projecten/${ADMINISTRATIE_ID}/${PROJECT_ID}`]}>
      <Routes>
        <Route path="/projecten/:administratieId/:projectId" element={<ProjectDetailScreen />} />
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('ProjectDetailScreen — contract-ontleding auto-first (D6)', () => {
  it('toont herkomst-chips op specs en staffels en een leesspoor zonder bevestig-knoppen', async () => {
    installMock({ detail: detail(), puts: [] })
    renderDetail()
    await screen.findByRole('heading', { name: '26031 Tilburg (Heijmans)' })

    // Specs: contract-velden dragen "uit contract", het door de mens gecorrigeerde contract-m² "handmatig".
    const soortWerk = screen.getByText('Soort werk', { selector: 'label' })
    expect(within(soortWerk).getByText('uit contract')).toBeTruthy()
    const contractM2 = screen.getByText('Contract-m²', { selector: 'label' })
    expect(within(contractM2).getByText('handmatig')).toBeTruthy()

    // Staffels: de contract-regel "uit contract", de oude rij zonder herkomst met bron 'handmatig' → "handmatig".
    const trap = screen.getByText('Trapsteiger', { selector: 'td' }).closest('tr')!
    expect(within(trap).getByText('uit contract')).toBeTruthy()
    const netten = screen.getByText('Netten', { selector: 'td' }).closest('tr')!
    expect(within(netten).getByText('handmatig', { selector: 'span' })).toBeTruthy() // de chip (bron-cel zegt ook 'handmatig')

    // Leesspoor: expliciete uitkomsten, reden bij "niet ingevuld", géén ✓/✗-knoppen meer.
    expect(screen.getByText('niet in contract aangetroffen')).toBeTruthy()
    expect(screen.getByText('handmatige waarde behouden')).toBeTruthy()
    expect(screen.getByText('✓ ingevuld uit contract')).toBeTruthy()
    expect(screen.getByText(/eenheid 'week' niet herkend/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: /^Bevestig / })).toBeNull()
    expect(screen.queryByRole('button', { name: /^Wijs .* af$/ })).toBeNull()
  })

  it('een inline correctie van een contract-staffel gaat via de wijzig-route en maakt de chip "handmatig"', async () => {
    const state = { detail: detail(), puts: [] as Array<{ url: string; body: unknown }> }
    installMock(state)
    renderDetail()
    await screen.findByRole('heading', { name: '26031 Tilburg (Heijmans)' })

    const trap = screen.getByText('Trapsteiger', { selector: 'td' }).closest('tr')!
    fireEvent.click(within(trap).getByRole('button', { name: 'wijzig' }))
    const prijs = screen.getByLabelText('Prijs') as HTMLInputElement
    expect(prijs.value).toBe('9.20')
    fireEvent.change(prijs, { target: { value: '9,50' } })
    const staffelVorm = prijs.closest('label')!.parentElement!
    fireEvent.click(within(staffelVorm).getByRole('button', { name: 'Opslaan' }))

    await waitFor(() => expect(state.puts).toHaveLength(1))
    expect(state.puts[0].url).toContain(`/projecten/${ADMINISTRATIE_ID}/staffels/${STAFFEL_CONTRACT}`)
    expect(state.puts[0].body).toMatchObject({ omschrijving: 'Trapsteiger', eenheid: 'm2', prijs_per_eenheid: '9.50' })
    // Ná de herlading toont de rij de gecorrigeerde prijs en de chip "handmatig".
    await waitFor(() => {
      const rij = screen.getByText('Trapsteiger', { selector: 'td' }).closest('tr')!
      expect(within(rij).getByText('handmatig', { selector: 'span' })).toBeTruthy()
    })
    expect(screen.getByText('Staffel gewijzigd.')).toBeTruthy()
  })
})
