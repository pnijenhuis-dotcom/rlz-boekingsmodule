import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../ui/basis'
import { BankDetailScreen } from './BankDetailScreen'
import { parseBedragCenten } from './Splitsen'

/* Deel 4 (25-08): de tweede en derde verwerkroute per mutatie — "Koppel aan relatie…" en
 * "Splitsen…" — plus de panelen "Openstaande aanbetalingen op relaties" en "Gesplitste mutaties". */

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const REKENING_ID = 'cccccccc-0000-0000-0000-000000000003'
const MUTATIE_ID = 'dddddddd-0000-0000-0000-000000000004'
const ITEM_ID = 'eeeeeeee-0000-0000-0000-000000000005'
const CREDITEUR_ID = '11111111-0000-0000-0000-000000000011'
const LEDGER_ID = '22222222-0000-0000-0000-000000000022'
const BOEKING_ID = '33333333-0000-0000-0000-000000000033'
const SPLITSING_ID = '44444444-0000-0000-0000-000000000044'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const rekening = {
  id: REKENING_ID,
  naam: 'ING zakelijk',
  iban: 'NL91 INGB 0002 4455 88',
  rekening_type: 1,
  is_kas: false,
  saldo: '48212.90',
  saldo_datum: '2026-07-31',
  open_mutaties: 1,
  heeft_aanlevering: true,
  laatste_import: null,
  probe_fout: null,
}

function handmatigeMutatie(overrides: Record<string, unknown> = {}) {
  return {
    id: MUTATIE_ID,
    boekdatum: '2026-08-20',
    bedrag: '-1000.00',
    open_bedrag: '-1000.00',
    tegenpartij_naam: 'Bouwmaat Nederland B.V.',
    omschrijving: 'aanbetaling order 8812',
    tegenrekening_iban: 'NL00BANK0123456789',
    voorstel: {
      soort: 'handmatig',
      kleur: 'oranje',
      bron: 'handmatig',
      reden: 'Geen regel en geen open-post-match',
      payment_item_id: null,
      open_post: null,
      regel_id: null,
      regels: [],
    },
    afletter_opdracht: null,
    regel_voorstel: null,
    ...overrides,
  }
}

function deelMatchMutatie() {
  return handmatigeMutatie({
    voorstel: {
      soort: 'deel_match',
      kleur: 'oranje',
      bron: 'gedeeltelijke match',
      reden: 'Referentie gevonden, bedrag afwijkend',
      payment_item_id: ITEM_ID,
      open_post: { id: ITEM_ID, bedrag: '800.00', referentie: '2026-0642', referentie2: null, rlz_document_id: null },
      regel_id: null,
      regels: [],
    },
  })
}

function splitsing(overrides: Record<string, unknown> = {}) {
  return {
    splitsing_id: SPLITSING_ID,
    payment_transaction_id: MUTATIE_ID,
    status: 'verwerkt',
    mutatie_bedrag: '-1000.00',
    aangemaakt_op: '2026-08-25T09:00:00Z',
    delen: [
      {
        deel_id: '55555555-0000-0000-0000-000000000055',
        volgnummer: 1,
        soort: 'grootboek',
        bedrag: '-600.00',
        status: 'verwerkt',
        fout: null,
        bank_boeking_id: BOEKING_ID,
        afletter_opdracht_id: null,
        relatie_boeking_id: null,
      },
      {
        deel_id: '66666666-0000-0000-0000-000000000066',
        volgnummer: 2,
        soort: 'grootboek',
        bedrag: '-400.00',
        status: 'verwerkt',
        fout: null,
        bank_boeking_id: BOEKING_ID,
        afletter_opdracht_id: null,
        relatie_boeking_id: null,
      },
    ],
    ...overrides,
  }
}

interface MockOpties {
  mutaties?: unknown[]
  koppelAanroepen?: { url: string; body: unknown }[]
  koppelResponse?: { status: number; body: unknown }
  splitsAanroepen?: { url: string; body: unknown }[]
  splitsResponse?: { status: number; body: unknown }
  hervatAanroepen?: string[]
  aanbetalingen?: unknown[]
  stornoAanroepen?: { url: string; body: unknown }[]
  splitsingen?: unknown[]
}

