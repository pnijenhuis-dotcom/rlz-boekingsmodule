import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { DoorbelastingMappingDto, DoorbelastingRunDto } from '../api/types'
import { DoorbelastingReviewScreen } from './DoorbelastingReviewScreen'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const RUN_ID = 'cccccccc-0000-0000-0000-000000000003'
const MAPPING_CHALETS = 'dddddddd-0000-0000-0000-000000000004'
const MAPPING_RUBICON = 'dddddddd-0000-0000-0000-000000000005'
const BRON_REGEL_1 = 'ffffffff-0000-0000-0000-000000000006'
const BRON_REGEL_2 = 'ffffffff-0000-0000-0000-000000000007'
const DOEL_ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000008'
const LEDGER_ID = '99999999-0000-0000-0000-000000000009'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const detail = {
  id: DOCUMENT_ID,
  administratie_id: ADMINISTRATIE_ID,
  bestandsnaam: 'bouwmaat-2026-0642.pdf',
  status: 'geboekt',
  bron: 'upload',
  soort: 'inkoopfactuur',
  mogelijk_duplicaat_van: null,
  toegewezen_aan: null,
  aangemaakt_op: '2026-08-13T08:00:00Z',
  laatst_gewijzigd_op: '2026-08-13T08:00:00Z',
  veldvoorstel: null,
  afwijzing: null,
  tijdlijn: [],
}

const boekvoorstel = {
  document_id: DOCUMENT_ID,
  vendor_id: null,
  referentie: '2026-0642',
  factuurdatum: '2026-08-01',
  totaalbedrag: '1419.85',
  rlz_boekstuknummer: 'INK-00042',
  opgeslagen: true,
  regels: [
    {
      id: BRON_REGEL_1,
      ledger_id: null,
      taxrate_id: null,
      project_id: null,
      netto_bedrag: '762.00',
      btw_bedrag: '160.02',
      omschrijving: 'Multiplex 18mm (12×)',
    },
    {
      id: BRON_REGEL_2,
      ledger_id: null,
      taxrate_id: null,
      project_id: null,
      netto_bedrag: '411.10',
      btw_bedrag: '86.33',
      omschrijving: 'Bevestigingsmateriaal',
    },
  ],
  regels_samenvoegen: false,
  samenvoegen_toegestaan: true,
  samengevoegde_regel: null,
}

const mappings: DoorbelastingMappingDto[] = [
  {
    id: MAPPING_CHALETS,
    doelentiteit_naam: 'Kempen Chalets B.V.',
    doel_customer_guid: 'f5d427fa-2d63-4b19-bdb0-e3120fcbd92b',
    doel_administratie_id: DOEL_ADMINISTRATIE_ID,
    intercompany: true,
    provisie_kosten_ledger_id: LEDGER_ID,
    laatste_kosten_ledger_id: null,
    actief: true,
  },
  {
    id: MAPPING_RUBICON,
    doelentiteit_naam: 'Rubicon Investments B.V.',
    doel_customer_guid: '2f432363-127b-40e4-b331-ea8c03d4653d',
    doel_administratie_id: null,
    intercompany: false,
    provisie_kosten_ledger_id: null,
    laatste_kosten_ledger_id: null,
    actief: true,
  },
]

function run(overrides: Partial<DoorbelastingRunDto> = {}): DoorbelastingRunDto {
  return {
    id: RUN_ID,
    document_id: DOCUMENT_ID,
    status: 'concept',
    laatste_fout: null,
    regels: [],
    previews: [],
    checks: { geblokkeerd: true, resultaten: [{ naam: 'Verdeling per regel = 100%', ok: false, melding: 'Geen verdeelregels — selecteer minimaal één regel' }] },
    ...overrides,
  }
}

/** Run met een volledige 100%-verdeling van regel 1 en groene checks. */
function runMetVerdeling(overrides: Partial<DoorbelastingRunDto> = {}): DoorbelastingRunDto {
  return run({
    regels: [
      {
        id: '11111111-0000-0000-0000-000000000001',
        bron_regel_id: BRON_REGEL_1,
        mapping_id: MAPPING_CHALETS,
        percentage: '50.00',
        netto_deel: '381.00',
        doel_kosten_ledger_id: LEDGER_ID,
      },
      {
        id: '11111111-0000-0000-0000-000000000002',
        bron_regel_id: BRON_REGEL_1,
        mapping_id: MAPPING_RUBICON,
        percentage: '50.00',
        netto_deel: '381.00',
        doel_kosten_ledger_id: null,
      },
    ],
    previews: [
      {
        mapping_id: MAPPING_CHALETS,
        doelentiteit_naam: 'Kempen Chalets B.V.',
        onboarded: true,
        netto_totaal: '381.00',
        provisie_bedrag: '19.05',
        btw_bedrag: '84.01',
        boeking_status: null,
        boeking_id: null,
      },
      {
        mapping_id: MAPPING_RUBICON,
        doelentiteit_naam: 'Rubicon Investments B.V.',
        onboarded: false,
        netto_totaal: '381.00',
        provisie_bedrag: '19.05',
        btw_bedrag: '84.01',
        boeking_status: null,
        boeking_id: null,
      },
    ],
    checks: { geblokkeerd: false, resultaten: [{ naam: 'Verdeling per regel = 100%', ok: true, melding: 'Elke geselecteerde regel is voor exact 100% verdeeld' }] },
    ...overrides,
  })
}

