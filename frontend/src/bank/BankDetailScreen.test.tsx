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

interface MockOpties {
  mutaties?: unknown[]
  rekeningenBody?: Record<string, unknown>
  klaarzettenAanroepen?: { url: string; body: unknown }[]
  intrekkenAanroepen?: string[]
  boekenAanroepen?: { url: string; body: unknown }[]
}

function installFetchMock(opties: MockOpties = {}) {
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
        return Promise.resolve(jsonResponse({ mutaties: opties.mutaties ?? [mutatie()] }))
      }
      if (url.includes('/afletteren-klaarzetten') && init?.method === 'POST') {
        opties.klaarzettenAanroepen?.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
        return Promise.resolve(jsonResponse({ opdracht_id: OPDRACHT_ID, uitkomst: 'wacht_op_mens_in_rlz' }, 201))
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

  it('zet een afletter-voorstel klaar voor Reeleezee (assist-model)', async () => {
    const klaarzettenAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ klaarzettenAanroepen })
    renderScherm()

    await userEvent.click(await screen.findByRole('button', { name: /Klaarzetten voor RLZ/ }))

    await waitFor(() => expect(klaarzettenAanroepen).toHaveLength(1))
    expect(klaarzettenAanroepen[0].body).toEqual({ payment_item_id: ITEM_ID })
  })

  it('toont een klaargezette opdracht als wachtend op verificatie, met intrekken', async () => {
    const intrekkenAanroepen: string[] = []
    installFetchMock({
      intrekkenAanroepen,
      mutaties: [
        mutatie({
          afletter_opdracht: {
            id: OPDRACHT_ID,
            status: 'klaargezet',
            payment_item_id: ITEM_ID,
            klaargezet_op: '2026-08-02T10:00:00Z',
          },
        }),
      ],
    })
    renderScherm()

    expect(await screen.findByText(/Af te letteren in Reeleezee — wacht op verificatie/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Intrekken' }))
    await waitFor(() => expect(intrekkenAanroepen).toHaveLength(1))
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
