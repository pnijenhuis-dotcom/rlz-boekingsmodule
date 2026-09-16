import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { OmzetBronnenBlok } from './OmzetBronnenBlok'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const REKENINGEN = [
  { ledger_id: 'gb-1010', code: '1010', naam: 'Kas' },
  { ledger_id: 'gb-1020', code: '1020', naam: 'Kruisposten PIN' },
  { ledger_id: 'gb-1025', code: '1025', naam: 'Stripe onderweg' },
  { ledger_id: 'gb-4890', code: '4890', naam: 'Kasverschillen' },
  { ledger_id: 'gb-4850', code: '4850', naam: 'Transactiekosten PSP' },
]
const TARIEVEN = [
  { taxrate_id: 'btw-laag', naam: 'NL, Laag Tarief', percentage: '0.09' },
  { taxrate_id: 'btw-hoog', naam: 'NL, Hoog Tarief', percentage: '0.21' },
]
// Vorm zoals X 'm bouwde (`service.defaults_voor`): btw per categorie-SLEUTEL als {klasse, taxrate_id}; psp/eten niet
// in defaults maar gemerged in de hoofdwaarden (GET geeft 'stripe'/'laag' terug als er niets is opgeslagen).
const DEFAULTS = {
  tegenrekeningen: { pin: 'gb-1020', cash: 'gb-1010', stripe: 'gb-1025', kasverschil: 'gb-4890', storting: null },
  categorie_btw: {
    pilateslessen: { klasse: 'laag', taxrate_id: 'btw-laag' },
    yoga: { klasse: 'laag', taxrate_id: 'btw-laag' },
    'kleding producten': { klasse: 'hoog', taxrate_id: 'btw-hoog' },
  },
  btw_per_klasse: { laag: 'btw-laag', hoog: 'btw-hoog', verlegd: null },
  product_categorieen: { '10 rittenkaart': 'Pilateslessen' },
  psp_kosten_ledger_id: 'gb-4850',
  psp_btw_herkomst: 'Stripe · EU-dienst verlegd',
}

function installFetchMock(opties: { stand?: Record<string, unknown>; putAanroepen?: unknown[]; putStatus?: number; putDetail?: unknown }) {
  let stand: Record<string, unknown> = {
    stores: [],
    product_categorieen: {},
    tegenrekeningen: { pin: null, cash: null, stripe: null, kasverschil: null, storting: null },
    categorie_btw: {},
    combi_regel: 'pro_rato_batch',
    psp: 'stripe',
    psp_kosten_ledger_id: null,
    eten_drinken_tarief: 'laag',
    ...(opties.stand ?? {}),
  }
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (!url.endsWith('/omzet/bron-instellingen')) return Promise.resolve(new Response(null, { status: 404 }))
      if (init?.method === 'PUT') {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>
        opties.putAanroepen?.push(body)
        if (opties.putStatus && opties.putStatus >= 400) {
          return Promise.resolve(jsonResponse({ detail: opties.putDetail ?? 'Onbekende rekening in tegenrekeningen — kies er één uit het schema.' }, opties.putStatus))
        }
        stand = { ...stand, ...body }
      }
      return Promise.resolve(jsonResponse({ ...stand, defaults: DEFAULTS, rekeningen: REKENINGEN, tarieven: TARIEVEN }))
    }),
  )
}