interface MockOpties {
  run?: DoorbelastingRunDto
  runNaBoeken?: DoorbelastingRunDto
  verdelingResponse?: DoorbelastingRunDto
  verdelingAanroepen?: { url: string; body: unknown }[]
  boekenResponse?: Response
  boekenAanroepen?: string[]
}

function installFetchMock(opties: MockOpties = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith(`/documenten/${DOCUMENT_ID}`) && !init?.method) {
        return Promise.resolve(jsonResponse(detail))
      }
      if (url.endsWith('/boekvoorstel')) return Promise.resolve(jsonResponse(boekvoorstel))
      if (url.endsWith(`/documenten/${DOCUMENT_ID}/run`) && init?.method === 'POST') {
        return Promise.resolve(jsonResponse(opties.run ?? runMetVerdeling()))
      }
      if (url.endsWith('/mappings')) return Promise.resolve(jsonResponse(mappings))
      if (url.endsWith('/grootboek')) {
        return Promise.resolve(
          jsonResponse({ rekeningen: [{ ledger_id: LEDGER_ID, code: '4110', naam: 'Bouwmaterialen', soort: 2 }] }),
        )
      }
      if (url.endsWith('/verdeling') && init?.method === 'PUT') {
        opties.verdelingAanroepen?.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
        return Promise.resolve(jsonResponse(opties.verdelingResponse ?? runMetVerdeling()))
      }
      if (url.endsWith('/boeken') && init?.method === 'POST') {
        opties.boekenAanroepen?.push(url)
        return Promise.resolve(
          opties.boekenResponse ??
            jsonResponse({ per_doelentiteit: { [MAPPING_CHALETS]: 'geboekt', [MAPPING_RUBICON]: 'spiegel_open' } }),
        )
      }
      if (url.endsWith(`/runs/${RUN_ID}`) && !init?.method) {
        return Promise.resolve(jsonResponse(opties.runNaBoeken ?? opties.run ?? runMetVerdeling()))
      }
      if (url.endsWith('/spiegel-taken')) return Promise.resolve(jsonResponse([]))
      return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
    }),
  )
}

