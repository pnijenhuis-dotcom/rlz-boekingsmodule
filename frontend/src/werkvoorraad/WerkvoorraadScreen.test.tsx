import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { WerkvoorraadScreen } from './WerkvoorraadScreen'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const GEBOEKT_DOCUMENT_ID = 'cccccccc-0000-0000-0000-000000000003'
const VERWIJDERD_DOCUMENT_ID = 'dddddddd-0000-0000-0000-000000000004'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function document(overrides: Record<string, unknown>) {
  return {
    id: DOCUMENT_ID,
    bestandsnaam: 'factuur.pdf',
    soort: 'inkoopfactuur',
    status: 'te_controleren',
    bron: 'upload',
    mogelijk_duplicaat_van: null,
    toegewezen_aan: null,
    aangemaakt_op: '2026-07-09T10:00:00Z',
    laatst_gewijzigd_op: '2026-07-09T10:00:00Z',
    automatisch_geboekt: false,
    ...overrides,
  }
}

interface MockOpties {
  documenten?: unknown[]
  verwijderdeDocumenten?: unknown[]
  verwijderenAanroepen?: { url: string; body: unknown }[]
  herstellenAanroepen?: string[]
  verwijderenStatus?: number
}

function installFetchMock(opties: MockOpties) {
  const documenten = opties.documenten ?? [document({})]
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/auth/administraties')) {
        return Promise.resolve(jsonResponse({ administraties: [{ id: ADMINISTRATIE_ID, naam: 'Testklant' }] }))
      }
      if (url.includes('/verwijderen') && init?.method === 'POST') {
        opties.verwijderenAanroepen?.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
        return Promise.resolve(
          jsonResponse({ document_id: DOCUMENT_ID, status: 'verwijderd' }, opties.verwijderenStatus ?? 200),
        )
      }
      if (url.includes('/herstellen') && init?.method === 'POST') {
        opties.herstellenAanroepen?.push(url)
        return Promise.resolve(jsonResponse({ document_id: VERWIJDERD_DOCUMENT_ID, status: 'te_controleren' }))
      }
      if (url.includes('/documenten') && (!init || init.method === undefined)) {
        const toontVerwijderd = url.includes('toon_verwijderd=true')
        return Promise.resolve(
          jsonResponse({ documenten: toontVerwijderd ? (opties.verwijderdeDocumenten ?? documenten) : documenten }),
        )
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

/** IA-verbouwing (designronde 15-08): de documentenlijst is het WERKEN-deelscherm achter
 * ?administratie=…&sectie=documenten — de kale klant-URL toont de STANDEN-klantpagina. */
function renderScherm() {
  return render(
    <MemoryRouter initialEntries={[`/?administratie=${ADMINISTRATIE_ID}&sectie=documenten`]}>
      <WerkvoorraadScreen />
    </MemoryRouter>,
  )
}

describe('WerkvoorraadScreen — verwijderen/herstellen (design-pass taak 4)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('toont het prullenbak-icoon en opent de bevestigingsdialoog met de bestandsnaam', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({ documenten: [document({})] })
    renderScherm()

    await waitFor(() => expect(screen.getByText('factuur.pdf')).toBeInTheDocument())
    await gebruiker.click(screen.getByRole('button', { name: 'Document verwijderen' }))

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText(/"factuur\.pdf" wordt niet definitief verwijderd/)).toBeInTheDocument()
  })

  it('bevestigen stuurt de optionele reden mee en herlaadt de lijst', async () => {
    const gebruiker = userEvent.setup()
    const verwijderenAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ documenten: [document({})], verwijderenAanroepen })
    renderScherm()

    await waitFor(() => expect(screen.getByText('factuur.pdf')).toBeInTheDocument())
    await gebruiker.click(screen.getByRole('button', { name: 'Document verwijderen' }))
    await gebruiker.type(screen.getByLabelText('Reden (optioneel)'), 'Dubbele upload')
    await gebruiker.click(screen.getByRole('button', { name: 'Verwijderen' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(verwijderenAanroepen).toHaveLength(1)
    expect(verwijderenAanroepen[0].url).toContain(`/documenten/${DOCUMENT_ID}/verwijderen`)
    expect(verwijderenAanroepen[0].body).toEqual({ reden: 'Dubbele upload' })
  })

  it('annuleren sluit de dialoog zonder een aanroep te doen', async () => {
    const gebruiker = userEvent.setup()
    const verwijderenAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ documenten: [document({})], verwijderenAanroepen })
    renderScherm()

    await waitFor(() => expect(screen.getByText('factuur.pdf')).toBeInTheDocument())
    await gebruiker.click(screen.getByRole('button', { name: 'Document verwijderen' }))
    await gebruiker.click(screen.getByRole('button', { name: 'Annuleren' }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(verwijderenAanroepen).toHaveLength(0)
  })

  it('een fout bij verwijderen blijft in de dialoog zichtbaar (bv. "geboekt" dat toch nog faalt)', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({ documenten: [document({})], verwijderenStatus: 409 })
    renderScherm()

    await waitFor(() => expect(screen.getByText('factuur.pdf')).toBeInTheDocument())
    await gebruiker.click(screen.getByRole('button', { name: 'Document verwijderen' }))
    await gebruiker.click(screen.getByRole('button', { name: 'Verwijderen' }))

    await waitFor(() => expect(within(screen.getByRole('dialog')).getByText(/Fout/)).toBeInTheDocument())
  })

  it('hard: het prullenbak-icoon wordt helemaal niet getoond voor een geboekt document (bewaarplicht)', async () => {
    installFetchMock({
      documenten: [document({ id: GEBOEKT_DOCUMENT_ID, bestandsnaam: 'geboekte-factuur.pdf', status: 'geboekt' })],
    })
    renderScherm()

    await waitFor(() => expect(screen.getByText('geboekte-factuur.pdf')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Document verwijderen' })).not.toBeInTheDocument()
  })

  it('hard: het prullenbak-icoon wordt ook niet getoond bij een lopende accordering', async () => {
    installFetchMock({
      documenten: [
        document({ id: GEBOEKT_DOCUMENT_ID, bestandsnaam: 'ter-accordering.pdf', status: 'ter_accordering' }),
      ],
    })
    renderScherm()

    await waitFor(() => expect(screen.getByText('ter-accordering.pdf')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Document verwijderen' })).not.toBeInTheDocument()
  })

  it('pollt de lijst vanzelf zolang een document in de extractie-wachtrij of bij de worker staat', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      installFetchMock({
        documenten: [document({ bestandsnaam: 'monsterfactuur.pdf', status: 'extractie_wachtrij' })],
      })
      renderScherm()

      await waitFor(() => expect(screen.getByText('monsterfactuur.pdf')).toBeInTheDocument())
      // De statustekst staat ook als optie in het statusfilter — minstens één zichtbare chip.
      expect(screen.getAllByText('In wachtrij (extractie)').length).toBeGreaterThan(0)

      const lijstAanroepen = () =>
        vi
          .mocked(fetch)
          .mock.calls.filter(([url]) => String(url).includes('/documenten') && !String(url).includes('/documenten/'))
          .length
      const voor = lijstAanroepen()
      await vi.advanceTimersByTimeAsync(3500)
      expect(lijstAanroepen()).toBeGreaterThan(voor)
    } finally {
      vi.useRealTimers()
    }
  })

  it('pollt niet als er geen lopende extracties zijn', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      installFetchMock({ documenten: [document({})] })
      renderScherm()

      await waitFor(() => expect(screen.getByText('factuur.pdf')).toBeInTheDocument())
      const lijstAanroepen = () =>
        vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes('/documenten')).length
      const voor = lijstAanroepen()
      await vi.advanceTimersByTimeAsync(7000)
      expect(lijstAanroepen()).toBe(voor)
    } finally {
      vi.useRealTimers()
    }
  })

  it('"toon verwijderde documenten" haalt de lijst met toon_verwijderd=true op en toont een herstelknop', async () => {
    const gebruiker = userEvent.setup()
    const herstellenAanroepen: string[] = []
    installFetchMock({
      documenten: [document({})],
      verwijderdeDocumenten: [
        document({ id: VERWIJDERD_DOCUMENT_ID, bestandsnaam: 'verwijderde-factuur.pdf', status: 'verwijderd' }),
      ],
      herstellenAanroepen,
    })
    renderScherm()

    await waitFor(() => expect(screen.getByText('factuur.pdf')).toBeInTheDocument())
    expect(screen.queryByText('verwijderde-factuur.pdf')).not.toBeInTheDocument()

    await gebruiker.click(screen.getByLabelText('Toon verwijderde documenten'))
    await waitFor(() => expect(screen.getByText('verwijderde-factuur.pdf')).toBeInTheDocument())

    await gebruiker.click(screen.getByRole('button', { name: /Herstellen/ }))
    await waitFor(() => expect(herstellenAanroepen).toHaveLength(1))
    expect(herstellenAanroepen[0]).toContain(`/documenten/${VERWIJDERD_DOCUMENT_ID}/herstellen`)
  })
})

