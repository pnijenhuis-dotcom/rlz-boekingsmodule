import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../ui/basis'
import { BankDetailScreen } from './BankDetailScreen'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const REKENING_ID = 'cccccccc-0000-0000-0000-000000000003'
const MUTATIE_ID = 'dddddddd-0000-0000-0000-000000000004'
const ITEM_ID = 'eeeeeeee-0000-0000-0000-000000000005'
const OPDRACHT_ID = 'ffffffff-0000-0000-0000-000000000006'

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
  laatste_import: { datum: '2026-07-31', bron: '1', type: 'MT940', bestandsnaam: 'x.940' },
  probe_fout: null,
}

function mutatie(overrides: Record<string, unknown> = {}) {
  return {
    id: MUTATIE_ID,
    boekdatum: '2026-07-01',
    bedrag: '-1847.23',
    open_bedrag: '-1847.23',
    tegenpartij_naam: 'Bouwmaat Nederland B.V.',
    omschrijving: 'fact. 2026-0642',
    tegenrekening_iban: 'NL00BANK0123456789',
    voorstel: {
      soort: 'exacte_match',
      kleur: 'groen',
      bron: 'naam + nummer + bedrag',
      reden: 'Open post: teken klopt, naam matcht, factuurnummer als heel token én bedrag cent-exact',
      payment_item_id: ITEM_ID,
      open_post: { id: ITEM_ID, bedrag: '1847.23', referentie: '2026-0642', referentie2: null, rlz_document_id: null },
      regel_id: null,
      regels: [],
    },
    afletter_opdracht: null,
    regel_voorstel: null,
    ...overrides,
  }
}

function afletterOpdracht(overrides: Record<string, unknown> = {}) {
  return {
    id: OPDRACHT_ID,
    status: 'klaargezet',
    payment_item_id: ITEM_ID,
    klaargezet_op: '2026-08-02T10:00:00Z',
    laatste_verificatie_poging_op: null,
    geverifieerd_op: null,
    voorstel_gevolgd: null,
    uitvoering: null,
    koppelingen: [],
    ...overrides,
  }
}

interface MockOpties {
  mutaties?: unknown[]
  /** Gevuld = de mutaties-GET geeft ná een klaarzetten-POST deze lijst terug (fallback-flow:
   * de rij toont dan de klaargezette opdracht met "Nu afletteren"). */
  mutatiesNaKlaarzetten?: unknown[]
  rekeningenBody?: Record<string, unknown>
  afletterOpdrachten?: unknown[]
  /** Blok 6a: teller van verwerkte opdrachten > 30 dagen (achter de toggle); `afletterOpdrachtenOud` = de lijst
   * die de GET mét ?toon_oud=true teruggeeft. */
  aantalOud?: number
  afletterOpdrachtenOud?: unknown[]
  afletterAanroepen?: string[]
  klaarzettenAanroepen?: { url: string; body: unknown }[]
  klaarzettenResponse?: { opdracht_id: string; uitkomst: string; fout: string | null }
  voerUitAanroepen?: string[]
  voerUitResponse?: { opdracht_id: string; uitkomst: string; fout: string | null }
  intrekkenAanroepen?: string[]
  boekenAanroepen?: { url: string; body: unknown }[]
  verifieerAanroepen?: string[]
  /** Blok C 16-09: "Afletteren (N)" op een batch-voorstel. */
  batchAanroepen?: string[]
  batchResponse?: Record<string, unknown>
  /** Blok E: geforceerde achtergrondronde via het ⟳-icoon; response = klaar-run mét resultaat. */
  syncAchtergrondAanroepen?: string[]
  syncAchtergrondKlaarResultaat?: Record<string, unknown>
}

