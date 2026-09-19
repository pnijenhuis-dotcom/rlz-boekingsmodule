import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { OmzetReviewScreen } from './OmzetReviewScreen'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const LEDGER_ID = 'cccccccc-0000-0000-0000-000000000003'
const TAXRATE_ID = 'dddddddd-0000-0000-0000-000000000004'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function documentDetail(overrides: Record<string, unknown> = {}) {
  return {
    id: DOCUMENT_ID,
    administratie_id: ADMINISTRATIE_ID,
    bestandsnaam: 'MargeRapport-wk37.pdf',
    status: 'te_controleren',
    bron: 'upload',
    soort: 'kassarapport',
    mogelijk_duplicaat_van: null,
    toegewezen_aan: null,
    aangemaakt_op: '2026-08-07T09:00:00Z',
    laatst_gewijzigd_op: '2026-08-07T09:00:00Z',
    veldvoorstel: null,
    afwijzing: null,
    tijdlijn: [],
    ...overrides,
  }
}

function voorstel(overrides: Record<string, unknown> = {}) {
  return {
    document_id: DOCUMENT_ID,
    periode_start: '2025-09-15',
    periode_eind: '2025-09-21',
    rapport_totaal_omzet: '22463.36',
    rapport_totaal_kostprijs: '14017.29',
    marge_pct: '160.3',
    regels: [
      {
        categorie: '1. Weed',
        categorie_sleutel: 'weed',
        omzet_bedrag: '13655.33',
        kostprijs_bedrag: '8585.32',
        omzet_ledger_id: LEDGER_ID,
        taxrate_id: TAXRATE_ID,
        kostprijs_ledger_id: LEDGER_ID,
        herkomst: 'mapping',
      },
      {
        categorie: 'Weed Prepacked',
        categorie_sleutel: 'weed prepacked',
        omzet_bedrag: '1440.38',
        kostprijs_bedrag: '854.40',
        omzet_ledger_id: null,
        taxrate_id: null,
        kostprijs_ledger_id: null,
        herkomst: 'nieuw',
      },
    ],
    voorraad_ledger_id: null,
    opgeslagen: false,
    rapport_titel: 'Margerapport',
    entiteit_naam: 'BLOW B.V.',
    ...overrides,
  }
}

interface MockOpties {
  detail?: Record<string, unknown>
  voorstelBody?: Record<string, unknown>
  putAanroepen?: { url: string; body: unknown }[]
  checksAanroepen?: string[]
  boekenAanroepen?: string[]
  boekenAntwoord?: () => Response
}

function installFetchMock(opties: MockOpties = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.includes('/omzet/') && url.endsWith('/voorstel') && init?.method === 'PUT') {
        opties.putAanroepen?.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
        return Promise.resolve(jsonResponse(voorstel({ ...opties.voorstelBody, opgeslagen: true })))
      }
      if (url.includes('/omzet/') && url.endsWith('/voorstel')) {
        return Promise.resolve(jsonResponse(voorstel(opties.voorstelBody ?? {})))
      }
      if (url.endsWith('/checks') && init?.method === 'POST') {
        opties.checksAanroepen?.push(url)
        return Promise.resolve(
          jsonResponse({
            voorstel: voorstel(opties.voorstelBody ?? {}),
            checks: {
              geblokkeerd: false,
              resultaten: [
                { naam: 'Memoriaal-saldo 0', ok: true, melding: 'Memoriaal sluit: debet = credit = € 14017.29' },
                { naam: 'Duplicaat per periode', ok: true, melding: 'Periode nog niet geboekt — geen duplicaat' },
              ],
            },
          }),
        )
      }
      if (url.endsWith('/boeken') && init?.method === 'POST') {
        opties.boekenAanroepen?.push(url)
        if (opties.boekenAntwoord) return Promise.resolve(opties.boekenAntwoord())
        return Promise.resolve(
          jsonResponse({
            document_id: DOCUMENT_ID,
            status: 'geboekt',
            verkoop_rlz_id: 'e1e1e1e1-0000-0000-0000-000000000009',
            verkoop_referentie: 'RLZ-372',
            verkoop_boekstuknummer: 'RLZ-01-00000393',
            memoriaal_rlz_id: 'f1f1f1f1-0000-0000-0000-000000000010',
            memoriaal_boekstuknummer: 'RLZ-06-00000502',
          }),
        )
      }
      if (url.includes('/documenten/') && url.endsWith('/bestand')) {
        return Promise.resolve(new Response(new Blob(['%PDF']), { status: 200, headers: { 'Content-Type': 'application/pdf' } }))
      }
      if (url.includes(`/documenten/${DOCUMENT_ID}`)) {
        return Promise.resolve(jsonResponse(documentDetail(opties.detail ?? {})))
      }
      if (url.includes('/grootboek')) {
        return Promise.resolve(
          jsonResponse({ rekeningen: [{ ledger_id: LEDGER_ID, code: '8001', naam: 'Omzet Wiet' }] }),
        )
      }
      if (url.includes('/btw-codes')) {
        return Promise.resolve(
          jsonResponse({ btw_codes: [{ id: TAXRATE_ID, naam: 'NL, Geen BTW (Vrijgesteld)', percentage: '0' }] }),
        )
      }
      return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
    }),
  )
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:test'), revokeObjectURL: vi.fn() }))
}