describe('WerkvoorraadScreen — vragenworkflow (PART B)', () => {
  const EIGENAAR_ID = 'eeeeeeee-0000-0000-0000-000000000009'

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function installVraagFetchMock(documenten: unknown[]) {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith('/auth/administraties')) {
          return Promise.resolve(jsonResponse({ administraties: [{ id: ADMINISTRATIE_ID, naam: 'Testklant' }] }))
        }
        if (url.endsWith('/medewerkers')) {
          return Promise.resolve(jsonResponse({ medewerkers: [{ id: EIGENAAR_ID, naam: 'M. de Boer' }] }))
        }
        if (url.includes('/vragen')) {
          return Promise.resolve(jsonResponse({ vragen: [] }))
        }
        if (url.includes('/documenten') && (!init || init.method === undefined)) {
          return Promise.resolve(jsonResponse({ documenten }))
        }
        return Promise.resolve(new Response(null, { status: 404 }))
      }),
    )
  }

  it('toont de vraag-open-chip, de toegewezen-naam en het vraag-segment met teller', async () => {
    installVraagFetchMock([document({ status: 'vraag_open', toegewezen_aan: EIGENAAR_ID })])
    renderScherm()

    // De statustekst staat als chip in de rij én als segment-filter met teller.
    await waitFor(() => expect(screen.getAllByText('Vraag open').length).toBeGreaterThan(0))
    expect(screen.getByText('M. de Boer')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Vraag open (1)' })).toBeInTheDocument()
  })

  it('klik op een vraag-regel opent de vraag (vragen-deelscherm gefilterd op het document)', async () => {
    const gebruiker = userEvent.setup()
    installVraagFetchMock([document({ status: 'vraag_open', toegewezen_aan: EIGENAAR_ID })])
    render(
      <MemoryRouter initialEntries={[`/?administratie=${ADMINISTRATIE_ID}&sectie=documenten`]}>
        <Routes>
          <Route path="/" element={<WerkvoorraadScreen />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(screen.getByText('factuur.pdf')).toBeInTheDocument())
    await gebruiker.click(screen.getByText('factuur.pdf'))
    // Het vragen-deelscherm (sectie=vragen) rendert binnen dezelfde route.
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Openstaande vragen' })).toBeInTheDocument())
  })

  it('zonder open vragen geen teller-chip', async () => {
    installVraagFetchMock([document({})])
    renderScherm()

    await waitFor(() => expect(screen.getByText('factuur.pdf')).toBeInTheDocument())
    expect(screen.queryByText(/vraag open/)).not.toBeInTheDocument()
  })
})

