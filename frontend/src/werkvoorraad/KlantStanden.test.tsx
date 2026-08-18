/** Klantpagina = STANDEN (IA-besluit 15-08): tellers per documentsoort en per bankrekening,
 * secties alleen zichtbaar bij teller > 0 (toon-regel), klik opent het deelscherm. */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { KlantStanden } from './KlantStanden'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function doc(overrides: Record<string, unknown>) {
  return {
    id: crypto.randomUUID(),
    bestandsnaam: 'factuur.pdf',
    status: 'te_controleren',
    bron: 'upload',
    soort: 'inkoopfactuur',
    mogelijk_duplicaat_van: null,
    toegewezen_aan: null,
    aangemaakt_op: '2026-08-10T10:00:00Z',
    laatst_gewijzigd_op: '2026-08-10T10:00:00Z',
    automatisch_geboekt: false,
    leverancier: null,
    totaalbedrag: null,
    factuurdatum: null,
    afwijzing: null,
    ...overrides,
  }
}

function installMock({
  documenten = [] as unknown[],
  rekeningen = [] as unknown[],
  vragen = [] as unknown[],
  laatstHerinnerd = {} as Record<string, string>,
} = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      if (url.endsWith('/accordering/herinneringen'))
        return Promise.resolve(jsonResponse({ laatst_herinnerd: laatstHerinnerd }))
      if (url.includes('/documenten')) return Promise.resolve(jsonResponse({ documenten }))
      if (url.includes('/rekeningen'))
        return Promise.resolve(
          jsonResponse({ rekeningen, laatste_sync_op: null, ooit_gesynchroniseerd: true, heeft_bankaanlevering: true }),
        )
      if (url.includes('/vragen')) return Promise.resolve(jsonResponse({ vragen }))
      if (url.endsWith('/medewerkers')) return Promise.resolve(jsonResponse({ medewerkers: [] }))
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

function LocatieProbe() {
  const locatie = useLocation()
  return <div data-testid="locatie">{`${locatie.pathname}${locatie.search}`}</div>
}

function renderStanden() {
  return render(
    <MemoryRouter initialEntries={[`/?administratie=${ADMINISTRATIE_ID}`]}>
      <Routes>
        <Route
          path="/"
          element={
            <>
              <KlantStanden administratieId={ADMINISTRATIE_ID} administratieNaam="Testklant" />
              <LocatieProbe />
            </>
          }
        />
        <Route path="/bank/:administratieId" element={<LocatieProbe />} />
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('KlantStanden (klantpagina = standen)', () => {
  it('toont per documentsoort een stand-regel — alleen soorten met openstand (toon-regel)', async () => {
    installMock({
      documenten: [
        doc({}),
        doc({}),
        doc({ soort: 'verkoopfactuur' }),
        doc({ soort: 'kassarapport', status: 'geboekt' }), // terminaal: telt niet mee
      ],
    })
    renderStanden()

    await waitFor(() => expect(screen.getByText('Inkoopfacturen')).toBeInTheDocument())
    expect(screen.getByText('Verkoopfacturen')).toBeInTheDocument()
    // Kassarapport is geboekt → geen regel voor die soort.
    expect(screen.queryByText('Omzetrapporten (kassarapporten)')).not.toBeInTheDocument()
  })

  it('klik op een soort-regel opent het documenten-deelscherm met soort-filter', async () => {
    const gebruiker = userEvent.setup()
    installMock({ documenten: [doc({})] })
    renderStanden()

    await waitFor(() => expect(screen.getByText('Inkoopfacturen')).toBeInTheDocument())
    await gebruiker.click(screen.getByText('Inkoopfacturen'))
    expect(screen.getByTestId('locatie')).toHaveTextContent(
      `/?administratie=${ADMINISTRATIE_ID}&sectie=documenten&soort=inkoopfactuur`,
    )
  })

  it('bank-sectie toont alleen rekeningen met open mutaties en linkt naar het afletterscherm', async () => {
    const gebruiker = userEvent.setup()
    installMock({
      rekeningen: [
        { id: 'rek-1', naam: 'Zakelijk', iban: 'NL91RABO0000004471', open_mutaties: 30 },
        { id: 'rek-2', naam: 'Spaar', iban: null, open_mutaties: 0 },
      ],
    })
    renderStanden()

    await waitFor(() => expect(screen.getByText('Zakelijk')).toBeInTheDocument())
    expect(screen.queryByText('Spaar')).not.toBeInTheDocument()
    await gebruiker.click(screen.getByText('Zakelijk'))
    expect(screen.getByTestId('locatie')).toHaveTextContent(`/bank/${ADMINISTRATIE_ID}?rekening=rek-1`)
  })

  it('vragen- en accorderingssecties verschijnen alleen bij teller > 0', async () => {
    installMock({ documenten: [doc({})] })
    renderStanden()

    await waitFor(() => expect(screen.getByText('Inkoopfacturen')).toBeInTheDocument())
    expect(screen.queryByText('Openstaande vragen')).not.toBeInTheDocument()
    expect(screen.queryByText('Bij klant ter accordering')).not.toBeInTheDocument()
    expect(screen.queryByText('Bank — af te letteren')).not.toBeInTheDocument()
  })

  it('dagrem herinner-knop: vandaag al herinnerd = disabled mét tijdstip, ouder = actief', async () => {
    const vandaagDoc = doc({ id: 'dddddddd-0000-0000-0000-000000000001', status: 'ter_accordering' })
    const gisterenDoc = doc({ id: 'dddddddd-0000-0000-0000-000000000002', status: 'ter_accordering' })
    installMock({
      documenten: [vandaagDoc, gisterenDoc],
      laatstHerinnerd: {
        [vandaagDoc.id as string]: new Date().toISOString(),
        [gisterenDoc.id as string]: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
      },
    })
    renderStanden()

    await waitFor(() => expect(screen.getByText('Bij klant ter accordering')).toBeInTheDocument())
    expect(await screen.findByText(/vandaag al herinnerd om \d{2}:\d{2}/)).toBeInTheDocument()
    const knoppen = screen.getAllByRole('button', { name: 'Herinner' })
    expect(knoppen).toHaveLength(2)
    expect(knoppen.filter((k) => (k as HTMLButtonElement).disabled)).toHaveLength(1)
  })

  it('een open vraag verschijnt in de vragen-sectie met beantwoorden-link', async () => {
    installMock({
      documenten: [doc({ status: 'vraag_open' })],
      vragen: [
        {
          id: 'vraag-1',
          document_id: 'doc-1',
          document_bestandsnaam: 'factuur.pdf',
          document_status: 'vraag_open',
          totaalbedrag: null,
          vraag_tekst: 'Welk grootboek voor servicekosten?',
          status: 'open',
          status_voor_vraag: 'te_controleren',
          gesteld_door: 'g-1',
          gesteld_op: '2026-08-14T09:00:00Z',
          toegewezen_aan: 'g-2',
          antwoord_tekst: null,
          beantwoord_door: null,
          beantwoord_op: null,
          ingetrokken_door: null,
          ingetrokken_op: null,
          ingetrokken_reden: null,
        },
      ],
    })
    renderStanden()

    await waitFor(() => expect(screen.getByText('Openstaande vragen')).toBeInTheDocument())
    expect(screen.getByText('Welk grootboek voor servicekosten?')).toBeInTheDocument()
  })
})
