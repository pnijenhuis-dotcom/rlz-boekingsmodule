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
  regels_samenvoegen: true,
  samenvoegen_toegestaan: true,
  samengevoegde_regel: null,
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
  /** Fix 3: elke PUT-body op /boekvoorstel wordt hier (geparsed) in gepusht. */
  putBodies?: unknown[]
  /** Fix 2: antwoord op POST /crediteuren — [body, status]; de aangemaakte crediteur wordt bij
   * een 201 ook aan de vendors-lijst toegevoegd zodat de refetch 'm kan tonen. */
  crediteurAanmakenResponse?: [unknown, number]
  crediteurAanmaakAanroepen?: unknown[]
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
      if (url.endsWith('/crediteuren') && init?.method === 'POST') {
        overrides.crediteurAanmaakAanroepen?.push(JSON.parse(String(init.body)))
        const [body, status] = overrides.crediteurAanmakenResponse ?? [null, 500]
        if (status === 201 && body && typeof body === 'object') vendors.push(body)
        return Promise.resolve(jsonResponse(body, status))
      }
      if (url.endsWith('/crediteuren')) return Promise.resolve(jsonResponse({ crediteuren: vendors }))
      if (url.endsWith('/projecten')) return Promise.resolve(jsonResponse({ projecten }))
      if (url.endsWith('/project-instelling')) return Promise.resolve(jsonResponse({ verplicht: overrides.projectVerplicht ?? false }))
      if (url.endsWith('/boekvoorstel') && (!init || init.method === undefined)) {
        return Promise.resolve(jsonResponse(overrides.boekvoorstel ?? LEEG_BOEKVOORSTEL))
      }
      if (url.endsWith('/boekvoorstel') && init?.method === 'PUT') {
        overrides.putBodies?.push(JSON.parse(String(init.body)))
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
    // getByRole i.p.v. getByText: het breedte-anker (aria-hidden) herhaalt de langste optietekst
    // in de DOM — de rol-query kijkt naar de toegankelijkheidsboom en ziet alleen de echte optie.
    await waitFor(() => expect(screen.getByRole('option', { name: 'Bouwmaat Nederland B.V.' })).toBeInTheDocument())
    await gebruiker.click(screen.getByRole('option', { name: 'Bouwmaat Nederland B.V.' }))
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
    await waitFor(() => expect(screen.getByRole('option', { name: 'NL Hoog 21%' })).toBeInTheDocument())
    await gebruiker.click(screen.getByRole('option', { name: 'NL Hoog 21%' }))

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
    expect(screen.getByRole('option', { name: 'P-001 Testproject' })).toBeInTheDocument()
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

  // ————— Fix 2 (2026-07-10): crediteur-voorstel als de AI de naam las maar de cache niet matcht —————

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
    regelaantal: 2,
    regels: [
      { omschrijving: 'Steigerhout', netto_bedrag: '60.00', btw_bedrag: '12.60', hoeveelheid: null, taxrate_id: null },
      { omschrijving: 'Bezorging', netto_bedrag: '40.00', btw_bedrag: '8.40', hoeveelheid: null, taxrate_id: null },
    ],
    zekerheid: { leverancier_naam: 0.93 },
    regel_zekerheid: [0.95, 0.9],
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

  const AI_BOEKVOORSTEL = {
    ...LEEG_BOEKVOORSTEL,
    referentie: 'F-1',
    factuurdatum: '2026-07-01',
    totaalbedrag: '121.00',
    regels: [
      { ledger_id: null, taxrate_id: null, project_id: null, netto_bedrag: '60.00', btw_bedrag: '12.60', omschrijving: 'Steigerhout' },
      { ledger_id: null, taxrate_id: null, project_id: null, netto_bedrag: '40.00', btw_bedrag: '8.40', omschrijving: 'Bezorging' },
    ],
    samengevoegde_regel: {
      ledger_id: null,
      taxrate_id: null,
      project_id: null,
      netto_bedrag: '100.00',
      btw_bedrag: '21.00',
      omschrijving: 'Factuur F-1 — samengevoegd (2 regels)',
    },
  }

  it('fix 2: AI-gelezen naam zonder cache-match toont een klikbaar voorstel met zekerheid, nooit alleen een leeg veld', async () => {
    installFetchMock({ boekvoorstel: AI_BOEKVOORSTEL, vendors: [] })
    render(
      <BoekvoorstelPanel
        administratieId={ADMINISTRATIE_ID}
        documentId={DOCUMENT_ID}
        status="te_controleren"
        veldvoorstel={AI_VOORSTEL}
        onGeboekt={() => {}}
        onHersteld={() => {}}
      />,
    )

    await waitFor(() => expect(screen.getByText(/AI las: „Confide BV”/)).toBeInTheDocument())
    expect(screen.getByText(/93%/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Nieuwe crediteur „Confide BV” aanmaken in RLZ/ })).toBeInTheDocument()
  })

  it('fix 2: "koppel aan bestaande" toont fuzzy-suggesties uit de cache en vult het veld bij een klik', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({
      boekvoorstel: AI_BOEKVOORSTEL,
      vendors: [
        { id: VENDOR_ID, naam: 'Confide B.V.' },
        { id: 'eeeeeeee-0000-0000-0000-000000000099', naam: 'Technische Unie' },
      ],
    })
    render(
      <BoekvoorstelPanel
        administratieId={ADMINISTRATIE_ID}
        documentId={DOCUMENT_ID}
        status="te_controleren"
        veldvoorstel={AI_VOORSTEL}
        onGeboekt={() => {}}
        onHersteld={() => {}}
      />,
    )

    await waitFor(() => expect(screen.getByRole('button', { name: 'Koppel aan „Confide B.V.”' })).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /Technische Unie/ })).not.toBeInTheDocument()

    await gebruiker.click(screen.getByRole('button', { name: 'Koppel aan „Confide B.V.”' }))

    expect(screen.getByLabelText('Crediteur', { exact: false })).toHaveValue('Confide B.V.')
    expect(screen.queryByText(/AI las:/)).not.toBeInTheDocument()
  })

  it('fix 2: "nieuwe crediteur aanmaken in RLZ" maakt aan met de AI-naam voorgevuld en selecteert het resultaat', async () => {
    const gebruiker = userEvent.setup()
    const aanroepen: unknown[] = []
    const nieuwId = 'eeeeeeee-0000-0000-0000-000000000042'
    installFetchMock({
      boekvoorstel: AI_BOEKVOORSTEL,
      vendors: [],
      crediteurAanmakenResponse: [{ id: nieuwId, naam: 'Confide BV' }, 201],
      crediteurAanmaakAanroepen: aanroepen,
    })
    render(
      <BoekvoorstelPanel
        administratieId={ADMINISTRATIE_ID}
        documentId={DOCUMENT_ID}
        status="te_controleren"
        veldvoorstel={AI_VOORSTEL}
        onGeboekt={() => {}}
        onHersteld={() => {}}
      />,
    )
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Nieuwe crediteur „Confide BV” aanmaken/ })).toBeInTheDocument(),
    )

    await gebruiker.click(screen.getByRole('button', { name: /Nieuwe crediteur „Confide BV” aanmaken/ }))

    await waitFor(() => expect(aanroepen).toEqual([{ naam: 'Confide BV' }]))
    await waitFor(() => expect(screen.getByLabelText('Crediteur', { exact: false })).toHaveValue('Confide BV'))
    expect(screen.queryByText(/AI las:/)).not.toBeInTheDocument()
  })

  it('fix 2: een 409 "bestaat al" selecteert de bestaande crediteur in plaats van een kale fout', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({
      boekvoorstel: AI_BOEKVOORSTEL,
      vendors: [{ id: VENDOR_ID, naam: 'Technische Unie' }], // geen fuzzy-match op "Confide BV"
      crediteurAanmakenResponse: [
        { detail: { message: 'Crediteur "Confide BV" bestaat al in deze administratie', vendor_id: VENDOR_ID } },
        409,
      ],
    })
    render(
      <BoekvoorstelPanel
        administratieId={ADMINISTRATIE_ID}
        documentId={DOCUMENT_ID}
        status="te_controleren"
        veldvoorstel={AI_VOORSTEL}
        onGeboekt={() => {}}
        onHersteld={() => {}}
      />,
    )
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Nieuwe crediteur „Confide BV” aanmaken/ })).toBeInTheDocument(),
    )

    await gebruiker.click(screen.getByRole('button', { name: /Nieuwe crediteur „Confide BV” aanmaken/ }))

    await waitFor(() => expect(screen.getByLabelText('Crediteur', { exact: false })).toHaveValue('Technische Unie'))
  })

  it('fix 2: directe cache-match (vendor_id in de dto) vult automatisch voor — geen voorstelblok', async () => {
    installFetchMock({
      boekvoorstel: { ...AI_BOEKVOORSTEL, vendor_id: VENDOR_ID },
      vendors: [{ id: VENDOR_ID, naam: 'Confide B.V.' }],
    })
    render(
      <BoekvoorstelPanel
        administratieId={ADMINISTRATIE_ID}
        documentId={DOCUMENT_ID}
        status="te_controleren"
        veldvoorstel={{ ...AI_VOORSTEL, vendor_suggestie: { vendor_id: VENDOR_ID, match: 'exact' } }}
        onGeboekt={() => {}}
        onHersteld={() => {}}
      />,
    )

    await waitFor(() => expect(screen.getByLabelText('Crediteur', { exact: false })).toHaveValue('Confide B.V.'))
    expect(screen.queryByText(/AI las:/)).not.toBeInTheDocument()
  })

  // ————— Fix 3 (2026-07-10): standaard één samengevoegde boekingsregel + vinkje "splitsen per regel" —————

  it('fix 3: toont standaard één samengevoegde regel met het vinkje, splitsen toont de losse regels', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({ boekvoorstel: AI_BOEKVOORSTEL })
    render(
      <BoekvoorstelPanel
        administratieId={ADMINISTRATIE_ID}
        documentId={DOCUMENT_ID}
        status="te_controleren"
        veldvoorstel={AI_VOORSTEL}
        onGeboekt={() => {}}
        onHersteld={() => {}}
      />,
    )

    await waitFor(() => expect(screen.getByLabelText('Splitsen per regel')).toBeInTheDocument())
    expect(screen.getByLabelText('Splitsen per regel')).not.toBeChecked()
    expect(screen.getAllByLabelText('Netto bedrag')).toHaveLength(1)
    expect(screen.getByLabelText('Netto bedrag')).toHaveValue('100.00')
    expect(screen.getByLabelText('Omschrijving')).toHaveValue('Factuur F-1 — samengevoegd (2 regels)')

    await gebruiker.click(screen.getByLabelText('Splitsen per regel'))

    expect(screen.getAllByLabelText('Netto bedrag')).toHaveLength(2)
    expect(screen.getAllByLabelText('Omschrijving')[0]).toHaveValue('Steigerhout')

    // Terugschakelen gooit niets weg: de samengevoegde regel staat er weer.
    await gebruiker.click(screen.getByLabelText('Splitsen per regel'))
    expect(screen.getAllByLabelText('Netto bedrag')).toHaveLength(1)
    expect(screen.getByLabelText('Netto bedrag')).toHaveValue('100.00')
  })

  it('fix 3: de splitskeuze reist mee met Controleren (PUT regels_samenvoegen) zodat de voorkeur per leverancier onthouden wordt', async () => {
    const gebruiker = userEvent.setup()
    const putBodies: unknown[] = []
    installFetchMock({
      boekvoorstel: AI_BOEKVOORSTEL,
      putBodies,
      putResponse: {
        boekvoorstel: AI_BOEKVOORSTEL,
        checks: { geblokkeerd: true, resultaten: [{ naam: 'Verplichte velden', ok: false, melding: 'Ontbrekend: crediteur' }] },
      },
    })
    render(
      <BoekvoorstelPanel
        administratieId={ADMINISTRATIE_ID}
        documentId={DOCUMENT_ID}
        status="te_controleren"
        veldvoorstel={AI_VOORSTEL}
        onGeboekt={() => {}}
        onHersteld={() => {}}
      />,
    )
    await waitFor(() => expect(screen.getByLabelText('Splitsen per regel')).toBeInTheDocument())

    await gebruiker.click(screen.getByRole('button', { name: 'Controleren' }))
    await waitFor(() => expect(putBodies).toHaveLength(1))
    expect((putBodies[0] as { regels_samenvoegen: boolean }).regels_samenvoegen).toBe(true)

    await gebruiker.click(screen.getByLabelText('Splitsen per regel'))
    await gebruiker.click(screen.getByRole('button', { name: 'Controleren' }))
    await waitFor(() => expect(putBodies).toHaveLength(2))
    const tweede = putBodies[1] as { regels_samenvoegen: boolean; regels: unknown[] }
    expect(tweede.regels_samenvoegen).toBe(false)
    expect(tweede.regels).toHaveLength(2)
  })

  it('fix 3: bij projectplicht (samenvoegen_toegestaan=false) geen vinkje en hard per-regel', async () => {
    installFetchMock({
      projectVerplicht: true,
      boekvoorstel: {
        ...AI_BOEKVOORSTEL,
        regels_samenvoegen: false,
        samenvoegen_toegestaan: false,
        samengevoegde_regel: null,
      },
    })
    render(
      <BoekvoorstelPanel
        administratieId={ADMINISTRATIE_ID}
        documentId={DOCUMENT_ID}
        status="te_controleren"
        veldvoorstel={AI_VOORSTEL}
        onGeboekt={() => {}}
        onHersteld={() => {}}
      />,
    )

    await waitFor(() => expect(screen.getAllByLabelText('Netto bedrag')).toHaveLength(2))
    expect(screen.queryByLabelText('Splitsen per regel')).not.toBeInTheDocument()
  })
})
