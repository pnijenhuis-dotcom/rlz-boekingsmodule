import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
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

describe('WerkvoorraadScreen — verwijderen/herstellen via het ⋯-rijmenu (design-pass taak 4, herzien 27/28-08 punt 4)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  /** Punt 4: verwijderen zit achter het ⋯-rijmenu (archief-patroon), nooit meer een kale knop. */
  async function openRijmenu(gebruiker: ReturnType<typeof userEvent.setup>, naam: RegExp | string) {
    await gebruiker.click(screen.getByRole('button', { name: naam }))
    return screen.getByRole('menu')
  }

  it('geen kale prullenbak-knop meer; het ⋯-menu opent de bevestigingsdialoog met de bestandsnaam', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({ documenten: [document({})] })
    renderScherm()

    await waitFor(() => expect(screen.getByText('factuur.pdf')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Document verwijderen' })).not.toBeInTheDocument()
    const menu = await openRijmenu(gebruiker, /Acties voor factuur\.pdf/)
    await gebruiker.click(within(menu).getByRole('menuitem', { name: /Verwijderen/ }))

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText(/"factuur\.pdf" verdwijnt uit de werkvoorraad/)).toBeInTheDocument()
    expect(screen.getByText(/wordt niet definitief verwijderd/)).toBeInTheDocument()
  })

  it('de reden is VERPLICHT: zonder reden blijft "Verwijderen" uit; mét reden gaat hij mee en herlaadt de lijst', async () => {
    const gebruiker = userEvent.setup()
    const verwijderenAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ documenten: [document({})], verwijderenAanroepen })
    renderScherm()

    await waitFor(() => expect(screen.getByText('factuur.pdf')).toBeInTheDocument())
    const menu = await openRijmenu(gebruiker, /Acties voor factuur\.pdf/)
    await gebruiker.click(within(menu).getByRole('menuitem', { name: /Verwijderen/ }))
    expect(screen.getByRole('button', { name: 'Verwijderen' })).toBeDisabled()
    await gebruiker.type(screen.getByLabelText('Reden (verplicht)'), 'Dubbele upload')
    expect(screen.getByRole('button', { name: 'Verwijderen' })).toBeEnabled()
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
    const menu = await openRijmenu(gebruiker, /Acties voor factuur\.pdf/)
    await gebruiker.click(within(menu).getByRole('menuitem', { name: /Verwijderen/ }))
    await gebruiker.click(screen.getByRole('button', { name: 'Annuleren' }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(verwijderenAanroepen).toHaveLength(0)
  })

  it('een fout bij verwijderen blijft in de dialoog zichtbaar (bv. "geboekt" dat toch nog faalt)', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({ documenten: [document({})], verwijderenStatus: 409 })
    renderScherm()

    await waitFor(() => expect(screen.getByText('factuur.pdf')).toBeInTheDocument())
    const menu = await openRijmenu(gebruiker, /Acties voor factuur\.pdf/)
    await gebruiker.click(within(menu).getByRole('menuitem', { name: /Verwijderen/ }))
    await gebruiker.type(screen.getByLabelText('Reden (verplicht)'), 'test')
    await gebruiker.click(screen.getByRole('button', { name: 'Verwijderen' }))

    await waitFor(() => expect(within(screen.getByRole('dialog')).getByText(/Fout/)).toBeInTheDocument())
  })

  it('hard: bij een geboekt document is "Verwijderen…" uitgeschakeld mét de bewaarplicht-uitleg', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({
      documenten: [document({ id: GEBOEKT_DOCUMENT_ID, bestandsnaam: 'geboekte-factuur.pdf', status: 'geboekt' })],
    })
    renderScherm()

    await waitFor(() => expect(screen.getByText('geboekte-factuur.pdf')).toBeInTheDocument())
    const menu = await openRijmenu(gebruiker, /Acties voor geboekte-factuur\.pdf/)
    expect(within(menu).getByRole('menuitem', { name: /Verwijderen/ })).toBeDisabled()
    expect(within(menu).getByText(/bewaarplicht/)).toBeInTheDocument()
    await gebruiker.click(within(menu).getByRole('menuitem', { name: /Verwijderen/ }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('hard: bij een lopende accordering is "Verwijderen…" uitgeschakeld mét "eerst intrekken"', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({
      documenten: [
        document({ id: GEBOEKT_DOCUMENT_ID, bestandsnaam: 'ter-accordering.pdf', status: 'ter_accordering' }),
      ],
    })
    renderScherm()

    await waitFor(() => expect(screen.getByText('ter-accordering.pdf')).toBeInTheDocument())
    const menu = await openRijmenu(gebruiker, /Acties voor ter-accordering\.pdf/)
    expect(within(menu).getByRole('menuitem', { name: /Verwijderen/ })).toBeDisabled()
    expect(within(menu).getByText(/trek de accordering eerst in/)).toBeInTheDocument()
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

    // Herstellen zit sinds 27/28-08 óók in het ⋯-rijmenu.
    await gebruiker.click(screen.getByRole('button', { name: /Acties voor verwijderde-factuur\.pdf/ }))
    await gebruiker.click(within(screen.getByRole('menu')).getByRole('menuitem', { name: /Herstellen/ }))
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

    // Punt 3a (27/28-08): leverancier is de vette hoofdregel, de bestandsnaam staat in de metaregel.
    // Blok D (01-09): binnenkomst zonder status = default "Te controleren" — b.pdf (klaar om te
    // boeken) verschijnt pas ná een expliciete filterkeuze.
    await waitFor(() => expect(screen.getByText('Eneco Zakelijk')).toBeInTheDocument())
    expect(screen.getByText(/a\.pdf/)).toBeInTheDocument()
    expect(screen.queryByText(/b\.pdf/)).not.toBeInTheDocument()
    await gebruiker.click(screen.getByRole('button', { name: 'Alle (2)' }))
    expect(screen.getByText(/b\.pdf/)).toBeInTheDocument()

    await gebruiker.type(screen.getByLabelText('Zoek in documenten'), 'eneco')
    expect(screen.getByText(/a\.pdf/)).toBeInTheDocument()
    expect(screen.queryByText(/b\.pdf/)).not.toBeInTheDocument()

    await gebruiker.clear(screen.getByLabelText('Zoek in documenten'))
    // Zoeken blijft óók op de bestandsnaam werken (metaregel).
    await gebruiker.type(screen.getByLabelText('Zoek in documenten'), 'b.pdf')
    expect(screen.queryByText(/a\.pdf/)).not.toBeInTheDocument()
    expect(screen.getByText(/b\.pdf/)).toBeInTheDocument()

    await gebruiker.clear(screen.getByLabelText('Zoek in documenten'))
    // Statusfilter = segment-knoppen (mockup #scherm-docs, IA-verbouwing 15-08).
    await gebruiker.click(screen.getByRole('button', { name: 'Klaar om te boeken (1)' }))
    expect(screen.queryByText(/a\.pdf/)).not.toBeInTheDocument()
    expect(screen.getByText(/b\.pdf/)).toBeInTheDocument()
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

describe('Blok D (01-09) — documentenlijst opent standaard op "Te controleren"', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  const werkEnGeboekt = [
    document({ id: DOCUMENT_ID, bestandsnaam: 'werk.pdf', status: 'te_controleren' }),
    document({ id: GEBOEKT_DOCUMENT_ID, bestandsnaam: 'geboekt.pdf', status: 'geboekt' }),
  ]

  it('binnenkomst zonder status: default "Te controleren" — alleen het werk, segment actief', async () => {
    installFetchMock({ documenten: werkEnGeboekt })
    renderScherm()

    await waitFor(() => expect(screen.getByText(/werk\.pdf/)).toBeInTheDocument())
    expect(screen.queryByText(/geboekt\.pdf/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Te controleren (1)' })).toHaveClass('actief')
  })

  it('randvoorwaarde 1: een expliciete status in de URL wint altijd van de default', async () => {
    installFetchMock({ documenten: werkEnGeboekt })
    render(
      <MemoryRouter initialEntries={[`/?administratie=${ADMINISTRATIE_ID}&status=geboekt`]}>
        <WerkvoorraadScreen />
      </MemoryRouter>,
    )

    await waitFor(() => expect(screen.getByText(/geboekt\.pdf/)).toBeInTheDocument())
    expect(screen.queryByText(/werk\.pdf/)).not.toBeInTheDocument()
  })

  it('randvoorwaarde 2: niets te controleren → default valt terug op "Alle" — nooit een leeg eerste beeld', async () => {
    installFetchMock({
      documenten: [
        document({ id: DOCUMENT_ID, bestandsnaam: 'klaar.pdf', status: 'klaar_om_te_boeken' }),
        document({ id: GEBOEKT_DOCUMENT_ID, bestandsnaam: 'geboekt.pdf', status: 'geboekt' }),
      ],
    })
    renderScherm()

    await waitFor(() => expect(screen.getByText(/klaar\.pdf/)).toBeInTheDocument())
    expect(screen.getByText(/geboekt\.pdf/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Alle (2)' })).toHaveClass('actief')
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

describe('Duplicaatsignaal in de lijst (besluit Peter 25-08, deel 2 punt 6)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('toont de chip "Mogelijk duplicaat in RLZ" onder de status en biedt het filter aan', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({
      documenten: [
        document({
          id: DOCUMENT_ID,
          bestandsnaam: 'dubbel.pdf',
          duplicaatsignaal: { uitkomst: 'mogelijk_duplicaat', aantal_treffers: 1, berekend_op: '2026-08-25T09:00:00Z' },
        }),
        document({ id: GEBOEKT_DOCUMENT_ID, bestandsnaam: 'schoon.pdf', duplicaatsignaal: { uitkomst: 'geen', aantal_treffers: 0, berekend_op: '2026-08-25T09:00:00Z' } }),
      ],
    })
    renderScherm()
    expect(await screen.findByText('Mogelijk duplicaat in RLZ')).toBeInTheDocument()
    expect(screen.getByText('schoon.pdf')).toBeInTheDocument()

    await gebruiker.click(screen.getByRole('button', { name: 'Mogelijk duplicaat (1)' }))
    expect(screen.getByText('dubbel.pdf')).toBeInTheDocument()
    expect(screen.queryByText('schoon.pdf')).not.toBeInTheDocument()
  })

  it('zonder duplicaatsignalen geen chip en geen filteroptie', async () => {
    installFetchMock({ documenten: [document({ duplicaatsignaal: { uitkomst: 'geen', aantal_treffers: 0, berekend_op: '2026-08-25T09:00:00Z' } })] })
    renderScherm()
    await screen.findByText('factuur.pdf')
    expect(screen.queryByText('Mogelijk duplicaat in RLZ')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Mogelijk duplicaat \(/ })).not.toBeInTheDocument()
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

  it('toont in de kolom Toegewezen de chip "boeken ná akkoord mislukt" (bugfix-run 28-08) mét reden als tooltip', async () => {
    installFetchMock({
      documenten: [
        document({
          id: 'd-2',
          status: 'ter_accordering',
          bestandsnaam: 'van-happen.pdf',
          accordering_boek_fout: 'Boeken staat uit voor deze administratie of via de globale kill switch',
        }),
      ],
    })
    renderLanding(`/?administratie=${ADMINISTRATIE_ID}&status=ter_accordering`)
    const chip = await screen.findByText('⚠ boeken ná akkoord mislukt')
    expect(chip).toHaveAttribute('title', 'Boeken staat uit voor deze administratie of via de globale kill switch')
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

// ————— Werkstroom- + UI-run 27/28-08 —————


// Node 22+/jsdom: geen bruikbare window.localStorage — in-memory vervanger (patroon
// ui/ReviewSplitter.test.tsx) zodat de voorkeur-/melding-opslag echt getoetst wordt.
function installeerLocalStorage() {
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
}

describe('Werkstroom-run 27/28-08 — kolom-tellers, bulk aanbieden, vervallen-melding, dichtheid', () => {
  const K2_ID = 'eeeeeeee-0000-0000-0000-000000000006'

  beforeAll(() => installeerLocalStorage())
  afterEach(() => {
    vi.unstubAllGlobals()
    window.localStorage.clear()
  })

  interface RunMock {
    documenten?: unknown[]
    klanten?: unknown[]
    accorderingAan?: boolean
    meldingen?: unknown[]
    bulkAanroepen?: { url: string; body: unknown }[]
    bulkResponse?: unknown
  }

  function installRunMock(opties: RunMock) {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith('/auth/administraties')) {
          return Promise.resolve(jsonResponse({ administraties: [{ id: ADMINISTRATIE_ID, naam: 'Testklant' }] }))
        }
        if (url.endsWith('/werkvoorraad/overzicht')) return Promise.resolve(jsonResponse({ klanten: opties.klanten ?? [] }))
        if (url.endsWith('/bank/overzicht')) return Promise.resolve(jsonResponse({ klanten: [] }))
        if (url.endsWith('/verzamelbak')) return Promise.resolve(jsonResponse({ items: [] }))
        if (url.endsWith('/accordering/instellingen')) {
          return Promise.resolve(jsonResponse({ ingeschakeld: opties.accorderingAan ?? false, lagen: [] }))
        }
        if (url.endsWith('/accordering/vervallen-meldingen')) return Promise.resolve(jsonResponse(opties.meldingen ?? []))
        if (url.endsWith('/accordering/documenten/bulk-aanbieden') && init?.method === 'POST') {
          opties.bulkAanroepen?.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
          return Promise.resolve(jsonResponse(opties.bulkResponse ?? { resultaten: [], aangeboden: 0, geboekt: 0, overgeslagen: 0 }))
        }
        if (url.includes('/vragen')) return Promise.resolve(jsonResponse({ vragen: [] }))
        if (url.includes('/documenten') && (!init || init.method === undefined)) {
          return Promise.resolve(jsonResponse({ documenten: opties.documenten ?? [] }))
        }
        return Promise.resolve(new Response(null, { status: 404 }))
      }),
    )
  }

  function renderOp(pad: string) {
    return render(
      <MemoryRouter initialEntries={[pad]}>
        <WerkvoorraadScreen />
      </MemoryRouter>,
    )
  }

  const klaarDocs = [
    document({ id: DOCUMENT_ID, bestandsnaam: 'a.pdf', leverancier: 'Eneco Zakelijk', status: 'klaar_om_te_boeken' }),
    document({ id: K2_ID, bestandsnaam: 'b.pdf', leverancier: 'Technische Unie', status: 'klaar_om_te_boeken' }),
    document({ id: GEBOEKT_DOCUMENT_ID, bestandsnaam: 'c.pdf', leverancier: 'Bouwmaat', status: 'te_controleren' }),
  ]

  it('punt 1a: de kolom-teller "Klaar om te boeken" (12) opent de documentenlijst VOORGEFILTERD op die status', async () => {
    const gebruiker = userEvent.setup()
    installRunMock({
      klanten: [
        {
          administratie_id: ADMINISTRATIE_ID,
          naam: 'Testklant',
          te_controleren: 1,
          klaar_om_te_boeken: 12,
          vragen: 0,
          afgewezen: 0,
          bij_klant: 0,
          iban_wachtend: 0,
        },
      ],
      documenten: klaarDocs,
    })
    renderOp('/')
    await gebruiker.click(await screen.findByText('12'))
    // Lijst mét filter actief: segment "Klaar om te boeken (2)" is actief, het te-controleren-document staat er niet.
    const segment = await screen.findByRole('button', { name: 'Klaar om te boeken (2)' })
    expect(segment).toHaveClass('actief')
    expect(screen.getByText('Eneco Zakelijk')).toBeInTheDocument()
    expect(screen.queryByText('Bouwmaat')).not.toBeInTheDocument()
    // Rij-link draagt de lijstcontext (punt 1) mee naar het controlescherm.
    expect(screen.getByText('Eneco Zakelijk').closest('tr')).toBeInTheDocument()
  })

  it('punt 2b: bulk "Ter accordering aanbieden" op de tab Klaar om te boeken — selectie, POST, overgeslagen mét reden', async () => {
    const gebruiker = userEvent.setup()
    const bulkAanroepen: { url: string; body: unknown }[] = []
    installRunMock({
      documenten: klaarDocs,
      accorderingAan: true,
      bulkAanroepen,
      bulkResponse: {
        resultaten: [
          { document_id: DOCUMENT_ID, bestandsnaam: 'a.pdf', uitkomst: 'aangeboden', reden: null, boek_fout: null },
          { document_id: K2_ID, bestandsnaam: 'b.pdf', uitkomst: 'overgeslagen', reden: 'Harde checks niet groen: Verplichte velden ontbreken', boek_fout: null },
        ],
        aangeboden: 1,
        geboekt: 0,
        overgeslagen: 1,
      },
    })
    renderOp(`/?administratie=${ADMINISTRATIE_ID}&status=klaar_om_te_boeken`)

    const balk = await screen.findByTestId('bulk-balk')
    expect(balk).toHaveTextContent('2 klaar om te boeken')
    await gebruiker.click(within(balk).getByLabelText('Alle documenten in deze lijst selecteren'))
    expect(balk).toHaveTextContent('2 van 2 geselecteerd')
    await gebruiker.click(screen.getByRole('button', { name: /Ter accordering aanbieden \(2\)/ }))

    await waitFor(() => expect(bulkAanroepen).toHaveLength(1))
    expect(bulkAanroepen[0].url).toContain(`/administraties/${ADMINISTRATIE_ID}/accordering/documenten/bulk-aanbieden`)
    expect(new Set((bulkAanroepen[0].body as { document_ids: string[] }).document_ids)).toEqual(new Set([DOCUMENT_ID, K2_ID]))
    expect(await screen.findByText(/1 aangeboden, 1 overgeslagen/)).toBeInTheDocument()
    expect(screen.getByText(/Harde checks niet groen: Verplichte velden ontbreken/)).toBeInTheDocument()
  })

  it('punt 2b: zonder accordering-toggle geen bulk-balk; op een andere tab ook niet', async () => {
    installRunMock({ documenten: klaarDocs, accorderingAan: false })
    renderOp(`/?administratie=${ADMINISTRATIE_ID}&status=klaar_om_te_boeken`)
    await screen.findByText('Eneco Zakelijk')
    expect(screen.queryByTestId('bulk-balk')).not.toBeInTheDocument()
  })

  it('punt 2a: eenmalige banner "accorderingen vervallen" mét reden; Sluiten onthoudt de keuze per batch', async () => {
    const gebruiker = userEvent.setup()
    installRunMock({
      documenten: klaarDocs,
      meldingen: [
        {
          batch_id: 'batch-1',
          tijdstip: '2026-08-27T14:02:00Z',
          door_gebruiker_id: 'x',
          door_naam: 'P. Nijenhuis',
          aantal: 34,
          nog_niet_opnieuw_aangeboden: 12,
          reden: 'accorderingsconfiguratie gewijzigd — opnieuw aanbieden vereist',
        },
      ],
    })
    renderOp(`/?administratie=${ADMINISTRATIE_ID}`)
    const banner = await screen.findByTestId('vervallen-melding')
    expect(banner).toHaveTextContent('34 accorderingen zijn vervallen')
    expect(banner).toHaveTextContent('configuratie gewijzigd door P. Nijenhuis')
    expect(banner).toHaveTextContent('accorderingsconfiguratie gewijzigd — opnieuw aanbieden vereist')
    expect(banner).toHaveTextContent('12 staan nog op “Klaar om te boeken”')
    await gebruiker.click(within(banner).getByRole('button', { name: 'Melding sluiten' }))
    expect(screen.queryByTestId('vervallen-melding')).not.toBeInTheDocument()
    expect(window.localStorage.getItem('rlz.melding.accordering_vervallen.batch-1')).toBe('1')
  })

  it('punt 2a: een batch die volledig opnieuw is aangeboden (0 open) toont geen banner', async () => {
    installRunMock({
      documenten: klaarDocs,
      meldingen: [{ batch_id: 'b', tijdstip: '2026-08-27T14:02:00Z', door_gebruiker_id: 'x', door_naam: null, aantal: 3, nog_niet_opnieuw_aangeboden: 0, reden: 'r' }],
    })
    // Blok D (01-09): binnenkomst zonder status = "Te controleren" — c.pdf (Bouwmaat) is dan het
    // zichtbare document; de banner-afweging staat daar los van.
    renderOp(`/?administratie=${ADMINISTRATIE_ID}`)
    await screen.findByText('Bouwmaat')
    expect(screen.queryByTestId('vervallen-melding')).not.toBeInTheDocument()
  })

  it('punt 3a/3b/3c: leverancier vet mét metaregel, dichtheid compact onthouden, geboekt-dot in --ok-klasse', async () => {
    const gebruiker = userEvent.setup()
    installRunMock({
      documenten: [
        document({ id: DOCUMENT_ID, bestandsnaam: 'a.pdf', leverancier: 'Eneco Zakelijk', bron: 'email', aangemaakt_op: '2026-08-26T14:42:00Z' }),
        document({ id: GEBOEKT_DOCUMENT_ID, bestandsnaam: 'g.pdf', leverancier: 'Bouwmaat', status: 'geboekt' }),
      ],
    })
    renderOp(`/?administratie=${ADMINISTRATIE_ID}&soort=alle`)
    const hoofd = await screen.findByText('Eneco Zakelijk')
    expect(hoofd).toHaveClass('lijst-hoofd')
    const meta = hoofd.parentElement?.querySelector('.lijst-meta')
    expect(meta).toHaveTextContent(/a\.pdf · email · 26 aug/)
    expect(screen.getByText('Geboekt')).toHaveClass('status', 'geboekt')

    const tabel = hoofd.closest('table') as HTMLElement
    expect(tabel).toHaveClass('documenten-tabel')
    expect(tabel).not.toHaveClass('dichtheid-compact')
    await gebruiker.click(screen.getByRole('button', { name: 'Compact' }))
    expect(tabel).toHaveClass('dichtheid-compact')
    expect(window.localStorage.getItem('rlz.documentenlijst.dichtheid')).toBe('compact')
  })

  it('punt 5: "/" zet de cursor in het zoekveld', async () => {
    const gebruiker = userEvent.setup()
    installRunMock({ documenten: klaarDocs })
    renderOp(`/?administratie=${ADMINISTRATIE_ID}`)
    await screen.findByText('Bouwmaat')
    await gebruiker.keyboard('/')
    expect(screen.getByLabelText('Zoek in documenten')).toHaveFocus()
  })

  it('punt 24 (opruimrun 28-08): rij mét compleet klant-akkoord is niet selecteerbaar — checkbox uit mét uitleg "boek direct"', async () => {
    installRunMock({
      documenten: [
        klaarDocs[0],
        document({ id: K2_ID, bestandsnaam: 'b.pdf', leverancier: 'Technische Unie', status: 'klaar_om_te_boeken', klant_akkoord_compleet: true }),
      ],
      accorderingAan: true,
    })
    renderOp(`/?administratie=${ADMINISTRATIE_ID}&status=klaar_om_te_boeken`)
    const balk = await screen.findByTestId('bulk-balk')
    // Telling telt alleen de selecteerbare rijen.
    expect(balk).toHaveTextContent('1 klaar om te boeken')
    const uit = screen.getByLabelText(/Technische Unie: klant-akkoord compleet — boek direct/)
    expect(uit).toBeDisabled()
    expect(screen.getByLabelText('Selecteer Eneco Zakelijk')).toBeEnabled()
  })

  it('punt 21 (opruimrun 28-08): kolomkop klikken sorteert oplopend, nogmaals aflopend, mét pijl + aria-sort', async () => {
    const gebruiker = userEvent.setup()
    installRunMock({
      documenten: [
        document({ id: DOCUMENT_ID, bestandsnaam: 'a.pdf', leverancier: 'Technische Unie', totaalbedrag: '9.50', status: 'klaar_om_te_boeken' }),
        document({ id: K2_ID, bestandsnaam: 'b.pdf', leverancier: 'Eneco Zakelijk', totaalbedrag: '121.00', status: 'klaar_om_te_boeken' }),
      ],
    })
    renderOp(`/?administratie=${ADMINISTRATIE_ID}&status=klaar_om_te_boeken`)
    await screen.findByText('Technische Unie')
    const leveranciers = () =>
      screen.getAllByRole('row').map((r) => r.textContent ?? '').filter((t) => /Technische Unie|Eneco Zakelijk/.test(t)).map((t) => (t.includes('Technische') ? 'TU' : 'Eneco'))
    // Backend-volgorde: zoals aangeleverd.
    expect(leveranciers()).toEqual(['TU', 'Eneco'])
    const kop = screen.getByRole('button', { name: /^Leverancier/ })
    await gebruiker.click(kop)
    expect(leveranciers()).toEqual(['Eneco', 'TU'])
    expect(kop.closest('th')).toHaveAttribute('aria-sort', 'ascending')
    expect(kop).toHaveTextContent('▲')
    await gebruiker.click(kop)
    expect(leveranciers()).toEqual(['TU', 'Eneco'])
    expect(kop.closest('th')).toHaveAttribute('aria-sort', 'descending')
    // Derde klik heft de sortering op.
    await gebruiker.click(kop)
    expect(kop.closest('th')).toHaveAttribute('aria-sort', 'none')
    // Een andere kolom (bedrag, numeriek): 9.50 vóór 121.00.
    await gebruiker.click(screen.getByRole('button', { name: /^Bedrag/ }))
    expect(leveranciers()).toEqual(['TU', 'Eneco'])
  })
})
