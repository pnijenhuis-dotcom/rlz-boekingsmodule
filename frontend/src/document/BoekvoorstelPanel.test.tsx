import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BoekvoorstelPanel } from './BoekvoorstelPanel'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const LEDGER_ID = 'cccccccc-0000-0000-0000-000000000003'
const TAXRATE_ID = 'dddddddd-0000-0000-0000-000000000004'
const VENDOR_ID = 'eeeeeeee-0000-0000-0000-000000000005'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const LEEG_BOEKVOORSTEL = {
  document_id: DOCUMENT_ID,
  vendor_id: null,
  referentie: null,
  factuurdatum: null,
  totaalbedrag: null,
  rlz_boekstuknummer: null,
  opgeslagen: false,
  regels: [],
}

interface FetchMockOverrides {
  boekvoorstel?: unknown
  putResponse?: unknown
  boekenResponse?: [unknown, number]
  projectVerplicht?: boolean
  grootboek?: unknown[]
  taxrates?: unknown[]
  vendors?: unknown[]
  projecten?: unknown[]
  syncAanroepen?: string[]
}

function installFetchMock(overrides: FetchMockOverrides) {
  const grootboek = overrides.grootboek ?? [{ ledger_id: LEDGER_ID, code: '4699', naam: 'Diverse kosten', soort: 2 }]
  const taxrates = overrides.taxrates ?? [{ id: TAXRATE_ID, naam: 'NL Hoog 21%' }]
  const vendors = overrides.vendors ?? [{ id: VENDOR_ID, naam: 'Bouwmaat Nederland B.V.' }]
  const projecten = overrides.projecten ?? []

  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.includes('/sync/') && init?.method === 'POST') {
        overrides.syncAanroepen?.push(url)
        return Promise.resolve(jsonResponse({ aangemaakt: 0, bijgewerkt: 0, verdwenen: 0 }))
      }
      if (url.endsWith('/grootboek')) return Promise.resolve(jsonResponse({ rekeningen: grootboek }))
      if (url.endsWith('/btw-codes')) return Promise.resolve(jsonResponse({ btw_codes: taxrates }))
      if (url.endsWith('/crediteuren')) return Promise.resolve(jsonResponse({ crediteuren: vendors }))
      if (url.endsWith('/projecten')) return Promise.resolve(jsonResponse({ projecten }))
      if (url.endsWith('/project-instelling')) return Promise.resolve(jsonResponse({ verplicht: overrides.projectVerplicht ?? false }))
      if (url.endsWith('/boekvoorstel') && (!init || init.method === undefined)) {
        return Promise.resolve(jsonResponse(overrides.boekvoorstel ?? LEEG_BOEKVOORSTEL))
      }
      if (url.endsWith('/boekvoorstel') && init?.method === 'PUT') {
        return Promise.resolve(jsonResponse(overrides.putResponse))
      }
      if (url.endsWith('/boeken') && init?.method === 'POST') {
        const [body, status] = overrides.boekenResponse ?? [{}, 200]
        return Promise.resolve(jsonResponse(body, status))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

describe('BoekvoorstelPanel', () => {
  beforeEach(() => {
    vi.stubGlobal('crypto', { ...globalThis.crypto, randomUUID: () => `local-${Math.random()}` })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('vult crediteur/GB/btw-comboboxen met de sync-cache en toont groene checks na controleren', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({
      putResponse: {
        boekvoorstel: { ...LEEG_BOEKVOORSTEL, opgeslagen: true, vendor_id: VENDOR_ID },
        checks: {
          geblokkeerd: false,
          resultaten: [
            { naam: 'Verplichte velden', ok: true, melding: 'Alle verplichte velden zijn ingevuld' },
            { naam: 'Regeltelling vs totaal', ok: true, melding: 'Som klopt' },
            { naam: 'Duplicaatcheck', ok: true, melding: 'Geen duplicaat gevonden' },
          ],
        },
      },
    })

    render(
      <BoekvoorstelPanel
        administratieId={ADMINISTRATIE_ID}
        documentId={DOCUMENT_ID}
        status="te_controleren"
        onGeboekt={() => {}}
        onHersteld={() => {}}
      />,
    )

    await waitFor(() => expect(screen.getByLabelText('Crediteur', { exact: false })).toBeInTheDocument())

    await gebruiker.click(screen.getByLabelText('Crediteur', { exact: false }))
    await waitFor(() => expect(screen.getByText('Bouwmaat Nederland B.V.')).toBeInTheDocument())
    await gebruiker.click(screen.getByText('Bouwmaat Nederland B.V.'))
    expect(screen.getByLabelText('Crediteur', { exact: false })).toHaveValue('Bouwmaat Nederland B.V.')

    const [grootboekVeld] = screen.getAllByLabelText('Grootboek', { exact: false })
    await gebruiker.click(grootboekVeld)
    // Design-pass taak 2: code (4699) en omschrijving (Diverse kosten) staan als losse
    // elementen in de rij (code vet) — geen aparte "·"-tekstnode meer om op te matchen.
    await waitFor(() => expect(screen.getByRole('option', { name: /4699.*Diverse kosten/ })).toBeInTheDocument())
    await gebruiker.click(screen.getByRole('option', { name: /4699.*Diverse kosten/ }))
    expect(grootboekVeld).toHaveValue('4699 · Diverse kosten')

    const [btwVeld] = screen.getAllByLabelText('Btw-code', { exact: false })
    await gebruiker.click(btwVeld)
    await waitFor(() => expect(screen.getByText('NL Hoog 21%')).toBeInTheDocument())
    await gebruiker.click(screen.getByText('NL Hoog 21%'))

    await gebruiker.click(screen.getByRole('button', { name: 'Controleren' }))

    await waitFor(() => expect(screen.getAllByText('OK')).toHaveLength(3))
    expect(screen.getByRole('button', { name: 'Boeken in RLZ ✓' })).toBeEnabled()
  })

  it('toont de blokkerende check en houdt de boekknop uit als de checks falen', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({
      putResponse: {
        boekvoorstel: LEEG_BOEKVOORSTEL,
        checks: {
          geblokkeerd: true,
          resultaten: [
            { naam: 'Verplichte velden', ok: false, melding: 'Ontbrekend: crediteur' },
            { naam: 'Regeltelling vs totaal', ok: false, melding: 'Geen factuurtotaal ingevuld' },
            { naam: 'Duplicaatcheck', ok: false, melding: 'Kan niet controleren' },
          ],
        },
      },
    })

    render(
      <BoekvoorstelPanel
        administratieId={ADMINISTRATIE_ID}
        documentId={DOCUMENT_ID}
        status="te_controleren"
        onGeboekt={() => {}}
        onHersteld={() => {}}
      />,
    )
    await waitFor(() => expect(screen.getByRole('button', { name: 'Controleren' })).toBeInTheDocument())
    await gebruiker.click(screen.getByRole('button', { name: 'Controleren' }))

    await waitFor(() => expect(screen.getAllByText('Blokkerend')).toHaveLength(3))
    expect(screen.getByRole('button', { name: 'Boeken in RLZ ✓' })).toBeDisabled()
  })

  it('toont het boekstuknummer na een geslaagde boeking', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({
      boekvoorstel: {
        ...LEEG_BOEKVOORSTEL,
        opgeslagen: true,
        vendor_id: VENDOR_ID,
        referentie: 'F-1',
        factuurdatum: '2026-07-01',
        totaalbedrag: '121.00',
        regels: [
          { ledger_id: LEDGER_ID, taxrate_id: TAXRATE_ID, project_id: null, netto_bedrag: '100.00', btw_bedrag: '21.00', omschrijving: null },
        ],
      },
      putResponse: {
        boekvoorstel: { document_id: DOCUMENT_ID, opgeslagen: true },
        checks: { geblokkeerd: false, resultaten: [{ naam: 'Verplichte velden', ok: true, melding: 'ok' }] },
      },
      boekenResponse: [
        { document_id: DOCUMENT_ID, status: 'geboekt', rlz_document_id: 'x', rlz_boekstuknummer: 'RLZ-04-00002001' },
        200,
      ],
    })

    render(
      <BoekvoorstelPanel
        administratieId={ADMINISTRATIE_ID}
        documentId={DOCUMENT_ID}
        status="te_controleren"
        onGeboekt={() => {}}
        onHersteld={() => {}}
      />,
    )
    await waitFor(() => expect(screen.getByRole('button', { name: 'Controleren' })).toBeInTheDocument())
    await gebruiker.click(screen.getByRole('button', { name: 'Controleren' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Boeken in RLZ ✓' })).toBeEnabled())

    await gebruiker.click(screen.getByRole('button', { name: 'Boeken in RLZ ✓' }))

    await waitFor(() => expect(screen.getByText('RLZ-04-00002001')).toBeInTheDocument())
  })

  it('een geboekt document toont het boekstuknummer en verbergt de bewerkbare velden', async () => {
    installFetchMock({
      boekvoorstel: {
        ...LEEG_BOEKVOORSTEL,
        opgeslagen: true,
        rlz_boekstuknummer: 'RLZ-04-00002001',
      },
    })

    render(
      <BoekvoorstelPanel
        administratieId={ADMINISTRATIE_ID}
        documentId={DOCUMENT_ID}
        status="geboekt"
        onGeboekt={() => {}}
        onHersteld={() => {}}
      />,
    )

    await waitFor(() => expect(screen.getByText('RLZ-04-00002001')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Boeken in RLZ ✓' })).not.toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: 'Referentie / factuurnummer' })).not.toBeInTheDocument()
    expect(
      screen.getByText('Wijzigen kan alleen via stornering in Reeleezee (actie 19); daarna komt het document hier terug als concept.'),
    ).toBeInTheDocument()
  })

  it('design-pass taak 7: een veldwijziging na een groene controle zet de boekknop weer uit', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({
      putResponse: {
        boekvoorstel: LEEG_BOEKVOORSTEL,
        checks: {
          geblokkeerd: false,
          resultaten: [{ naam: 'Verplichte velden', ok: true, melding: 'ok' }],
        },
      },
    })

    render(
      <BoekvoorstelPanel
        administratieId={ADMINISTRATIE_ID}
        documentId={DOCUMENT_ID}
        status="te_controleren"
        onGeboekt={() => {}}
        onHersteld={() => {}}
      />,
    )
    await waitFor(() => expect(screen.getByRole('button', { name: 'Controleren' })).toBeInTheDocument())
    await gebruiker.click(screen.getByRole('button', { name: 'Controleren' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Boeken in RLZ ✓' })).toBeEnabled())

    await gebruiker.type(screen.getByLabelText('Referentie / factuurnummer'), 'X')

    expect(screen.getByRole('button', { name: 'Boeken in RLZ ✓' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Boeken in RLZ ✓' })).toHaveAttribute(
      'title',
      expect.stringContaining('opnieuw'),
    )
    expect(screen.getByText(/verouderd/)).toBeInTheDocument()
  })

  it('design-pass taak 4: de Project-kolom is verborgen als project_verplicht uit staat', async () => {
    installFetchMock({ projectVerplicht: false })
    render(
      <BoekvoorstelPanel
        administratieId={ADMINISTRATIE_ID}
        documentId={DOCUMENT_ID}
        status="te_controleren"
        onGeboekt={() => {}}
        onHersteld={() => {}}
      />,
    )
    await waitFor(() => expect(screen.getByRole('button', { name: 'Controleren' })).toBeInTheDocument())
    expect(screen.queryByText('Project')).not.toBeInTheDocument()
  })

  it('design-pass taak 4: de Project-kolom is zichtbaar en verplicht als project_verplicht aan staat', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({
      projectVerplicht: true,
      projecten: [{ id: 'ffffffff-0000-0000-0000-000000000006', naam: 'P-001 Testproject' }],
    })
    render(
      <BoekvoorstelPanel
        administratieId={ADMINISTRATIE_ID}
        documentId={DOCUMENT_ID}
        status="te_controleren"
        onGeboekt={() => {}}
        onHersteld={() => {}}
      />,
    )
    await waitFor(() => expect(screen.getByText('Project')).toBeInTheDocument())

    const projectVeld = screen.getByLabelText(/Project/, { exact: false })
    await gebruiker.click(projectVeld)
    expect(screen.getByText('P-001 Testproject')).toBeInTheDocument()
  })

  it('design-pass taak 8: de live aansluit-indicator reageert op typen, zonder Controleren te klikken', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({
      boekvoorstel: {
        ...LEEG_BOEKVOORSTEL,
        regels: [
          {
            ledger_id: LEDGER_ID,
            taxrate_id: TAXRATE_ID,
            project_id: null,
            netto_bedrag: '100,00',
            btw_bedrag: '21,00',
            omschrijving: null,
          },
        ],
      },
    })
    render(
      <BoekvoorstelPanel
        administratieId={ADMINISTRATIE_ID}
        documentId={DOCUMENT_ID}
        status="te_controleren"
        onGeboekt={() => {}}
        onHersteld={() => {}}
      />,
    )
    await waitFor(() => expect(screen.getByLabelText('Totaalbedrag (incl. btw)')).toBeInTheDocument())

    await gebruiker.type(screen.getByLabelText('Totaalbedrag (incl. btw)'), '121,00')
    await waitFor(() => expect(screen.getByText(/Aansluitend/)).toBeInTheDocument())

    await gebruiker.clear(screen.getByLabelText('Totaalbedrag (incl. btw)'))
    await gebruiker.type(screen.getByLabelText('Totaalbedrag (incl. btw)'), '999,00')
    await waitFor(() => expect(screen.getByText(/Afwijking/)).toBeInTheDocument())
  })

  it('design-pass taak 3: btw-bedrag wordt automatisch afgeleid uit netto x taxrate-percentage', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({ taxrates: [{ id: TAXRATE_ID, naam: 'NL Hoog Tarief', percentage: '0.2100' }] })
    render(
      <BoekvoorstelPanel
        administratieId={ADMINISTRATIE_ID}
        documentId={DOCUMENT_ID}
        status="te_controleren"
        onGeboekt={() => {}}
        onHersteld={() => {}}
      />,
    )
    await waitFor(() => expect(screen.getAllByLabelText('Grootboek', { exact: false })[0]).toBeInTheDocument())

    const [btwCodeVeld] = screen.getAllByLabelText('Btw-code', { exact: false })
    await gebruiker.click(btwCodeVeld)
    await waitFor(() => expect(screen.getByRole('option', { name: /21%.*NL Hoog Tarief/ })).toBeInTheDocument())
    await gebruiker.click(screen.getByRole('option', { name: /21%.*NL Hoog Tarief/ }))

    await gebruiker.type(screen.getByLabelText('Netto bedrag'), '100,00')

    expect(screen.getByLabelText('Btw bedrag')).toHaveValue('21,00')
    expect(screen.queryByText(/Berekend:/)).not.toBeInTheDocument()
  })

  it('design-pass taak 3: een handmatig ingevoerd btw-bedrag wordt nooit overschreven, maar krijgt een afwijking-hint', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({ taxrates: [{ id: TAXRATE_ID, naam: 'NL Hoog Tarief', percentage: '0.2100' }] })
    render(
      <BoekvoorstelPanel
        administratieId={ADMINISTRATIE_ID}
        documentId={DOCUMENT_ID}
        status="te_controleren"
        onGeboekt={() => {}}
        onHersteld={() => {}}
      />,
    )
    await waitFor(() => expect(screen.getAllByLabelText('Grootboek', { exact: false })[0]).toBeInTheDocument())

    await gebruiker.type(screen.getByLabelText('Btw bedrag'), '5,00')

    const [btwCodeVeld] = screen.getAllByLabelText('Btw-code', { exact: false })
    await gebruiker.click(btwCodeVeld)
    await waitFor(() => expect(screen.getByRole('option', { name: /21%.*NL Hoog Tarief/ })).toBeInTheDocument())
    await gebruiker.click(screen.getByRole('option', { name: /21%.*NL Hoog Tarief/ }))
    await gebruiker.type(screen.getByLabelText('Netto bedrag'), '100,00')

    expect(screen.getByLabelText('Btw bedrag')).toHaveValue('5,00')
    expect(screen.getByText('Berekend: € 21,00')).toBeInTheDocument()
  })

  it('design-pass taak 3: lege cache toont een melding met "Nu synchroniseren", die alle vier de caches verversen', async () => {
    const gebruiker = userEvent.setup()
    const syncAanroepen: string[] = []
    installFetchMock({ grootboek: [], taxrates: [], vendors: [], syncAanroepen })

    render(
      <BoekvoorstelPanel
        administratieId={ADMINISTRATIE_ID}
        documentId={DOCUMENT_ID}
        status="te_controleren"
        onGeboekt={() => {}}
        onHersteld={() => {}}
      />,
    )

    await waitFor(() => expect(screen.getByText(/nog niet gesynchroniseerd voor crediteuren/)).toBeInTheDocument())
    expect(screen.getByText(/nog niet gesynchroniseerd voor het grootboekschema/)).toBeInTheDocument()

    const [knop] = screen.getAllByRole('button', { name: 'Nu synchroniseren' })
    await gebruiker.click(knop)

    await waitFor(() =>
      expect(syncAanroepen.map((u) => u.split('/sync/')[1])).toEqual(
        expect.arrayContaining(['ledgers', 'taxrates', 'vendors', 'projects']),
      ),
    )
  })
})