function installFetchMock(opties: MockOpties = {}) {
  let klaargezet = false
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
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
            ...(opties.rekeningenBody ?? {}),
          }),
        )
      }
      if (url.includes('/mutaties') && (!init || init.method === undefined)) {
        const lijst =
          klaargezet && opties.mutatiesNaKlaarzetten ? opties.mutatiesNaKlaarzetten : opties.mutaties ?? [mutatie()]
        return Promise.resolve(jsonResponse({ mutaties: lijst }))
      }
      if (url.includes('/afletter-opdrachten') && (!init || init.method === undefined)) {
        opties.afletterAanroepen?.push(url)
        const toonOud = url.includes('toon_oud=true')
        return Promise.resolve(
          jsonResponse({
            opdrachten: toonOud ? opties.afletterOpdrachtenOud ?? opties.afletterOpdrachten ?? [] : opties.afletterOpdrachten ?? [],
            aantal_oud: opties.aantalOud ?? 0,
            toon_oud: toonOud,
            oud_na_dagen: 30,
          }),
        )
      }
      if (url.includes('/verifieer-afletteren') && init?.method === 'POST') {
        opties.verifieerAanroepen?.push(url)
        return Promise.resolve(jsonResponse({ geverifieerd: 1 }))
      }
      if (url.includes('/afletteren-batch') && init?.method === 'POST') {
        opties.batchAanroepen?.push(url)
        return Promise.resolve(
          jsonResponse(
            opties.batchResponse ?? {
              sleutel: 'RLZEE_CT_20260915_101500_4471_0001',
              gekoppeld: 2,
              overgeslagen: 0,
              mislukt: 0,
              rijen: [
                { payment_item_id: 'p1', uitkomst: 'afgeletterd_via_api', fout: null, opdracht_id: 'o1' },
                { payment_item_id: 'p2', uitkomst: 'afgeletterd_via_api', fout: null, opdracht_id: 'o2' },
              ],
            },
          ),
        )
      }
      if (url.includes('/afletteren-klaarzetten') && init?.method === 'POST') {
        opties.klaarzettenAanroepen?.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
        klaargezet = true
        return Promise.resolve(
          jsonResponse(
            opties.klaarzettenResponse ?? { opdracht_id: OPDRACHT_ID, uitkomst: 'afgeletterd_via_api', fout: null },
            201,
          ),
        )
      }
      if (url.includes('/voer-uit') && init?.method === 'POST') {
        opties.voerUitAanroepen?.push(url)
        return Promise.resolve(
          jsonResponse(
            opties.voerUitResponse ?? { opdracht_id: OPDRACHT_ID, uitkomst: 'afgeletterd_via_api', fout: null },
          ),
        )
      }
      if (url.includes('/intrekken') && init?.method === 'POST') {
        opties.intrekkenAanroepen?.push(url)
        return Promise.resolve(new Response(null, { status: 204 }))
      }
      if (url.includes('/direct-boeken') && init?.method === 'POST') {
        opties.boekenAanroepen?.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
        return Promise.resolve(
          jsonResponse({
            boeking_id: OPDRACHT_ID,
            rlz_boekstuknummer: 'RLZ-07-00000001',
            al_eerder_geboekt: false,
            vaste_regel_aangemaakt: false,
          }),
        )
      }
      if (url.includes('/grootboek') || url.includes('/btw-codes')) {
        return Promise.resolve(jsonResponse({ rekeningen: [], btw_codes: [] }))
      }
      // Deel 4 (25-08): auto-verversing + de nieuwe panelen — in deze suite neutraal (actueel/leeg).
      if (url.includes('/bank/sync-achtergrond') && init?.method === 'POST') {
        opties.syncAchtergrondAanroepen?.push(url)
        if (url.includes('forceer=true')) {
          return Promise.resolve(
            jsonResponse(
              {
                run_id: 'run-9',
                status: 'klaar',
                overgeslagen: false,
                laatste_sync_op: '2026-09-02T00:30:00Z',
                resultaat: {
                  mutaties_nieuw: 0,
                  mutaties_bijgewerkt: 27,
                  open_ververst: 0,
                  afletteren_geverifieerd: 0,
                  afletteren_wachtend: 0,
                  automatisch_afgeletterd: 0,
                  automatisch_geboekt: 0,
                  fouten: [],
                  ...(opties.syncAchtergrondKlaarResultaat ?? {}),
                },
                fout_reden: null,
              },
              202,
            ),
          )
        }
        return Promise.resolve(
          jsonResponse(
            {
              run_id: null,
              status: 'overgeslagen',
              overgeslagen: true,
              laatste_sync_op: '2026-08-02T06:00:00Z',
              resultaat: null,
              fout_reden: null,
            },
            202,
          ),
        )
      }
      if (url.endsWith('/bank/aanbetalingen')) return Promise.resolve(jsonResponse({ aanbetalingen: [] }))
      if (url.endsWith('/splitsingen')) return Promise.resolve(jsonResponse({ splitsingen: [] }))
      if (url.endsWith('/crediteuren')) return Promise.resolve(jsonResponse({ crediteuren: [] }))
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

