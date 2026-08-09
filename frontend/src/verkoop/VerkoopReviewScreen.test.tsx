import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { VerkoopReviewScreen } from './VerkoopReviewScreen'

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
    bestandsnaam: 'vastly-factuur-VF-2026-0012.xml',
    status: 'te_controleren',
    bron: 'email',
    soort: 'verkoopfactuur',
    mogelijk_duplicaat_van: null,
    toegewezen_aan: null,
    aangemaakt_op: '2026-08-09T09:00:00Z',
    laatst_gewijzigd_op: '2026-08-09T09:00:00Z',
    veldvoorstel: null,
    afwijzing: null,
    tijdlijn: [],
    ...overrides,
  }
}

function voorstel(overrides: Record<string, unknown> = {}) {
  return {
    document_id: DOCUMENT_ID,
    debiteur_naam: 'Huurder Jansen B.V.',
    factuurnummer: 'VF-2026-0012',
    factuurdatum: '2026-08-01',
    totaalbedrag_incl: '1270.50',
    is_creditnota: false,
    gecrediteerd_factuurnummer: null,
    regels: [
      {
        volgnummer: 1,
        omschrijving: 'Huur augustus 2026',
        netto_bedrag: '1000.00',
        btw_bedrag: '210.00',
        gb_code: '8000',
        ledger_id: LEDGER_ID,
        taxrate_id: TAXRATE_ID,
        gb_code_status: 'bekend',
        herkomst: 'ubl',
      },
      {
        volgnummer: 2,
        omschrijving: 'Servicekosten',
        netto_bedrag: '50.00',
        btw_bedrag: '10.50',
        gb_code: '9999',
        ledger_id: null,
        taxrate_id: null,
        gb_code_status: 'onbekend',
        herkomst: 'ubl',
      },
    ],
    opgeslagen: false,
    rlz_boekstuknummer: null,
    ...overrides,
  }
}

interface MockOpties {
  detail?: Record<string, unknown>
  voorstelBody?: Record<string, unknown>
  putAanroepen?: { url: string; body: unknown }[]
  checksAanroepen?: string[]
  checksAntwoord?: () => Response
  boekenAanroepen?: string[]
  boekenAntwoord?: () => Response
}

function installFetchMock(opties: MockOpties = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.includes('/verkoop/') && url.endsWith('/voorstel') && init?.method === 'PUT') {
        opties.putAanroepen?.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
        return Promise.resolve(jsonResponse(voorstel({ ...opties.voorstelBody, opgeslagen: true })))
      }
      if (url.includes('/verkoop/') && url.endsWith('/voorstel')) {
        return Promise.resolve(jsonResponse(voorstel(opties.voorstelBody ?? {})))
      }
      if (url.endsWith('/checks') && init?.method === 'POST') {
        opties.checksAanroepen?.push(url)
        if (opties.checksAntwoord) return Promise.resolve(opties.checksAntwoord())
        return Promise.resolve(
          jsonResponse({
            voorstel: voorstel(opties.voorstelBody ?? {}),
            checks: {
              geblokkeerd: false,
              resultaten: [
                { naam: 'GB-codes bekend', ok: true, melding: 'Alle regels hebben een bekende grootboekrekening' },
                { naam: 'Totalen sluiten', ok: true, melding: 'Regels sluiten aan op het totaalbedrag incl. btw' },
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
            verkoop_referentie: 'RLZ-411',
            verkoop_boekstuknummer: 'RLZ-01-00000442',
          }),
        )
      }
      if (url.includes('/documenten/') && url.endsWith('/bestand')) {
        return Promise.resolve(
          new Response('<?xml version="1.0"?><Invoice><cbc:ID>VF-2026-0012</cbc:ID></Invoice>', {
            status: 200,
            headers: { 'Content-Type': 'application/xml' },
          }),
        )
      }
      if (url.includes(`/documenten/${DOCUMENT_ID}`)) {
        return Promise.resolve(jsonResponse(documentDetail(opties.detail ?? {})))
      }
      if (url.includes('/grootboek')) {
        return Promise.resolve(
          jsonResponse({ rekeningen: [{ ledger_id: LEDGER_ID, code: '8000', naam: 'Omzet verhuur' }] }),
        )
      }
      if (url.includes('/btw-codes')) {
        return Promise.resolve(
          jsonResponse({ btw_codes: [{ id: TAXRATE_ID, naam: 'NL, Hoog tarief', percentage: '0.21' }] }),
        )
      }
      return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
    }),
  )
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:test'), revokeObjectURL: vi.fn() }))
}

