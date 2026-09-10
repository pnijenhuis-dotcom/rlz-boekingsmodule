// Blok 3 nachtrun 10/11-09 — deels afgeletterde bankmutaties (bug Peter 10-09 avond, Zilver Beheer): mutatie A 01-07
// +5.023,09 is in RLZ al voor € 2.512,04 gekoppeld aan verkoopfactuur 2024840 (RLZ-01-00000800), nog open 2.511,05;
// mutatie B 08-09 −2.511,05 "retour dubbele betaling" van dezelfde tegenpartij. Het scherm toont het open bedrag, boekt
// en splitst op het open bedrag, en toont de 409 van de backend letterlijk.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../ui/basis'
import { BankDetailScreen } from './BankDetailScreen'
import { isDeelsAfgeletterd, openBedrag, type MutatieDto } from './bankApi'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-4000-8000-000000000001'
const REKENING_ID = 'cccccccc-0000-4000-8000-000000000003'
const MUTATIE_A = 'cccccccc-0000-4000-8000-000000000a01'
const MUTATIE_B = 'cccccccc-0000-4000-8000-000000000b01'
const LEDGER_ID = '22222222-0000-0000-0000-000000000022'
const ITEM_ID = 'dddddddd-0000-4000-8000-000000002024'

const BEDRAG_DEKT_NIET =
  'Bedrag dekt niet het open bedrag van de mutatie: geboekt 5023.09, open 2511.05 (in Reeleezee is 2512.04 al afgeletterd).'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const rekening = {
  id: REKENING_ID,
  naam: 'Rabobank zakelijk',
  iban: 'NL39 RABO 0300 0652 64',
  rekening_type: 1,
  is_kas: false,
  saldo: '18211.44',
  saldo_datum: '2026-09-08',
  open_mutaties: 2,
  heeft_aanlevering: true,
  laatste_import: { datum: '2026-09-08', bron: '1', type: 'MT940', bestandsnaam: 'x.940' },
  probe_fout: null,
}

const KOPPELING = {
  document_id: 'eeeeeeee-0000-4000-8000-000000000800',
  boekstuknummer: 'RLZ-01-00000800',
  referentie: '2024840',
  bedrag: '2512.04',
  document_type: 2,
  omschrijving: 'Verkoopfactuur 2024840',
}

/** Mutatie A: deels afgeletterd (contract-velden gevuld). */
function mutatieA(overrides: Partial<MutatieDto> = {}): MutatieDto {
  return {
    id: MUTATIE_A,
    boekdatum: '2026-07-01',
    bedrag: '5023.09',
    open_bedrag: '2511.05',
    tegenpartij_naam: 'Zilver Beheer B.V.',
    omschrijving: 'Factuur 2024840 en 2024841',
    tegenrekening_iban: 'NL02ABNA0123456789',
    voorstel: {
      soort: 'handmatig',
      kleur: 'oranje',
      bron: 'geen open post of regel',
      reden: 'Geen open post of regel gevonden — handmatig beoordelen.',
      payment_item_id: null,
      open_post: null,
      regel_id: null,
      regels: [],
    },
    afletter_opdracht: null,
    regel_voorstel: null,
    deels_afgeletterd: true,
    rlz_koppelingen: [KOPPELING],
    ...overrides,
  }
}

/** Mutatie B: retour dubbele betaling, gewoon volledig open (handmatig). */
function mutatieB(): MutatieDto {
  return {
    ...mutatieA(),
    id: MUTATIE_B,
    boekdatum: '2026-09-08',
    bedrag: '-2511.05',
    open_bedrag: '-2511.05',
    omschrijving: 'retour dubbele betaling',
    deels_afgeletterd: false,
    rlz_koppelingen: [],
  }
}

interface MockOpties {
  mutaties?: unknown[]
  boekenAanroepen?: { url: string; body: unknown }[]
  boekenResponse?: { status: number; body: unknown }
  splitsAanroepen?: { url: string; body: unknown }[]
}