function installFetchMock(opties: MockOpties = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      const body = init?.body ? (JSON.parse(String(init.body)) as unknown) : null
      if (url.endsWith('/auth/administraties')) {
        return Promise.resolve(jsonResponse({ administraties: [{ id: ADMINISTRATIE_ID, naam: 'Kempen Groep B.V.' }] }))
      }
      if (url.endsWith('/bank/rekeningen')) {
        return Promise.resolve(
          jsonResponse({
            rekeningen: [rekening],
            laatste_sync_op: '2026-08-02T06:00:00Z',
            ooit_gesynchroniseerd: true,
            heeft_bankaanlevering: true,
          }),
        )
      }
      if (url.endsWith('/bank/sync-achtergrond') && method === 'POST') {
        return Promise.resolve(
          jsonResponse(
            { run_id: null, status: 'overgeslagen', overgeslagen: true, laatste_sync_op: null, resultaat: null, fout_reden: null },
            202,
          ),
        )
      }
      if (url.includes('/koppel-relatie') && method === 'POST') {
        opties.koppelAanroepen?.push({ url, body })
        const r = opties.koppelResponse ?? {
          status: 201,
          body: { boeking_id: BOEKING_ID, rlz_document_id: 'x', rlz_boekstuknummer: 'RLZ-07-00000042', open_restant: '0.00' },
        }
        return Promise.resolve(jsonResponse(r.body, r.status))
      }
      if (url.includes('/splitsen') && method === 'POST') {
        opties.splitsAanroepen?.push({ url, body })
        const r = opties.splitsResponse ?? { status: 201, body: splitsing() }
        return Promise.resolve(jsonResponse(r.body, r.status))
      }
      if (url.includes('/hervat') && method === 'POST') {
        opties.hervatAanroepen?.push(url)
        return Promise.resolve(jsonResponse(splitsing()))
      }
      if (url.includes('/aanbetalingen/') && url.endsWith('/storno') && method === 'POST') {
        opties.stornoAanroepen?.push({ url, body })
        return Promise.resolve(new Response(null, { status: 204 }))
      }
      if (url.includes('/mutaties') && method === 'GET') {
        return Promise.resolve(jsonResponse({ mutaties: opties.mutaties ?? [handmatigeMutatie()] }))
      }
      if (url.includes('/afletter-opdrachten')) return Promise.resolve(jsonResponse({ opdrachten: [] }))
      if (url.endsWith('/bank/aanbetalingen')) {
        return Promise.resolve(jsonResponse({ aanbetalingen: opties.aanbetalingen ?? [] }))
      }
      if (url.endsWith('/splitsingen')) return Promise.resolve(jsonResponse({ splitsingen: opties.splitsingen ?? [] }))
      if (url.endsWith('/crediteuren')) {
        return Promise.resolve(jsonResponse({ crediteuren: [{ id: CREDITEUR_ID, naam: 'Bouwmaat Nederland B.V.' }] }))
      }
      if (url.includes('/grootboek')) {
        return Promise.resolve(
          jsonResponse({ rekeningen: [{ ledger_id: LEDGER_ID, code: '2100', naam: 'Kruisposten' }] }),
        )
      }
      if (url.includes('/btw-codes')) return Promise.resolve(jsonResponse({ btw_codes: [] }))
      if (url.includes('/bank/debiteuren')) return Promise.resolve(jsonResponse({ debiteuren: [] }))
      return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
    }),
  )
}

function renderScherm() {
  return render(
    <ToastProvider>
    <MemoryRouter initialEntries={[`/bank/${ADMINISTRATIE_ID}`]}>
      <Routes>
        <Route path="/bank/:administratieId" element={<BankDetailScreen />} />
      </Routes>
    </MemoryRouter>
    </ToastProvider>,
  )
}

/** Kiest een optie in een SearchableCombobox (opent, typt, kiest de eerste match). */
async function kiesCombobox(label: RegExp, zoek: string, optieTekst: RegExp) {
  const input = screen.getByRole('combobox', { name: label })
  await userEvent.click(input)
  await userEvent.type(input, zoek)
  const optie = await screen.findByRole('option', { name: optieTekst })
  await userEvent.click(optie)
}