describe('BankDetailScreen', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('toont de bankpicker met saldo en de mutatie met herkomst-chip', async () => {
    installFetchMock()
    renderScherm()

    expect(await screen.findByText(/Bouwmaat Nederland B.V./)).toBeInTheDocument()
    // Blok E6: de match-reden staat als chip ín de voorstel-kaart, niet meer als losse kolom.
    expect(screen.getByTestId('voorstel-kaart')).toHaveTextContent('exacte match — naam + nummer + bedrag')
    expect(screen.queryByRole('columnheader', { name: 'Bron voorstel' })).not.toBeInTheDocument()
    expect(screen.getByLabelText('Rekening')).toBeInTheDocument()
    expect(screen.getByText(/Saldo/)).toBeInTheDocument()
  })

  it('lettert een voorstel direct af via de API en meldt succes (uitkomst afgeletterd_via_api)', async () => {
    const klaarzettenAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ klaarzettenAanroepen })
    renderScherm()

    await userEvent.click(await screen.findByRole('button', { name: 'Afletteren ✓' }))

    await waitFor(() => expect(klaarzettenAanroepen).toHaveLength(1))
    expect(klaarzettenAanroepen[0].url).toContain(`/bank/mutaties/${MUTATIE_ID}/afletteren-klaarzetten`)
    expect(klaarzettenAanroepen[0].body).toEqual({ payment_item_id: ITEM_ID })
    expect(
      await screen.findByText(/Afgeletterd — koppeling direct in Reeleezee gelegd en geverifieerd/),
    ).toBeInTheDocument()
  })

  it('fallback: API-fout bij afletteren toont de fout, daarna lettert "Nu afletteren" alsnog af', async () => {
    const klaarzettenAanroepen: { url: string; body: unknown }[] = []
    const voerUitAanroepen: string[] = []
    installFetchMock({
      klaarzettenAanroepen,
      voerUitAanroepen,
      klaarzettenResponse: {
        opdracht_id: OPDRACHT_ID,
        uitkomst: 'wacht_op_mens_in_rlz',
        fout: 'RLZ gaf 400 _InvalidData',
      },
      mutatiesNaKlaarzetten: [mutatie({ afletter_opdracht: afletterOpdracht() })],
    })
    renderScherm()

    await userEvent.click(await screen.findByRole('button', { name: 'Afletteren ✓' }))

    // Fout zichtbaar (nooit stil), mét handelingsperspectief; de opdracht staat klaar.
    expect(await screen.findByText(/De API-koppeling is niet gelukt \(RLZ gaf 400 _InvalidData\)/)).toBeInTheDocument()
    expect(screen.getByText(/probeer “Nu afletteren” opnieuw of leg de koppeling in Reeleezee/)).toBeInTheDocument()

    // "Nu afletteren" roept het voer-uit-endpoint aan en meldt bij succes hetzelfde als de directe route.
    await userEvent.click(await screen.findByRole('button', { name: 'Nu afletteren ✓' }))
    await waitFor(() => expect(voerUitAanroepen).toHaveLength(1))
    expect(voerUitAanroepen[0]).toContain(`/bank/afletter-opdrachten/${OPDRACHT_ID}/voer-uit`)
    expect(
      await screen.findByText(/Afgeletterd — koppeling direct in Reeleezee gelegd en geverifieerd/),
    ).toBeInTheDocument()
  })

  it('toont een klaargezette opdracht met "Nu afletteren" en intrekken (geen RLZ-instructie meer)', async () => {
    const intrekkenAanroepen: string[] = []
    installFetchMock({
      intrekkenAanroepen,
      mutaties: [mutatie({ afletter_opdracht: afletterOpdracht() })],
    })
    renderScherm()

    expect(await screen.findByText('Klaargezet — nog niet gekoppeld')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Nu afletteren ✓' })).toBeInTheDocument()
    // De oude instructie-staat ("leg de koppeling in Reeleezee; de sync verifieert") is vervangen.
    expect(screen.queryByText(/eerstvolgende bank-sync verifieert automatisch/)).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Meer acties' }))
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Intrekken' }))
    await waitFor(() => expect(intrekkenAanroepen).toHaveLength(1))
  })

  it('toont "wacht op verificatie" zodra er een verificatiepoging is geweest', async () => {
    installFetchMock({
      mutaties: [
        mutatie({
          afletter_opdracht: afletterOpdracht({ laatste_verificatie_poging_op: '2026-08-08T09:15:00Z' }),
        }),
      ],
    })
    renderScherm()

    expect(await screen.findByText(/Wacht op verificatie — laatst gecontroleerd/)).toBeInTheDocument()
    expect(screen.getByText(/nog\s+open in RLZ/)).toBeInTheDocument()
  })

  it('blok E1/E2: geen "Verversen"/"Nu verifiëren"-knoppen; versheid + ⟳ staan in de paneelkop; ⟳ start een geforceerde ronde (zelfde endpoint) en de uitkomst is een toast zonder layout-shift', async () => {
    const syncAchtergrondAanroepen: string[] = []
    installFetchMock({ syncAchtergrondAanroepen, syncAchtergrondKlaarResultaat: { afletteren_wachtend: 2, afletteren_geverifieerd: 1 } })
    renderScherm()

    await screen.findByText(/Bouwmaat Nederland B.V./)
    expect(screen.queryByRole('button', { name: /Nu verifiëren/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Verversen uit Reeleezee/ })).not.toBeInTheDocument()
    const kop = screen.getByTestId('ververs-hint')
    expect(kop.closest('.bank-p-kop')).not.toBeNull()
    expect(kop).toHaveTextContent(/laatst ververst/)
    const tabel = screen.getByRole('table')
    expect(tabel.previousElementSibling).toHaveClass('bank-p-kop')

    await userEvent.click(screen.getByRole('button', { name: 'Nu verversen uit Reeleezee' }))
    await waitFor(() => expect(syncAchtergrondAanroepen.some((u) => u.includes('forceer=true'))).toBe(true))
    // Uitkomst = toast (blok E4) mét de meeliftende verificatie (blok E3: er wachtten 2 opdrachten).
    expect(await screen.findByText(/⟳ Ververst: 0 nieuwe mutaties · 27 bijgewerkt — 1 aflettering\(en\) geverifieerd, 1 wacht nog in Reeleezee/)).toBeInTheDocument()
    // Geen statusregel boven de tabel: de tabel volgt nog steeds direct op de paneelkop.
    expect(screen.getByRole('table').previousElementSibling).toHaveClass('bank-p-kop')
  })

  it('blok E3: zonder wachtende afletteropdrachten zwijgt de toast over verificatie', async () => {
    const syncAchtergrondAanroepen: string[] = []
    installFetchMock({ syncAchtergrondAanroepen, syncAchtergrondKlaarResultaat: { afletteren_wachtend: 0, afletteren_geverifieerd: 0 } })
    renderScherm()
    await screen.findByText(/Bouwmaat Nederland B.V./)
    await userEvent.click(screen.getByRole('button', { name: 'Nu verversen uit Reeleezee' }))
    const toast = await screen.findByText(/⟳ Ververst: 0 nieuwe mutaties · 27 bijgewerkt/)
    expect(toast).not.toHaveTextContent(/aflettering|wacht/)
  })

  it('blok E7: deelmatch toont het restant cent-exact en de knop heet "Afletteren (deel)"', async () => {
    installFetchMock({
      mutaties: [
        mutatie({
          bedrag: '-1000.00',
          open_bedrag: '-1000.00',
          voorstel: {
            soort: 'deel_match',
            kleur: 'oranje',
            bron: 'naam + nummer, bedrag wijkt af',
            reden: 'Open post matcht op naam + nummer, bedrag wijkt af — bevestigen',
            payment_item_id: ITEM_ID,
            open_post: {
              id: ITEM_ID,
              bedrag: '1200.00',
              referentie: '26-0441',
              referentie2: 'RLZ-01-00000921 14-08-2026',
              rlz_document_id: null,
              tegenpartij_naam: 'Bouwbedrijf Verhagen B.V.',
              documentsoort: 'Inkoopfactuur',
              boekstuknummer: 'RLZ-01-00000921',
              factuurdatum: '2026-08-14',
            },
            regel_id: null,
            regels: [],
          },
        }),
      ],
    })
    renderScherm()
    const kaart = await screen.findByTestId('voorstel-kaart')
    expect(kaart).toHaveTextContent('Bouwbedrijf Verhagen B.V.')
    expect(kaart).toHaveTextContent('Inkoopfactuur 26-0441 · RLZ-01-00000921')
    expect(screen.getByTestId('voorstel-deelbetaling')).toHaveTextContent('deelbetaling — restant € 200,00 blijft open')
    expect(kaart).toHaveTextContent('match op naam + nummer, bedrag wijkt af — bevestigen')
    expect(screen.getByRole('button', { name: 'Afletteren (deel) ✓' })).toBeInTheDocument()
  })

  it('iteratie 2: geen match = klein chipje "handmatig" (geen herhaalde tekstregel), geen lege kaart; één primaire knop + ⋯-menu', async () => {
    installFetchMock({
      mutaties: [mutatie({ voorstel: { soort: 'handmatig', kleur: 'oranje', bron: 'handmatig', reden: 'Geen regel en geen open-post-match', payment_item_id: null, open_post: null, regel_id: null, regels: [] } })],
    })
    renderScherm()
    expect(await screen.findByTestId('voorstel-handmatig')).toHaveTextContent('handmatig')
    expect(screen.queryByText('Geen open post of regel gevonden — handmatig beoordelen.')).not.toBeInTheDocument()
    expect(screen.queryByTestId('voorstel-kaart')).not.toBeInTheDocument()
    // Eén primaire knop; de overige routes achter ⋯
    expect(screen.getByRole('button', { name: 'Boeken…' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Koppel aan relatie…' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Meer acties' }))
    expect(await screen.findByRole('menuitem', { name: 'Koppel aan relatie…' })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: 'Splitsen…' })).toBeInTheDocument()
  })

  it('toont de levenscyclus-sectie met geverifieerd resultaat, afwijkend-gevolgd en "Nu afletteren"', async () => {
    const voerUitAanroepen: string[] = []
    const KLAARGEZET_ID = 'ffffffff-0000-0000-0000-000000000008'
    installFetchMock({
      voerUitAanroepen,
      mutaties: [],
      afletterOpdrachten: [
        {
          opdracht: afletterOpdracht({ id: KLAARGEZET_ID }),
          boekdatum: '2026-07-03',
          tegenpartij_naam: 'Nog te koppelen partij',
          bedrag: '-99.00',
        },
        {
          opdracht: afletterOpdracht({
            status: 'geverifieerd',
            geverifieerd_op: '2026-08-08T12:00:00Z',
            voorstel_gevolgd: true,
            koppelingen: [{ rlz_document_id: 'x', boekstuknummer: 'RLZ-04-00002012', bedrag: '1847.23' }],
          }),
          boekdatum: '2026-07-01',
          tegenpartij_naam: 'Bouwmaat Nederland B.V.',
          bedrag: '-1847.23',
        },
        {
          opdracht: afletterOpdracht({
            id: 'ffffffff-0000-0000-0000-000000000007',
            status: 'geverifieerd',
            geverifieerd_op: '2026-08-08T12:00:00Z',
            voorstel_gevolgd: false,
            koppelingen: [{ rlz_document_id: 'y', boekstuknummer: 'RLZ-04-00002099', bedrag: null }],
          }),
          boekdatum: '2026-07-02',
          tegenpartij_naam: 'Andere partij',
          bedrag: '-10.00',
        },
      ],
    })
    renderScherm()

    expect(await screen.findByText('Afletteren via Reeleezee — levenscyclus')).toBeInTheDocument()
    expect(screen.getByText(/Geverifieerd — afgeletterd in RLZ/)).toBeInTheDocument()
    expect(screen.getByText(/RLZ-04-00002012/)).toBeInTheDocument()
    // Afwijkend gevolgd = zichtbaar, nooit stil (mens koppelde in RLZ iets anders dan het voorstel).
    expect(screen.getByText(/Afwijkend gevolgd — in RLZ anders gekoppeld/)).toBeInTheDocument()
    // Tijdlijn: klaargezet → geverifieerd met tijdstippen.
    expect(screen.getAllByText(/Klaargezet .*→ geverifieerd/).length).toBeGreaterThan(0)

    // Klaargezette opdracht in de lijst heeft de "Nu afletteren"-knop → voer-uit-endpoint.
    await userEvent.click(screen.getByRole('button', { name: 'Nu afletteren ✓' }))
    await waitFor(() => expect(voerUitAanroepen).toHaveLength(1))
    expect(voerUitAanroepen[0]).toContain(`/bank/afletter-opdrachten/${KLAARGEZET_ID}/voer-uit`)
    expect(
      await screen.findByText(/Afgeletterd — koppeling direct in Reeleezee gelegd en geverifieerd/),
    ).toBeInTheDocument()
  })

  it('toont "al afgeletterd in RLZ" als geverifieerd-zonder-fout (kliktest 2026-08-09)', async () => {
    // Randgeval: "Nu afletteren" op een opdracht waarvan de mutatie intussen al in RLZ was
    // afgeletterd — vroeger een kale 404, nu een succes-melding + eigen chip.
    const voerUitAanroepen: string[] = []
    installFetchMock({
      voerUitAanroepen,
      voerUitResponse: { opdracht_id: OPDRACHT_ID, uitkomst: 'al_afgeletterd_in_rlz', fout: null },
      mutaties: [],
      afletterOpdrachten: [
        {
          opdracht: afletterOpdracht({ id: OPDRACHT_ID }),
          boekdatum: '2026-07-03',
          tegenpartij_naam: 'Al gekoppelde partij',
          bedrag: '-99.00',
        },
        {
          opdracht: afletterOpdracht({
            id: 'ffffffff-0000-0000-0000-000000000009',
            status: 'geverifieerd',
            geverifieerd_op: '2026-08-09T12:00:00Z',
            voorstel_gevolgd: true,
            uitvoering: 'al_afgeletterd_in_rlz',
            koppelingen: [{ rlz_document_id: 'z', boekstuknummer: 'RLZ-04-00002100', bedrag: '99.00' }],
          }),
          boekdatum: '2026-07-04',
          tegenpartij_naam: 'Eerder al gekoppelde partij',
          bedrag: '-99.00',
        },
      ],
    })
    renderScherm()

    // De eerder-geverifieerde opdracht draagt de eigen chip.
    expect(await screen.findByText(/Geverifieerd — al afgeletterd in RLZ/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Nu afletteren ✓' }))
    await waitFor(() => expect(voerUitAanroepen).toHaveLength(1))
    expect(await screen.findByText(/Al afgeletterd in Reeleezee — de opdracht is als geverifieerd/)).toBeInTheDocument()
  })

  it('boekt een vaste-regel-voorstel direct met de meegeleverde regels', async () => {
    const boekenAanroepen: { url: string; body: unknown }[] = []
    const ledgerId = '11111111-0000-0000-0000-000000000011'
    installFetchMock({
      boekenAanroepen,
      mutaties: [
        mutatie({
          bedrag: '-24.50',
          open_bedrag: '-24.50',
          tegenpartij_naam: 'ING Bank N.V.',
          omschrijving: 'kosten zakelijk juni',
          voorstel: {
            soort: 'vaste_regel',
            kleur: 'groen',
            bron: 'vaste regel',
            reden: 'Tegenpartij matcht een vaste regel',
            payment_item_id: null,
            open_post: null,
            regel_id: '22222222-0000-0000-0000-000000000022',
            regels: [
              {
                ledger_id: ledgerId,
                netto_bedrag: '-24.50',
                btw_bedrag: null,
                taxrate_id: null,
                project_id: null,
                omschrijving: 'Bankkosten',
              },
            ],
          },
        }),
      ],
    })
    renderScherm()

    await userEvent.click(await screen.findByRole('button', { name: /Akkoord/ }))

    await waitFor(() => expect(boekenAanroepen).toHaveLength(1))
    const body = boekenAanroepen[0].body as {
      bron: string
      regels: { ledger_id: string; netto_bedrag: string }[]
    }
    expect(body.bron).toBe('vaste_regel')
    expect(body.regels[0]).toMatchObject({ ledger_id: ledgerId, netto_bedrag: '-24.50' })
  })

  it('blok B (10-09): historie-regel op de rij — groen "historie-regel — k van n op ‹rekening›" of oranje "… — bevestigen"; AI-twijfel/overgeslagen als chip op de rij', async () => {
    installFetchMock({
      mutaties: [
        mutatie({
          id: 'm-groen',
          tegenpartij_naam: 'Verhuurder Vastgoed B.V.',
          voorstel: { soort: 'historie_regel', kleur: 'groen', bron: 'historie: 12 van 12 op 4400 Huur', reden: 'IBAN + omschrijvingskern, 12 eerdere boekingen', payment_item_id: null, open_post: null, regel_id: null, regels: [], ledger_id: 'l-4400', taxrate_id: null, historie_k: 12, historie_n: 12 },
          ai_toets_uitkomst: 'twijfel',
          ai_toets_reden: 'bedrag afwijkend van de historie',
          ai_toets_op: '2026-09-10T03:00:00Z',
        }),
        mutatie({
          id: 'm-oranje',
          tegenpartij_naam: 'KPN B.V.',
          voorstel: { soort: 'historie_regel', kleur: 'oranje', bron: 'historie: 4 van 6 op 4300 Telefoon', reden: 'gelijkstand', payment_item_id: null, open_post: null, regel_id: null, regels: [], historie_k: 4, historie_n: 6 },
          ai_toets_uitkomst: 'overgeslagen',
          ai_toets_reden: 'avg_gate — intake-AI staat uit',
          ai_toets_op: null,
        }),
      ],
    })
    renderScherm()
    await screen.findByText(/Verhuurder Vastgoed B.V./)
    const chips = screen.getAllByTestId('voorstel-historie')
    expect(chips[0]).toHaveTextContent('historie-regel — 12 van 12 op 4400 Huur')
    expect(chips[0]).toHaveClass('geheugen')
    expect(chips[1]).toHaveTextContent('historie: 4 van 6 op 4300 Telefoon — bevestigen')
    expect(chips[1]).toHaveClass('ai')
    expect(screen.getByTestId('ai-toets-twijfel')).toHaveTextContent('AI-twijfel: bedrag afwijkend van de historie')
    expect(screen.getByTestId('ai-toets-overgeslagen')).toHaveTextContent('zonder AI-toets: avg_gate — intake-AI staat uit')
    // Geen lege/wachtende voorstel-kaart voor een historie-regel (open_post is null).
    expect(screen.queryByTestId('voorstel-kaart')).not.toBeInTheDocument()
  })

  it('toont het 3×-regelvoorstel als hint', async () => {
    installFetchMock({
      mutaties: [
        mutatie({
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
          regel_voorstel: {
            tegenpartij_sleutel: 'bank ing n v',
            ledger_id: '11111111-0000-0000-0000-000000000011',
            taxrate_id: null,
            aantal_boekingen: 3,
          },
        }),
      ],
    })
    renderScherm()

    expect(await screen.findByText(/Al 3× zo geboekt/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Boeken…' })).toBeInTheDocument()
  })

  it('blok 1 (08-09): nog-niet-gesynchroniseerd is een neutrale regel ("vannacht automatisch"), geen start-opdracht; de versheid is een zichtbare chip', async () => {
    installFetchMock({ rekeningenBody: { ooit_gesynchroniseerd: false, laatste_sync_op: null }, mutaties: [] })
    renderScherm()

    expect(await screen.findByText(/nog niet gesynchroniseerd — vannacht automatisch/)).toBeInTheDocument()
    expect(screen.queryByText(/start hieronder de eerste/)).not.toBeInTheDocument()
    const kop = screen.getByTestId('ververs-hint')
    // De versheid staat in een chip (role=status), niet als losse grijze tekst.
    await waitFor(() => expect(kop.querySelector('.chip')).not.toBeNull())
    expect(kop.querySelector('.chip')).toHaveAttribute('role', 'status')
  })

  it('blok 1 (08-09): ná een afgeronde achtergrondronde toont de chip "zojuist ververst" (groen = status) en is de lijst herladen', async () => {
    const syncAchtergrondAanroepen: string[] = []
    installFetchMock({ syncAchtergrondAanroepen, syncAchtergrondKlaarResultaat: { afletteren_wachtend: 0 } })
    renderScherm()
    await screen.findByText(/Bouwmaat Nederland B.V./)
    const fetchMock = vi.mocked(fetch)
    const mutatiesVoor = fetchMock.mock.calls.filter(([u]) => String(u).includes('/mutaties')).length
    await userEvent.click(screen.getByRole('button', { name: 'Nu verversen uit Reeleezee' }))
    const chip = await screen.findByText(/zojuist ververst/)
    expect(chip).toHaveClass('chip', 'ok')
    // De mutatielijst is ná `klaar` opnieuw opgehaald (onKlaar → verversAlles).
    await waitFor(() =>
      expect(fetchMock.mock.calls.filter(([u]) => String(u).includes('/mutaties')).length).toBeGreaterThan(mutatiesVoor),
    )
  })

  it('blok 6a (08-09): verwerkte opdrachten ouder dan 30 dagen staan achter "Toon verwerkte mutaties ouder dan 30 dagen (N)"; de toggle haalt ze server-side op', async () => {
    const afletterAanroepen: string[] = []
    const oud = {
      opdracht: afletterOpdracht({ id: 'oud-1', status: 'geverifieerd', geverifieerd_op: '2026-07-01T10:00:00Z', klaargezet_op: '2026-06-30T10:00:00Z' }),
      boekdatum: '2026-06-29',
      tegenpartij_naam: 'Oude Tegenpartij B.V.',
      bedrag: '-10.00',
    }
    installFetchMock({ afletterOpdrachten: [], aantalOud: 1, afletterOpdrachtenOud: [oud], afletterAanroepen, mutaties: [] })
    renderScherm()

    // Sectie zichtbaar dankzij de teller, ook zonder recente rijen; de oude rij zelf nog niet.
    const toggle = await screen.findByLabelText('Toon verwerkte mutaties ouder dan 30 dagen (1)')
    expect(screen.queryByText('Oude Tegenpartij B.V.')).not.toBeInTheDocument()
    expect(afletterAanroepen.some((u) => u.includes('toon_oud=true'))).toBe(false)

    await userEvent.click(toggle)
    expect(await screen.findByText('Oude Tegenpartij B.V.')).toBeInTheDocument()
    expect(afletterAanroepen.some((u) => u.includes('toon_oud=true'))).toBe(true)
    // Teller blijft zichtbaar met de toggle aan.
    expect(screen.getByLabelText('Toon verwerkte mutaties ouder dan 30 dagen (1)')).toBeChecked()
  })

  it('blok C (16-09): een vermoede dubbele betaling is een oranje chip "mogelijk dubbel betaald" mét de zin als tooltip; zonder vermoeden geen chip', async () => {
    const tekst =
      'Aan Bouwmaat Nederland B.V. is € 1.847,23 twee keer betaald (18-08 en 03-09) voor wat één factuur lijkt — controleer of terugvordering nodig is.'
    installFetchMock({
      mutaties: [
        mutatie({
          dubbele_betaling: { tekst, datums: ['2026-08-18', '2026-09-03'], bedrag: '1847.23', mutatie_ids: [MUTATIE_ID, OPDRACHT_ID] },
        }),
      ],
    })
    renderScherm()

    const chip = await screen.findByTestId('chip-dubbele-betaling')
    expect(chip).toHaveTextContent('mogelijk dubbel betaald')
    expect(chip).toHaveAttribute('title', tekst)
    expect(chip.className).toContain('afwijking')
  })

  it('blok C (16-09): zonder vermoeden geen dubbele-betaling-chip', async () => {
    installFetchMock()
    renderScherm()
    await screen.findByText(/Bouwmaat Nederland B.V./)
    expect(screen.queryByTestId('chip-dubbele-betaling')).not.toBeInTheDocument()
  })

  it('toont de onboarding-melding zonder bankaanlevering', async () => {
    installFetchMock({
      rekeningenBody: { heeft_bankaanlevering: false },
      mutaties: [],
    })
    renderScherm()

    expect(await screen.findByText(/Geen bankaanlevering gevonden/)).toBeInTheDocument()
  })
})


/** Blok A/C/D 16-09 (Peter, screenshot Bouwadvies Oost Nederland): zoekveld op tegenpartij/IBAN/bedrag/nummer mét teller en
 * totaal, klik op de naam vult het zoekveld, batch-kaart mét "Afletteren (N)" = één POST, compacte "N facturen gekoppeld"-regel
 * met de volledige lijst in de uitklap. */
describe('BankDetailScreen — zoekveld, batch en compacte koppelingen (16-09)', () => {
  afterEach(() => vi.unstubAllGlobals())

  const BATCH = {
    sleutel: 'RLZEE_CT_20260915_101500_4471_0001',
    aantal: 2,
    som: '40723.85',
    open_bedrag: '-40723.85',
    verschil: '0.00',
    sluit: true,
    posten: [
      { id: 'p1', bedrag: '-40000.00', referentie: '700', referentie2: null, rlz_document_id: null, boekstuknummer: 'RLZ-04-00000497', klantreferentie: '92953485', tegenpartij_naam: 'Leverancier 0' },
      { id: 'p2', bedrag: '-723.85', referentie: '701', referentie2: null, rlz_document_id: null, boekstuknummer: 'RLZ-04-00000498', klantreferentie: '92953490', tegenpartij_naam: 'Leverancier 1' },
    ],
  }
  const koppelingen = Array.from({ length: 14 }, (_, i) => ({
    document_id: `d${i}`,
    boekstuknummer: `RLZ-04-0000${480 + i}`,
    referentie: `9295${3400 + i}`,
    bedrag: '1053.71',
    document_type: 1,
    omschrijving: null,
  }))
  const batchMutatie = mutatie({
    id: 'm-batch',
    bedrag: '-560925.88',
    open_bedrag: '-40723.85',
    deels_afgeletterd: true,
    rlz_koppelingen: koppelingen,
    tegenpartij_naam: 'TOTAAL 14 VZ',
    omschrijving: 'TOTAAL 14 VZ betaalkenmerk: PREF',
    tegenrekening_iban: null,
    voorstel: {
      soort: 'batch',
      kleur: 'groen',
      bron: 'betaalbatch RLZEE_CT_20260915_101500_4471_0001, 2 facturen',
      reden: 'RLZ-betaalbatch …',
      payment_item_id: null,
      open_post: null,
      regel_id: null,
      regels: [],
      batch: BATCH,
    },
  })
  const zuilichem = mutatie({ id: 'm-z', tegenpartij_naam: 'Heren van Zuilichem B.V.', omschrijving: 'huur september', bedrag: '385000.00', open_bedrag: '385000.00', tegenrekening_iban: 'NL39RABO0300065264', voorstel: { soort: 'handmatig', kleur: 'oranje', bron: 'handmatig', reden: '', payment_item_id: null, open_post: null, regel_id: null, regels: [] } })

  it('zoekveld filtert op naam/IBAN/bedrag/nummer mét teller en totaal; klik op de naam vult het veld; Escape leegt', async () => {
    installFetchMock({ mutaties: [mutatie(), batchMutatie, zuilichem] })
    const gebruiker = userEvent.setup()
    renderScherm()
    const veld = await screen.findByTestId('bank-zoekveld')
    const rijen = () => document.querySelectorAll('table.bank-tabel > tbody > tr').length
    expect(rijen()).toBe(3)
    await gebruiker.type(veld, 'zuilichem')
    expect(screen.getByTestId('bank-zoek-teller')).toHaveTextContent('1 van 3')
    expect(screen.getByTestId('bank-zoek-teller')).toHaveTextContent('€ 385.000,00 in 1 mutatie')
    expect(rijen()).toBe(1)
    await gebruiker.clear(veld)
    await gebruiker.type(veld, '560.925,88')
    expect(screen.getByTestId('bank-zoek-teller')).toHaveTextContent('1 van 3')
    expect(screen.getByText('TOTAAL 14 VZ')).toBeInTheDocument()
    await gebruiker.clear(veld)
    await gebruiker.type(veld, '92953490') // factuurnummer in de batch-posten
    expect(screen.getByTestId('bank-zoek-teller')).toHaveTextContent('1 van 3')
    await gebruiker.clear(veld)
    await gebruiker.type(veld, 'NL39 RABO')
    expect(screen.getByTestId('bank-zoek-teller')).toHaveTextContent('1 van 3')
    await gebruiker.clear(veld)
    await gebruiker.type(veld, 'bestaat-niet')
    expect(screen.getByTestId('bank-zoek-leeg')).toHaveTextContent('Geen mutatie past bij “bestaat-niet”')
    await gebruiker.keyboard('{Escape}')
    expect(rijen()).toBe(3)
    // Klik op de tegenpartijnaam = zoekveld gevuld met die naam.
    await gebruiker.click(screen.getByRole('button', { name: 'Heren van Zuilichem B.V.' }))
    expect(veld).toHaveValue('Heren van Zuilichem B.V.')
    expect(rijen()).toBe(1)
  })

  it('batch-voorstel: kaart mét N facturen en som, posten in de uitklap, "Afletteren (2)" = één POST afletteren-batch', async () => {
    const batchAanroepen: string[] = []
    installFetchMock({ mutaties: [batchMutatie], batchAanroepen })
    const gebruiker = userEvent.setup()
    renderScherm()
    const kaart = await screen.findByTestId('batch-kaart')
    expect(kaart).toHaveTextContent('Betaalbatch RLZEE_CT_20260915_101500_4471_0001')
    expect(kaart).toHaveTextContent('2 facturen · som € 40.723,85 · open € -40.723,85')
    expect(kaart).toHaveTextContent('betaalbatch — 2 facturen, som cent-exact')
    expect(screen.queryByTestId('batch-verschil')).not.toBeInTheDocument()
    expect(within(kaart).getByTestId('batch-posten')).toHaveTextContent('RLZ-04-00000497')
    await gebruiker.click(screen.getByTestId('batch-afletteren'))
    await waitFor(() => expect(batchAanroepen).toHaveLength(1))
    expect(batchAanroepen[0]).toBe(`/administraties/${ADMINISTRATIE_ID}/bank/mutaties/m-batch/afletteren-batch`)
    expect(await screen.findByText(/Betaalbatch RLZEE_CT_20260915_101500_4471_0001: 2 gekoppeld\./)).toBeInTheDocument()
  })

  it('oranje batch toont het verschil; mislukte batch-aflettering blijft als fout in de rij staan', async () => {
    const oranje = mutatie({
      ...batchMutatie,
      voorstel: { ...batchMutatie.voorstel, kleur: 'oranje', batch: { ...BATCH, som: '40700.00', verschil: '23.85', sluit: false } },
    })
    installFetchMock({
      mutaties: [oranje],
      batchResponse: {
        sleutel: BATCH.sleutel,
        gekoppeld: 0,
        overgeslagen: 0,
        mislukt: 2,
        rijen: [
          { payment_item_id: 'p1', uitkomst: 'wacht_op_mens_in_rlz', fout: '_InvalidData (simulatie)', opdracht_id: 'o1' },
          { payment_item_id: 'p2', uitkomst: 'niet_uitgevoerd', fout: 'niet uitgevoerd ná een eerdere API-fout', opdracht_id: null },
        ],
      },
    })
    const gebruiker = userEvent.setup()
    renderScherm()
    expect(await screen.findByTestId('batch-verschil')).toHaveTextContent('verschil € 23,85')
    await gebruiker.click(screen.getByTestId('batch-afletteren'))
    expect(await screen.findByText(/2 niet gelukt\. Eerste fout: _InvalidData/)).toBeInTheDocument()
  })

  it('deels afgeletterd mét 14 koppelingen: één compacte regel, volledige lijst in de uitklap (monospace)', async () => {
    installFetchMock({ mutaties: [batchMutatie] })
    renderScherm()
    const compact = await screen.findByTestId('deels-afgeletterd-koppelingen')
    expect(compact.tagName).toBe('DETAILS')
    expect(compact.querySelector('summary')).toHaveTextContent('14 facturen gekoppeld · open € -40.723,85')
    expect(compact.querySelectorAll('tbody tr')).toHaveLength(14)
    expect(compact).toHaveTextContent('RLZ-04-0000480')
    expect(compact).toHaveTextContent('92953413')
  })
})
