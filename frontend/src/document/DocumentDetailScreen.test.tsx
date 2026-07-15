import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DocumentDetailScreen } from './DocumentDetailScreen'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const ORIGINEEL_ID = 'cccccccc-0000-0000-0000-000000000003'

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

function installFetchMock(detail: unknown, opties?: { extractieAanroepen?: string[] }) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/extractie') && init?.method === 'POST') {
        opties?.extractieAanroepen?.push(url)
        return Promise.resolve(jsonResponse({ document_id: DOCUMENT_ID, status: 'extractie_bezig' }))
      }
      if (url.endsWith(`/documenten/${DOCUMENT_ID}`)) return Promise.resolve(jsonResponse(detail))
      if (url.endsWith('/bestand')) return Promise.resolve(new Response(new Blob(['%PDF-1.4']), { status: 200, headers: { 'Content-Type': 'application/pdf' } }))
      if (url.endsWith('/boekvoorstel')) {
        return Promise.resolve(
          jsonResponse({
            document_id: DOCUMENT_ID,
            vendor_id: null,
            referentie: null,
            factuurdatum: null,
            totaalbedrag: null,
            rlz_boekstuknummer: null,
            opgeslagen: false,
            regels: [],
          }),
        )
      }
      if (url.endsWith('/grootboek')) return Promise.resolve(jsonResponse({ rekeningen: [] }))
      if (url.endsWith('/btw-codes')) return Promise.resolve(jsonResponse({ btw_codes: [] }))
      if (url.endsWith('/crediteuren')) return Promise.resolve(jsonResponse({ crediteuren: [] }))
      if (url.endsWith('/projecten')) return Promise.resolve(jsonResponse({ projecten: [] }))
      if (url.endsWith('/project-instelling')) return Promise.resolve(jsonResponse({ verplicht: false }))
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