describe('WerkvoorraadScreen — klantenlijst met tellers (mockup-flow, browserreview 2026-08-07)', () => {
  const TWEEDE_ADMINISTRATIE_ID = 'ffffffff-0000-0000-0000-000000000005'

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function klant(overrides: Record<string, unknown>) {
    return {
      administratie_id: ADMINISTRATIE_ID,
      naam: 'Testklant',
      te_controleren: 0,
      klaar_om_te_boeken: 0,
      vragen: 0,
      afgewezen: 0,
      bij_klant: 0,
      iban_wachtend: 0,
      ...overrides,
    }
  }

  function installOverzichtMock(klanten: unknown[], bankKlanten: unknown[] = []) {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/auth/administraties')) {
          return Promise.resolve(
            jsonResponse({
              administraties: [
                { id: ADMINISTRATIE_ID, naam: 'Testklant' },
                { id: TWEEDE_ADMINISTRATIE_ID, naam: 'Klant Zonder Werk' },
              ],
            }),
          )
        }
        if (url.endsWith('/werkvoorraad/overzicht')) {
          return Promise.resolve(jsonResponse({ klanten }))
        }
        if (url.endsWith('/bank/overzicht')) {
          return Promise.resolve(jsonResponse({ klanten: bankKlanten }))
        }
        if (url.endsWith('/verzamelbak')) {
          return Promise.resolve(jsonResponse({ items: [] }))
        }
        if (url.includes('/vragen')) {
          return Promise.resolve(jsonResponse({ vragen: [] }))
        }
        if (url.includes('/documenten')) {
          return Promise.resolve(jsonResponse({ documenten: [] }))
        }
        return Promise.resolve(new Response(null, { status: 404 }))
      }),
    )
  }

  function renderIngang() {
    return render(
      <MemoryRouter initialEntries={['/']}>
        <WerkvoorraadScreen />
      </MemoryRouter>,
    )
  }

  it('toont alleen klanten mét openstaand werk en meldt het aantal verborgen', async () => {
    installOverzichtMock([
      klant({ te_controleren: 2, klaar_om_te_boeken: 1 }),
      klant({ administratie_id: TWEEDE_ADMINISTRATIE_ID, naam: 'Klant Zonder Werk' }),
    ])
    renderIngang()

    await waitFor(() => expect(screen.getByText('Testklant')).toBeInTheDocument())
    expect(screen.queryByText('Klant Zonder Werk')).not.toBeInTheDocument()
    expect(screen.getByText(/1 klant zonder openstaande zaken \(verborgen\)/)).toBeInTheDocument()
  })

  it('klik op een klant landt DIRECT op de documentenlijst met soort-tabs (besluit 25-08, punt C — herziet 15-08)', async () => {
    const gebruiker = userEvent.setup()
    installOverzichtMock([klant({ te_controleren: 1 })])
    renderIngang()

    await waitFor(() => expect(screen.getByText('Testklant')).toBeInTheDocument())
    await gebruiker.click(screen.getByText('Testklant'))
    // Geen standen-tussenlaag meer: meteen de tabs + de documententabel.
    await waitFor(() => expect(screen.getByRole('tablist', { name: 'Documentsoort' })).toBeInTheDocument())
    expect(screen.queryByText('Te verwerken documenten')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Werkvoorraad' })).toBeInTheDocument()
    // Standen blijven bereikbaar via de chip-rij.
    expect(screen.getByRole('link', { name: /Standen & overzicht/ })).toHaveAttribute(
      'href',
      `/?administratie=${ADMINISTRATIE_ID}&sectie=standen`,
    )
  })

  it('bank-teller komt uit het bank-overzicht en een bankfout blokkeert de lijst niet', async () => {
    installOverzichtMock(
      [klant({ te_controleren: 1 })],
      [{ administratie_id: ADMINISTRATIE_ID, naam: 'Testklant', open_mutaties: 3 }],
    )
    renderIngang()

    await waitFor(() => expect(screen.getByText('Testklant')).toBeInTheDocument())
    // Bank-teller staat in de lijst én telt mee in de KPI-kaart — minstens één zichtbaar.
    expect(screen.getAllByText('3').length).toBeGreaterThan(0)
  })

  it('de KPI-kaarten zijn klikbaar en openen de kantoorbrede dwarsdoorsnede', async () => {
    const gebruiker = userEvent.setup()
    installOverzichtMock([klant({ te_controleren: 2, vragen: 1 })])
    renderIngang()

    await waitFor(() => expect(screen.getByText('Testklant')).toBeInTheDocument())
    await gebruiker.click(screen.getByRole('button', { name: /Open vragen/ }))
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Open vragen — alle klanten' })).toBeInTheDocument(),
    )
  })

  it('lege staat: alles bij — geen tabelinhoud, wél een duidelijke melding', async () => {
    installOverzichtMock([klant({}), klant({ administratie_id: TWEEDE_ADMINISTRATIE_ID, naam: 'Klant Zonder Werk' })])
    renderIngang()

    await waitFor(() => expect(screen.getByText(/Geen openstaand werk/)).toBeInTheDocument())
  })
})