describe('Koppel aan relatie', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('opent het formulier, koppelt aan een crediteur met de juiste body en meldt het boekstuknummer', async () => {
    const koppelAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ koppelAanroepen })
    renderScherm()

    await userEvent.click(await screen.findByRole('button', { name: 'Koppel aan relatie…' }))
    const form = screen.getByTestId('koppel-relatie-form')
    expect(within(form).getByRole('radio', { name: 'Crediteur' })).toBeChecked()
    expect(within(form).getByText(/vooruitbetalingsrekening 1403\/1806/)).toBeInTheDocument()
    // Zonder relatie kan er niet gekoppeld worden.
    expect(within(form).getByRole('button', { name: 'Koppel aan relatie ✓' })).toBeDisabled()

    await kiesCombobox(/Crediteur/, 'Bouw', /Bouwmaat Nederland/)
    await userEvent.click(within(form).getByRole('button', { name: 'Koppel aan relatie ✓' }))

    await waitFor(() => expect(koppelAanroepen).toHaveLength(1))
    expect(koppelAanroepen[0].url).toContain(`/bank/mutaties/${MUTATIE_ID}/koppel-relatie`)
    expect(koppelAanroepen[0].body).toEqual({
      relatie_soort: 'crediteur',
      entity_id: CREDITEUR_ID,
      omschrijving: 'aanbetaling order 8812',
    })
    expect(await screen.findByText(/aanbetalingsdocument RLZ-07-00000042 geboekt en de mutatie afgeletterd/)).toBeInTheDocument()
  })

  it('toont de 409-detailtekst in de rij (nooit stil)', async () => {
    installFetchMock({
      koppelResponse: { status: 409, body: { detail: 'Vooruitbetalingsrekening crediteuren (1403) is niet ingesteld' } },
    })
    renderScherm()

    await userEvent.click(await screen.findByRole('button', { name: 'Koppel aan relatie…' }))
    await kiesCombobox(/Crediteur/, 'Bouw', /Bouwmaat Nederland/)
    await userEvent.click(screen.getByRole('button', { name: 'Koppel aan relatie ✓' }))

    expect(await screen.findByText('Vooruitbetalingsrekening crediteuren (1403) is niet ingesteld')).toBeInTheDocument()
    // Het formulier blijft open zodat de mens kan corrigeren.
    expect(screen.getByTestId('koppel-relatie-form')).toBeInTheDocument()
  })

  it('wisselt naar debiteur en toont het live zoekveld (min. 2 tekens)', async () => {
    installFetchMock()
    renderScherm()

    await userEvent.click(await screen.findByRole('button', { name: 'Koppel aan relatie…' }))
    await userEvent.click(screen.getByRole('radio', { name: 'Debiteur' }))
    expect(screen.getByPlaceholderText(/Zoek debiteur op naam/)).toBeInTheDocument()
  })
})

