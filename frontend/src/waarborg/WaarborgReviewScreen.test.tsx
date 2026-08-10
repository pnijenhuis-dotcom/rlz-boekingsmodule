import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { WaarborgReviewScreen } from './WaarborgReviewScreen'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const LEDGER_ID = 'cccccccc-0000-0000-0000-000000000003'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function documentDetail(overrides: Record<string, unknown> = {}) {
  return {
    id: DOCUMENT_ID,
    administratie_id: ADMINISTRATIE_ID,
    bestandsnaam: 'vastly-waarborg-ct-2026-0042.xml',
    status: 'te_controleren',
    bron: 'email',
    soort: 'waarborg',
    mogelijk_duplicaat_van: null,
    toegewezen_aan: null,
    aangemaakt_op: '2026-08-10T09:00:00Z',
    laatst_gewijzigd_op: '2026-08-10T09:00:00Z',
    veldvoorstel: null,
    afwijzing: null,
    tijdlijn: [],
    ...overrides,
  }
}

function voorstel(overrides: Record<string, unknown> = {}) {
  return {
    document_id: DOCUMENT_ID,
    bericht_id: '7d444840-9dc0-11d1-b245-5ffdce74fad2',
    verhuurder_entiteit: 'Rubicon Investments B.V.',
    contract_referentie: 'CT-2026-0042',
    huurder: 'J. de Tester',
    bedrag: '1500.00',
    richting: 'ontvangst',
    datum: '2026-08-01',
    balans_gb_code: '0204',
    balans_ledger_id: 'dddddddd-0000-0000-0000-000000000005',
    balans_gb_status: 'bekend',
    tegenrekening_ledger_id: null,
    status: 'open',
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
  boekenAntwoord?: () => Response
}

function installFetchMock(opties: MockOpties = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/tegenrekening') && init?.method === 'PUT') {
        opties.putAanroepen?.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
        const gekozen = init.body ? (JSON.parse(String(init.body)) as { tegenrekening_ledger_id: string | null }) : null
        return Promise.resolve(
          jsonResponse(voorstel({ ...opties.voorstelBody, tegenrekening_ledger_id: gekozen?.tegenrekening_ledger_id ?? null })),
        )
      }
      if (url.includes('/waarborg/') && url.endsWith('/voorstel')) {
        return Promise.resolve(jsonResponse(voorstel(opties.voorstelBody ?? {})))
      }
      if (url.endsWith('/checks') && init?.method === 'POST') {
        opties.checksAanroepen?.push(url)
        if (opties.checksAntwoord) return Promise.resolve(opties.checksAntwoord())
        return Promise.resolve(
          jsonResponse({
            geblokkeerd: false,
            resultaten: [{ naam: 'verplichte_velden', ok: true, melding: 'Alle verplichte velden zijn gevuld' }],
          }),
        )
      }
      if (url.endsWith('/boeken') && init?.method === 'POST') {
        if (opties.boekenAntwoord) return Promise.resolve(opties.boekenAntwoord())
        return Promise.resolve(
          jsonResponse({
            document_id: DOCUMENT_ID,
            status: 'geboekt',
            memoriaal_rlz_id: 'e1e1e1e1-0000-0000-0000-000000000009',
            rlz_boekstuknummer: 'RLZ-06-00000777',
          }),
        )
      }
      if (url.includes('/documenten/') && url.endsWith('/bestand')) {
        return Promise.resolve(
          new Response('<?xml version="1.0"?><VastlyWaarborg versie="1.0"><BerichtId>x</BerichtId></VastlyWaarborg>', {
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
          jsonResponse({ rekeningen: [{ ledger_id: LEDGER_ID, code: '2050', naam: 'Kruisposten' }] }),
        )
      }
      return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
    }),
  )
}