function renderScherm() {
  return render(
    <MemoryRouter initialEntries={[`/omzet/${ADMINISTRATIE_ID}/${DOCUMENT_ID}`]}>
      <Routes>
        <Route path="/omzet/:administratieId/:documentId" element={<OmzetReviewScreen />} />
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('OmzetReviewScreen', () => {
  it('toont het herkende rapport met periode, marge en de categorie-regels', async () => {
    installFetchMock()
    renderScherm()

    expect(await screen.findByText(/Rapport herkend:/)).toBeInTheDocument()
    expect(screen.getByText(/2025-09-15 t\/m 2025-09-21/)).toBeInTheDocument()
    expect(screen.getByText('160.3%')).toBeInTheDocument()
    // De categorie staat in de verkoop- én kostprijstabel (twee gekoppelde documenten).
    expect(screen.getAllByText('1. Weed')).toHaveLength(2)
    expect(screen.getByText(/omzetboeking · kassarapport/)).toBeInTheDocument()
  })

  it('toont bij een spreadsheet-bron het bronblok met betaalwijzen, kascheck en controles (Peter 15-09)', async () => {
    installFetchMock({
      voorstelBody: voorstel({
        rapport_titel: 'Dagstaat Elderveld',
        entiteit_naam: null,
        bron: 'zonnestudio_dagstaat',
        bron_detail: {
          store: 'Elderveld',
          datum: '2026-09-08',
          wacht_op: null,
          sluit: false,
          betaalwijzen: { Cash: '86.81', PIN: '932.22', Punten: '0.00' },
          grand_total: { netto: '885.57', btw: '133.46', bruto: '1019.03' },
          points_redeemed: '921.00',
          kas: {
            beginsaldo: '198.20',
            telling: '286.00',
            eindsaldo: '286.00',
            storting: '80.00',
            eindsaldo_na_storting: '206.00',
            contante_omzet: '87.80',
          },
          controles: [
            { naam: 'Regelsom = Grand Total', ok: true, detail: '1019.03', blokkerend: true },
            { naam: 'Puntenwaarde bekend', ok: false, detail: '921 punten ingewisseld, waarde onbekend', blokkerend: true },
            {
              naam: 'Kasverschil (contante omzet kascheck vs Cash POS)',
              ok: false,
              detail: '87.80 vs 86.81 = 0.99',
              blokkerend: false,
            },
          ],
        },
      }),
    })
    renderScherm()
    const blok = await screen.findByTestId('bronblok')
    expect(blok.textContent).toContain('Bron: dagstaat zonnestudio')
    expect(blok.textContent).toContain('1 blokkerende controle')
    expect(screen.getByLabelText('Betaalwijzen').textContent).toContain('PIN')
    expect(screen.getByLabelText('Kascheck').textContent).toContain('Contante omzet volgens kascheck')
    expect(blok.textContent).toContain('Puntenwaarde bekend')
    expect(blok.textContent).toContain('Kasverschil')
    // Geen PDF-viewer voor een spreadsheet, wél een download.
    expect(screen.queryByText(/PDF-weergave niet beschikbaar/)).toBeNull()
    expect(await screen.findByText('Download het bestand')).toBeTruthy()
  })

  it('toont bij een pilates-batch de tegenrekening per betaalwijze mét herkomst en de combi-verdeling mét basis (besluiten Peter 16-09)', async () => {
    installFetchMock({
      voorstelBody: voorstel({
        rapport_titel: 'Uitbetaling po_123',
        entiteit_naam: null,
        bron: 'pilates_betalingsexport',
        bron_detail: {
          batch_id: 'po_123',
          uitbetaaldatum: '2026-09-10',
          bruto: '1250.00',
          kosten: '18.40',
          netto: '1231.60',
          controles: [{ naam: 'Regelsom = netto uitbetaling', ok: true, detail: '1231.60', blokkerend: true }],
          // X-vorm: `tegenzijde.regels[]` (alleen ledger_id — code · naam komen uit de grootboek-opties van het scherm)
          // + eigen controles; combi als record categorie → bedrag mét `aandeel`.
          tegenzijde: {
            vorm: 'aflettering',
            regels: [
              { betaalwijze: 'stripe', bedrag: '1231.60', datum: '2026-09-10', ledger_id: LEDGER_ID, herkomst: 'default', richting: 'ontvangst', label: 'Stripe/PSP', venster_dagen: [1, 7] },
              { betaalwijze: 'cash', bedrag: '0.00', datum: '2026-09-10', ledger_id: LEDGER_ID, herkomst: 'instelling', richting: 'kas', label: 'Contant', venster_dagen: [0, 0] },
            ],
            controles: [{ naam: 'Tegenrekening Stripe/PSP', ok: true, detail: 'default uit het rekeningschema — Stripe/PSP € 1231.60', blokkerend: true }],
          },
          combi_verdeling: {
            bedrag: '120.00',
            basis: 'batch',
            aandeel: { Pilateslessen: '0.8000', Yoga: '0.2000' },
            verdeling: { Pilateslessen: '96.00', Yoga: '24.00' },
            transacties: 3,
          },
        },
      }),
    })
    renderScherm()
    const blok = await screen.findByTestId('bronblok')
    const tegen = screen.getByLabelText('Tegenrekeningen')
    expect(tegen.textContent).toContain('Stripe/PSP')
    // ledger_id → code · naam via de gesyncte grootboek-opties van het scherm (fetch-mock /grootboek).
    expect(tegen.textContent).toContain('8001 · Omzet Wiet')
    expect(tegen.textContent).toContain('standaard (op naam)')
    expect(tegen.textContent).toContain('ingesteld')
    expect(tegen.textContent).toContain('bank +1…+7 d')
    expect(blok.textContent).toContain('Tegenrekening Stripe/PSP')
    const combi = screen.getByTestId('combi-verdeling')
    expect(combi.textContent).toContain('netto-omzet batch')
    expect(screen.getByLabelText('Combi-verdeling').textContent).toContain('Pilateslessen')
    expect(screen.getByLabelText('Combi-verdeling').textContent).toContain('80 %')
    expect(screen.getByLabelText('Combi-verdeling').textContent).toContain('24,00')
    expect(blok.textContent).toContain('sluit')
  })

  it('markeert nieuwe categorieën zonder mapping als blokkerend signaal', async () => {
    installFetchMock()
    renderScherm()

    expect(await screen.findByText(/Nieuwe categorie zonder mapping/)).toBeInTheDocument()
    expect(screen.getByText('nieuw — mapping instellen')).toBeInTheDocument()
    expect(screen.getByText('uit mapping')).toBeInTheDocument()
  })

  it('slaat het voorstel op met genormaliseerde bedragen en mapping_onthouden', async () => {
    const putAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ putAanroepen })
    renderScherm()
    await screen.findByText(/Rapport herkend:/)

    await userEvent.click(screen.getByRole('button', { name: 'Opslaan' }))

    await waitFor(() => expect(putAanroepen).toHaveLength(1))
    const body = putAanroepen[0].body as { regels: unknown[]; mapping_onthouden: boolean; periode_start: string }
    expect(body.mapping_onthouden).toBe(true)
    expect(body.periode_start).toBe('2025-09-15')
    expect(body.regels).toHaveLength(2)
  })

  it('draait de checks automatisch bij openen (read-only) en de boekknop wordt vanzelf bruikbaar', async () => {
    const putAanroepen: { url: string; body: unknown }[] = []
    const checksAanroepen: string[] = []
    const boekenAanroepen: string[] = []
    installFetchMock({ putAanroepen, checksAanroepen, boekenAanroepen })
    renderScherm()
    await screen.findByText(/Rapport herkend:/)

    // Geen knop en geen menselijke handeling: het rapport verschijnt vanzelf bij openen.
    await screen.findByText(/Memoriaal sluit/)
    expect(screen.queryByRole('button', { name: 'Controleren' })).not.toBeInTheDocument()
    expect(checksAanroepen).toHaveLength(1)
    // Bij openen wordt er NIET opgeslagen (read-only checks over voorstel/prefill).
    expect(putAanroepen).toHaveLength(0)

    await waitFor(() => expect(screen.getByRole('button', { name: /Boeken in RLZ/ })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: /Boeken in RLZ/ }))

    await screen.findByText(/Geboekt in RLZ — verkoopfactuur/)
    expect(boekenAanroepen).toHaveLength(1)
    expect(screen.getByText('RLZ-01-00000393')).toBeInTheDocument()
    expect(screen.getByText('RLZ-06-00000502')).toBeInTheDocument()
  })

  it('een wijziging triggert gedebounced automatisch opslaan + checks', async () => {
    const putAanroepen: { url: string; body: unknown }[] = []
    const checksAanroepen: string[] = []
    installFetchMock({ putAanroepen, checksAanroepen })
    renderScherm()
    await screen.findByText(/Rapport herkend:/)
    await screen.findByText(/Memoriaal sluit/)
    expect(checksAanroepen).toHaveLength(1)

    await userEvent.type(screen.getByLabelText('Rapport-totaal omzet'), '1')

    // Debounce (800 ms) → automatisch opslaan + checks, zonder klik.
    await waitFor(() => expect(putAanroepen.length).toBeGreaterThanOrEqual(1), { timeout: 4000 })
    await waitFor(() => expect(checksAanroepen.length).toBeGreaterThanOrEqual(2), { timeout: 4000 })
  })

  it('toont een pop-up met de concrete gefaalde checks bij een 409-blokkade van de boekactie', async () => {
    const putAanroepen: { url: string; body: unknown }[] = []
    const checksAanroepen: string[] = []
    const boekenAanroepen: string[] = []
    installFetchMock({
      putAanroepen,
      checksAanroepen,
      boekenAanroepen,
      boekenAntwoord: () =>
        jsonResponse(
          {
            detail: {
              melding: 'Boeken geblokkeerd door harde checks',
              checks: {
                geblokkeerd: true,
                resultaten: [
                  { naam: 'Duplicaat per periode', ok: false, melding: 'Periode overlapt met al geboekte omzetperiode(s)' },
                ],
              },
            },
          },
          409,
        ),
    })
    renderScherm()
    await screen.findByText(/Rapport herkend:/)

    await waitFor(() => expect(screen.getByRole('button', { name: /Boeken in RLZ/ })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: /Boeken in RLZ/ }))

    // Blok B: server-side blokkade → POP-UP met de concrete gefaalde check(s).
    const dialoog = await screen.findByRole('dialog')
    expect(dialoog).toHaveTextContent('Boeken geblokkeerd door harde checks')
    expect(dialoog).toHaveTextContent('Periode overlapt')
    await userEvent.click(screen.getByRole('button', { name: 'Sluiten' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('een geboekt document is read-only', async () => {
    installFetchMock({ detail: { status: 'geboekt' } })
    renderScherm()

    expect(await screen.findByText(/geboekt in RLZ\. Wijzigen kan alleen via stornering/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Boeken in RLZ/ })).not.toBeInTheDocument()
  })
})

// Node 22+/jsdom: geen bruikbare window.localStorage — in-memory vervanger (patroon WerkvoorraadScreen.test.tsx) voor de
// netto/bruto-voorkeur.
function installeerLocalStorage() {
  const opslag = new Map<string, string>()
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: {
      getItem: (sleutel: string) => opslag.get(sleutel) ?? null,
      setItem: (sleutel: string, waarde: string) => void opslag.set(sleutel, String(waarde)),
      removeItem: (sleutel: string) => void opslag.delete(sleutel),
      clear: () => opslag.clear(),
    },
  })
}