function renderScherm() {
  return render(
    <MemoryRouter initialEntries={[`/verkoop/${ADMINISTRATIE_ID}/${DOCUMENT_ID}`]}>
      <Routes>
        <Route path="/verkoop/:administratieId/:documentId" element={<VerkoopReviewScreen />} />
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('VerkoopReviewScreen', () => {
  it('toont de kopvelden en regels uit het voorstel, met de UBL-herkomstchips', async () => {
    installFetchMock()
    renderScherm()

    expect(await screen.findByText(/UBL-verkoopfactuur \(VASTLY-VERKOOP\)/)).toBeInTheDocument()
    expect(screen.getByLabelText('Debiteur (huurder)')).toHaveValue('Huurder Jansen B.V.')
    expect(screen.getByLabelText('Factuurnummer')).toHaveValue('VF-2026-0012')
    expect(screen.getByLabelText('Totaalbedrag (incl. btw)')).toHaveValue('1270.50')
    expect(screen.getByDisplayValue('Huur augustus 2026')).toBeInTheDocument()
    expect(screen.getByDisplayValue('Servicekosten')).toBeInTheDocument()
    // Beide regels komen deterministisch uit de UBL.
    expect(screen.getAllByText('uit UBL')).toHaveLength(2)
    expect(screen.getByText(/verkoopfactuur · Vastly/)).toBeInTheDocument()
  })

  it('toont de UBL-bron als geformatteerde XML in het linkerpaneel', async () => {
    installFetchMock()
    renderScherm()

    // formatteerXml legt elke tag op een eigen regel — match op de openingstag + inhoud.
    expect(await screen.findByText(/<cbc:ID>VF-2026-0012/)).toBeInTheDocument()
  })

  it('markeert een onbekende GB-code met een blokkerende chip en een waarschuwingsbanner', async () => {
    installFetchMock()
    renderScherm()

    expect(await screen.findByText('onbekende code 9999')).toBeInTheDocument()
    expect(screen.getByText(/zonder bekende\s+grootboekrekening/)).toBeInTheDocument()
  })

  it('toont de "geen GB-code — kies zelf"-chip als de UBL geen code meegaf', async () => {
    const body = voorstel()
    ;(body.regels as Record<string, unknown>[])[1] = {
      ...(body.regels as Record<string, unknown>[])[1],
      gb_code: null,
      gb_code_status: 'ontbreekt',
    }
    installFetchMock({ voorstelBody: body })
    renderScherm()

    expect(await screen.findByText('geen GB-code — kies zelf')).toBeInTheDocument()
  })

  it('toont de creditnota-chip met het gecrediteerde factuurnummer', async () => {
    installFetchMock({ voorstelBody: { is_creditnota: true, gecrediteerd_factuurnummer: 'VF-2026-0005' } })
    renderScherm()

    expect(await screen.findByText(/Creditnota — crediteert VF-2026-0005/)).toBeInTheDocument()
  })

  it('checks uitvoeren slaat eerst op en toont een blokkerende check; boeken blijft geblokkeerd', async () => {
    const putAanroepen: { url: string; body: unknown }[] = []
    const checksAanroepen: string[] = []
    installFetchMock({
      putAanroepen,
      checksAanroepen,
      checksAntwoord: () =>
        jsonResponse({
          voorstel: voorstel(),
          checks: {
            geblokkeerd: true,
            resultaten: [
              { naam: 'GB-codes bekend', ok: false, melding: 'Regel 2 heeft een onbekende grootboekcode (9999)' },
            ],
          },
        }),
    })
    renderScherm()
    await screen.findByText(/UBL-verkoopfactuur/)

    await userEvent.click(screen.getByRole('button', { name: 'Checks uitvoeren' }))

    expect(await screen.findByText(/onbekende grootboekcode \(9999\)/)).toBeInTheDocument()
    expect(screen.getByText('Blokkerend')).toBeInTheDocument()
    expect(putAanroepen).toHaveLength(1)
    expect(checksAanroepen).toHaveLength(1)
    expect(screen.getByRole('button', { name: /Boeken in RLZ/ })).toBeDisabled()
  })

  it('boekknop is geblokkeerd tot de checks groen zijn, daarna boekt hij en toont het boekstuknummer', async () => {
    const putAanroepen: { url: string; body: unknown }[] = []
    const checksAanroepen: string[] = []
    const boekenAanroepen: string[] = []
    installFetchMock({ putAanroepen, checksAanroepen, boekenAanroepen })
    renderScherm()
    await screen.findByText(/UBL-verkoopfactuur/)

    const boekKnop = screen.getByRole('button', { name: /Boeken in RLZ/ })
    expect(boekKnop).toBeDisabled()

    await userEvent.click(screen.getByRole('button', { name: 'Checks uitvoeren' }))
    await screen.findByText(/Alle regels hebben een bekende grootboekrekening/)
    expect(checksAanroepen).toHaveLength(1)

    await waitFor(() => expect(screen.getByRole('button', { name: /Boeken in RLZ/ })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: /Boeken in RLZ/ }))

    await screen.findByText(/Geboekt in RLZ — verkoopfactuur/)
    expect(boekenAanroepen).toHaveLength(1)
    expect(screen.getByText('RLZ-01-00000442')).toBeInTheDocument()
  })

  it('toont het meegestuurde checkrapport bij een 409-blokkade van de boekactie', async () => {
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
                  { naam: 'Duplicaat', ok: false, melding: 'Factuurnummer VF-2026-0012 is al geboekt in RLZ' },
                ],
              },
            },
          },
          409,
        ),
    })
    renderScherm()
    await screen.findByText(/UBL-verkoopfactuur/)

    await userEvent.click(screen.getByRole('button', { name: 'Checks uitvoeren' }))
    await waitFor(() => expect(screen.getByRole('button', { name: /Boeken in RLZ/ })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: /Boeken in RLZ/ }))

    expect(await screen.findByText(/Boeken geblokkeerd door harde checks/)).toBeInTheDocument()
    expect(screen.getByText(/is al geboekt in RLZ/)).toBeInTheDocument()
  })

  it('een geboekt document is read-only en toont het RLZ-boekstuknummer', async () => {
    installFetchMock({
      detail: { status: 'geboekt' },
      voorstelBody: { opgeslagen: true, rlz_boekstuknummer: 'RLZ-01-00000442' },
    })
    renderScherm()

    expect(await screen.findByText(/geboekt in RLZ/)).toBeInTheDocument()
    expect(screen.getByText('RLZ-01-00000442')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Boeken in RLZ/ })).not.toBeInTheDocument()
  })
})
