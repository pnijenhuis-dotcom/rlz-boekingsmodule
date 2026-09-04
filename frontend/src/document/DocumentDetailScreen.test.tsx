import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../ui/basis'
import { boekdatumVerschovenHint, DocumentDetailScreen } from './DocumentDetailScreen'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const ORIGINEEL_ID = 'cccccccc-0000-0000-0000-000000000003'

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

interface MockOpties {
  extractieAanroepen?: string[]
  alBetaald?: unknown
  /** Deel 4 punt 3: antwoord op GET …/aanbetaling-open (default: niet toetsbaar). */
  aanbetaling?: unknown
  /** Deel 4 punt 1: de documentenlijst van de klant (GET …/documenten) voor de doorloop. */
  lijst?: unknown[]
  lijstAanroepen?: string[]
  /** Blok B: antwoord op de automatische open-run POST …/boekvoorstel/checks (default 404). */
  checksResponse?: unknown
  /** Antwoord op POST …/boeken. */
  boekenResponse?: unknown
  boekenAanroepen?: string[]
  /** Override voor GET …/boekvoorstel. */
  boekvoorstel?: unknown
  taxrates?: unknown[]
}

function installFetchMock(detail: unknown, opties?: MockOpties) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/extractie') && init?.method === 'POST') {
        opties?.extractieAanroepen?.push(url)
        return Promise.resolve(jsonResponse({ document_id: DOCUMENT_ID, status: 'extractie_bezig' }))
      }
      if (url.endsWith('/boekvoorstel/checks') && init?.method === 'POST') {
        if (opties?.checksResponse === undefined) return Promise.resolve(new Response(null, { status: 404 }))
        return Promise.resolve(jsonResponse(opties.checksResponse))
      }
      if (url.endsWith('/boeken') && init?.method === 'POST') {
        opties?.boekenAanroepen?.push(url)
        return Promise.resolve(jsonResponse(opties?.boekenResponse ?? {}))
      }
      if (url.endsWith('/documenten')) {
        opties?.lijstAanroepen?.push(url)
        return Promise.resolve(jsonResponse({ documenten: opties?.lijst ?? [] }))
      }
      if (url.endsWith('/aanbetaling-open'))
        return Promise.resolve(jsonResponse(opties?.aanbetaling ?? { toetsbaar: false, treffers: [] }))
      // Klant-accordering: vóór de documenten-match — /accordering/documenten/{id} eindigt óók
      // op /documenten/{id}.
      if (url.includes('/accordering/instellingen'))
        return Promise.resolve(jsonResponse({ ingeschakeld: false, lagen: [] }))
      if (url.includes('/accordering/documenten/')) return Promise.resolve(jsonResponse(null))
      if (url.endsWith(`/documenten/${DOCUMENT_ID}`)) return Promise.resolve(jsonResponse(detail))
      if (url.endsWith('/al-betaald')) return Promise.resolve(jsonResponse(opties?.alBetaald ?? { toetsbaar: false, treffers: [] }))
      if (url.endsWith('/bestand')) return Promise.resolve(new Response(new Blob(['%PDF-1.4']), { status: 200, headers: { 'Content-Type': 'application/pdf' } }))
      if (url.endsWith('/boekvoorstel')) {
        return Promise.resolve(
          jsonResponse(
            opties?.boekvoorstel ?? {
              document_id: DOCUMENT_ID,
              vendor_id: null,
              referentie: null,
              factuurdatum: null,
              totaalbedrag: null,
              rlz_boekstuknummer: null,
              opgeslagen: false,
              regels: [],
            },
          ),
        )
      }
      if (url.endsWith('/grootboek')) return Promise.resolve(jsonResponse({ rekeningen: [] }))
      if (url.endsWith('/btw-codes')) return Promise.resolve(jsonResponse({ btw_codes: opties?.taxrates ?? [] }))
      if (url.endsWith('/crediteuren')) return Promise.resolve(jsonResponse({ crediteuren: [] }))
      if (url.endsWith('/projecten')) return Promise.resolve(jsonResponse({ projecten: [] }))
      if (url.endsWith('/project-instelling')) return Promise.resolve(jsonResponse({ verplicht: false }))
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

/** Locatie-probe voor de doorloop-tests: toont het actuele pad + query, waar de router ook landt. */
function LocatieProbe() {
  const loc = useLocation()
  return <div data-testid="locatie">{loc.pathname + loc.search}</div>
}

