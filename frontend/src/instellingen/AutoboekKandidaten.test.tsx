// Autoboek-kandidaten (blok B 01-09, mockup autoboek-kandidaten.html): tabs mét tellers + stand-tijdstip,
// onderbouwings-chips, bulk aanzetten mét bevestiging en uitkomst-lijst (overgeslagen mét reden), verbergen
// = verplichte reden, heroverwegen = advies + uitzetten mét bevestiging, drempel instelbaar.
// Restpunten 03-09 (mockup inzicht-kantoorbreed ⑧): verbergen = ÉÉN request mét uitkomst per rij;
// "Selecteer alle N resultaten" verschijnt alleen als het totaal groter is dan de pagina en stuurt {alle: true, …}.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AutoboekKandidaten } from './AutoboekKandidaten'

const ADM = 'aaaaaaaa-0000-0000-0000-000000000001'
const TELLERS = { kandidaten: 2, actief: 1, heroverwegen: 1, verborgen: 0, administraties_met_kandidaten: 1, drempel: 5, laatste_run_op: '2026-09-01T06:00:00Z' }

function rij(over: Record<string, unknown>) {
  return {
    administratie_id: ADM,
    administratie_naam: 'Administratiekantoor Nijenhuis C.V.',
    vendor_id: 'v-1',
    leverancier_naam: 'Ebbers Salarisadvies B.V.',
    reeks_ongewijzigd: 12,
    correcties: 0,
    open_vragen: 0,
    kwalificeert: true,
    actief: false,
    actief_sinds: null,
    redenen: [],
    chips: ['12 op rij ongewijzigd', 'geheugen bevestigd', '0 vragen / 0 correcties', 'vast maandbedrag'],
    heroverweeg_signalen: [],
    laatste_factuur_datum: '2026-08-25',
    laatste_factuur_bedrag: '2721.83',
    laatste_document_id: 'doc-1',
    snooze_reden: null,
    snooze_op: null,
    berekend_op: '2026-09-01T06:00:00Z',
    ...over,
  }
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function installFetch(aanroepen: { url: string; body: unknown }[], opties: { totaal?: number } = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.startsWith('/instellingen/autoboeken/kandidaten?')) {
        const params = new URL(url, 'http://x').searchParams
        const tab = params.get('tab')
        const rijen =
          tab === 'kandidaten'
            ? params.get('verborgen') === 'true'
              ? [rij({ vendor_id: 'v-9', leverancier_naam: 'Verborgen B.V.', snooze_reden: 'wil ik handmatig houden', snooze_op: '2026-08-30T10:00:00Z' })]
              : [rij({}), rij({ vendor_id: 'v-2', leverancier_naam: 'Transip B.V.', reeks_ongewijzigd: 9, chips: ['9 op rij ongewijzigd', 'geheugen bevestigd', '0 vragen / 0 correcties'] })]
            : tab === 'heroverwegen'
              ? [rij({ vendor_id: 'v-3', leverancier_naam: 'Bouwmaat Eindhoven', actief: true, actief_sinds: '2026-08-12T09:00:00Z', kwalificeert: false, heroverweeg_signalen: ['2 correcties ná activatie', 'GB-code gewijzigd door mens (28 Aug)'] })]
              : [rij({ vendor_id: 'v-3', leverancier_naam: 'Bouwmaat Eindhoven', actief: true, actief_sinds: '2026-08-12T09:00:00Z', heroverweeg_signalen: ['2 correcties ná activatie'] })]
        return Promise.resolve(json({ rijen, totaal: opties.totaal ?? rijen.length, pagina: 1, per_pagina: 25, tellers: TELLERS }))
      }
      if (url === '/instellingen/autoboeken/kandidaten/aanzetten' && init?.method === 'POST') {
        const body = JSON.parse(String(init.body))
        aanroepen.push({ url, body })
        return Promise.resolve(
          json({
            uitkomsten: [
              { administratie_id: ADM, vendor_id: 'v-1', status: 'aangezet', reden: null },
              { administratie_id: ADM, vendor_id: 'v-2', status: 'overgeslagen', reden: 'kwalificeert niet meer: 1 open vraag' },
            ],
            aangezet: 1,
            overgeslagen: 1,
          }),
        )
      }
      if (url === '/instellingen/autoboeken/kandidaten/verbergen' && init?.method === 'POST') {
        const body = JSON.parse(String(init.body))
        aanroepen.push({ url, body })
        return Promise.resolve(
          json({
            uitkomsten: [
              { administratie_id: ADM, vendor_id: 'v-1', status: 'verborgen', reden: null, leverancier_naam: 'Ebbers Salarisadvies B.V.', administratie_naam: 'Administratiekantoor Nijenhuis C.V.' },
              { administratie_id: ADM, vendor_id: 'v-7', status: 'overgeslagen', reden: 'al verborgen', leverancier_naam: 'Elders B.V.', administratie_naam: 'Andere B.V.' },
            ],
            verborgen: 1,
            overgeslagen: 1,
          }),
        )
      }
      if (url.endsWith('/uitzetten') && init?.method === 'POST') {
        aanroepen.push({ url, body: null })
        return Promise.resolve(new Response(null, { status: 204 }))
      }
      if (url === '/instellingen/autoboeken/instelling' && init?.method === 'PUT') {
        aanroepen.push({ url, body: JSON.parse(String(init.body)) })
        return Promise.resolve(json({ drempel_op_rij: 8, laatste_run_op: null }))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

function renderScherm() {
  return render(
    <MemoryRouter>
      <AutoboekKandidaten />
    </MemoryRouter>,
  )
}

describe('AutoboekKandidaten', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('toont tabs mét tellers, de stand van de laatste run, kandidaten mét onderbouwings-chips en laatste factuur', async () => {
    installFetch([])
    renderScherm()
    expect(await screen.findByText('Ebbers Salarisadvies B.V.')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Kandidaten (2)' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: 'Actief (1)' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Heroverwegen (1)' })).toBeInTheDocument()
    expect(screen.getByText(/criteria: ≥ 5 boekingen op rij/)).toBeInTheDocument()
    expect(screen.getByText(/Stand van 01-09/)).toBeInTheDocument()
    expect(screen.getByText('12 op rij ongewijzigd')).toBeInTheDocument()
    expect(screen.getByText('vast maandbedrag')).toBeInTheDocument()
    expect(screen.getAllByText('€ 2.721,83')).toHaveLength(2)
    expect(screen.getByText('2 kandidaten over 1 administraties')).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: 'Administratiekantoor Nijenhuis C.V.' })[0]).toHaveAttribute('href', `/instellingen/administraties/${ADM}?tab=boeken-ai`)
  })

  it('bulk aanzetten: selectie → bulkvoet → bevestiging → POST → uitkomst-lijst mét overgeslagen reden', async () => {
    const gebruiker = userEvent.setup()
    const aanroepen: { url: string; body: unknown }[] = []
    installFetch(aanroepen)
    renderScherm()
    await screen.findByText('Ebbers Salarisadvies B.V.')
    expect(screen.queryByRole('toolbar', { name: 'Bulk-bediening kandidaten' })).not.toBeInTheDocument()
    await gebruiker.click(screen.getByRole('checkbox', { name: 'Alle kandidaten op deze pagina selecteren' }))
    expect(screen.getByText('2 geselecteerd')).toBeInTheDocument()
    await gebruiker.click(screen.getByRole('button', { name: 'Autoboeken aanzetten (2)' }))
    expect(screen.getByText(/opnieuw getoetst; een leverancier die intussen niet meer kwalificeert wordt overgeslagen/)).toBeInTheDocument()
    expect(aanroepen).toHaveLength(0)
    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await waitFor(() => expect(aanroepen).toHaveLength(1))
    expect(aanroepen[0].body).toEqual({ items: [{ administratie_id: ADM, vendor_id: 'v-1' }, { administratie_id: ADM, vendor_id: 'v-2' }] })
    const uitkomst = await screen.findByTestId('aanzet-uitkomsten')
    expect(uitkomst).toHaveTextContent('1 aangezet · 1 overgeslagen')
    expect(uitkomst).toHaveTextContent('Transip B.V. · Administratiekantoor Nijenhuis C.V.: overgeslagen — kwalificeert niet meer: 1 open vraag')
  })

  it('kandidaat verbergen vereist een reden en stuurt ÉÉN bulk-request mét uitkomst per rij; het filter "verborgen" toont de rij mét reden en "Weer tonen"', async () => {
    const gebruiker = userEvent.setup()
    const aanroepen: { url: string; body: unknown }[] = []
    installFetch(aanroepen)
    renderScherm()
    await screen.findByText('Ebbers Salarisadvies B.V.')
    // Twee rijen aanvinken → één request met beide items (vroeger N losse requests).
    await gebruiker.click(screen.getByRole('checkbox', { name: /Selecteer Ebbers/ }))
    await gebruiker.click(screen.getByRole('checkbox', { name: /Selecteer Transip/ }))
    await gebruiker.click(screen.getByRole('button', { name: 'Kandidaat verbergen…' }))
    const dialoog = await screen.findByTestId('verberg-dialoog')
    expect(within(dialoog).getByRole('button', { name: 'Verbergen (2)' })).toBeDisabled()
    await gebruiker.type(within(dialoog).getByLabelText('Reden'), 'wil ik handmatig houden')
    await gebruiker.click(within(dialoog).getByRole('button', { name: 'Verbergen (2)' }))
    await waitFor(() => expect(aanroepen).toHaveLength(1))
    expect(aanroepen[0]).toEqual({
      url: '/instellingen/autoboeken/kandidaten/verbergen',
      body: { items: [{ administratie_id: ADM, vendor_id: 'v-1' }, { administratie_id: ADM, vendor_id: 'v-2' }], reden: 'wil ik handmatig houden' },
    })
    const uitkomst = await screen.findByTestId('aanzet-uitkomsten')
    expect(uitkomst).toHaveTextContent('1 verborgen · 1 overgeslagen')
    expect(uitkomst).toHaveTextContent('Ebbers Salarisadvies B.V. · Administratiekantoor Nijenhuis C.V.: verborgen')
    // De naam van een rij buiten de huidige pagina komt uit de server-uitkomst zelf.
    expect(uitkomst).toHaveTextContent('Elders B.V. · Andere B.V.: overgeslagen — al verborgen')
    await gebruiker.click(screen.getByRole('checkbox', { name: 'Verborgen kandidaten tonen' }))
    expect(await screen.findByText('Verborgen B.V.')).toBeInTheDocument()
    expect(screen.getByText(/wil ik handmatig houden/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Weer tonen Verborgen B.V.' })).toBeInTheDocument()
  })

  it('"Selecteer alle N resultaten" verschijnt alleen bij totaal > pagina en stuurt een server-side selectie {alle: true, …} mee', async () => {
    const gebruiker = userEvent.setup()
    const aanroepen: { url: string; body: unknown }[] = []
    installFetch(aanroepen, { totaal: 60 })
    renderScherm()
    await screen.findByText('Ebbers Salarisadvies B.V.')
    // Losse rij-selectie: geen "alle N"-knop (de pagina is nog niet volledig geselecteerd).
    await gebruiker.click(screen.getByRole('checkbox', { name: /Selecteer Ebbers/ }))
    expect(screen.queryByRole('button', { name: 'Selecteer alle 60 resultaten' })).not.toBeInTheDocument()
    await gebruiker.click(screen.getByRole('checkbox', { name: 'Alle kandidaten op deze pagina selecteren' }))
    expect(screen.getByText('Pagina geselecteerd (2)')).toBeInTheDocument()
    await gebruiker.click(screen.getByRole('button', { name: 'Selecteer alle 60 resultaten' }))
    expect(screen.getByText('Alle 60 resultaten geselecteerd')).toBeInTheDocument()
    // Veiligheidsrem: het aantal staat in de bevestigknop én in de dialoogtitel.
    await gebruiker.click(screen.getByRole('button', { name: 'Autoboeken aanzetten (60)' }))
    expect(screen.getByText('Autoboeken aanzetten voor 60 leveranciers?')).toBeInTheDocument()
    expect(screen.getByText(/álle 60 resultaten binnen het huidige filter/)).toBeInTheDocument()
    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await waitFor(() => expect(aanroepen).toHaveLength(1))
    expect(aanroepen[0].body).toEqual({ alle: true, tab: 'kandidaten', q: '', verborgen: false })
    expect(await screen.findByTestId('aanzet-uitkomsten')).toHaveTextContent('1 aangezet · 1 overgeslagen')
    // "Alleen deze pagina" zet terug naar een pagina-selectie; en zonder meer rijen dan de pagina géén knop.
    await gebruiker.click(screen.getByRole('checkbox', { name: 'Alle kandidaten op deze pagina selecteren' }))
    await gebruiker.click(screen.getByRole('button', { name: 'Selecteer alle 60 resultaten' }))
    await gebruiker.click(screen.getByRole('button', { name: 'Alleen deze pagina' }))
    expect(screen.getByText('Pagina geselecteerd (2)')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Autoboeken aanzetten (2)' })).toBeInTheDocument()
  })

  it('zonder meer resultaten dan de pagina is er géén "Selecteer alle N"-knop', async () => {
    const gebruiker = userEvent.setup()
    installFetch([])
    renderScherm()
    await screen.findByText('Ebbers Salarisadvies B.V.')
    await gebruiker.click(screen.getByRole('checkbox', { name: 'Alle kandidaten op deze pagina selecteren' }))
    expect(screen.getByText('2 geselecteerd')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Selecteer alle/ })).not.toBeInTheDocument()
  })

  it('heroverwegen: advies-waarschuwing, signaal-chips, uitzetten mét bevestiging → POST uitzetten', async () => {
    const gebruiker = userEvent.setup()
    const aanroepen: { url: string; body: unknown }[] = []
    installFetch(aanroepen)
    renderScherm()
    await screen.findByText('Ebbers Salarisadvies B.V.')
    fireEvent.click(screen.getByRole('tab', { name: 'Heroverwegen (1)' }))
    expect(await screen.findByText('Bouwmaat Eindhoven')).toBeInTheDocument()
    expect(screen.getByText(/Heroverwegen zet níéts automatisch uit/)).toBeInTheDocument()
    expect(screen.getByText('2 correcties ná activatie')).toBeInTheDocument()
    expect(screen.getByText(/actief sinds 12 aug/)).toBeInTheDocument()
    await gebruiker.click(screen.getByRole('button', { name: 'Autoboeken uitzetten voor Bouwmaat Eindhoven' }))
    expect(screen.getByText(/wachten weer op de boek-klik/)).toBeInTheDocument()
    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await waitFor(() => expect(aanroepen).toHaveLength(1))
    expect(aanroepen[0].url).toBe(`/instellingen/autoboeken/kandidaten/${ADM}/v-3/uitzetten`)
  })

  it('drempel opslaan PUT de instelling (1–50)', async () => {
    const gebruiker = userEvent.setup()
    const aanroepen: { url: string; body: unknown }[] = []
    installFetch(aanroepen)
    renderScherm()
    await screen.findByText('Ebbers Salarisadvies B.V.')
    const invoer = screen.getByRole('spinbutton', { name: 'Drempel op rij ongewijzigd' })
    expect(invoer).toHaveValue(5)
    await gebruiker.clear(invoer)
    await gebruiker.type(invoer, '8')
    await gebruiker.click(screen.getByRole('button', { name: 'Drempel opslaan' }))
    await waitFor(() => expect(aanroepen).toHaveLength(1))
    expect(aanroepen[0]).toEqual({ url: '/instellingen/autoboeken/instelling', body: { drempel_op_rij: 8 } })
  })
})
