import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { VerzamelbakPaneel } from './VerzamelbakPaneel'

const ADMIN_A = 'aaaaaaaa-0000-0000-0000-000000000001'
const ADMIN_B = 'bbbbbbbb-0000-0000-0000-000000000002'
const DOC_ID = 'cccccccc-0000-0000-0000-000000000003'
const SPLITSING_ID = 'dddddddd-0000-0000-0000-000000000004'
const DOC_ID_2 = 'eeeeeeee-0000-0000-0000-000000000005'

const ADMINISTRATIES = [
  { id: ADMIN_A, naam: 'BLOW B.V.' },
  { id: ADMIN_B, naam: 'Kempen Groep B.V.' },
]

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function item(overrides: Record<string, unknown> = {}) {
  return {
    document_id: DOC_ID,
    bestandsnaam: 'factuur_energie.pdf',
    soort: 'inkoopfactuur',
    bron: 'email',
    afzender_hint: 'info@blow.nl',
    tenaamstelling: 'BLOW Holding',
    suggestie_administratie_id: ADMIN_A,
    suggestie_bron: 'afzender_regel_maar_onbekende_tenaamstelling',
    aangemaakt_op: '2026-08-07T09:00:00Z',
    splitsing_id: null,
    splitsing_voorstel: null,
    ...overrides,
  }
}