function renderScherm() {
  return render(
    <MemoryRouter initialEntries={[`/documenten/${ADMINISTRATIE_ID}/${DOCUMENT_ID}`]}>
      <ToastProvider>
        <LocatieProbe />
        <Routes>
          <Route path="/documenten/:administratieId/:documentId" element={<DocumentDetailScreen />} />
          <Route path="*" element={<div>elders</div>} />
        </Routes>
      </ToastProvider>
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

describe('DocumentDetailScreen — al-betaald-signaal (besluit Peter 25-08, deel 2 punt 1)', () => {
  afterEach(() => vi.unstubAllGlobals())

  const detail = {
    id: DOCUMENT_ID,
    administratie_id: ADMINISTRATIE_ID,
    bestandsnaam: 'factuur.pdf',
    soort: 'inkoopfactuur',
    status: 'te_controleren',
    bron: 'upload',
    mogelijk_duplicaat_van: null,
    toegewezen_aan: null,
    aangemaakt_op: '2026-07-09T10:00:00Z',
    laatst_gewijzigd_op: '2026-07-09T10:00:00Z',
    veldvoorstel: null,
    tijdlijn: [],
  }

  it('toont "Waarschijnlijk al betaald" met datum, rekening, bedrag en matchreden — als signaal, niet als blokkade', async () => {
    installFetchMock(detail, {
      alBetaald: {
        toetsbaar: true,
        treffers: [
          {
            mutatie_id: 'm1',
            boekdatum: '2026-08-14',
            bedrag: '-1512.50',
            rekening_naam: 'ING zakelijk',
            rekening_iban: 'NL22INGB0001238102',
            tegenpartij_naam: 'Floor Bouwliften B.V.',
            omschrijving: 'Factuur 88122',
            redenen: ['bedrag incl. btw exact gelijk', 'factuurnummer in omschrijving'],
          },
        ],
      },
    })
    renderScherm()
    expect(await screen.findByText('Waarschijnlijk al betaald')).toBeInTheDocument()
    // Het signaal-blok zelf (de ToastProvider draagt óók role=status).
    const blok = screen.getByText('Waarschijnlijk al betaald').closest('.al-betaald-signaal') as HTMLElement
    expect(blok).toHaveTextContent(/ING zakelijk/)
    expect(blok).toHaveTextContent(/bedrag incl\. btw exact gelijk \+ factuurnummer in omschrijving/)
    expect(blok).toHaveTextContent(/geen blokkade/)
  })

  it('geen signaal zonder treffers', async () => {
    installFetchMock(detail, { alBetaald: { toetsbaar: true, treffers: [] } })
    renderScherm()
    await screen.findByText('factuur.pdf')
    expect(screen.queryByText('Waarschijnlijk al betaald')).not.toBeInTheDocument()
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

  it('blok C (02-09): een geboekt document draagt in de kop de chip "Geboekt in RLZ · boekstuk · crediteur"', async () => {
    installFetchMock(
      detailMet({
        status: 'geboekt',
        geboekt_in_rlz: {
          regel: 'Geboekt in RLZ · boekstuk RLZ-04-00002001 · Universal Nederland B.V.',
          boekstuknummer: 'RLZ-04-00002001',
          rlz_document_id: 'x',
          tegenpartij: 'Universal Nederland B.V.',
          tegenpartij_rol: 'crediteur',
          geboekt_op: '2026-09-02T10:00:00Z',
          memoriaal_boekstuknummer: null,
          vindplaats_hint: null,
        },
      }),
    )
    renderScherm()
    const chip = await screen.findByTestId('geboekt-in-rlz-chip')
    expect(chip).toHaveTextContent('Geboekt in RLZ · boekstuk RLZ-04-00002001 · Universal Nederland B.V.')
    expect(chip).toHaveAttribute('title', 'Geboekt in RLZ · boekstuk RLZ-04-00002001 · Universal Nederland B.V.')
  })

  it('Odoo-adapter blok E (03-09): de GEBOEKT-gebeurtenis benoemt backend + company en de btw-cent-override; de tegenboeking draagt de kruisverwijzing', async () => {
    installFetchMock(
      detailMet({
        status: 'geboekt',
        tijdlijn: [
          { van_status: null, naar_status: 'ontvangen', actor_id: 'x', actor_is_systeem: false, detail: null, tijdstip: '2026-09-03T10:00:00Z' },
          {
            van_status: 'klaar_om_te_boeken',
            naar_status: 'geboekt',
            actor_id: 'x',
            actor_is_systeem: false,
            detail: { backend: 'odoo', odoo_naam: 'BILL/2026/09/0001', odoo_company_id: 1, btw_override: [{ tarief: '21%', verschil: '0.01' }] },
            tijdstip: '2026-09-03T10:05:00Z',
          },
          {
            van_status: 'geboekt',
            naar_status: 'geboekt',
            actor_id: 'x',
            actor_is_systeem: false,
            detail: { tegenboeking: { soort: 'volledig', backend: 'odoo', rlz_boekstuknummer: 'RBILL/2026/09/0002', kruisverwijzing: 'Reversal · RBILL/2026/09/0002 ↔ BILL/2026/09/0001', reden: 'dubbel' } },
            tijdstip: '2026-09-03T11:00:00Z',
          },
        ],
      }),
    )
    renderScherm()
    expect(await screen.findByTestId('tijdlijn-geboekt-odoo')).toHaveTextContent('Geboekt in Odoo · BILL/2026/09/0001 (company 1)')
    expect(screen.getByTestId('tijdlijn-btw-override')).toHaveTextContent('btw-cent-override')
    expect(screen.getByTestId('tijdlijn-btw-override')).toHaveTextContent('Btw-cent-override toegepast (± € 0,02 per tarief) — zie boeking')
    expect(screen.getByText(/tegenboeking RBILL\/2026\/09\/0002 in Odoo · Reversal · RBILL\/2026\/09\/0002 ↔ BILL\/2026\/09\/0001 — “dubbel”/)).toBeInTheDocument()
  })

  it('Odoo-slotstuk 04-09 (A2): een GEBOEKT-detail mét `boekdatum_verschoven` krijgt de tijdlijn-hint "Boekdatum verschoven naar … — factuurdatum … valt in een in Odoo afgesloten (aangegeven) periode"', async () => {
    installFetchMock(
      detailMet({
        status: 'geboekt',
        tijdlijn: [
          {
            van_status: 'klaar_om_te_boeken',
            naar_status: 'geboekt',
            actor_id: 'x',
            actor_is_systeem: false,
            detail: {
              backend: 'odoo',
              odoo_naam: 'BILL/2026/01/0001',
              odoo_company_id: 1,
              boekdatum_verschoven: { van: '2025-12-15', naar: '2026-01-01', lock_veld: 'tax_lock_date', lock_datum: '2025-12-31', reden: 'Factuurdatum 15-12-2025 valt in een in Odoo afgesloten periode' },
            },
            tijdstip: '2026-09-04T20:11:00Z',
          },
        ],
      }),
    )
    renderScherm()
    const hint = await screen.findByTestId('tijdlijn-boekdatum-verschoven')
    expect(hint).toHaveTextContent('boekdatum verschoven')
    expect(hint).toHaveTextContent('Boekdatum verschoven naar 01-01-2026 — factuurdatum 15-12-2025 valt in een in Odoo afgesloten (aangegeven) periode (t/m 31-12-2025); factuurdatum ongewijzigd')
    expect(screen.getByTestId('tijdlijn-geboekt-odoo')).toHaveTextContent('Geboekt in Odoo · BILL/2026/01/0001 (company 1)')
    // Puur: zonder het veld, of met een kaal object, geen hint.
    expect(boekdatumVerschovenHint({ backend: 'odoo' })).toBeNull()
    expect(boekdatumVerschovenHint({ boekdatum_verschoven: { naar: '2026-01-01' } })).toBeNull()
    expect(boekdatumVerschovenHint(null)).toBeNull()
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

// ————— Deterministische extractie-terugval (best-practice-besluit 2, 31-08 / gebouwd 01-09) —————

describe('DocumentDetailScreen — veldvoorstel uit template', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('toont het paneel als template-voorstel mét herkomst-chip per veld, zonder AI-scores', async () => {
    installFetchMock(
      detailMet({
        veldvoorstel: {
          ...AI_VOORSTEL,
          bron: 'template',
          zekerheid: { leverancier_naam: 1, factuurnummer: 1, totaal_incl: 1 },
          template: {
            id: 't-1',
            sleutel_soort: 'btw_nummer',
            versie: 1,
            herkend_op: 'btw_nummer',
            velden: { factuurnummer: 'template' },
            btw_percentage: '21',
          },
        },
      }),
    )

    renderScherm()

    await screen.findByText('Veldvoorstel (template)')
    expect(screen.getByText('uit template — mens boekt')).toBeInTheDocument()
    expect(screen.queryByText('AI-voorstel — mens boekt')).not.toBeInTheDocument()
    // Per gevuld veld een "uit template"-chip i.p.v. een percentage.
    expect(screen.getAllByText('uit template').length).toBeGreaterThanOrEqual(3)
    expect(screen.queryByText('100%')).not.toBeInTheDocument()
    expect(screen.getByText(/geen AI-aanroep, geen data naar buiten/)).toBeInTheDocument()
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
        if (url.includes('/accordering/instellingen'))
          return Promise.resolve(jsonResponse({ ingeschakeld: false, lagen: [] }))
        if (url.includes('/accordering/documenten/')) return Promise.resolve(jsonResponse(null))
        if (url.endsWith(`/documenten/${DOCUMENT_ID}`)) return Promise.resolve(jsonResponse(detail))
        if (url.endsWith('/al-betaald')) return Promise.resolve(jsonResponse({ toetsbaar: false, treffers: [] }))
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

  it('actiebalk staat ÓNDER het boekvoorstel-paneel en het doorbelast-blok (feedback Peter 27-08: eerst de verdeling, dan de knoppen)', async () => {
    installMetHeropenen(detailMet({ status: 'te_controleren', afwijzing: null }), [])

    renderScherm()

    const afwijzen = await screen.findByRole('button', { name: 'Afwijzen…' })
    const boeken = screen.getByRole('button', { name: /Boeken in RLZ/ })
    // De knoppen renderen via de portal in het anker dat het controlescherm ná
    // <DoorbelastenNaBoeken> plaatst — niet meer inline in het boekvoorstel-paneel.
    const doel = screen.getByTestId('actiebalk-doel')
    expect(doel).toContainElement(afwijzen)
    expect(doel).toContainElement(boeken)
    // DOM-volgorde: alle boekvoorstel-koppen (kopgegevens, regels, checks) staan vóór het anker.
    for (const kop of screen.getAllByRole('heading', { level: 2 })) {
      if (doel.contains(kop)) continue
      const naDeKop = Boolean(kop.compareDocumentPosition(doel) & Node.DOCUMENT_POSITION_FOLLOWING)
      const onderDeTijdlijn = /Tijdlijn|Opmerkingen/.test(kop.textContent ?? '')
      if (!onderDeTijdlijn) expect(naDeKop).toBe(true)
    }
  })
})

describe('DocumentDetailScreen — v2 werkvolgorde (mockup controlescherm-v2, 02-09)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('groen = topbar-chip + inklapregel; AI-details, e-mail, opmerkingen en tijdlijn zijn inklapregels; de actiebalk zit in de sticky wrapper', async () => {
    installFetchMock(detailMet({ soort: 'inkoopfactuur', tijdlijn: [], status: 'te_controleren' }), { checksResponse: GROEN_RAPPORT })
    renderScherm()

    await waitFor(() => expect(screen.getByTestId('controles-chip')).toHaveTextContent('alle controles groen ✓'))
    const rijen = screen.getByTestId('inklap-rijen')
    expect(within(rijen).getByTestId('controles-inklap')).toBeInTheDocument()
    expect(within(rijen).getByTestId('extractie-inklap')).toHaveTextContent(/Extractie-details \(AI/)
    expect(within(rijen).getByTestId('opmerkingen-inklap')).toBeInTheDocument()
    expect(within(rijen).getByTestId('tijdlijn-inklap')).toBeInTheDocument()
    // Geen vast checks-blok meer boven de actiebalk; de knoppen staan in de sticky wrapper.
    expect(screen.queryByText('Harde checks')).not.toBeInTheDocument()
    const doel = screen.getByTestId('actiebalk-doel')
    expect(doel.parentElement).toHaveClass('actiebalk-sticky')
    expect(screen.queryByTestId('controles-banner')).not.toBeInTheDocument()
  })

  it('een rode check = banner boven de actiebalk (klik = detail) en een rode topbar-chip', async () => {
    installFetchMock(detailMet({ soort: 'inkoopfactuur', tijdlijn: [], status: 'te_controleren' }), {
      checksResponse: { geblokkeerd: true, resultaten: [{ naam: 'Verplichte velden', ok: false, melding: 'Ontbrekend: crediteur' }] },
    })
    renderScherm()
    await waitFor(() => expect(screen.getByTestId('controles-chip')).toHaveTextContent('1 controle(s) rood'))
    const banner = screen.getByTestId('controles-banner')
    expect(banner).toHaveTextContent('Verplichte velden: Ontbrekend: crediteur')
    const { default: userEvent } = await import('@testing-library/user-event')
    await userEvent.setup().click(within(banner).getByRole('button'))
    expect(await screen.findByRole('dialog')).toHaveTextContent('Ontbrekend: crediteur')
  })
})

describe('DocumentDetailScreen — blok "Uit de e-mail" (feedbackronde 25-08 deel 3, punt 1b)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  const basis = {
    id: DOCUMENT_ID,
    administratie_id: ADMINISTRATIE_ID,
    bestandsnaam: 'factuur.pdf',
    status: 'te_controleren',
    bron: 'email',
    soort: 'inkoopfactuur',
    mogelijk_duplicaat_van: null,
    toegewezen_aan: null,
    aangemaakt_op: '2026-08-25T10:00:00Z',
    laatst_gewijzigd_op: '2026-08-25T10:00:00Z',
    veldvoorstel: null,
    tijdlijn: [],
  }

  it('toont afzender, onderwerp en het begeleidend schrijven, ingeklapt', async () => {
    installFetchMock({
      ...basis,
      herkomst_mail: {
        afzender: 'collega@kempengroep.nl',
        onderwerp: 'Factuur Bouwmaat',
        ontvangen_op: '2026-08-25T09:00:00+02:00',
        body_tekst: 'Hoi Peter,\n\nDit is voor Oirschot.',
        bron: 'imap',
      },
    })
    renderScherm()
    const blok = await screen.findByTestId('uit-de-email')
    expect(blok).not.toHaveAttribute('open')
    expect(blok).toHaveTextContent('Uit de e-mail')
    expect(blok).toHaveTextContent('collega@kempengroep.nl')
    expect(blok).toHaveTextContent('Factuur Bouwmaat')
    expect(blok).toHaveTextContent('Dit is voor Oirschot.')
    expect(blok).toHaveTextContent('postvak')
  })

  it('zonder body staat er eerlijk dat er geen mailtekst is; zonder mail-herkomst géén blok', async () => {
    installFetchMock({
      ...basis,
      herkomst_mail: { afzender: 'x@y.nl', onderwerp: null, ontvangen_op: null, body_tekst: null, bron: 'eml_upload' },
    })
    renderScherm()
    const blok = await screen.findByTestId('uit-de-email')
    expect(blok).toHaveTextContent('Geen mailtekst beschikbaar')
    vi.unstubAllGlobals()

    installFetchMock({ ...basis, bron: 'upload', herkomst_mail: null })
    const { unmount } = renderScherm()
    await waitFor(() => expect(screen.getAllByText(/Kopgegevens|Bijlage/).length).toBeGreaterThan(0))
    expect(screen.queryAllByTestId('uit-de-email')).toHaveLength(1) // alleen het eerste (nog gemounte) scherm
    unmount()
  })
})

// ————— Deel 4 punt 1 (besluit Peter 25-08): ná boeken direct door naar het volgende document —————

const VOLGEND_ID = 'dddddddd-0000-0000-0000-000000000004'

function lijstItem(id: string, soort: string, status: string) {
  return {
    id,
    bestandsnaam: `${id}.pdf`,
    status,
    bron: 'upload',
    soort,
    mogelijk_duplicaat_van: null,
    toegewezen_aan: null,
    aangemaakt_op: '2026-08-25T10:00:00Z',
    laatst_gewijzigd_op: '2026-08-25T10:00:00Z',
    afwijzing: null,
    leverancier: null,
    totaalbedrag: null,
    factuurdatum: null,
    automatisch_geboekt: false,
  }
}

const GROEN_RAPPORT = { geblokkeerd: false, resultaten: [{ naam: 'Verplichte velden', ok: true, melding: 'ok' }] }

describe('DocumentDetailScreen — doorloop ná boeken (deel 4 punt 1)', () => {
  afterEach(() => vi.unstubAllGlobals())

  const boekOpties = (lijst: unknown[]): MockOpties => ({
    lijst,
    lijstAanroepen: [],
    boekenAanroepen: [],
    checksResponse: GROEN_RAPPORT,
    boekenResponse: { document_id: DOCUMENT_ID, status: 'geboekt', rlz_document_id: 'x', rlz_boekstuknummer: 'RLZ-04-00002001' },
    boekvoorstel: {
      document_id: DOCUMENT_ID,
      vendor_id: null,
      referentie: 'F-1',
      factuurdatum: null,
      totaalbedrag: null,
      rlz_boekstuknummer: null,
      opgeslagen: true,
      regels: [],
    },
  })

  it('boekt, toont een toast met referentie + boekstuk en opent het volgende inkoopdocument van de klant', async () => {
    const { default: userEvent } = await import('@testing-library/user-event')
    const gebruiker = userEvent.setup()
    const opties = boekOpties([
      lijstItem(DOCUMENT_ID, 'inkoopfactuur', 'te_controleren'),
      lijstItem('eeeeeeee-0000-0000-0000-000000000005', 'verkoopfactuur', 'te_controleren'),
      lijstItem(VOLGEND_ID, 'inkoopfactuur', 'klaar_om_te_boeken'),
    ])
    installFetchMock(detailMet({ soort: 'inkoopfactuur', veldvoorstel: null, tijdlijn: [] }), opties)
    renderScherm()

    const knop = await screen.findByRole('button', { name: 'Boeken in RLZ ✓' })
    await waitFor(() => expect(knop).toBeEnabled())
    await gebruiker.click(knop)

    await waitFor(() => expect(opties.boekenAanroepen).toHaveLength(1))
    expect(await screen.findByText('Geboekt — F-1 · boekstuk RLZ-04-00002001')).toBeInTheDocument()
    await waitFor(() => expect(opties.lijstAanroepen).toHaveLength(1))
    await waitFor(() =>
      expect(screen.getByTestId('locatie')).toHaveTextContent(`/documenten/${ADMINISTRATIE_ID}/${VOLGEND_ID}`),
    )
  })

  it('zonder te verwerken documenten gaat het terug naar de documentenlijst van de klant', async () => {
    const { default: userEvent } = await import('@testing-library/user-event')
    const gebruiker = userEvent.setup()
    const opties = boekOpties([
      lijstItem(DOCUMENT_ID, 'inkoopfactuur', 'geboekt'),
      lijstItem(VOLGEND_ID, 'inkoopfactuur', 'ter_accordering'),
      lijstItem('eeeeeeee-0000-0000-0000-000000000005', 'inkoopfactuur', 'afgewezen'),
    ])
    installFetchMock(detailMet({ soort: 'inkoopfactuur', veldvoorstel: null, tijdlijn: [] }), opties)
    renderScherm()

    const knop = await screen.findByRole('button', { name: 'Boeken in RLZ ✓' })
    await waitFor(() => expect(knop).toBeEnabled())
    await gebruiker.click(knop)

    await waitFor(() => expect(screen.getByTestId('locatie')).toHaveTextContent(`/?administratie=${ADMINISTRATIE_ID}`))
    expect(screen.getByText('elders')).toBeInTheDocument()
  })
})

// ————— Deel 4 punt 3: aanbetaling-open-signaal + verrekenregel —————

describe('DocumentDetailScreen — aanbetaling-open-signaal (deel 4 punt 3)', () => {
  afterEach(() => vi.unstubAllGlobals())

  const detail = detailMet({ soort: 'inkoopfactuur', veldvoorstel: null, tijdlijn: [] })
  const TREFFER = {
    boeking_id: 'b1',
    payment_transaction_id: 'pt1',
    bedrag: '250.00',
    boekdatum: '2026-08-12',
    geboekt_op: '2026-08-12T10:00:00Z',
    rlz_boekstuknummer: 'RLZ-04-00002036',
    entity_naam: 'Bouwmaat Nederland B.V.',
    vooruit_ledger_id: 'ledger-vooruit',
    herkenning: 'iban',
  }

  it('toont het signaal met bedrag, datum, boekstuk, herkenning-chip en banklink', async () => {
    installFetchMock(detail, { aanbetaling: { toetsbaar: true, treffers: [TREFFER] } })
    renderScherm()
    expect(await screen.findByText('Aanbetaling open')).toBeInTheDocument()
    const blok = screen.getByText('Aanbetaling open').closest('.aanbetaling-signaal') as HTMLElement
    expect(blok).toHaveTextContent(/Voor deze leverancier staat nog een aanbetaling open/)
    expect(blok).toHaveTextContent(/250,00/)
    expect(blok).toHaveTextContent(/12 aug 2026/)
    expect(blok).toHaveTextContent(/boekstuk RLZ-04-00002036/)
    expect(blok).toHaveTextContent('via IBAN')
    expect(screen.getByRole('link', { name: /Bekijk in bank/ })).toHaveAttribute('href', `/bank/${ADMINISTRATIE_ID}`)
  })

  it('geen signaal zonder treffers', async () => {
    installFetchMock(detail, { aanbetaling: { toetsbaar: true, treffers: [] } })
    renderScherm()
    await screen.findByText('factuur.pdf')
    expect(screen.queryByText('Aanbetaling open')).not.toBeInTheDocument()
  })

  it('"Verrekenregel toevoegen" zet een negatieve regel op de vooruit-rekening in het boekvoorstel (0%-tarief als dat eenduidig is)', async () => {
    const { default: userEvent } = await import('@testing-library/user-event')
    const gebruiker = userEvent.setup()
    installFetchMock(detail, {
      aanbetaling: { toetsbaar: true, treffers: [TREFFER] },
      taxrates: [
        { id: 'tr-hoog', naam: 'NL Hoog 21%', percentage: '0.21' },
        { id: 'tr-nul', naam: 'Nul tarief', percentage: '0' },
      ],
    })
    renderScherm()

    await screen.findByText('Aanbetaling open')
    // Eén lege startregel in het boekvoorstel.
    await waitFor(() => expect(screen.getAllByLabelText('Netto bedrag')).toHaveLength(1))
    await gebruiker.click(screen.getByRole('button', { name: 'Verrekenregel toevoegen' }))

    await waitFor(() => expect(screen.getAllByLabelText('Netto bedrag')).toHaveLength(2))
    const netto = screen.getAllByLabelText('Netto bedrag').map((el) => (el as HTMLInputElement).value)
    expect(netto).toContain('-250.00')
    const omschrijvingen = screen
      .getAllByRole('textbox')
      .map((el) => (el as HTMLInputElement).value)
    expect(omschrijvingen).toContain('Verrekening aanbetaling RLZ-04-00002036 2026-08-12')
    // Twee keer klikken = twee regels (elke klik een nieuw volgnummer).
    await gebruiker.click(screen.getByRole('button', { name: 'Verrekenregel toevoegen' }))
    await waitFor(() => expect(screen.getAllByLabelText('Netto bedrag')).toHaveLength(3))
  })
})

describe('DocumentDetailScreen — ⋯-menu "Verplaats naar andere administratie…" (addendum 27-08 punt 5)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  const DOEL_ID = 'aaaaaaaa-0000-0000-0000-000000000002'

  function basisDetail(status: string, extra: Record<string, unknown> = {}) {
    return {
      id: DOCUMENT_ID,
      administratie_id: ADMINISTRATIE_ID,
      bestandsnaam: 'arvum-4711.pdf',
      status,
      bron: 'email',
      soort: 'inkoopfactuur',
      mogelijk_duplicaat_van: null,
      toegewezen_aan: null,
      aangemaakt_op: '2026-08-27T10:00:00Z',
      laatst_gewijzigd_op: '2026-08-27T10:00:00Z',
      veldvoorstel: null,
      afwijzing: null,
      tijdlijn: [{ van_status: null, naar_status: 'ontvangen', actor_id: 'x', actor_is_systeem: false, detail: null, tijdstip: '2026-08-27T10:00:00Z' }],
      ...extra,
    }
  }

  /** Bovenop de standaard-mock: administraties (voor de modal) + het verplaats-endpoint. */
  function metVerplaatsMock(verplaatsAanroepen: unknown[]) {
    const basis = globalThis.fetch
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith('/auth/administraties')) {
          return Promise.resolve(
            jsonResponse({
              administraties: [
                { id: ADMINISTRATIE_ID, naam: 'ARVUM B.V.' },
                { id: DOEL_ID, naam: 'Port of Rotterdam N.V.' },
              ],
            }),
          )
        }
        if (url.endsWith('/verplaats') && init?.method === 'POST') {
          verplaatsAanroepen.push(JSON.parse(String(init.body)))
          return Promise.resolve(
            jsonResponse({
              document_id: DOCUMENT_ID,
              status: 'te_controleren',
              van_administratie_id: ADMINISTRATIE_ID,
              van_administratie_naam: 'ARVUM B.V.',
              naar_administratie_id: DOEL_ID,
              naar_administratie_naam: 'Port of Rotterdam N.V.',
              leerregels_gecorrigeerd: ['tenaamstelling', 'afzender'],
              vragen_verhuisd: 0,
              vragen_hertoegewezen: 0,
            }),
          )
        }
        return basis(url, init)
      }),
    )
  }

  it('te_controleren: menu-item actief → modal → verplaatsen → toast + navigatie naar het document in het doel', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock(basisDetail('te_controleren'))
    const aanroepen: unknown[] = []
    metVerplaatsMock(aanroepen)
    renderScherm()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Meer acties' })).toBeInTheDocument())

    await gebruiker.click(screen.getByRole('button', { name: 'Meer acties' }))
    const item = screen.getByRole('menuitem', { name: 'Verplaats naar andere administratie…' })
    expect(item).toBeEnabled()
    await gebruiker.click(item)

    expect(await screen.findByRole('dialog', { name: 'Verplaats naar andere administratie' })).toBeInTheDocument()
    const veld = screen.getByRole('combobox', { name: /Doeladministratie/ })
    await gebruiker.click(veld)
    await gebruiker.click(await screen.findByRole('option', { name: 'Port of Rotterdam N.V.' }))
    await gebruiker.click(screen.getByRole('button', { name: 'Verplaatsen naar Port of Rotterdam N.V.' }))

    await waitFor(() => expect(screen.getByTestId('locatie')).toHaveTextContent(`/documenten/${DOEL_ID}/${DOCUMENT_ID}`))
    expect(aanroepen).toEqual([{ doel_administratie_id: DOEL_ID, onthoud_tenaamstelling: false }])
    expect(screen.getByText(/Verplaatst naar Port of Rotterdam N.V./)).toBeInTheDocument()
  })

  it.each([
    ['geboekt', /storno|Tegenboeken/],
    ['ter_accordering', /trek de accordering eerst in/],
  ])('%s: menu-item uitgeschakeld mét uitleg waarom (server-side afgedwongen)', async (status, uitleg) => {
    const gebruiker = userEvent.setup()
    installFetchMock(basisDetail(status))
    renderScherm()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Meer acties' })).toBeInTheDocument())
    await gebruiker.click(screen.getByRole('button', { name: 'Meer acties' }))
    const item = screen.getByRole('menuitem', { name: 'Verplaats naar andere administratie…' })
    expect(item).toBeDisabled()
    expect(screen.getByRole('menu')).toHaveTextContent(uitleg)
    await gebruiker.click(item)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('tijdlijn toont de verhuizing leesbaar: van → naar, geheugen-correctie en de vervallen extractie', async () => {
    installFetchMock(
      basisDetail('te_controleren', {
        tijdlijn: [
          { van_status: null, naar_status: 'ontvangen', actor_id: 'x', actor_is_systeem: false, detail: null, tijdstip: '2026-08-27T10:00:00Z' },
          {
            van_status: 'te_controleren',
            naar_status: 'ontvangen',
            actor_id: 'x',
            actor_is_systeem: false,
            detail: {
              verplaatst: {
                van_administratie_id: 'a',
                van_administratie_naam: 'ARVUM B.V.',
                naar_administratie_id: DOEL_ID,
                naar_administratie_naam: 'Port of Rotterdam N.V.',
                van_status: 'te_controleren',
              },
              veldvoorstel_vervallen: true,
              leerregels_gecorrigeerd: ['tenaamstelling', 'afzender'],
              vragen_verhuisd: ['v1'],
            },
            tijdstip: '2026-08-27T11:00:00Z',
          },
          {
            van_status: 'te_controleren',
            naar_status: 'vraag_open',
            actor_id: 'x',
            actor_is_systeem: false,
            detail: { vraag_id: 'v1', vraag_hersteld_na_extractie: true },
            tijdstip: '2026-08-27T11:00:05Z',
          },
        ],
      }),
    )
    renderScherm()
    await waitFor(() => expect(screen.getByText(/Verplaatst van ARVUM B.V. naar Port of Rotterdam N.V./)).toBeInTheDocument())
    expect(screen.getByText(/toewijzings-geheugen gecorrigeerd \(tenaamstelling, afzender\)/)).toBeInTheDocument()
    expect(screen.getByText(/1 open vraag verhuisd/)).toBeInTheDocument()
    expect(screen.getByText(/veldvoorstel vervallen, extractie opnieuw/)).toBeInTheDocument()
    expect(screen.getByText(/Open vraag blokkeert boeken weer ná de nieuwe extractie/)).toBeInTheDocument()
  })
})

// ————— Werkstroom-run 27/28-08: lijstcontext (punt 1), sneltoetsen (punt 5), vervallen-regel (punt 2a) —————

const CONTEXT_QUERY = 'soort=inkoopfactuur&status=klaar_om_te_boeken'
const K2_ID = 'dddddddd-0000-0000-0000-00000000000b'
const T1_ID = 'dddddddd-0000-0000-0000-00000000000c'

function renderSchermMetQuery(query: string) {
  return render(
    <MemoryRouter initialEntries={[`/documenten/${ADMINISTRATIE_ID}/${DOCUMENT_ID}?${query}`]}>
      <ToastProvider>
        <LocatieProbe />
        <Routes>
          <Route path="/documenten/:administratieId/:documentId" element={<DocumentDetailScreen />} />
          <Route path="*" element={<div>elders</div>} />
        </Routes>
      </ToastProvider>
    </MemoryRouter>,
  )
}

describe('DocumentDetailScreen — lijstcontext reist mee (punt 1b/1c)', () => {
  afterEach(() => vi.unstubAllGlobals())

  const lijst = [
    lijstItem(DOCUMENT_ID, 'inkoopfactuur', 'klaar_om_te_boeken'),
    lijstItem(T1_ID, 'inkoopfactuur', 'te_controleren'),
    lijstItem(K2_ID, 'inkoopfactuur', 'klaar_om_te_boeken'),
  ]

  it('toont "1 van 2" binnen het filter, ‹ uit, › naar het volgende klaar-om-te-boeken-document mét context; terugweg houdt het filter', async () => {
    const { default: userEvent } = await import('@testing-library/user-event')
    const gebruiker = userEvent.setup()
    installFetchMock(detailMet({ soort: 'inkoopfactuur', veldvoorstel: null, tijdlijn: [], status: 'klaar_om_te_boeken' }), { lijst })
    renderSchermMetQuery(CONTEXT_QUERY)

    const nav = await screen.findByTestId('lijst-navigatie')
    expect(nav).toHaveTextContent('1 van 2')
    expect(screen.getByRole('button', { name: 'Vorige document in de lijst' })).toBeDisabled()
    expect(screen.getByRole('link', { name: /← Werkvoorraad/ })).toHaveAttribute(
      'href',
      `/?administratie=${ADMINISTRATIE_ID}&${CONTEXT_QUERY}`,
    )

    await gebruiker.click(screen.getByRole('button', { name: 'Volgende document in de lijst' }))
    await waitFor(() =>
      expect(screen.getByTestId('locatie')).toHaveTextContent(`/documenten/${ADMINISTRATIE_ID}/${K2_ID}?${CONTEXT_QUERY}`),
    )
  })

  it('B5a (bugfix 02-09): ‹ ›-navigatie herlaadt de PDF — nieuw <object> mét nieuwe blob-URL, geen hergebruik van het oude element', async () => {
    const { default: userEvent } = await import('@testing-library/user-event')
    const gebruiker = userEvent.setup()
    const detail1 = detailMet({ soort: 'inkoopfactuur', veldvoorstel: null, tijdlijn: [], status: 'klaar_om_te_boeken' })
    installFetchMock(detail1, { lijst })
    // Het volgende document krijgt óók een detail-antwoord (de basis-mock kent alleen DOCUMENT_ID).
    const basis = fetch
    vi.stubGlobal('fetch', (url: string, init?: RequestInit) =>
      url.endsWith(`/documenten/${K2_ID}`) && !url.includes('/accordering/') && !init?.method
        ? Promise.resolve(jsonResponse({ ...detail1, id: K2_ID, bestandsnaam: 'tweede.pdf' }))
        : basis(url, init),
    )
    renderSchermMetQuery(CONTEXT_QUERY)

    const eerste = await screen.findByTestId('bijlage-pdf')
    const eersteUrl = eerste.getAttribute('data')
    expect(eersteUrl).toMatch(/^blob:/)
    // Fix C2 (04-09): de viewer opent zónder miniaturen-zijbalk (openingsstand in het
    // URL-fragment); nooit toolbar=0 — de gebruiker moet de zijbalk via ☰ kunnen openen.
    expect(eersteUrl).toContain('#pagemode=none&navpanes=0&view=FitH')
    expect(eersteUrl).not.toContain('toolbar=0')

    await gebruiker.click(screen.getByRole('button', { name: 'Volgende document in de lijst' }))
    await waitFor(() => expect(screen.getByTestId('locatie')).toHaveTextContent(`/documenten/${ADMINISTRATIE_ID}/${K2_ID}`))
    await waitFor(() => {
      const tweede = screen.getByTestId('bijlage-pdf')
      expect(tweede.getAttribute('data')).not.toBe(eersteUrl)
    })
    // Het oude <object> is vervangen (key op de blob-URL), niet gemuteerd.
    expect(eerste).not.toBeInTheDocument()
  })

  it('B5b (bugfix 02-09): de uitleg van › staat als tooltip bij de knop (anker-popup), niet als losse title', async () => {
    const { default: userEvent } = await import('@testing-library/user-event')
    const gebruiker = userEvent.setup()
    installFetchMock(detailMet({ soort: 'inkoopfactuur', veldvoorstel: null, tijdlijn: [], status: 'klaar_om_te_boeken' }), { lijst })
    renderSchermMetQuery(CONTEXT_QUERY)
    const volgende = await screen.findByRole('button', { name: 'Volgende document in de lijst' })
    expect(volgende).not.toHaveAttribute('title')
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
    await gebruiker.hover(volgende)
    expect(await screen.findByRole('tooltip')).toHaveTextContent('Volgende in de gefilterde lijst — sneltoets →')
    // Anker-popup: portal op documentniveau mét position: fixed (nooit afgekapt/verdwaald linksboven).
    expect(screen.getByRole('tooltip')).toHaveStyle({ position: 'fixed' })
    await gebruiker.unhover(volgende)
    await waitFor(() => expect(screen.queryByRole('tooltip')).not.toBeInTheDocument())
  })

  it('zonder context: geen ‹ ›-navigatie en de kale terugweg (bestaand gedrag)', async () => {
    installFetchMock(detailMet({ soort: 'inkoopfactuur', veldvoorstel: null, tijdlijn: [] }), { lijst })
    renderScherm()
    await screen.findByText('factuur.pdf')
    expect(screen.queryByTestId('lijst-navigatie')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: /← Werkvoorraad/ })).toHaveAttribute('href', `/?administratie=${ADMINISTRATIE_ID}`)
  })

  it('boeken vanuit het filter "Klaar om te boeken" opent het volgende klaar-om-te-boeken-document (niet het te-controleren-document)', async () => {
    const { default: userEvent } = await import('@testing-library/user-event')
    const gebruiker = userEvent.setup()
    const opties: MockOpties = {
      lijst,
      lijstAanroepen: [],
      boekenAanroepen: [],
      checksResponse: GROEN_RAPPORT,
      boekenResponse: { document_id: DOCUMENT_ID, status: 'geboekt', rlz_document_id: 'x', rlz_boekstuknummer: 'RLZ-1' },
      boekvoorstel: {
        document_id: DOCUMENT_ID,
        vendor_id: null,
        referentie: 'F-1',
        factuurdatum: null,
        totaalbedrag: null,
        rlz_boekstuknummer: null,
        opgeslagen: true,
        regels: [],
      },
    }
    installFetchMock(detailMet({ soort: 'inkoopfactuur', veldvoorstel: null, tijdlijn: [], status: 'klaar_om_te_boeken' }), opties)
    renderSchermMetQuery(CONTEXT_QUERY)

    const knop = await screen.findByRole('button', { name: 'Boeken in RLZ ✓' })
    await waitFor(() => expect(knop).toBeEnabled())
    await gebruiker.click(knop)
    await waitFor(() => expect(opties.boekenAanroepen).toHaveLength(1))
    await waitFor(() =>
      expect(screen.getByTestId('locatie')).toHaveTextContent(`/documenten/${ADMINISTRATIE_ID}/${K2_ID}?${CONTEXT_QUERY}`),
    )
  })

  it('filter leeg ná boeken → terug naar de lijst mét dat filter', async () => {
    const { default: userEvent } = await import('@testing-library/user-event')
    const gebruiker = userEvent.setup()
    const opties: MockOpties = {
      lijst: [lijstItem(DOCUMENT_ID, 'inkoopfactuur', 'klaar_om_te_boeken'), lijstItem(T1_ID, 'inkoopfactuur', 'te_controleren')],
      boekenAanroepen: [],
      checksResponse: GROEN_RAPPORT,
      boekenResponse: { document_id: DOCUMENT_ID, status: 'geboekt', rlz_document_id: 'x', rlz_boekstuknummer: 'RLZ-1' },
      boekvoorstel: { document_id: DOCUMENT_ID, vendor_id: null, referentie: 'F-1', factuurdatum: null, totaalbedrag: null, rlz_boekstuknummer: null, opgeslagen: true, regels: [] },
    }
    installFetchMock(detailMet({ soort: 'inkoopfactuur', veldvoorstel: null, tijdlijn: [], status: 'klaar_om_te_boeken' }), opties)
    renderSchermMetQuery(CONTEXT_QUERY)
    const knop = await screen.findByRole('button', { name: 'Boeken in RLZ ✓' })
    await waitFor(() => expect(knop).toBeEnabled())
    await gebruiker.click(knop)
    await waitFor(() => expect(screen.getByTestId('locatie')).toHaveTextContent(`/?administratie=${ADMINISTRATIE_ID}&${CONTEXT_QUERY}`))
  })
})