describe('OmzetReviewScreen — ProfX Journaal (bouwnorm mockup/omzet-kassarapport-v2.html, Peter 16-09)', () => {
  beforeAll(() => installeerLocalStorage())
  afterEach(() => {
    vi.unstubAllGlobals()
    window.localStorage.clear()
  })

  const profx = (marge: Record<string, unknown>, metKostprijs: boolean) => ({
    rapport_titel: 'ProfX Journaal',
    entiteit_naam: 'De Bazar Apeldoorn B.V.',
    periode_start: '2026-09-11',
    periode_eind: '2026-09-11',
    rapport_totaal_omzet: '10998.16',
    rapport_totaal_kostprijs: metKostprijs ? '6295.23' : null,
    marge_pct: metKostprijs ? '42.8' : null,
    bron: 'profx_journaal',
    bron_detail: {
      kassas: ['Kassa 1', 'Kassa 2'],
      klanten: 604,
      betaalwijzen: { Cash: '6410.66', PIN: '4587.50' },
      controles: [
        { naam: 'Sluitcontrole: Σ groepen = bruto omzet', ok: true, detail: '€ 10.998,16', blokkerend: true },
        { naam: 'Edible: categorie bevestigen', ok: false, detail: 'Edible: categorie uit default (vrijgesteld) — eerste keer bevestigen', blokkerend: false },
      ],
      marge,
    },
    regels: [
      { categorie: 'Dranken', categorie_sleutel: 'dranken', omzet_bedrag: '88.50', kostprijs_bedrag: metKostprijs ? '31.00' : null, omzet_ledger_id: LEDGER_ID, taxrate_id: TAXRATE_ID, kostprijs_ledger_id: LEDGER_ID, herkomst: 'mapping', btw_herkomst: 'default_laag' },
      { categorie: 'Edible', categorie_sleutel: 'edible', omzet_bedrag: '285.00', kostprijs_bedrag: metKostprijs ? '142.50' : null, omzet_ledger_id: LEDGER_ID, taxrate_id: TAXRATE_ID, kostprijs_ledger_id: LEDGER_ID, herkomst: 'default', btw_herkomst: 'default_vrijgesteld' },
      { categorie: 'Wiet', categorie_sleutel: 'wiet', omzet_bedrag: '6431.47', kostprijs_bedrag: metKostprijs ? '3858.88' : null, omzet_ledger_id: LEDGER_ID, taxrate_id: TAXRATE_ID, kostprijs_ledger_id: LEDGER_ID, herkomst: 'mapping', btw_herkomst: 'default_vrijgesteld' },
    ],
  })

  it('toont bronchips, de marge-stand "gebundeld", twee kaarten en de knop "2 documenten"; het kopje wisselt netto/bruto', async () => {
    installFetchMock({ voorstelBody: profx({ stand: 'gebundeld' }, true) })
    renderScherm()
    await screen.findByText(/Rapport herkend:/)
    expect(screen.getByTestId('omzet-bronchips').textContent).toContain('ProfX Journaal')
    expect(screen.getByTestId('marge-stand').textContent).toBe('Margerapport gekoppeld · zelfde dag')
    expect(screen.getByTestId('kaart-verkoop').textContent).toContain('3 regels')
    expect(screen.getByTestId('kaart-kostprijs').textContent).toContain('€ 4.032,38')
    expect(screen.getByTestId('omzet-strook').textContent).toContain('PIN € 4.587,50')
    expect(screen.getByText('bevestig')).toBeInTheDocument() // Edible: categorie uit default → oranje chip op die regel
    await screen.findByText(/Memoriaal sluit/)
    await waitFor(() => expect(screen.getByRole('button', { name: /Boeken in RLZ \(2 documenten\)/ })).toBeEnabled())
    // Netto/bruto: standaard netto; de btw-code in de mock is 0 % → netto = bruto; het kopje wisselt de modus.
    const kop = screen.getByRole('button', { name: /Omzet netto/ })
    expect((screen.getByLabelText('Netto omzetbedrag Wiet') as HTMLInputElement).value).toBe('6431,47')
    await userEvent.click(kop)
    expect(screen.getByRole('button', { name: /Omzet bruto/ })).toHaveAttribute('aria-pressed', 'true')
    expect((screen.getByLabelText('Bruto omzetbedrag Wiet') as HTMLInputElement).value).toBe('6431.47')
    expect(window.localStorage.getItem('rlz.bedragmodus')).toBe('bruto')
  })

  it('zonder margerapport: oranje stand "verwacht", kostprijskaart wacht en de knop wordt "alleen omzet"', async () => {
    installFetchMock({ voorstelBody: profx({ stand: 'verwacht', week: 37 }, false) })
    renderScherm()
    await screen.findByText(/Rapport herkend:/)
    expect(screen.getByTestId('marge-stand').textContent).toContain('weekrapport 37 verwacht')
    expect(screen.getByTestId('kaart-kostprijs').textContent).toContain('wacht op margerapport')
    await screen.findByText(/Memoriaal sluit/)
    await waitFor(() => expect(screen.getByRole('button', { name: /Boeken in RLZ \(alleen omzet\)/ })).toBeEnabled())
  })
})