function renderScherm() {
  return render(
    <MemoryRouter initialEntries={[`/documenten/${ADMINISTRATIE_ID}/${DOCUMENT_ID}`]}>
      <Routes>
        <Route path="/documenten/:administratieId/:documentId" element={<DocumentDetailScreen />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('DocumentDetailScreen — tijdlijn en duplicaat', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('toont "Document binnengekomen" i.p.v. de kale "Ontvangen (status )"-placeholder', async () => {
    installFetchMock({
      id: DOCUMENT_ID,
      administratie_id: ADMINISTRATIE_ID,
      bestandsnaam: 'factuur.pdf',
      status: 'te_controleren',
      bron: 'upload',
      mogelijk_duplicaat_van: null,
      toegewezen_aan: null,
      aangemaakt_op: '2026-07-09T10:00:00Z',
      laatst_gewijzigd_op: '2026-07-09T10:00:00Z',
      veldvoorstel: null,
      tijdlijn: [{ van_status: null, naar_status: 'ontvangen', actor_id: 'x', detail: null, tijdstip: '2026-07-09T10:00:00Z' }],
    })

    renderScherm()

    await waitFor(() => expect(screen.getByText(/Document binnengekomen/)).toBeInTheDocument())
    expect(screen.queryByText(/status \)/)).not.toBeInTheDocument()
  })

  it('toont de achtergrond-banner (geen boekvoorstel-formulier) en pollt zolang de extractie loopt', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      installFetchMock({
        id: DOCUMENT_ID,
        administratie_id: ADMINISTRATIE_ID,
        bestandsnaam: 'monsterfactuur.pdf',
        status: 'extractie_wachtrij',
        bron: 'upload',
        mogelijk_duplicaat_van: null,
        toegewezen_aan: null,
        aangemaakt_op: '2026-07-10T10:00:00Z',
        laatst_gewijzigd_op: '2026-07-10T10:00:00Z',
        veldvoorstel: null,
        tijdlijn: [
          { van_status: null, naar_status: 'ontvangen', actor_id: 'x', actor_is_systeem: false, detail: null, tijdstip: '2026-07-10T10:00:00Z' },
          {
            van_status: 'ontvangen',
            naar_status: 'extractie_wachtrij',
            actor_id: 'x',
            actor_is_systeem: false,
            detail: { extractie_wachtrij: 'groot_document', paginas: 42, bytes: 5 * 1024 * 1024 },
            tijdstip: '2026-07-10T10:00:01Z',
          },
        ],
      })

      renderScherm()

      await waitFor(() => expect(screen.getByText(/Wordt op de achtergrond verwerkt/)).toBeInTheDocument())
      expect(screen.getByText(/staat in de wachtrij voor AI-extractie/)).toBeInTheDocument()
      expect(screen.getByText(/42 pagina's, 5\.0 MB/)).toBeInTheDocument()
      // Geen (misleidend) boekvoorstel-formulier zolang de worker nog een voorstel gaat schrijven.
      expect(screen.queryByText(/Boekvoorstel/)).not.toBeInTheDocument()

      const detailAanroepen = () =>
        vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith(`/documenten/${DOCUMENT_ID}`)).length
      const voor = detailAanroepen()
      await vi.advanceTimersByTimeAsync(3500)
      expect(detailAanroepen()).toBeGreaterThan(voor)
    } finally {
      vi.useRealTimers()
    }
  })

  it('markeert overgangen van de achtergrondworker herkenbaar als systeem in de tijdlijn', async () => {
    installFetchMock({
      id: DOCUMENT_ID,
      administratie_id: ADMINISTRATIE_ID,
      bestandsnaam: 'monsterfactuur.pdf',
      status: 'te_controleren',
      bron: 'upload',
      mogelijk_duplicaat_van: null,
      toegewezen_aan: null,
      aangemaakt_op: '2026-07-10T10:00:00Z',
      laatst_gewijzigd_op: '2026-07-10T10:05:00Z',
      veldvoorstel: null,
      tijdlijn: [
        { van_status: null, naar_status: 'ontvangen', actor_id: 'x', actor_is_systeem: false, detail: null, tijdstip: '2026-07-10T10:00:00Z' },
        { van_status: 'extractie_wachtrij', naar_status: 'extractie_bezig', actor_id: 'sys', actor_is_systeem: true, detail: null, tijdstip: '2026-07-10T10:01:00Z' },
        { van_status: 'extractie_bezig', naar_status: 'te_controleren', actor_id: 'sys', actor_is_systeem: true, detail: null, tijdstip: '2026-07-10T10:05:00Z' },
      ],
    })

    renderScherm()

    await waitFor(() => expect(screen.getAllByText(/systeem/)).toHaveLength(2))
    expect(screen.getByText(/In wachtrij \(extractie\) →/)).toBeInTheDocument()
  })

  it('toont een klikbare duplicaat-link met bestandsnaam en datum, geen kale UUID', async () => {
    installFetchMock({
      id: DOCUMENT_ID,
      administratie_id: ADMINISTRATIE_ID,
      bestandsnaam: 'kopie.pdf',
      status: 'te_controleren',
      bron: 'upload',
      mogelijk_duplicaat_van: {
        document_id: ORIGINEEL_ID,
        bestandsnaam: 'origineel.pdf',
        aangemaakt_op: '2026-07-08T09:00:00Z',
      },
      toegewezen_aan: null,
      aangemaakt_op: '2026-07-09T10:00:00Z',
      laatst_gewijzigd_op: '2026-07-09T10:00:00Z',
      veldvoorstel: null,
      tijdlijn: [{ van_status: null, naar_status: 'ontvangen', actor_id: 'x', detail: null, tijdstip: '2026-07-09T10:00:00Z' }],
    })

    renderScherm()

    const link = await screen.findByRole('link', { name: /origineel\.pdf/ })
    expect(link).toHaveAttribute('href', `/documenten/${ADMINISTRATIE_ID}/${ORIGINEEL_ID}`)
    expect(screen.queryByText(ORIGINEEL_ID)).not.toBeInTheDocument()
  })
})

// ————— UX-fix 2026-07-11: "↻ Opnieuw extraheren" ook op een gesláágd voorstel —————