describe('DocumentDetailScreen — sneltoetsen (punt 5)', () => {
  afterEach(() => vi.unstubAllGlobals())

  const lijst = [lijstItem(DOCUMENT_ID, 'inkoopfactuur', 'klaar_om_te_boeken'), lijstItem(K2_ID, 'inkoopfactuur', 'klaar_om_te_boeken')]

  it('B boekt via de actieve knop (pas als die actief is); ? toont het overzicht; Esc gaat terug naar de lijst', async () => {
    const { default: userEvent } = await import('@testing-library/user-event')
    const gebruiker = userEvent.setup()
    const opties: MockOpties = {
      lijst,
      boekenAanroepen: [],
      checksResponse: GROEN_RAPPORT,
      boekenResponse: { document_id: DOCUMENT_ID, status: 'geboekt', rlz_document_id: 'x', rlz_boekstuknummer: 'RLZ-1' },
      boekvoorstel: { document_id: DOCUMENT_ID, vendor_id: null, referentie: 'F-1', factuurdatum: null, totaalbedrag: null, rlz_boekstuknummer: null, opgeslagen: true, regels: [] },
    }
    installFetchMock(detailMet({ soort: 'inkoopfactuur', veldvoorstel: null, tijdlijn: [], status: 'klaar_om_te_boeken' }), opties)
    renderSchermMetQuery(CONTEXT_QUERY)
    await screen.findByTestId('lijst-navigatie')

    // Overzicht via "?" — en de dialoog blokkeert daarna de andere sneltoetsen.
    await gebruiker.keyboard('?')
    expect(await screen.findByRole('dialog')).toHaveTextContent('Sneltoetsen')
    await gebruiker.keyboard('b')
    expect(opties.boekenAanroepen).toHaveLength(0)
    await gebruiker.click(screen.getByRole('button', { name: 'Sluiten' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())

    // B = de actieve knop (tooltip vermeldt de toets).
    const knop = screen.getByRole('button', { name: 'Boeken in RLZ ✓' })
    expect(knop).toHaveAttribute('title', expect.stringContaining('sneltoets B'))
    await waitFor(() => expect(knop).toBeEnabled())
    await gebruiker.keyboard('b')
    await waitFor(() => expect(opties.boekenAanroepen).toHaveLength(1))
  })

  it('Esc = terug naar de lijst mét filter; → = volgende in de lijst; in een invoerveld doen de toetsen niets', async () => {
    const { default: userEvent } = await import('@testing-library/user-event')
    const gebruiker = userEvent.setup()
    installFetchMock(detailMet({ soort: 'inkoopfactuur', veldvoorstel: null, tijdlijn: [], status: 'klaar_om_te_boeken' }), { lijst })
    renderSchermMetQuery(CONTEXT_QUERY)
    await screen.findByTestId('lijst-navigatie')

    // Focus in een invoerveld (referentie) → geen sneltoets. Wacht tot het boekvoorstel-paneel staat.
    const veld = (await screen.findAllByRole('textbox'))[0]
    veld.focus()
    await gebruiker.keyboard('{ArrowRight}')
    expect(screen.getByTestId('locatie')).toHaveTextContent(`/documenten/${ADMINISTRATIE_ID}/${DOCUMENT_ID}`)
    veld.blur()

    await gebruiker.keyboard('{ArrowRight}')
    await waitFor(() => expect(screen.getByTestId('locatie')).toHaveTextContent(`/documenten/${ADMINISTRATIE_ID}/${K2_ID}?${CONTEXT_QUERY}`))
  })

  it('Esc gaat terug naar de documentenlijst mét het actieve filter', async () => {
    const { default: userEvent } = await import('@testing-library/user-event')
    const gebruiker = userEvent.setup()
    installFetchMock(detailMet({ soort: 'inkoopfactuur', veldvoorstel: null, tijdlijn: [], status: 'klaar_om_te_boeken' }), { lijst })
    renderSchermMetQuery(CONTEXT_QUERY)
    await screen.findByTestId('lijst-navigatie')
    await gebruiker.keyboard('{Escape}')
    await waitFor(() => expect(screen.getByTestId('locatie')).toHaveTextContent(`/?administratie=${ADMINISTRATIE_ID}&${CONTEXT_QUERY}`))
  })
})

describe('DocumentDetailScreen — tijdlijnregel "accordering vervallen" mét reden (punt 2a)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('toont de reden letterlijk bij de statusovergang Bij klant → Klaar om te boeken', async () => {
    installFetchMock(
      detailMet({
        status: 'klaar_om_te_boeken',
        veldvoorstel: null,
        tijdlijn: [
          {
            van_status: 'ter_accordering',
            naar_status: 'klaar_om_te_boeken',
            actor_id: 'beheerder',
            actor_is_systeem: false,
            detail: {
              accordering_id: 'acc-1',
              accordering_vervallen: true,
              reden: 'accorderingsconfiguratie gewijzigd — opnieuw aanbieden vereist',
              batch_id: 'batch-1',
            },
            tijdstip: '2026-08-27T14:02:00Z',
          },
        ],
      }),
    )
    renderScherm()
    expect(await screen.findByText(/Accordering vervallen — accorderingsconfiguratie gewijzigd — opnieuw aanbieden vereist/)).toBeInTheDocument()
  })
})