describe('Klantpagina — kolommen, zoekveld en statusfilter (mockup #klantpagina)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('toont leverancier, factuurdatum en bedrag uit de extractie', async () => {
    installFetchMock({
      documenten: [
        document({
          leverancier: 'Bouwmaat Nederland B.V.',
          totaalbedrag: '1847.23',
          factuurdatum: '2026-06-29',
        }),
      ],
    })
    renderScherm()

    await waitFor(() => expect(screen.getByText('Bouwmaat Nederland B.V.')).toBeInTheDocument())
    expect(screen.getByText(/1\.847,23/)).toBeInTheDocument()
    expect(screen.getByText('29 jun 2026')).toBeInTheDocument()
  })

  it('zoekveld filtert op leverancier; statusfilter op status', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({
      documenten: [
        document({ id: DOCUMENT_ID, bestandsnaam: 'a.pdf', leverancier: 'Eneco Zakelijk' }),
        document({
          id: GEBOEKT_DOCUMENT_ID,
          bestandsnaam: 'b.pdf',
          leverancier: 'Technische Unie',
          status: 'klaar_om_te_boeken',
        }),
      ],
    })
    renderScherm()

    await waitFor(() => expect(screen.getByText('a.pdf')).toBeInTheDocument())
    expect(screen.getByText('b.pdf')).toBeInTheDocument()

    await gebruiker.type(screen.getByLabelText('Zoek in documenten'), 'eneco')
    expect(screen.getByText('a.pdf')).toBeInTheDocument()
    expect(screen.queryByText('b.pdf')).not.toBeInTheDocument()

    await gebruiker.clear(screen.getByLabelText('Zoek in documenten'))
    // Statusfilter = segment-knoppen (mockup #scherm-docs, IA-verbouwing 15-08).
    await gebruiker.click(screen.getByRole('button', { name: 'Klaar om te boeken (1)' }))
    expect(screen.queryByText('a.pdf')).not.toBeInTheDocument()
    expect(screen.getByText('b.pdf')).toBeInTheDocument()
  })

  it('lege zoekresultaten geven een duidelijke melding, geen lege tabel', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({ documenten: [document({})] })
    renderScherm()

    await waitFor(() => expect(screen.getByText('factuur.pdf')).toBeInTheDocument())
    await gebruiker.type(screen.getByLabelText('Zoek in documenten'), 'bestaat-niet-xyz')
    expect(screen.getByText(/Geen documenten die aan de zoekterm/)).toBeInTheDocument()
  })
})