describe('Splitsen', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('parseert bedraginvoer in centen (NL en toetsenbord-notatie, absoluut)', () => {
    expect(parseBedragCenten('1.234,56')).toBe(123456)
    expect(parseBedragCenten('1234.56')).toBe(123456)
    expect(parseBedragCenten('-600')).toBe(60000)
    expect(parseBedragCenten('€ 12,5')).toBe(1250)
    expect(parseBedragCenten('')).toBeNull()
    expect(parseBedragCenten('abc')).toBeNull()
  })

  it('rest-teller loopt live mee, versturen pas bij rest 0 en complete bestemmingen; body draagt de getekende bedragen', async () => {
    const splitsAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ splitsAanroepen })
    renderScherm()

    await userEvent.click(await screen.findByRole('button', { name: 'Splitsen…' }))
    const form = screen.getByTestId('splitsen-form')
    const rest = within(form).getByTestId('splits-rest')
    const verstuur = within(form).getByRole('button', { name: /Splitsen en verwerken/ })

    expect(rest).toHaveTextContent('Rest: € -1.000,00')
    expect(verstuur).toBeDisabled()

    await userEvent.type(within(form).getByLabelText('Bedrag deel 1'), '600')
    expect(rest).toHaveTextContent('Rest: € -400,00')
    expect(verstuur).toBeDisabled()

    await userEvent.type(within(form).getByLabelText('Bedrag deel 2'), '400')
    expect(rest).toHaveTextContent('Rest: € 0,00 — klopt')
    // Rest klopt, maar de grootboekbestemmingen ontbreken nog.
    expect(verstuur).toBeDisabled()

    await kiesCombobox(/Grootboekrekening deel 1/, '2100', /Kruisposten/)
    expect(verstuur).toBeDisabled()
    await kiesCombobox(/Grootboekrekening deel 2/, '2100', /Kruisposten/)
    expect(verstuur).toBeEnabled()

    await userEvent.click(verstuur)
    await waitFor(() => expect(splitsAanroepen).toHaveLength(1))
    expect(splitsAanroepen[0].url).toContain(`/bank/mutaties/${MUTATIE_ID}/splitsen`)
    const body = splitsAanroepen[0].body as { delen: Record<string, unknown>[] }
    expect(body.delen).toHaveLength(2)
    expect(body.delen[0]).toMatchObject({ soort: 'grootboek', bedrag: '-600.00' })
    expect(body.delen[1]).toMatchObject({ soort: 'grootboek', bedrag: '-400.00' })
    expect((body.delen[0].regels as Record<string, unknown>[])[0]).toMatchObject({
      ledger_id: LEDGER_ID,
      netto_bedrag: '-600.00',
      btw_bedrag: null,
    })

    // Resultaat zichtbaar: volledig verwerkt, per deel een chip.
    const resultaat = await screen.findByTestId('splits-resultaat')
    expect(within(resultaat).getByText('volledig verwerkt')).toBeInTheDocument()
    expect(within(resultaat).getAllByText('verwerkt')).toHaveLength(2)
  })

  it('biedt bij een deelmatch de bekende open post als bestemming, voorgevuld als eerste deel', async () => {
    const splitsAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ splitsAanroepen, mutaties: [deelMatchMutatie()] })
    renderScherm()

    await userEvent.click(await screen.findByRole('button', { name: 'Splitsen…' }))
    const form = screen.getByTestId('splitsen-form')
    expect(within(form).getByLabelText('Bedrag deel 1')).toHaveValue('800.00')
    expect(within(form).getByLabelText('Bestemming deel 1')).toHaveValue('open_post')
    // E9: dezelfde voorstel-kaart als in de mutatielijst, compact (zonder chip).
    expect(within(form).getByTestId('voorstel-kaart')).toHaveClass('vk-compact')
    expect(within(form).getByText(/De enige open post die de matchmotor/)).toBeInTheDocument()
    expect(within(form).getByTestId('splits-rest')).toHaveTextContent('Rest: € -200,00')

    await userEvent.type(within(form).getByLabelText('Bedrag deel 2'), '200')
    await kiesCombobox(/Grootboekrekening deel 2/, '2100', /Kruisposten/)
    await userEvent.click(within(form).getByRole('button', { name: /Splitsen en verwerken/ }))

    await waitFor(() => expect(splitsAanroepen).toHaveLength(1))
    const body = splitsAanroepen[0].body as { delen: Record<string, unknown>[] }
    expect(body.delen[0]).toMatchObject({ soort: 'open_post', bedrag: '-800.00', payment_item_id: ITEM_ID })
    expect(body.delen[1]).toMatchObject({ soort: 'grootboek', bedrag: '-200.00' })
  })

  it('zonder bekende open post is de open-post-bestemming niet kiesbaar', async () => {
    installFetchMock()
    renderScherm()
    await userEvent.click(await screen.findByRole('button', { name: 'Splitsen…' }))
    const select = screen.getByLabelText('Bestemming deel 1')
    const optie = within(select).getByRole('option', { name: /Open post/ })
    expect(optie).toBeDisabled()
  })

  it('toont de 422-detailtekst van de server', async () => {
    installFetchMock({
      splitsResponse: { status: 422, body: { detail: 'De delen tellen op tot -999.99, de mutatie is -1000.00' } },
    })
    renderScherm()

    await userEvent.click(await screen.findByRole('button', { name: 'Splitsen…' }))
    const form = screen.getByTestId('splitsen-form')
    await userEvent.type(within(form).getByLabelText('Bedrag deel 1'), '600')
    await userEvent.type(within(form).getByLabelText('Bedrag deel 2'), '400')
    await kiesCombobox(/Grootboekrekening deel 1/, '2100', /Kruisposten/)
    await kiesCombobox(/Grootboekrekening deel 2/, '2100', /Kruisposten/)
    await userEvent.click(within(form).getByRole('button', { name: /Splitsen en verwerken/ }))

    expect(await screen.findByText('De delen tellen op tot -999.99, de mutatie is -1000.00')).toBeInTheDocument()
  })

  it('half_verwerkt toont per deel de fout en een "Hervatten"-knop die het hervat-endpoint aanroept', async () => {
    const hervatAanroepen: string[] = []
    installFetchMock({
      hervatAanroepen,
      splitsResponse: {
        status: 201,
        body: splitsing({
          status: 'half_verwerkt',
          delen: [
            { ...splitsing().delen[0] },
            { ...splitsing().delen[1], status: 'fout', fout: 'RLZ gaf 400 _InvalidData op de tweede regel', bank_boeking_id: null },
          ],
        }),
      },
    })
    renderScherm()

    await userEvent.click(await screen.findByRole('button', { name: 'Splitsen…' }))
    const form = screen.getByTestId('splitsen-form')
    await userEvent.type(within(form).getByLabelText('Bedrag deel 1'), '600')
    await userEvent.type(within(form).getByLabelText('Bedrag deel 2'), '400')
    await kiesCombobox(/Grootboekrekening deel 1/, '2100', /Kruisposten/)
    await kiesCombobox(/Grootboekrekening deel 2/, '2100', /Kruisposten/)
    await userEvent.click(within(form).getByRole('button', { name: /Splitsen en verwerken/ }))

    const resultaat = await screen.findByTestId('splits-resultaat')
    expect(within(resultaat).getByText('half verwerkt — hervatten')).toBeInTheDocument()
    expect(within(resultaat).getByText('RLZ gaf 400 _InvalidData op de tweede regel')).toBeInTheDocument()
    expect(within(resultaat).getByText('fout')).toBeInTheDocument()

    await userEvent.click(within(resultaat).getByRole('button', { name: 'Hervatten' }))
    await waitFor(() => expect(hervatAanroepen).toHaveLength(1))
    expect(hervatAanroepen[0]).toContain(`/bank/splitsingen/${SPLITSING_ID}/hervat`)
    expect(await within(resultaat).findByText('volledig verwerkt')).toBeInTheDocument()
  })

  it('paneel "Gesplitste mutaties" toont bestaande splitsingen per rekening', async () => {
    installFetchMock({ mutaties: [], splitsingen: [splitsing()] })
    renderScherm()

    expect(await screen.findByText('Gesplitste mutaties')).toBeInTheDocument()
    expect(screen.getByText('volledig verwerkt')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Storno deel…' })).toHaveLength(2)
  })
})