function installFetchMock(opties: MockOpties = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      const body = init?.body ? (JSON.parse(String(init.body)) as unknown) : null
      if (url.endsWith('/auth/administraties')) {
        return Promise.resolve(jsonResponse({ administraties: [{ id: ADMINISTRATIE_ID, naam: 'Zilver Beheer B.V.' }] }))
      }
      if (url.endsWith('/bank/rekeningen')) {
        return Promise.resolve(
          jsonResponse({ rekeningen: [rekening], laatste_sync_op: '2026-09-10T06:00:00Z', ooit_gesynchroniseerd: true, heeft_bankaanlevering: true }),
        )
      }
      if (url.endsWith('/bank/sync-achtergrond') && method === 'POST') {
        return Promise.resolve(
          jsonResponse({ run_id: null, status: 'overgeslagen', overgeslagen: true, laatste_sync_op: null, resultaat: null, fout_reden: null }, 202),
        )
      }
      if (url.includes('/direct-boeken') && method === 'POST') {
        opties.boekenAanroepen?.push({ url, body })
        const r = opties.boekenResponse ?? {
          status: 201,
          body: { boeking_id: 'x', rlz_boekstuknummer: 'RLZ-07-00000001', al_eerder_geboekt: false, vaste_regel_aangemaakt: false },
        }
        return Promise.resolve(jsonResponse(r.body, r.status))
      }
      if (url.includes('/splitsen') && method === 'POST') {
        opties.splitsAanroepen?.push({ url, body })
        return Promise.resolve(
          jsonResponse({ splitsing_id: 's1', payment_transaction_id: MUTATIE_A, status: 'verwerkt', mutatie_bedrag: '2511.05', aangemaakt_op: null, delen: [] }, 201),
        )
      }
      if (url.includes('/mutaties') && method === 'GET') {
        return Promise.resolve(jsonResponse({ mutaties: opties.mutaties ?? [mutatieA(), mutatieB()] }))
      }
      if (url.includes('/afletter-opdrachten')) return Promise.resolve(jsonResponse({ opdrachten: [], aantal_oud: 0, toon_oud: false, oud_na_dagen: 30 }))
      if (url.endsWith('/bank/aanbetalingen')) return Promise.resolve(jsonResponse({ aanbetalingen: [] }))
      if (url.endsWith('/splitsingen')) return Promise.resolve(jsonResponse({ splitsingen: [] }))
      if (url.endsWith('/crediteuren')) return Promise.resolve(jsonResponse({ crediteuren: [] }))
      if (url.includes('/grootboek')) {
        return Promise.resolve(jsonResponse({ rekeningen: [{ ledger_id: LEDGER_ID, code: '1300', naam: 'Debiteuren' }] }))
      }
      if (url.includes('/btw-codes')) return Promise.resolve(jsonResponse({ btw_codes: [] }))
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

async function kiesCombobox(label: RegExp, zoek: string, optieTekst: RegExp) {
  const input = screen.getByRole('combobox', { name: label })
  await userEvent.click(input)
  await userEvent.type(input, zoek)
  await userEvent.click(await screen.findByRole('option', { name: optieTekst }))
}

/** Rij van mutatie A (de eerste rij) — de acties zitten in de laatste cel. */
async function rijA(): Promise<HTMLElement> {
  const cel = await screen.findByText('Factuur 2024840 en 2024841')
  return cel.closest('tr') as HTMLElement
}

describe('openBedrag / isDeelsAfgeletterd (één bron, cent-exact)', () => {
  it('open bedrag = open_bedrag, terugval bedrag; deels = contractveld, anders afgeleid uit de bedragen', () => {
    expect(openBedrag({ bedrag: '5023.09', open_bedrag: '2511.05' })).toBe('2511.05')
    expect(openBedrag({ bedrag: '5023.09', open_bedrag: null })).toBe('5023.09')
    expect(openBedrag({ bedrag: null, open_bedrag: null })).toBeNull()
    // Contractveld wint (ook als het afwijkt van de afleiding — de backend is de bron).
    expect(isDeelsAfgeletterd({ bedrag: '5023.09', open_bedrag: '2511.05', deels_afgeletterd: true })).toBe(true)
    expect(isDeelsAfgeletterd({ bedrag: '5023.09', open_bedrag: '5023.09', deels_afgeletterd: false })).toBe(false)
    // Oudere mock zonder veld: afleiding open ≠ bedrag én ≠ 0.
    expect(isDeelsAfgeletterd({ bedrag: '5023.09', open_bedrag: '2511.05' })).toBe(true)
    expect(isDeelsAfgeletterd({ bedrag: '-2511.05', open_bedrag: '-2511.05' })).toBe(false)
    expect(isDeelsAfgeletterd({ bedrag: '100.00', open_bedrag: '0.00' })).toBe(false)
    expect(isDeelsAfgeletterd({ bedrag: '100.00', open_bedrag: null })).toBe(false)
  })
})

describe('Deels afgeletterde mutatie in de lijst (3.1)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('toont "€ 5.023,09" + "open € 2.511,05" + chip "deels afgeletterd in RLZ" mét de koppeling als tooltip en regel; B blijft gewoon', async () => {
    installFetchMock()
    renderScherm()
    const rij = await rijA()
    const bedragCel = within(rij).getByTestId('mutatie-bedrag')
    expect(bedragCel).toHaveTextContent('€ 5.023,09')
    expect(within(rij).getByTestId('mutatie-open-bedrag')).toHaveTextContent('open € 2.511,05')
    const chip = within(rij).getByTestId('chip-deels-afgeletterd')
    expect(chip).toHaveTextContent('deels afgeletterd in RLZ')
    expect(chip).toHaveClass('chip')
    // toLocaleString zet een harde spatie ná het €-teken — de title vergelijken we daarom whitespace-tolerant.
    const title = (chip.getAttribute('title') ?? '').replace(/\s/g, ' ')
    expect(title).toContain('nog open € 2.511,05 van € 5.023,09')
    expect(title).toContain('RLZ-01-00000800 · factuur 2024840 · € 2.512,04')
    expect(within(rij).getByTestId('deels-afgeletterd-koppelingen')).toHaveTextContent(
      'gekoppeld: RLZ-01-00000800 · factuur 2024840 · € 2.512,04',
    )
    // Mutatie B (volledig open): geen chip, geen open-regel.
    const rijB = (await screen.findByText('retour dubbele betaling')).closest('tr') as HTMLElement
    expect(within(rijB).getByTestId('mutatie-bedrag')).toHaveTextContent('€ -2.511,05')
    expect(within(rijB).queryByTestId('chip-deels-afgeletterd')).toBeNull()
    expect(within(rijB).queryByTestId('mutatie-open-bedrag')).toBeNull()
  })

  it('zonder rlz_koppelingen (sync kent ze nog niet) alleen de bedragen — chip blijft, geen koppelingsregel', async () => {
    installFetchMock({ mutaties: [mutatieA({ rlz_koppelingen: [] })] })
    renderScherm()
    const rij = await rijA()
    const chip = within(rij).getByTestId('chip-deels-afgeletterd')
    expect(chip.getAttribute('title')).toContain('weet de sync (nog) niet')
    expect(within(rij).queryByTestId('deels-afgeletterd-koppelingen')).toBeNull()
    expect(within(rij).getByTestId('mutatie-open-bedrag')).toHaveTextContent('open € 2.511,05')
  })

  it('oudere DTO zonder de nieuwe velden: de chip volgt de bedragen (open ≠ bedrag) — niets breekt', async () => {
    const zonderVelden = { ...mutatieA() } as Record<string, unknown>
    delete zonderVelden.deels_afgeletterd
    delete zonderVelden.rlz_koppelingen
    installFetchMock({ mutaties: [zonderVelden] })
    renderScherm()
    const rij = await rijA()
    expect(within(rij).getByTestId('chip-deels-afgeletterd')).toBeInTheDocument()
    expect(within(rij).getByTestId('mutatie-open-bedrag')).toHaveTextContent('open € 2.511,05')
  })
})