function installFetchMock(opties: {
  items?: unknown[]
  aanroepen?: { url: string; body: unknown }[]
  bestandAanroepen?: string[]
}) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/bestand') && (!init || !init.method)) {
        opties.bestandAanroepen?.push(url)
        return Promise.resolve(new Response(new Blob(['%PDF-1.4'], { type: 'application/pdf' }), { status: 200 }))
      }
      if (url.endsWith('/verzamelbak') && (!init || !init.method)) {
        return Promise.resolve(jsonResponse({ items: opties.items ?? [item()] }))
      }
      if (url.endsWith('/ubl-samenvatting') && (!init || !init.method)) {
        return Promise.resolve(
          jsonResponse({
            leverancier: 'Saleswizard BV',
            afnemer: 'Belastingbutler B.V.',
            factuurnummer: '2026-8151',
            factuurdatum: '2026-09-02',
            totaal_excl: '29.50',
            totaal_incl: '35.70',
            valuta: 'EUR',
            regelaantal: 1,
            regels: [{ omschrijving: 'Abonnement', netto_bedrag: '29.50', aantal: '1' }],
          }),
        )
      }
      if (init?.method === 'POST') {
        opties.aanroepen?.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
        if (url.endsWith('/verzamelbak/samenvoegen')) {
          return Promise.resolve(
            jsonResponse({ document_id: DOC_ID, samengevoegd_document_id: DOC_ID_2, beeld_bestandsnaam: 'factuur_energie.pdf', waarschuwingen: [] }),
          )
        }
        return Promise.resolve(jsonResponse({ document_id: DOC_ID, status: 'te_controleren' }))
      }
      return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
    }),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('VerzamelbakPaneel', () => {
  it('toont herkomst, tenaamstelling en de AI-suggestie', async () => {
    installFetchMock({})
    render(<VerzamelbakPaneel administraties={ADMINISTRATIES} />)

    expect(await screen.findByText(/Niet toegewezen — handmatig koppelen \(1\)/)).toBeInTheDocument()
    expect(screen.getByText(/e-mail · info@blow.nl/)).toBeInTheDocument()
    expect(screen.getByText(/“BLOW Holding”/)).toBeInTheDocument()
    expect(screen.getByText('suggestie: BLOW B.V.')).toBeInTheDocument()
  })

  it('toont de échte intake-reden (02-09): verworpen AI-voorstel ≠ "geen tenaamstelling gelezen"', async () => {
    installFetchMock({
      items: [
        item({
          tenaamstelling: null,
          suggestie_administratie_id: null,
          suggestie_bron: null,
          reden: "splitsingsdetectie_mislukt: Splitsingsvoorstel ongeldig: paginabereik 1–2 valt buiten het document (1 pagina's)",
          reden_label: 'AI-voorstel verworpen door code: paginabereik 1–2 valt buiten het document — tenaamstelling niet overgenomen',
        }),
        item({
          document_id: 'eeeeeeee-0000-0000-0000-000000000005',
          bestandsnaam: 'leeg.pdf',
          tenaamstelling: null,
          suggestie_administratie_id: null,
          reden: 'tenaamstelling_niet_eenduidig',
          reden_label: 'geen tenaamstelling gelezen',
        }),
        item({
          document_id: 'ffffffff-0000-0000-0000-000000000006',
          bestandsnaam: 'oud.pdf',
          tenaamstelling: null,
          suggestie_administratie_id: null,
          // Oudere server zonder label-veld: terugval blijft de oude chip.
          reden: undefined,
          reden_label: undefined,
        }),
      ],
    })
    render(<VerzamelbakPaneel administraties={ADMINISTRATIES} />)
    expect(await screen.findByText(/AI-voorstel verworpen door code: paginabereik 1–2/)).toBeInTheDocument()
    expect(screen.getAllByText('geen tenaamstelling gelezen')).toHaveLength(2)
  })

  it('een splitsingsvoorstel met een ongeldig deel toont de reden en kan niet blind bevestigd worden', async () => {
    const aanroepen: { url: string; body: unknown }[] = []
    installFetchMock({
      aanroepen,
      items: [
        item({
          bestandsnaam: 'batchscan.pdf',
          tenaamstelling: null,
          reden: "splitsingsvoorstel_ter_controle: 2 facturen herkend, 1 deel ongeldig — paginabereik 3–7 valt buiten het document (3 pagina's)",
          reden_label: 'splitsingsvoorstel bevat een ongeldig deel — beoordeel de bereiken',
          splitsing_id: SPLITSING_ID,
          splitsing_voorstel: [
            { start_pagina: 1, eind_pagina: 2, tenaamstelling: 'BLOW B.V.', leverancier: null, factuurnummer: null, zekerheid: 0.95 },
            {
              start_pagina: 3,
              eind_pagina: 7,
              tenaamstelling: 'Kempen Groep B.V.',
              leverancier: null,
              factuurnummer: null,
              zekerheid: 0.9,
              ongeldig_reden: "paginabereik 3–7 valt buiten het document (3 pagina's)",
            },
          ],
        }),
      ],
    })
    render(<VerzamelbakPaneel administraties={ADMINISTRATIES} />)
    expect(await screen.findByText(/⚠ ongeldig \(paginabereik 3–7/)).toBeInTheDocument()
    expect(screen.getByText('splitsingsvoorstel bevat een ongeldig deel — beoordeel de bereiken')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Splitsing bevestigen ✓' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Is één factuur' })).toBeEnabled()
    expect(aanroepen).toHaveLength(0)
  })

  it('preview (D1, besluit 25-08): niets vooraf opgehaald; hover laadt het bestand één keer en toont de popup', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const bestandAanroepen: string[] = []
    installFetchMock({ items: [item()], bestandAanroepen })
    render(<VerzamelbakPaneel administraties={ADMINISTRATIES} />)
    const knop = await screen.findByRole('button', { name: 'Voorbeeld van factuur_energie.pdf' })
    // Lazy: geen enkele bestand-request vóór hover/klik.
    expect(bestandAanroepen).toHaveLength(0)

    fireEvent.mouseEnter(knop.parentElement as HTMLElement)
    await vi.advanceTimersByTimeAsync(250)
    expect(await screen.findByRole('tooltip', { name: 'Voorbeeld factuur_energie.pdf' })).toBeInTheDocument()
    await waitFor(() => expect(bestandAanroepen).toHaveLength(1))
    expect(bestandAanroepen[0]).toContain(`/verzamelbak/${DOC_ID}/bestand`)

    // Opnieuw hoveren: uit de cache, geen tweede request.
    fireEvent.mouseLeave(knop.parentElement as HTMLElement)
    fireEvent.mouseEnter(knop.parentElement as HTMLElement)
    await vi.advanceTimersByTimeAsync(250)
    expect(bestandAanroepen).toHaveLength(1)
    vi.useRealTimers()
  })

  it('is onzichtbaar zolang de bak leeg is', async () => {
    installFetchMock({ items: [] })
    const { container } = render(<VerzamelbakPaneel administraties={ADMINISTRATIES} />)
    await waitFor(() => expect(container.firstChild).toBeNull())
  })

  it('toewijzen stuurt de gekozen administratie (suggestie voorgeselecteerd)', async () => {
    const aanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ aanroepen })
    render(<VerzamelbakPaneel administraties={ADMINISTRATIES} />)
    await screen.findByText(/handmatig koppelen/)

    await userEvent.click(screen.getByRole('button', { name: 'Toewijzen ✓' }))
    await waitFor(() => expect(aanroepen).toHaveLength(1))
    expect(aanroepen[0].url).toContain(`/verzamelbak/${DOC_ID}/toewijzen`)
    expect(aanroepen[0].body).toEqual({ administratie_id: ADMIN_A })
  })

  it('hoort niet bij ons vereist een reden', async () => {
    const aanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ aanroepen })
    render(<VerzamelbakPaneel administraties={ADMINISTRATIES} />)
    await screen.findByText(/handmatig koppelen/)

    await userEvent.click(screen.getByRole('button', { name: 'Hoort niet bij ons' }))
    const vastleggen = screen.getByRole('button', { name: 'Vastleggen ✓' })
    expect(vastleggen).toBeDisabled()

    await userEvent.type(screen.getByLabelText('Reden (verplicht)'), 'Ander kantoor')
    await userEvent.click(screen.getByRole('button', { name: 'Vastleggen ✓' }))
    await waitFor(() => expect(aanroepen).toHaveLength(1))
    expect(aanroepen[0].url).toContain('/hoort-niet-bij-ons')
    expect(aanroepen[0].body).toEqual({ reden: 'Ander kantoor' })
  })

  it('optimistisch (besluit 26-08): de rij verdwijnt direct en de teller telt af, nog vóór de server antwoordt', async () => {
    let los: ((r: Response) => void) | null = null
    const items = [item(), item({ document_id: 'cccccccc-0000-0000-0000-000000000004', bestandsnaam: 'tweede.pdf' })]
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith('/verzamelbak') && (!init || !init.method)) return Promise.resolve(jsonResponse({ items }))
        if (init?.method === 'POST') return new Promise<Response>((resolve) => (los = resolve))
        return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
      }),
    )
    const onGewijzigd = vi.fn()
    render(<VerzamelbakPaneel administraties={ADMINISTRATIES} onGewijzigd={onGewijzigd} />)
    await screen.findByText(/handmatig koppelen \(2\)/)

    await userEvent.click(screen.getAllByRole('button', { name: 'Toewijzen ✓' })[0])
    // Direct weg + teller af, terwijl het request nog open staat.
    expect(screen.getByText(/handmatig koppelen \(1\)/)).toBeInTheDocument()
    expect(screen.queryByText('factuur_energie.pdf')).not.toBeInTheDocument()
    expect(onGewijzigd).not.toHaveBeenCalled()

    los!(jsonResponse({ document_id: DOC_ID, status: 'te_controleren' }))
    await waitFor(() => expect(onGewijzigd).toHaveBeenCalledTimes(1))
    expect(screen.queryByText('factuur_energie.pdf')).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('mislukt (4xx/5xx/time-out): de rij komt LUID terug op haar plek mét rode reden — nooit stil', async () => {
    const items = [item(), item({ document_id: 'cccccccc-0000-0000-0000-000000000004', bestandsnaam: 'tweede.pdf' })]
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith('/verzamelbak') && (!init || !init.method)) return Promise.resolve(jsonResponse({ items }))
        if (init?.method === 'POST') {
          return Promise.resolve(jsonResponse({ detail: "Dit document is al afgehandeld als 'hoort niet bij ons' — er is niets gewijzigd." }, 409))
        }
        return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
      }),
    )
    const onGewijzigd = vi.fn()
    render(<VerzamelbakPaneel administraties={ADMINISTRATIES} onGewijzigd={onGewijzigd} />)
    await screen.findByText(/handmatig koppelen \(2\)/)

    await userEvent.click(screen.getAllByRole('button', { name: 'Toewijzen ✓' })[0])
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/Niet verwerkt: Dit document is al afgehandeld als 'hoort niet bij ons'/)
    expect(screen.getByText(/handmatig koppelen \(2\)/)).toBeInTheDocument()
    // Terug op de oorspronkelijke plek (eerste rij), niet onderaan.
    const rijen = screen.getAllByRole('row')
    expect(rijen[1]).toHaveTextContent('factuur_energie.pdf')
    expect(onGewijzigd).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Lijst verversen' })).toBeInTheDocument()
  })

  it('al verwerkt (tweede klik / collega): rij blijft weg, rustige melding in plaats van een rode fout', async () => {
    const items = [item(), item({ document_id: 'cccccccc-0000-0000-0000-000000000004', bestandsnaam: 'tweede.pdf' })]
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith('/verzamelbak') && (!init || !init.method)) return Promise.resolve(jsonResponse({ items }))
        if (init?.method === 'POST') {
          return Promise.resolve(
            jsonResponse({ document_id: DOC_ID, status: 'ontvangen', al_verwerkt: true, melding: 'Was al toegewezen aan BLOW B.V. — niets opnieuw gedaan.' }),
          )
        }
        return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
      }),
    )
    render(<VerzamelbakPaneel administraties={ADMINISTRATIES} />)
    await screen.findByText(/handmatig koppelen \(2\)/)

    await userEvent.click(screen.getAllByRole('button', { name: 'Toewijzen ✓' })[0])
    const melding = await screen.findByTestId('verzamelbak-al-verwerkt')
    expect(melding).toHaveTextContent('factuur_energie.pdf: Was al toegewezen aan BLOW B.V. — niets opnieuw gedaan.')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.queryByText('factuur_energie.pdf', { exact: true })).not.toBeInTheDocument()
    expect(screen.getByText(/handmatig koppelen \(1\)/)).toBeInTheDocument()
  })

  it('een splitsingsvoorstel toont de delen en bevestigt met de paginabereiken', async () => {
    const aanroepen: { url: string; body: unknown }[] = []
    installFetchMock({
      aanroepen,
      items: [
        item({
          bestandsnaam: 'batchscan.pdf',
          splitsing_id: SPLITSING_ID,
          splitsing_voorstel: [
            { start_pagina: 1, eind_pagina: 2, tenaamstelling: 'BLOW B.V.', leverancier: null, factuurnummer: null, zekerheid: 0.95 },
            { start_pagina: 3, eind_pagina: 3, tenaamstelling: 'Kempen Groep B.V.', leverancier: null, factuurnummer: null, zekerheid: 0.9 },
          ],
        }),
      ],
    })
    render(<VerzamelbakPaneel administraties={ADMINISTRATIES} />)
    await screen.findByText(/Splitsingsvoorstel: 2 facturen/)

    await userEvent.click(screen.getByRole('button', { name: 'Splitsing bevestigen ✓' }))
    await waitFor(() => expect(aanroepen).toHaveLength(1))
    expect(aanroepen[0].url).toContain(`/intake/splitsingen/${SPLITSING_ID}/bevestigen`)
    expect(aanroepen[0].body).toEqual({
      delen: [
        { start_pagina: 1, eind_pagina: 2, tenaamstelling: 'BLOW B.V.' },
        { start_pagina: 3, eind_pagina: 3, tenaamstelling: 'Kempen Groep B.V.' },
      ],
    })
  })

  it('B4 (02-09): gebundeld UBL+PDF-document toont het PDF-beeld als chip en de preview volgt het geserveerde bestand', async () => {
    const bestandAanroepen: string[] = []
    installFetchMock({
      // Eigen id: de preview-blobcache is module-breed (één keer ophalen per document).
      items: [item({ document_id: 'ffffffff-0000-0000-0000-00000000000f', bestandsnaam: '2026-8151.xml', beeld_bestandsnaam: '2026-8151.pdf', tenaamstelling: 'Belastingbutler B.V.' })],
      bestandAanroepen,
    })
    render(<VerzamelbakPaneel administraties={ADMINISTRATIES} />)
    expect(await screen.findByTestId('beeld-chip')).toHaveTextContent('2026-8151.pdf')
    await userEvent.click(screen.getByRole('button', { name: 'Voorbeeld van 2026-8151.xml' }))
    await waitFor(() => expect(bestandAanroepen).toHaveLength(1))
    // Het beeld (PDF) wordt geserveerd en als PDF getoond — geen "geen inline weergave"-tekst.
    await waitFor(() => expect(screen.getByLabelText('Documentweergave')).toBeInTheDocument())
    expect(screen.queryByText(/Geen inline weergave/)).not.toBeInTheDocument()
    expect(screen.queryByText(/geen paginabeeld/)).not.toBeInTheDocument()
  })

  it('B4 (02-09): losse UBL zonder beeld toont een gerenderde samenvatting i.p.v. "geen paginabeeld"', async () => {
    installFetchMock({ items: [item({ bestandsnaam: '2026-8151.xml', tenaamstelling: 'Belastingbutler B.V.' })] })
    render(<VerzamelbakPaneel administraties={ADMINISTRATIES} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Voorbeeld van 2026-8151.xml' }))
    const kaart = await screen.findByTestId('ubl-samenvatting')
    expect(kaart).toHaveTextContent('Saleswizard BV')
    expect(kaart).toHaveTextContent('Belastingbutler B.V.')
    expect(kaart).toHaveTextContent('Factuur 2026-8151')
  })

  it('B4 (02-09): twee rijen selecteren → Samenvoegen → dialoog kiest de UBL als leidend → POST mét beide id\'s', async () => {
    const aanroepen: { url: string; body: unknown }[] = []
    installFetchMock({
      items: [
        item({ document_id: DOC_ID, bestandsnaam: '2026-8151.pdf', tenaamstelling: null, intake_bericht_id: 'm1' }),
        item({ document_id: DOC_ID_2, bestandsnaam: '2026-8151.xml', tenaamstelling: 'Belastingbutler B.V.', intake_bericht_id: 'm1' }),
      ],
      aanroepen,
    })
    render(<VerzamelbakPaneel administraties={ADMINISTRATIES} />)
    await userEvent.click(await screen.findByLabelText('Selecteer 2026-8151.pdf voor samenvoegen'))
    expect(screen.getByRole('button', { name: 'Samenvoegen (1)' })).toBeDisabled()
    await userEvent.click(screen.getByLabelText('Selecteer 2026-8151.xml voor samenvoegen'))
    await userEvent.click(screen.getByRole('button', { name: 'Samenvoegen (2)' }))
    // Default leidend = de UBL (velden deterministisch); zelfde mail → geen waarschuwing.
    expect(await screen.findByRole('radio', { name: /2026-8151\.xml/ })).toBeChecked()
    expect(screen.queryByTestId('samenvoeg-waarschuwing-mail')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Samenvoegen — 2026-8151\.xml leidend/ }))
    await waitFor(() => expect(aanroepen.some((a) => a.url.endsWith('/verzamelbak/samenvoegen'))).toBe(true))
    expect(aanroepen.find((a) => a.url.endsWith('/verzamelbak/samenvoegen'))!.body).toEqual({
      leidend_document_id: DOC_ID_2,
      ander_document_id: DOC_ID,
      bevestig_zelfde_type: false,
    })
  })

  it('B4 (02-09): twee PDF\'s vragen een expliciete bevestiging; andere mail = zichtbare waarschuwing', async () => {
    installFetchMock({
      items: [
        item({ document_id: DOC_ID, bestandsnaam: 'a.pdf', intake_bericht_id: 'm1' }),
        item({ document_id: DOC_ID_2, bestandsnaam: 'b.pdf', intake_bericht_id: 'm2' }),
      ],
    })
    render(<VerzamelbakPaneel administraties={ADMINISTRATIES} />)
    await userEvent.click(await screen.findByLabelText('Selecteer a.pdf voor samenvoegen'))
    await userEvent.click(screen.getByLabelText('Selecteer b.pdf voor samenvoegen'))
    await userEvent.click(screen.getByRole('button', { name: 'Samenvoegen (2)' }))
    expect(await screen.findByTestId('samenvoeg-waarschuwing-mail')).toBeInTheDocument()
    const bevestig = screen.getByRole('button', { name: /Samenvoegen — a\.pdf leidend/ })
    expect(bevestig).toBeDisabled()
    await userEvent.click(screen.getByRole('checkbox', { name: /Toch samenvoegen/ }))
    expect(bevestig).toBeEnabled()
  })

  it('B4 (02-09): een handmatig samengevoegde rij biedt "samenvoegen ongedaan maken"', async () => {
    const aanroepen: { url: string; body: unknown }[] = []
    installFetchMock({
      items: [item({ bestandsnaam: 'f.xml', beeld_bestandsnaam: 'f.pdf', samengevoegd_document_id: DOC_ID_2, samengevoegd_bestandsnaam: 'f.pdf' })],
      aanroepen,
    })
    render(<VerzamelbakPaneel administraties={ADMINISTRATIES} />)
    await userEvent.click(await screen.findByRole('button', { name: 'samenvoegen ongedaan maken' }))
    await waitFor(() => expect(aanroepen.some((a) => a.url.endsWith(`/verzamelbak/${DOC_ID}/samenvoegen-ongedaan`))).toBe(true))
  })
})