function renderScherm() {
  return render(
    <MemoryRouter initialEntries={[`/waarborg/${ADMINISTRATIE_ID}/${DOCUMENT_ID}`]}>
      <Routes>
        <Route path="/waarborg/:administratieId/:documentId" element={<WaarborgReviewScreen />} />
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('WaarborgReviewScreen', () => {
  it('toont de brongegeven berichtvelden read-only met de balans-GB-status', async () => {
    installFetchMock()
    renderScherm()

    expect(await screen.findByText(/VASTLY-WAARBORG-bericht/)).toBeInTheDocument()
    expect(screen.getByText('CT-2026-0042')).toBeInTheDocument()
    expect(screen.getByText('J. de Tester')).toBeInTheDocument()
    expect(screen.getByText(/€ 1\.500,00/)).toBeInTheDocument()
    expect(screen.getByText('bekend in het rekeningschema')).toBeInTheDocument()
    // Geen invoervelden voor berichtdata — alleen de tegenrekening-combobox.
    expect(screen.getByLabelText(/Tegenrekening/)).toBeInTheDocument()
  })

  it('draait de checks automatisch bij openen en de tegenrekening-keuze triggert opslaan + checks', async () => {
    const putAanroepen: { url: string; body: unknown }[] = []
    const checksAanroepen: string[] = []
    installFetchMock({
      putAanroepen,
      checksAanroepen,
      checksAntwoord: () =>
        jsonResponse({
          geblokkeerd: true,
          resultaten: [{ naam: 'verplichte_velden', ok: false, melding: 'Ontbrekend: tegenrekening' }],
        }),
    })
    renderScherm()

    expect(await screen.findByText(/Ontbrekend: tegenrekening/)).toBeInTheDocument()
    expect(checksAanroepen).toHaveLength(1)
    expect(putAanroepen).toHaveLength(0)
    expect(screen.getByRole('button', { name: /Boeken in RLZ/ })).toBeDisabled()

    const gebruiker = userEvent.setup()
    await gebruiker.click(screen.getByLabelText(/Tegenrekening/))
    await waitFor(() => expect(screen.getByRole('option', { name: /Kruisposten/ })).toBeInTheDocument())
    await gebruiker.click(screen.getByRole('option', { name: /Kruisposten/ }))

    await waitFor(() => expect(putAanroepen.length).toBeGreaterThanOrEqual(1), { timeout: 4000 })
    await waitFor(() => expect(checksAanroepen.length).toBeGreaterThanOrEqual(2), { timeout: 4000 })
    expect((putAanroepen[0].body as { tegenrekening_ledger_id: string }).tegenrekening_ledger_id).toBe(LEDGER_ID)
  })

  it('boekt zodra de checks groen zijn en toont het memoriaal-boekstuknummer', async () => {
    installFetchMock()
    renderScherm()
    await screen.findByText(/VASTLY-WAARBORG-bericht/)

    await waitFor(() => expect(screen.getByRole('button', { name: /Boeken in RLZ/ })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: /Boeken in RLZ/ }))

    expect(await screen.findByText(/Geboekt in RLZ als memoriaal/)).toBeInTheDocument()
    expect(screen.getByText('RLZ-06-00000777')).toBeInTheDocument()
  })

  it('toont een pop-up met de gefaalde checks bij een 409-blokkade van de boekactie', async () => {
    installFetchMock({
      boekenAntwoord: () =>
        jsonResponse(
          {
            detail: {
              melding: 'Boeken geblokkeerd door harde checks',
              checks: {
                geblokkeerd: true,
                resultaten: [{ naam: 'duplicaat', ok: false, melding: 'dit bericht is al geboekt' }],
              },
            },
          },
          409,
        ),
    })
    renderScherm()
    await screen.findByText(/VASTLY-WAARBORG-bericht/)
    await waitFor(() => expect(screen.getByRole('button', { name: /Boeken in RLZ/ })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: /Boeken in RLZ/ }))

    const dialoog = await screen.findByRole('dialog')
    expect(dialoog).toHaveTextContent('Boeken geblokkeerd door harde checks')
    expect(dialoog).toHaveTextContent('al geboekt')
  })
})
