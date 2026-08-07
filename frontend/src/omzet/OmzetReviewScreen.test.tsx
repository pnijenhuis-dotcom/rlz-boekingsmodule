import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
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
    kasomzet_naam: null,
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

  it('boekknop is geblokkeerd tot de checks groen zijn, daarna boekt hij en toont boekstuknummers', async () => {
    const putAanroepen: { url: string; body: unknown }[] = []
    const checksAanroepen: string[] = []
    const boekenAanroepen: string[] = []
    installFetchMock({ putAanroepen, checksAanroepen, boekenAanroepen })
    renderScherm()
    await screen.findByText(/Rapport herkend:/)

    const boekKnop = screen.getByRole('button', { name: /Boeken in RLZ/ })
    expect(boekKnop).toBeDisabled()

    await userEvent.click(screen.getByRole('button', { name: 'Controleren' }))
    await screen.findByText(/Memoriaal sluit/)
    expect(checksAanroepen).toHaveLength(1)

    await waitFor(() => expect(screen.getByRole('button', { name: /Boeken in RLZ/ })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: /Boeken in RLZ/ }))

    await screen.findByText(/Geboekt in RLZ — verkoopfactuur/)
    expect(boekenAanroepen).toHaveLength(1)
    expect(screen.getByText('RLZ-01-00000393')).toBeInTheDocument()
    expect(screen.getByText('RLZ-06-00000502')).toBeInTheDocument()
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

    await userEvent.click(screen.getByRole('button', { name: 'Controleren' }))
    await waitFor(() => expect(screen.getByRole('button', { name: /Boeken in RLZ/ })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: /Boeken in RLZ/ }))

    expect(await screen.findByText(/Boeken geblokkeerd door harde checks/)).toBeInTheDocument()
    expect(screen.getByText(/Periode overlapt/)).toBeInTheDocument()
  })

  it('een geboekt document is read-only', async () => {
    installFetchMock({ detail: { status: 'geboekt' } })
    renderScherm()

    expect(await screen.findByText(/geboekt in RLZ\. Wijzigen kan alleen via stornering/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Boeken in RLZ/ })).not.toBeInTheDocument()
  })
})
