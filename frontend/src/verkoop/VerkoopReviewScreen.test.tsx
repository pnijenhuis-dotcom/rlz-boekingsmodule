import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { VerkoopReviewScreen } from './VerkoopReviewScreen'

// Node 22+ schaduwt window.localStorage in de jsdom-testomgeving met zijn eigen (lege)
// experimental global — in-memory vervanger, zelfde patroon als ReviewSplitter.test.tsx.
beforeAll(() => {
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
})

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
        btw_categorie: 'S',
        btw_percentage_ubl: '21.00',
        btw_vergrendeld: true,
        btw_bron: 'factuur',
        btw_kandidaten: [],
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
        btw_categorie: 'S',
        btw_percentage_ubl: '21.00',
        btw_vergrendeld: false,
        btw_bron: null,
        btw_kandidaten: [],
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

  it('vergrendelt de btw-code die uit de factuur volgt (geen combobox, wél de bron-chip)', async () => {
    installFetchMock()
    renderScherm()

    // Regel 1 is vergrendeld: chip met de factuur-btw, geen vrije keuze meer (blok A 2026-08-10).
    expect(await screen.findByText(/uit factuur \(S · 21%\)/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Btw-code regel 1')).not.toBeInTheDocument()
    // Regel 2 (niet deterministisch) houdt de combobox.
    expect(screen.getByLabelText('Btw-code regel 2')).toBeInTheDocument()
  })

  it('toont bij echte ambiguïteit de kandidaten-chip met eenmalige-keuze-uitleg', async () => {
    const body = voorstel()
    ;(body.regels as Record<string, unknown>[])[1] = {
      ...(body.regels as Record<string, unknown>[])[1],
      btw_kandidaten: [TAXRATE_ID, 'dddddddd-0000-0000-0000-000000000005'],
    }
    installFetchMock({ voorstelBody: body })
    renderScherm()

    expect(await screen.findByText(/2 passende tarieven \(S · 21%\) — kies\s+één keer/)).toBeInTheDocument()
  })

  it('toont de onthouden-keuze-chip wanneer de code uit het administratie-geheugen komt', async () => {
    const body = voorstel()
    ;(body.regels as Record<string, unknown>[])[0] = {
      ...(body.regels as Record<string, unknown>[])[0],
      btw_bron: 'onthouden',
    }
    installFetchMock({ voorstelBody: body })
    renderScherm()

    expect(await screen.findByText(/uit factuur \(S · 21%\) · onthouden keuze/)).toBeInTheDocument()
  })

  it('toont de creditnota-chip met het gecrediteerde factuurnummer', async () => {
    installFetchMock({ voorstelBody: { is_creditnota: true, gecrediteerd_factuurnummer: 'VF-2026-0005' } })
    renderScherm()

    expect(await screen.findByText(/Creditnota — crediteert VF-2026-0005/)).toBeInTheDocument()
  })

  it('draait de checks automatisch bij openen (read-only, zonder opslaan) en toont een blokkerende check', async () => {
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

    // Geen knop en geen menselijke handeling: het rapport verschijnt vanzelf.
    expect(await screen.findByText(/onbekende grootboekcode \(9999\)/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Checks uitvoeren/ })).not.toBeInTheDocument()
    expect(checksAanroepen).toHaveLength(1)
    // Bij openen wordt er NIET opgeslagen (read-only checks over voorstel/prefill).
    expect(putAanroepen).toHaveLength(0)
    expect(screen.getByRole('button', { name: /Boeken in RLZ/ })).toBeDisabled()
  })

  it('een wijziging triggert gedebounced automatisch opslaan + checks; daarna boekt de boekknop', async () => {
    const putAanroepen: { url: string; body: unknown }[] = []
    const checksAanroepen: string[] = []
    const boekenAanroepen: string[] = []
    installFetchMock({ putAanroepen, checksAanroepen, boekenAanroepen })
    renderScherm()
    await screen.findByText(/UBL-verkoopfactuur/)
    // De open-run is klaar zodra het groene resultaat er staat.
    await screen.findByText(/Alle regels hebben een bekende grootboekrekening/)
    expect(checksAanroepen).toHaveLength(1)

    await userEvent.type(screen.getByLabelText('Factuurnummer'), '9')

    // Debounce (800 ms) → automatisch opslaan + checks, zonder klik.
    await waitFor(() => expect(putAanroepen.length).toBeGreaterThanOrEqual(1), { timeout: 4000 })
    await waitFor(() => expect(checksAanroepen.length).toBeGreaterThanOrEqual(2), { timeout: 4000 })

    await waitFor(() => expect(screen.getByRole('button', { name: /Boeken in RLZ/ })).toBeEnabled(), {
      timeout: 4000,
    })
    await userEvent.click(screen.getByRole('button', { name: /Boeken in RLZ/ }))

    await screen.findByText(/Geboekt in RLZ — verkoopfactuur/)
    expect(boekenAanroepen).toHaveLength(1)
    expect(screen.getByText('RLZ-01-00000442')).toBeInTheDocument()
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
    await waitFor(() => expect(screen.getByRole('button', { name: /Boeken in RLZ/ })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: /Boeken in RLZ/ }))

    // Blok B: de server-side herdraaide checks blokkeren → POP-UP met de gefaalde check(s).
    const dialoog = await screen.findByRole('dialog')
    expect(dialoog).toHaveTextContent('Boeken geblokkeerd door harde checks')
    expect(dialoog).toHaveTextContent('is al geboekt in RLZ')
    await userEvent.click(screen.getByRole('button', { name: 'Sluiten' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('blok C: de "breed"-schakelaar stapelt de layout en bewaart de voorkeur in localStorage', async () => {
    window.localStorage.removeItem('rlz.verkoop.breedGestapeld')
    installFetchMock()
    const { container } = renderScherm()
    await screen.findByText(/UBL-verkoopfactuur/)

    // Standaard: naast elkaar (splitter aanwezig, geen gestapelde klasse).
    expect(container.querySelector('.review.review-gestapeld')).toBeNull()
    expect(container.querySelector('.review-splitter')).not.toBeNull()

    await userEvent.click(screen.getByRole('button', { name: '⬒ Breed' }))
    expect(container.querySelector('.review.review-gestapeld')).not.toBeNull()
    expect(container.querySelector('.review-splitter')).toBeNull()
    expect(window.localStorage.getItem('rlz.verkoop.breedGestapeld')).toBe('1')

    await userEvent.click(screen.getByRole('button', { name: '◫ Naast elkaar' }))
    expect(container.querySelector('.review.review-gestapeld')).toBeNull()
    expect(window.localStorage.getItem('rlz.verkoop.breedGestapeld')).toBe('0')
  })

  it('blok C: de bewaarde "breed"-voorkeur wordt bij openen hersteld', async () => {
    window.localStorage.setItem('rlz.verkoop.breedGestapeld', '1')
    installFetchMock()
    const { container } = renderScherm()
    await screen.findByText(/UBL-verkoopfactuur/)

    expect(container.querySelector('.review.review-gestapeld')).not.toBeNull()
    window.localStorage.removeItem('rlz.verkoop.breedGestapeld')
  })

  it('blok C (+ regelrij-UI 25-08): de regel-omschrijving is een meegroeiend doorloopveld met de volledige tekst als hover-title', async () => {
    installFetchMock()
    renderScherm()
    await screen.findByText(/UBL-verkoopfactuur/)

    const veld = screen.getByLabelText('Omschrijving regel 1')
    expect(veld.tagName).toBe('TEXTAREA')
    // Regelrij-UI 25-08: start op één regel en groeit mee met de inhoud (scrollHeight) — nooit afkappen.
    expect(veld).toHaveAttribute('rows', '1')
    expect(veld).toHaveAttribute('title', 'Huur augustus 2026')
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

  it('blok C (02-09): een geboekt document toont "Geboekt in RLZ · boekstuk · debiteur" mét de vindplaats-hint (Elissen-casus)', async () => {
    installFetchMock({
      detail: { status: 'geboekt', geboekt_in_rlz: {
      regel: 'Geboekt in RLZ · boekstuk RLZ-01-00000442 · J.G.M. Elissen Holding BV',
      boekstuknummer: 'RLZ-01-00000442',
      rlz_document_id: 'x',
      tegenpartij: 'J.G.M. Elissen Holding BV',
      tegenpartij_rol: 'debiteur',
      geboekt_op: '2026-09-02T10:00:00Z',
      memoriaal_boekstuknummer: null,
      vindplaats_hint: 'In RLZ zichtbaar op de debiteurenkaart en in het verkoopboek — níét in Verkopen → Facturen.',
    } },
      voorstelBody: { opgeslagen: true, rlz_boekstuknummer: 'RLZ-01-00000442' },
    })
    renderScherm()

    const regel = await screen.findByTestId('geboekt-in-rlz-regel')
    expect(regel).toHaveTextContent('Geboekt in RLZ · boekstuk RLZ-01-00000442 · J.G.M. Elissen Holding BV')
    expect(regel).toHaveTextContent('níét in Verkopen → Facturen')
    expect(screen.getByText(/Wijzigen kan alleen via stornering/)).toBeInTheDocument()
  })
})
