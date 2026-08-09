import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ZoekenScreen } from './ZoekenScreen'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function documentHit(overrides: Record<string, unknown> = {}) {
  return {
    document_id: DOCUMENT_ID,
    administratie_id: ADMINISTRATIE_ID,
    administratie_naam: 'Kempen Groep B.V.',
    soort: 'inkoopfactuur',
    status: 'geboekt',
    bestandsnaam: 'bouwmaat-factuur.pdf',
    leverancier: 'Bouwmaat Nederland B.V.',
    referentie: '2026-0601',
    rlz_boekstuknummer: 'IF-2026-0219',
    totaalbedrag: '922.04',
    factuurdatum: '2026-06-20',
    aangemaakt_op: '2026-06-24T10:00:00Z',
    automatisch_geboekt: false,
    vragen: [],
    accordering: [],
    ...overrides,
  }
}

function installFetchMock(body: {
  documenten?: unknown[]
  audit?: unknown[]
}) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      const pad = String(url)
      if (pad.startsWith('/zoeken?term=')) {
        const term = decodeURIComponent(pad.slice('/zoeken?term='.length))
        return Promise.resolve(
          jsonResponse({ term, documenten: body.documenten ?? [], audit: body.audit ?? [] }),
        )
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

function renderScherm() {
  return render(
    <MemoryRouter initialEntries={['/zoeken']}>
      <Routes>
        <Route path="/zoeken" element={<ZoekenScreen />} />
        <Route path="/documenten/:administratieId/:documentId" element={<div>controlescherm-probe</div>} />
        <Route path="/omzet/:administratieId/:documentId" element={<div>omzetreview-probe</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('ZoekenScreen — globaal zoeken (mockup #zoeken)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('typt term → boekingen met leverancier, boekstuk in de geboekt-chip en klant zichtbaar', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({ documenten: [documentHit({ automatisch_geboekt: true })] })
    renderScherm()

    await gebruiker.type(screen.getByLabelText('Globaal zoeken'), 'bouwmaat')

    await waitFor(() => expect(screen.getByText(/Bouwmaat Nederland B\.V\./)).toBeInTheDocument())
    expect(screen.getByText('Boekingen (1)')).toBeInTheDocument()
    // Geboekt mét RLZ-boekstuknummer in de chip (mockup: "Geboekt · IF-2026-0219").
    expect(screen.getByText(/Geboekt · IF-2026-0219/)).toBeInTheDocument()
    expect(screen.getByText('Kempen Groep B.V.')).toBeInTheDocument()
    expect(screen.getByText(/922,04/)).toBeInTheDocument()
    expect(screen.getByText('automatisch')).toBeInTheDocument()
  })

  it('toont de accorderingshistorie compact in de Historie-kolom', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({
      documenten: [
        documentHit({
          accordering: [
            {
              volgnummer: 1,
              accordeur_naam: 'S. Bakker',
              besluit: 'akkoord',
              besluit_bron: 'handmatig',
              besloten_op: '2026-06-17T09:00:00Z',
            },
            {
              volgnummer: 2,
              accordeur_naam: 'R. Jansen',
              besluit: 'akkoord',
              besluit_bron: 'staande_goedkeuring',
              besloten_op: '2026-06-18T09:00:00Z',
            },
          ],
        }),
      ],
    })
    renderScherm()

    await gebruiker.type(screen.getByLabelText('Globaal zoeken'), 'bouwmaat')

    await waitFor(() => expect(screen.getByText(/akkoord S\. Bakker \(laag 1\)/)).toBeInTheDocument())
    expect(screen.getByText(/akkoord R\. Jansen \(laag 2\).*staande goedkeuring/)).toBeInTheDocument()
  })

  it('toont een vraag inline (eerste ~60 tekens + status)', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({
      documenten: [
        documentHit({
          status: 'vraag_open',
          rlz_boekstuknummer: null,
          vragen: [
            {
              vraag_tekst: 'Is deze levering voor project 26012 of voor de overhead van de werkplaats in Deurne?',
              antwoord_tekst: null,
              status: 'open',
            },
          ],
        }),
      ],
    })
    renderScherm()

    await gebruiker.type(screen.getByLabelText('Globaal zoeken'), 'bouwmaat')

    // Afgekapt op ~60 tekens: het begin is zichtbaar, het einde niet.
    await waitFor(() =>
      expect(screen.getByText(/vraag: .Is deze levering voor project 26012/)).toBeInTheDocument(),
    )
    expect(screen.queryByText(/Deurne/)).not.toBeInTheDocument()
    expect(screen.getByText(/— open/)).toBeInTheDocument()
  })

  it('toont de audit-sectie met tijdstip, gebruiker, actie en compact detail', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({
      audit: [
        {
          tijdstip: '2026-06-24T11:40:00Z',
          actor_naam: 'P. Nijenhuis',
          actie: 'document_geboekt',
          administratie_naam: 'Kempen Groep B.V.',
          detail: { referentie: '2026-0601', bedrag: '922.04' },
        },
      ],
    })
    renderScherm()

    await gebruiker.type(screen.getByLabelText('Globaal zoeken'), 'bouwmaat')

    await waitFor(() => expect(screen.getByText('Audit-gebeurtenissen (1)')).toBeInTheDocument())
    expect(screen.getByText('P. Nijenhuis')).toBeInTheDocument()
    expect(screen.getByText('document_geboekt')).toBeInTheDocument()
    expect(screen.getByText(/referentie: 2026-0601 · bedrag: 922\.04/)).toBeInTheDocument()
  })

  it('lege staat: duidelijke melding mét de gezochte term', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({})
    renderScherm()

    await gebruiker.type(screen.getByLabelText('Globaal zoeken'), 'bestaat-niet-xyz')

    await waitFor(() => expect(screen.getByText(/Geen resultaten voor .bestaat-niet-xyz./)).toBeInTheDocument())
  })

  it('zoekt niet onder de 2 tekens (geen aanroep, wél de typ-hint)', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({})
    renderScherm()

    await gebruiker.type(screen.getByLabelText('Globaal zoeken'), 'b')
    // Ruim voorbij de debounce wachten — er mag géén zoek-aanroep gedaan zijn.
    await new Promise((resolve) => setTimeout(resolve, 450))

    expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).startsWith('/zoeken'))).toHaveLength(0)
    expect(screen.getByText(/Typ minimaal 2 tekens/)).toBeInTheDocument()
  })

  it('rij-klik navigeert naar het reviewscherm van de juiste soort (kassarapport → omzet)', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({ documenten: [documentHit({ soort: 'kassarapport' })] })
    renderScherm()

    await gebruiker.type(screen.getByLabelText('Globaal zoeken'), 'bouwmaat')
    await waitFor(() => expect(screen.getByText(/Bouwmaat Nederland B\.V\./)).toBeInTheDocument())
    await gebruiker.click(screen.getByText(/Bouwmaat Nederland B\.V\./))

    await waitFor(() => expect(screen.getByText('omzetreview-probe')).toBeInTheDocument())
  })
})