describe('Handmatig boeken op het open bedrag (3.2 frontend)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('formulier zegt "Te boeken: € 2.511,05" en stuurt netto 2511.05 (niet 5023.09)', async () => {
    const boekenAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ boekenAanroepen })
    renderScherm()
    const rij = await rijA()
    await userEvent.click(within(rij).getByRole('button', { name: 'Boeken…' }))
    const form = within(rij).getByTestId('handmatig-boeken-form')
    expect(within(form).getByTestId('handmatig-te-boeken')).toHaveTextContent('Te boeken: € 2.511,05')
    expect(within(form).getByTestId('handmatig-te-boeken')).toHaveTextContent('van de mutatie (€ 5.023,09) is de rest in Reeleezee al afgeletterd')
    await kiesCombobox(/Grootboekrekening/, '1300', /Debiteuren/)
    await userEvent.click(within(form).getByRole('button', { name: /Boeken in RLZ/ }))
    await waitFor(() => expect(boekenAanroepen).toHaveLength(1))
    const body = boekenAanroepen[0].body as { regels: { netto_bedrag: string; btw_bedrag: string | null }[] }
    expect(body.regels[0]).toMatchObject({ netto_bedrag: '2511.05', btw_bedrag: null })
  })

  it('volledig open mutatie: te boeken = het volledige mutatiebedrag (ongewijzigd gedrag)', async () => {
    const boekenAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ boekenAanroepen, mutaties: [mutatieB()] })
    renderScherm()
    const rij = (await screen.findByText('retour dubbele betaling')).closest('tr') as HTMLElement
    await userEvent.click(within(rij).getByRole('button', { name: 'Boeken…' }))
    expect(within(rij).getByTestId('handmatig-te-boeken')).toHaveTextContent('Te boeken: € -2.511,05 (het volledige mutatiebedrag)')
    await kiesCombobox(/Grootboekrekening/, '1300', /Debiteuren/)
    await userEvent.click(within(rij).getByRole('button', { name: /Boeken in RLZ/ }))
    await waitFor(() => expect(boekenAanroepen).toHaveLength(1))
    expect((boekenAanroepen[0].body as { regels: { netto_bedrag: string }[] }).regels[0].netto_bedrag).toBe('-2511.05')
  })

  it('409 "Bedrag dekt niet het open bedrag van de mutatie …" staat letterlijk in het formulier (nooit stil)', async () => {
    installFetchMock({ boekenResponse: { status: 409, body: { detail: BEDRAG_DEKT_NIET } } })
    renderScherm()
    const rij = await rijA()
    await userEvent.click(within(rij).getByRole('button', { name: 'Boeken…' }))
    await kiesCombobox(/Grootboekrekening/, '1300', /Debiteuren/)
    await userEvent.click(within(rij).getByRole('button', { name: /Boeken in RLZ/ }))
    expect(await within(rij).findByText(BEDRAG_DEKT_NIET)).toBeInTheDocument()
    // Het formulier blijft staan (geen verversen/sluiten alsof het gelukt is).
    expect(within(rij).getByTestId('handmatig-boeken-form')).toBeInTheDocument()
  })
})