describe('DocumentDetailScreen — tijdlijn bugfix-run 28-08: elke ⚙-systeemovergang draagt een reden', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('toont "alle lagen akkoord", de boekfout ná akkoord en een generieke systeem-reden', async () => {
    installFetchMock(
      detailMet({
        status: 'ter_accordering',
        veldvoorstel: null,
        tijdlijn: [
          {
            van_status: 'ter_accordering',
            naar_status: 'ter_accordering',
            actor_id: 'systeem',
            actor_is_systeem: true,
            detail: { accordering_id: 'acc-1', alle_lagen_akkoord: true, reden: 'alle lagen akkoord — boeken gestart' },
            tijdstip: '2026-08-27T15:57:00Z',
          },
          {
            van_status: 'ter_accordering',
            naar_status: 'klaar_om_te_boeken',
            actor_id: 'systeem',
            actor_is_systeem: true,
            detail: { harde_checks: 'doorstaan', reden: 'harde checks doorstaan — boekpoging gestart' },
            tijdstip: '2026-08-27T15:57:01Z',
          },
          {
            van_status: 'klaar_om_te_boeken',
            naar_status: 'ter_accordering',
            actor_id: 'systeem',
            actor_is_systeem: true,
            detail: {
              accordering_id: 'acc-1',
              accordering_boek_fout: 'Boeken staat uit voor deze administratie of via de globale kill switch',
              reden: 'boeken ná het laatste klant-akkoord mislukt: Boeken staat uit …',
            },
            tijdstip: '2026-08-27T15:57:02Z',
          },
        ],
      }),
    )
    renderScherm()
    expect(await screen.findByText(/Alle lagen akkoord — boeken gestart/)).toBeInTheDocument()
    expect(screen.getByText(/Reden: harde checks doorstaan — boekpoging gestart/)).toBeInTheDocument()
    expect(
      screen.getByText(/Boeken ná het laatste klant-akkoord mislukt — Boeken staat uit voor deze administratie/),
    ).toBeInTheDocument()
    // Geen dubbele reden-regel bij de specifieke boekfout-regel.
    expect(screen.queryByText(/Reden: boeken ná het laatste klant-akkoord/)).not.toBeInTheDocument()
  })
})
