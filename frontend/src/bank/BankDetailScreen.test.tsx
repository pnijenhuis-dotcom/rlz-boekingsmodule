import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
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
      bron: 'exacte match — referentie + bedrag',
      reden: 'Referentie gevonden én bedrag exact gelijk',
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
  klaarzettenAanroepen?: { url: string; body: unknown }[]
  klaarzettenResponse?: { opdracht_id: string; uitkomst: string; fout: string | null }
  voerUitAanroepen?: string[]
  voerUitResponse?: { opdracht_id: string; uitkomst: string; fout: string | null }
  intrekkenAanroepen?: string[]
  boekenAanroepen?: { url: string; body: unknown }[]
  verifieerAanroepen?: string[]
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
        return Promise.resolve(jsonResponse({ opdrachten: opties.afletterOpdrachten ?? [] }))
      }
      if (url.includes('/verifieer-afletteren') && init?.method === 'POST') {
        opties.verifieerAanroepen?.push(url)
        return Promise.resolve(jsonResponse({ geverifieerd: 1 }))
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
      return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
    }),
  )
}

function renderScherm() {
  return render(
    <MemoryRouter initialEntries={[`/bank/${ADMINISTRATIE_ID}`]}>
      <Routes>
        <Route path="/bank/:administratieId" element={<BankDetailScreen />} />
      </Routes>
    </MemoryRouter>,
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
    expect(screen.getByText('exacte match — referentie + bedrag')).toBeInTheDocument()
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
    await userEvent.click(screen.getByRole('button', { name: 'Intrekken' }))
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

  it('draait de verificatieronde met de "Nu verifiëren"-knop en meldt het resultaat', async () => {
    const verifieerAanroepen: string[] = []
    installFetchMock({ verifieerAanroepen })
    renderScherm()

    await userEvent.click(await screen.findByRole('button', { name: /Nu verifiëren/ }))

    await waitFor(() => expect(verifieerAanroepen).toHaveLength(1))
    expect(verifieerAanroepen[0]).toContain(`/bank/rekeningen/${REKENING_ID}/verifieer-afletteren`)
    expect(await screen.findByText(/1 aflettering\(en\) geverifieerd/)).toBeInTheDocument()
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

  it('toont de onboarding-melding zonder bankaanlevering', async () => {
    installFetchMock({
      rekeningenBody: { heeft_bankaanlevering: false },
      mutaties: [],
    })
    renderScherm()

    expect(await screen.findByText(/Geen bankaanlevering gevonden/)).toBeInTheDocument()
  })
})