const AI_VOORSTEL = {
  bron: 'ai',
  leverancier_naam: 'Confide BV',
  factuurnummer: 'F-1',
  factuurdatum: '2026-07-01',
  vervaldatum: null,
  valuta: 'EUR',
  totaal_excl: '100.00',
  totaal_incl: '121.00',
  btw_bedrag: '21.00',
  regelaantal: 1,
  regels: [{ omschrijving: 'Steigerhuur', netto_bedrag: '100.00', btw_bedrag: '21.00', hoeveelheid: null, taxrate_id: null }],
  zekerheid: { leverancier_naam: 0.93 },
  regel_zekerheid: [0.95],
  zekerheid_drempel: 0.8,
  vendor_suggestie: null,
  controle: {
    regelsom: '121.00',
    regelsom_wijkt_af: false,
    onparseerbaar: [],
    lage_zekerheid: [],
    bsn_verwijderd: 0,
    onvolledig: false,
  },
}

function detailMet(overrides: Record<string, unknown>) {
  return {
    id: DOCUMENT_ID,
    administratie_id: ADMINISTRATIE_ID,
    bestandsnaam: 'factuur.pdf',
    status: 'te_controleren',
    bron: 'upload',
    mogelijk_duplicaat_van: null,
    toegewezen_aan: null,
    aangemaakt_op: '2026-07-10T10:00:00Z',
    laatst_gewijzigd_op: '2026-07-10T10:05:00Z',
    veldvoorstel: AI_VOORSTEL,
    tijdlijn: [
      { van_status: null, naar_status: 'ontvangen', actor_id: 'x', actor_is_systeem: false, detail: null, tijdstip: '2026-07-10T10:00:00Z' },
      { van_status: 'extractie_bezig', naar_status: 'te_controleren', actor_id: 'sys', actor_is_systeem: true, detail: { veldvoorstel: AI_VOORSTEL }, tijdstip: '2026-07-10T10:05:00Z' },
    ],
    ...overrides,
  }
}

describe('DocumentDetailScreen — opnieuw extraheren vanaf een geslaagd voorstel', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('toont de knop bij een PDF in te_controleren en start de her-run pas na bevestiging', async () => {
    const { default: userEvent } = await import('@testing-library/user-event')
    const gebruiker = userEvent.setup()
    const extractieAanroepen: string[] = []
    installFetchMock(detailMet({}), { extractieAanroepen })

    renderScherm()

    const knop = await screen.findByRole('button', { name: '↻ Opnieuw extraheren' })
    await gebruiker.click(knop)

    // Eerst bevestigen — de her-run overschrijft het huidige voorstel.
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText(/overschrijft het huidige/)).toBeInTheDocument()
    expect(extractieAanroepen).toHaveLength(0)

    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))

    await waitFor(() => expect(extractieAanroepen).toHaveLength(1))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('annuleren sluit de dialoog zonder her-run', async () => {
    const { default: userEvent } = await import('@testing-library/user-event')
    const gebruiker = userEvent.setup()
    const extractieAanroepen: string[] = []
    installFetchMock(detailMet({}), { extractieAanroepen })

    renderScherm()

    await gebruiker.click(await screen.findByRole('button', { name: '↻ Opnieuw extraheren' }))
    await gebruiker.click(screen.getByRole('button', { name: 'Annuleren' }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(extractieAanroepen).toHaveLength(0)
  })

  it('geen knop op een geboekt document, ook al is er een AI-voorstel', async () => {
    installFetchMock(detailMet({ status: 'geboekt' }))

    renderScherm()

    // Het AI-voorstel-paneel staat er wél (context blijft zichtbaar), de her-run-knop niet.
    await screen.findByText('AI-voorstel — mens boekt')
    expect(screen.queryByRole('button', { name: '↻ Opnieuw extraheren' })).not.toBeInTheDocument()
  })

  it('geen knop op een niet-PDF (UBL is deterministisch)', async () => {
    installFetchMock(detailMet({ bestandsnaam: 'factuur.xml' }))

    renderScherm()

    await screen.findByText('AI-voorstel — mens boekt')
    expect(screen.queryByRole('button', { name: '↻ Opnieuw extraheren' })).not.toBeInTheDocument()
  })
})