describe('Openstaande aanbetalingen op relaties', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('is verborgen zonder aanbetalingen', async () => {
    installFetchMock({ mutaties: [] })
    renderScherm()
    expect(await screen.findByText('Geen onverwerkte mutaties op deze rekening.')).toBeInTheDocument()
    expect(screen.queryByText('Openstaande aanbetalingen op relaties')).not.toBeInTheDocument()
  })

  it('toont de rijen en storneert met verplichte reden', async () => {
    const stornoAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({
      mutaties: [],
      stornoAanroepen,
      aanbetalingen: [
        {
          boeking_id: BOEKING_ID,
          payment_transaction_id: MUTATIE_ID,
          relatie_soort: 'crediteur',
          entity_id: CREDITEUR_ID,
          entity_naam: 'Bouwmaat Nederland B.V.',
          bedrag: '-1000.00',
          boekdatum: '2026-08-20',
          rlz_boekstuknummer: 'RLZ-07-00000042',
          geboekt_op: '2026-08-25T09:00:00Z',
          status: 'geboekt',
        },
      ],
    })
    renderScherm()

    expect(await screen.findByText('Openstaande aanbetalingen op relaties')).toBeInTheDocument()
    expect(screen.getByText('RLZ-07-00000042')).toBeInTheDocument()
    expect(screen.getByText(/Bouwmaat Nederland B.V./)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Storno…' }))
    const bevestig = screen.getByRole('button', { name: 'Storno bevestigen' })
    expect(bevestig).toBeDisabled()
    await userEvent.type(screen.getByLabelText(/Reden storno/), 'verkeerde relatie gekozen')
    await userEvent.click(bevestig)

    await waitFor(() => expect(stornoAanroepen).toHaveLength(1))
    expect(stornoAanroepen[0].url).toContain(`/bank/aanbetalingen/${BOEKING_ID}/storno`)
    expect(stornoAanroepen[0].body).toEqual({ reden: 'verkeerde relatie gekozen' })
    expect(await screen.findByText(/Aanbetaling gestorneerd/)).toBeInTheDocument()
  })
})