function renderScherm() {
  return render(
    <MemoryRouter initialEntries={[`/doorbelasting/${ADMINISTRATIE_ID}/${DOCUMENT_ID}`]}>
      <Routes>
        <Route path="/doorbelasting/:administratieId/:documentId" element={<DoorbelastingReviewScreen />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('DoorbelastingReviewScreen', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('toont per bron-regel de 100%-chip; een regel zonder verdeling heet "niet doorbelast"', async () => {
    installFetchMock()
    renderScherm()

    expect(await screen.findByText('Multiplex 18mm (12×)')).toBeInTheDocument()
    // Regel 1: 50+50 → exact 100%.
    expect(screen.getByText('100% ✓')).toBeInTheDocument()
    // Regel 2 heeft geen verdeelregels.
    expect(screen.getByText('niet doorbelast')).toBeInTheDocument()
  })

  it('markeert een verdeling die niet op 100% sluit', async () => {
    const nietSluitend = runMetVerdeling()
    nietSluitend.regels = [nietSluitend.regels[0]] // alleen de 50%-regel
    installFetchMock({ run: nietSluitend })
    renderScherm()

    expect(await screen.findByText('50% — moet exact 100% zijn')).toBeInTheDocument()
  })

  it('houdt de boekknop uit zolang de harde checks blokkeren', async () => {
    installFetchMock({ run: run() })
    renderScherm()

    const knop = await screen.findByRole('button', { name: 'Doorbelasten in RLZ ✓' })
    expect(knop).toBeDisabled()
    expect(screen.getByText('blokkerend')).toBeInTheDocument()
    expect(screen.getByText(/Geen verdeelregels/)).toBeInTheDocument()
  })

  it('slaat de verdeling op en toont daarna de server-berekende netto-delen', async () => {
    const verdelingAanroepen: { url: string; body: unknown }[] = []
    // Start met een lege run: de gebruiker bouwt de verdeling zelf op.
    installFetchMock({ run: run(), verdelingAanroepen, verdelingResponse: runMetVerdeling() })
    renderScherm()
    const gebruiker = userEvent.setup()

    // Voeg op regel 1 twee doelentiteiten toe (50/50 — de rest-prefill zet 100 en dan 0,
    // dus we typen de percentages zelf).
    const toevoegKnoppen = await screen.findAllByRole('button', { name: '+ Doelentiteit toevoegen' })
    await gebruiker.click(toevoegKnoppen[0])
    await gebruiker.selectOptions(
      screen.getByLabelText('Doelentiteit voor Multiplex 18mm (12×)'),
      MAPPING_CHALETS,
    )
    const pctVeld = screen.getByLabelText('Percentage voor Multiplex 18mm (12×)')
    await gebruiker.clear(pctVeld)
    await gebruiker.type(pctVeld, '50')
    await gebruiker.click(toevoegKnoppen[0])
    const selects = screen.getAllByLabelText('Doelentiteit voor Multiplex 18mm (12×)')
    await gebruiker.selectOptions(selects[1], MAPPING_RUBICON)
    const pctVelden = screen.getAllByLabelText('Percentage voor Multiplex 18mm (12×)')
    await gebruiker.clear(pctVelden[1])
    await gebruiker.type(pctVelden[1], '50')

    // Vóór opslaan: geen server-bedragen, wel de "na opslaan"-plek.
    expect(screen.getAllByText('na opslaan').length).toBeGreaterThan(0)

    await gebruiker.click(screen.getByRole('button', { name: 'Verdeling opslaan' }))

    await waitFor(() => expect(verdelingAanroepen).toHaveLength(1))
    expect(verdelingAanroepen[0].body).toEqual({
      regels: [
        { bron_regel_id: BRON_REGEL_1, mapping_id: MAPPING_CHALETS, percentage: '50', doel_kosten_ledger_id: null },
        { bron_regel_id: BRON_REGEL_1, mapping_id: MAPPING_RUBICON, percentage: '50', doel_kosten_ledger_id: null },
      ],
    })
    // Server-netto_delen (grootste-rest) zichtbaar ná opslaan.
    expect(await screen.findAllByText('€ 381,00')).not.toHaveLength(0)
  })

  it('boekt en toont het per-doelentiteit-resultaat, ook bij gedeeltelijk succes', async () => {
    const boekenAanroepen: string[] = []
    installFetchMock({
      boekenAanroepen,
      boekenResponse: jsonResponse({
        per_doelentiteit: { [MAPPING_CHALETS]: 'geboekt', [MAPPING_RUBICON]: 'half_geboekt' },
      }),
      runNaBoeken: runMetVerdeling({ status: 'concept' }),
    })
    renderScherm()
    const gebruiker = userEvent.setup()

    const knop = await screen.findByRole('button', { name: 'Doorbelasten in RLZ ✓' })
    expect(knop).toBeEnabled()
    await gebruiker.click(knop)

    await waitFor(() => expect(boekenAanroepen).toHaveLength(1))
    expect(boekenAanroepen[0]).toContain(`/runs/${RUN_ID}/boeken`)
    expect(await screen.findByText('Resultaat per doelentiteit:')).toBeInTheDocument()
    expect(screen.getByText('geboekt ✓')).toBeInTheDocument()
    expect(screen.getByText('half geboekt')).toBeInTheDocument()
  })

  it('toont bij een 409 met checks de pop-up met de gefaalde check (server herdraait bindend)', async () => {
    installFetchMock({
      boekenResponse: jsonResponse(
        {
          detail: {
            melding: 'De server herdraaide de harde checks: blokkerend.',
            checks: {
              geblokkeerd: true,
              resultaten: [{ naam: 'Doel-mapping en instellingen', ok: false, melding: 'btw-tarief doorbelasting niet ingesteld (Instellingen)' }],
            },
          },
        },
        409,
      ),
    })
    renderScherm()
    const gebruiker = userEvent.setup()

    await gebruiker.click(await screen.findByRole('button', { name: 'Doorbelasten in RLZ ✓' }))

    // Pop-up (ChecksPopup) mét de servermelding; de gefaalde check staat in de pop-up én in de
    // ververste inline checklijst — vandaar getAllByText.
    expect(await screen.findByText('Boeken geblokkeerd door harde checks')).toBeInTheDocument()
    expect(screen.getByText('De server herdraaide de harde checks: blokkerend.')).toBeInTheDocument()
    expect(screen.getAllByText(/btw-tarief doorbelasting niet ingesteld/).length).toBeGreaterThan(0)
  })
})