describe('OmzetBronnenBlok — Beheerder-UI omzetbronnen (besluiten Peter 16-09 blok B)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('rendert lege stores als actie-tekst, de defaults als voorgevulde comboboxen mét chip "standaard (op naam)" en de vaste combi-regel', async () => {
    installFetchMock({})
    render(<OmzetBronnenBlok administratieId={ADMINISTRATIE_ID} naam="Zonnestudio Elderveld B.V." />)
    const blok = await screen.findByTestId('omzetbronnen-blok')
    expect(within(blok).getByTestId('stores-leeg').textContent).toContain('Nog geen store gekoppeld — voeg de naam toe zoals hij in de dagstaat staat')
    // Tegenrekeningen: PIN voorgevuld uit defaults (combobox toont code · naam) mét default-chip; storting zonder default = "geen standaard".
    const tegen = within(blok).getByLabelText('Tegenrekeningen per betaalwijze')
    expect(within(tegen).getByLabelText('Tegenrekening PIN')).toHaveValue('1020 · Kruisposten PIN')
    expect(within(tegen).getAllByText('standaard (op naam)')).toHaveLength(4)
    expect(within(tegen).getByText('geen standaard')).toBeInTheDocument()
    // Btw per categorie uit defaults: Pilateslessen 9 %, chip "standaard (RLZ-tarief)".
    const btw = within(blok).getByLabelText('Btw-tarief per categorie')
    expect(within(btw).getByLabelText('Btw-tarief pilateslessen')).toHaveValue('9% · NL, Laag Tarief')
    expect(within(btw).getAllByText('standaard (RLZ-tarief)')).toHaveLength(3)
    // psp komt als 'stripe' (= code-default) terug → chip "standaard", niet "gekozen"; herkomst-tekst uit defaults.
    expect(within(blok).getByText('Stripe · EU-dienst verlegd')).toBeInTheDocument()
    // Combi-regel vast, PSP default Stripe, Opslaan pas actief ná een wijziging.
    expect(within(blok).getByTestId('combi-regel').textContent).toContain('pro rato binnen de batch')
    expect(within(blok).getByLabelText('Betaalprovider voor Zonnestudio Elderveld B.V.')).toHaveValue('stripe')
    expect(within(blok).getByRole('button', { name: 'Opslaan' })).toBeDisabled()
  })

  it('store toevoegen → PUT-body draagt de stores en de nog-lege instelbare sleutels (defaults blijven bij de code)', async () => {
    const putAanroepen: Record<string, unknown>[] = []
    installFetchMock({ stand: { stores: ['Elderveld'] }, putAanroepen })
    render(<OmzetBronnenBlok administratieId={ADMINISTRATIE_ID} naam="Zonnestudio" />)
    await screen.findByTestId('omzetbronnen-blok')
    await userEvent.type(screen.getByLabelText('Naam nieuwe store'), 'Sunshine Island')
    await userEvent.click(screen.getByRole('button', { name: '+ Store toevoegen' }))
    expect(screen.getByText('Sunshine Island')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Opslaan' }))
    await waitFor(() => expect(putAanroepen).toHaveLength(1))
    const body = putAanroepen[0]
    expect(body.stores).toEqual(['Elderveld', 'Sunshine Island'])
    expect(body.tegenrekeningen).toEqual({ pin: null, cash: null, stripe: null, kasverschil: null, storting: null })
    expect(body.categorie_btw).toEqual({})
    expect(body.psp).toBe('stripe')
    expect(body.combi_regel).toBe('pro_rato_batch')
    expect(body).not.toHaveProperty('defaults')
    expect(body).not.toHaveProperty('rekeningen')
    expect(await screen.findByText('opgeslagen')).toBeInTheDocument()
  })

  it('tarief kiezen voor een categorie → PUT-body `categorie_btw` mét taxrate_id; chip wordt "gekozen"', async () => {
    const putAanroepen: Record<string, unknown>[] = []
    installFetchMock({ putAanroepen })
    render(<OmzetBronnenBlok administratieId={ADMINISTRATIE_ID} naam="Pilates" />)
    const blok = await screen.findByTestId('omzetbronnen-blok')
    const btw = within(blok).getByLabelText('Btw-tarief per categorie')
    const input = within(btw).getByLabelText('Btw-tarief kleding producten')
    await userEvent.click(input)
    await userEvent.clear(input)
    await userEvent.type(input, 'Laag')
    await userEvent.click(await screen.findByRole('option', { name: /Laag Tarief/ }))
    const rij = input.closest('tr')!
    expect(within(rij).getByText('gekozen')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Opslaan' }))
    await waitFor(() => expect(putAanroepen).toHaveLength(1))
    // Sleutel = genormaliseerde categorie (backend `normaliseer_categorie_sleutel`), nooit de leesbare naam.
    expect((putAanroepen[0].categorie_btw as Record<string, string>)['kleding producten']).toBe('btw-laag')
  })

  it('422 uit de PUT staat zichtbaar bij het veld (tegenrekeningen) en de wijziging blijft staan', async () => {
    installFetchMock({ putStatus: 422 })
    render(<OmzetBronnenBlok administratieId={ADMINISTRATIE_ID} naam="Zonnestudio" />)
    const blok = await screen.findByTestId('omzetbronnen-blok')
    const tegen = within(blok).getByLabelText('Tegenrekeningen per betaalwijze')
    const input = within(tegen).getByLabelText('Tegenrekening Storting automaat')
    await userEvent.click(input)
    await userEvent.type(input, 'Kas')
    await userEvent.click(await screen.findByRole('option', { name: /^1010/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Opslaan' }))
    const fout = await screen.findByRole('alert')
    expect(fout.textContent).toContain('Onbekende rekening in tegenrekeningen')
    // Bij het veld: de fout staat direct ná de tegenrekeningen-tabel, vóór de categorie-kop.
    expect(fout.compareDocumentPosition(tegen) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy()
    expect(within(blok).getByText('niet opgeslagen wijzigingen')).toBeInTheDocument()
  })
})