describe('DocumentDetailScreen — afgewezen (mockup #afwijsmodal-vervolg)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  const AFWIJZING = {
    id: 'ffffffff-0000-0000-0000-000000000009',
    reden: 'niet onze bestelling, navragen bij leverancier',
    afgewezen_door: 'x',
    afgewezen_op: '2026-07-15T09:00:00Z',
    toegewezen_aan: 'y',
    status_voor_afwijzing: 'te_controleren',
  }

  function installMetHeropenen(detail: unknown, heropenAanroepen: string[]) {
    const basis = vi.mocked(globalThis.fetch)
    void basis
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith('/heropenen') && init?.method === 'POST') {
          heropenAanroepen.push(url)
          return Promise.resolve(jsonResponse({ id: AFWIJZING.id, status: 'heropend' }))
        }
        if (url.endsWith(`/documenten/${DOCUMENT_ID}`)) return Promise.resolve(jsonResponse(detail))
        if (url.endsWith('/bestand')) return Promise.resolve(new Response(new Blob(['%PDF-1.4']), { status: 200, headers: { 'Content-Type': 'application/pdf' } }))
        if (url.endsWith('/boekvoorstel')) {
          return Promise.resolve(
            jsonResponse({
              document_id: DOCUMENT_ID,
              vendor_id: null,
              referentie: null,
              factuurdatum: null,
              totaalbedrag: null,
              rlz_boekstuknummer: null,
              opgeslagen: false,
              regels: [],
            }),
          )
        }
        return Promise.resolve(jsonResponse({ rekeningen: [], btw_codes: [], crediteuren: [], projecten: [], verplicht: false, medewerkers: [], vragen: [] }))
      }),
    )
  }

  it('toont de afgewezen-banner met reden + heropenen-knop en heropent via de backend', async () => {
    const heropenAanroepen: string[] = []
    installMetHeropenen(
      detailMet({
        status: 'afgewezen',
        afwijzing: AFWIJZING,
        tijdlijn: [
          { van_status: null, naar_status: 'ontvangen', actor_id: 'x', actor_is_systeem: false, detail: null, tijdstip: '2026-07-10T10:00:00Z' },
          {
            van_status: 'te_controleren',
            naar_status: 'afgewezen',
            actor_id: 'x',
            actor_is_systeem: false,
            detail: { afwijzing_id: AFWIJZING.id, reden: AFWIJZING.reden, toegewezen_aan: 'y', status_voor_afwijzing: 'te_controleren' },
            tijdstip: '2026-07-15T09:00:00Z',
          },
        ],
      }),
      heropenAanroepen,
    )

    renderScherm()

    // Reden zichtbaar in de banner én als tijdlijn-entry ("blijft zichtbaar" — nooit alleen
    // een kale statuschip).
    const redenen = await screen.findAllByText(/niet onze bestelling, navragen bij leverancier/)
    expect(redenen.length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText(/Afgewezen door/)).toBeInTheDocument()
    // Geen boekknop of afwijsknop op een al afgewezen document (read-only voorstel).
    expect(screen.queryByRole('button', { name: /Boeken in RLZ/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Afwijzen…' })).not.toBeInTheDocument()

    const { default: userEvent } = await import('@testing-library/user-event')
    const gebruiker = userEvent.setup()
    await gebruiker.click(screen.getByRole('button', { name: '↺ Heropenen' }))
    await waitFor(() => expect(heropenAanroepen).toHaveLength(1))
    expect(heropenAanroepen[0]).toContain(`/documenten/${DOCUMENT_ID}/heropenen`)
  })

  it('toont de Afwijzen…-knop in de actiebalk op een te_controleren document', async () => {
    installMetHeropenen(detailMet({ status: 'te_controleren', afwijzing: null }), [])

    renderScherm()

    await screen.findByText('AI-voorstel — mens boekt')
    expect(await screen.findByRole('button', { name: 'Afwijzen…' })).toBeInTheDocument()
  })
})