describe('Splitsen op het open bedrag (3.2 frontend)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('rest-teller start op het open bedrag en de body telt op tot 2511.05', async () => {
    const splitsAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ splitsAanroepen })
    renderScherm()
    const rij = await rijA()
    await userEvent.click(within(rij).getByRole('button', { name: 'Meer acties' }))
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Splitsen…' }))
    const form = within(rij).getByTestId('splitsen-form')
    expect(within(form).getByTestId('splitsen-uitleg')).toHaveTextContent('Open bedrag € 2.511,05 van mutatie € 5.023,09 verdelen')
    expect(within(form).getByTestId('splits-rest')).toHaveTextContent('Rest: € 2.511,05')
    await userEvent.type(within(form).getByLabelText('Bedrag deel 1'), '2000')
    await userEvent.type(within(form).getByLabelText('Bedrag deel 2'), '511,05')
    expect(within(form).getByTestId('splits-rest')).toHaveTextContent('Rest: € 0,00 — klopt')
    await kiesCombobox(/Grootboekrekening deel 1/, '1300', /Debiteuren/)
    await kiesCombobox(/Grootboekrekening deel 2/, '1300', /Debiteuren/)
    await userEvent.click(within(form).getByRole('button', { name: /Splitsen en verwerken/ }))
    await waitFor(() => expect(splitsAanroepen).toHaveLength(1))
    const body = splitsAanroepen[0].body as { delen: { bedrag: string }[] }
    expect(body.delen.map((d) => d.bedrag)).toEqual(['2000.00', '511.05'])
  })
})

describe('Voorstel-kaart toetst het open bedrag (3.2 frontend)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('deel_match op A: restant = open post − OPEN bedrag (niet − volle bedrag); knop "Afletteren (deel)"', async () => {
    installFetchMock({
      mutaties: [
        mutatieA({
          voorstel: {
            soort: 'deel_match',
            kleur: 'oranje',
            bron: 'naam + nummer, bedrag wijkt af',
            reden: 'bevestigen',
            payment_item_id: ITEM_ID,
            open_post: {
              id: ITEM_ID,
              bedrag: '3000.00',
              referentie: '2024841',
              referentie2: null,
              rlz_document_id: null,
              tegenpartij_naam: 'Zilver Beheer B.V.',
              documentsoort: 'Verkoopfactuur',
              boekstuknummer: 'RLZ-01-00000801',
              factuurdatum: '2026-06-20',
            },
            regel_id: null,
            regels: [],
          },
        }),
      ],
    })
    renderScherm()
    const rij = await rijA()
    // 3.000,00 − 2.511,05 = 488,95 (met het volle bedrag 5.023,09 zou er géén deelbetaling zijn).
    expect(within(rij).getByTestId('voorstel-deelbetaling')).toHaveTextContent('deelbetaling — restant € 488,95 blijft open')
    expect(within(rij).getByRole('button', { name: 'Afletteren (deel) ✓' })).toBeInTheDocument()
  })
})