describe('Klantpagina — chip en filter "automatisch geboekt" (autoboeken-opt-in per leverancier)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('een automatisch geboekt document toont de chip "automatisch" naast de statuschip', async () => {
    installFetchMock({
      documenten: [
        document({
          id: GEBOEKT_DOCUMENT_ID,
          bestandsnaam: 'auto-factuur.pdf',
          status: 'geboekt',
          automatisch_geboekt: true,
        }),
      ],
    })
    renderScherm()

    await waitFor(() => expect(screen.getByText('auto-factuur.pdf')).toBeInTheDocument())
    const chip = screen.getByText('automatisch')
    expect(chip).toHaveClass('chip')
    // Naast de statuschip: de geboekt-status blijft gewoon zichtbaar.
    expect(screen.getAllByText('Geboekt').length).toBeGreaterThan(0)
  })

  it('het statusfilter krijgt de optie "Automatisch geboekt" en filtert op de eigenschap', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({
      documenten: [
        document({ id: DOCUMENT_ID, bestandsnaam: 'handmatig.pdf', status: 'geboekt' }),
        document({
          id: GEBOEKT_DOCUMENT_ID,
          bestandsnaam: 'auto-factuur.pdf',
          status: 'geboekt',
          automatisch_geboekt: true,
        }),
      ],
    })
    renderScherm()

    await waitFor(() => expect(screen.getByText('handmatig.pdf')).toBeInTheDocument())
    await gebruiker.click(screen.getByRole('button', { name: 'Automatisch geboekt' }))

    expect(screen.queryByText('handmatig.pdf')).not.toBeInTheDocument()
    expect(screen.getByText('auto-factuur.pdf')).toBeInTheDocument()
  })

  it('zonder automatisch geboekte documenten geen chip en geen filteroptie (aanwezigeStatussen-patroon)', async () => {
    installFetchMock({ documenten: [document({ status: 'geboekt' })] })
    renderScherm()

    await waitFor(() => expect(screen.getByText('factuur.pdf')).toBeInTheDocument())
    expect(screen.queryByText('automatisch')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Automatisch geboekt' })).not.toBeInTheDocument()
  })
})