describe('OmzetReviewScreen — "Boekt in Reeleezee als" (Peter 16-09, casus Van Boxtel)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('toont binder · categorie mét herkomst en zet een keuze uit de lijst als default (PUT verkoop-categorie)', async () => {
    const puts: { url: string; body: unknown }[] = []
    const basis = voorstel({
      verkoop_categorie: { id: 'cat-1', naam: 'Verkoopfactuur (Omzet)', binder: 'Inkomsten', bron: 'automatisch', is_inkomsten: true },
      verkoop_categorieen: [
        { id: 'cat-1', naam: 'Verkoopfactuur (Omzet)', binder: 'Inkomsten', is_inkomsten: true },
        { id: 'cat-2', naam: 'Diverse opbrengsten', binder: 'Inkomsten', is_inkomsten: true },
        { id: 'cat-3', naam: 'BTW Prive bijdrage auto', binder: 'Uitgaven', is_inkomsten: false },
      ],
    })
    installFetchMock({ voorstelBody: basis })
    const origineel = globalThis.fetch as unknown as (url: string, init?: RequestInit) => Promise<Response>
    vi.stubGlobal('fetch', (url: string, init?: RequestInit) => {
      if (url.endsWith('/omzet/verkoop-categorie') && init?.method === 'PUT') {
        puts.push({ url, body: JSON.parse(String(init.body)) })
        return Promise.resolve(
          jsonResponse({ id: 'cat-3', naam: 'BTW Prive bijdrage auto', binder: 'Uitgaven', bron: 'mens', is_inkomsten: false }),
        )
      }
      return origineel(url, init)
    })
    renderScherm()
    await screen.findByText(/Rapport herkend:/)
    const regel = screen.getByTestId('omzet-categorie')
    expect(regel).toHaveTextContent('Boekt in Reeleezee als: Inkomsten · Verkoopfactuur (Omzet)')
    expect(regel).toHaveTextContent('automatisch')
    const select = screen.getByLabelText('Omzetcategorie in Reeleezee') as HTMLSelectElement
    expect(select.querySelectorAll('optgroup')).toHaveLength(2)
    expect(select.querySelector('optgroup[label*="Uitgaven"]')?.getAttribute('label')).toContain('verschijnt in RLZ onder Uitgaven')
    await userEvent.selectOptions(select, 'cat-3')
    await waitFor(() => expect(puts).toHaveLength(1))
    expect(puts[0].body).toEqual({ categorie_id: 'cat-3', document_id: DOCUMENT_ID })
    await waitFor(() => expect(screen.getByTestId('omzet-categorie')).toHaveTextContent('Uitgaven · BTW Prive bijdrage auto'))
    expect(screen.getByTestId('omzet-categorie')).toHaveTextContent('gekozen')
    expect(screen.getByTestId('omzet-categorie')).toHaveTextContent('verschijnt in RLZ onder Uitgaven')
  })
})