describe('Klantlanding — tabs per soort + chip-rij (besluit Peter 25-08, punt C)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function renderLanding(pad = `/?administratie=${ADMINISTRATIE_ID}`) {
    return render(
      <MemoryRouter initialEntries={[pad]}>
        <WerkvoorraadScreen />
      </MemoryRouter>,
    )
  }

  it('toont alleen tabs voor soorten met teller > 0, kiest de eerste tab en houdt "Alle documenten" bereikbaar', async () => {
    installFetchMock({
      documenten: [
        document({ id: 'd-1', soort: 'inkoopfactuur', status: 'te_controleren', bestandsnaam: 'inkoop.pdf' }),
        document({ id: 'd-2', soort: 'verkoopfactuur', status: 'klaar_om_te_boeken', bestandsnaam: 'verkoop.xml' }),
        document({ id: 'd-3', soort: 'kassarapport', status: 'geboekt', bestandsnaam: 'kas.pdf' }),
      ],
    })
    renderLanding()

    await screen.findByRole('tab', { name: 'Inkoopfacturen (1)' })
    const tablist = screen.getByRole('tablist', { name: 'Documentsoort' })
    const tabs = within(tablist).getAllByRole('tab')
    expect(tabs.map((t) => t.textContent)).toEqual(['Inkoopfacturen (1)', 'Verkoopfacturen (1)', 'Alle documenten'])
    // Geboekt kassarapport = geen open teller → geen tab (toon-regel).
    expect(within(tablist).queryByText(/Omzetrapporten/)).not.toBeInTheDocument()
    // Eerste tab actief zonder soort-param: alleen de inkoopfactuur in de tabel.
    expect(within(tablist).getByRole('tab', { name: 'Inkoopfacturen (1)' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText('inkoop.pdf')).toBeInTheDocument()
    expect(screen.queryByText('verkoop.xml')).not.toBeInTheDocument()
  })

  it('tab-klik wisselt de soort; "Alle documenten" toont ook geboekte documenten (herstel-pad)', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({
      documenten: [
        document({ id: 'd-1', soort: 'inkoopfactuur', status: 'te_controleren', bestandsnaam: 'inkoop.pdf' }),
        document({ id: 'd-2', soort: 'verkoopfactuur', status: 'klaar_om_te_boeken', bestandsnaam: 'verkoop.xml' }),
        document({ id: 'd-3', soort: 'kassarapport', status: 'geboekt', bestandsnaam: 'kas.pdf' }),
      ],
    })
    renderLanding()

    await gebruiker.click(await screen.findByRole('tab', { name: 'Verkoopfacturen (1)' }))
    await waitFor(() => expect(screen.getByText('verkoop.xml')).toBeInTheDocument())
    expect(screen.queryByText('inkoop.pdf')).not.toBeInTheDocument()

    await gebruiker.click(screen.getByRole('tab', { name: 'Alle documenten' }))
    await waitFor(() => expect(screen.getByText('kas.pdf')).toBeInTheDocument())
    expect(screen.getByText('inkoop.pdf')).toBeInTheDocument()
    expect(screen.getByText('verkoop.xml')).toBeInTheDocument()
  })

  it('chip-rij toont alleen standen met teller > 0 en ?status= kiest het segment-filter voor', async () => {
    installFetchMock({
      documenten: [
        document({ id: 'd-1', status: 'te_controleren', bestandsnaam: 'open.pdf' }),
        document({ id: 'd-2', status: 'ter_accordering', bestandsnaam: 'bij-klant.pdf' }),
      ],
    })
    renderLanding(`/?administratie=${ADMINISTRATIE_ID}&status=ter_accordering`)

    await screen.findByRole('tab', { name: 'Inkoopfacturen (2)' })
    const chips = screen.getByRole('navigation', { name: 'Overige standen' })
    expect(within(chips).getByRole('button', { name: /1 bij klant ter accordering/ })).toBeInTheDocument()
    expect(within(chips).queryByRole('button', { name: /afgewezen/ })).not.toBeInTheDocument()
    // Voorgekozen statusfilter: alleen het bij-klant-document zichtbaar.
    await waitFor(() => expect(screen.getByText('bij-klant.pdf')).toBeInTheDocument())
    expect(screen.queryByText('open.pdf')).not.toBeInTheDocument()
  })

  it('oude URL sectie=documenten blijft werken en sectie=standen toont het standen-overzicht', async () => {
    installFetchMock({})
    renderLanding(`/?administratie=${ADMINISTRATIE_ID}&sectie=documenten`)
    expect(await screen.findByRole('tablist', { name: 'Documentsoort' })).toBeInTheDocument()
    vi.unstubAllGlobals()
    installFetchMock({})
    renderLanding(`/?administratie=${ADMINISTRATIE_ID}&sectie=standen`)
    expect(await screen.findByText('Te verwerken documenten')).toBeInTheDocument()
  })
})