describe('OmzetReviewScreen — automatisch getypeerd + "Tóch inkoopfactuur…" (Peter 19-09)', () => {
  it('toont de chip, vraagt een reden en navigeert ná terugzetten naar het doel_pad', async () => {
    installFetchMock({
      voorstelBody: voorstel({ bron: 'profx_journaal', automatisch_getypeerd: true, automatisch_getypeerd_bron: 'profx_journaal' }),
    })
    const basis = globalThis.fetch
    const tochAanroepen: { url: string; body: unknown }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith('/toch-inkoopfactuur') && init?.method === 'POST') {
          tochAanroepen.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
          return Promise.resolve(
            jsonResponse({
              document_id: DOCUMENT_ID,
              status: 'ontvangen',
              correcties: 1,
              bron: 'profx_journaal',
              valt_terug_op_melden: false,
              doel_pad: `/?administratie=${ADMINISTRATIE_ID}&document=${DOCUMENT_ID}`,
            }),
          )
        }
        return basis(url, init)
      }),
    )
    render(
      <MemoryRouter initialEntries={[`/omzet/${ADMINISTRATIE_ID}/${DOCUMENT_ID}`]}>
        <Routes>
          <Route path="/omzet/:administratieId/:documentId" element={<OmzetReviewScreen />} />
          <Route path="/" element={<div>WERKVOORRAAD-DOEL</div>} />
        </Routes>
      </MemoryRouter>,
    )
    expect(await screen.findByTestId('chip-automatisch-getypeerd')).toHaveTextContent('automatisch getypeerd')
    await userEvent.click(screen.getByRole('button', { name: 'Tóch inkoopfactuur…' }))
    const dialoog = await screen.findByRole('dialog')
    expect(dialoog).toHaveTextContent('ProfX Journaal')
    const knop = screen.getByRole('button', { name: 'Terug naar inkoopfactuur' })
    expect(knop).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Reden (verplicht)'), 'Factuur van de kassaleverancier')
    expect(knop).toBeEnabled()
    await userEvent.click(knop)
    await waitFor(() => expect(tochAanroepen).toHaveLength(1))
    expect(tochAanroepen[0].body).toEqual({ reden: 'Factuur van de kassaleverancier' })
    expect(tochAanroepen[0].url).toContain(`/administraties/${ADMINISTRATIE_ID}/omzet/documenten/${DOCUMENT_ID}/toch-inkoopfactuur`)
    expect(await screen.findByText('WERKVOORRAAD-DOEL')).toBeInTheDocument()
  })

  it('zonder automatische typering: geen chip en geen knop', async () => {
    installFetchMock()
    renderScherm()
    expect(await screen.findByText(/omzetboeking · kassarapport/)).toBeInTheDocument()
    expect(screen.queryByTestId('chip-automatisch-getypeerd')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Tóch inkoopfactuur…' })).not.toBeInTheDocument()
  })
})
