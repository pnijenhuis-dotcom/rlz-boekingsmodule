import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { LeverancierAutoboeken, standVan } from './LeverancierAutoboeken'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const VENDOR_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const TWEEDE_VENDOR_ID = 'cccccccc-0000-0000-0000-000000000003'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function installFetchMock(opties: {
  leveranciers?: unknown[]
  putAanroepen?: { url: string; body: unknown }[]
  putStatus?: number
}) {
  const leveranciers = opties.leveranciers ?? [
    { vendor_id: VENDOR_ID, naam: 'Bouwmaat Nederland B.V.', autoboeken_ingeschakeld: false },
    { vendor_id: TWEEDE_VENDOR_ID, naam: 'Technische Unie', autoboeken_ingeschakeld: true },
  ]
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/leveranciers-autoboeken') && (!init || init.method === undefined)) {
        return Promise.resolve(jsonResponse({ leveranciers }))
      }
      if (url.endsWith('/autoboeken-instelling') && init?.method === 'PUT') {
        const body = init.body ? (JSON.parse(String(init.body)) as { ingeschakeld: boolean }) : null
        opties.putAanroepen?.push({ url, body })
        if (opties.putStatus && opties.putStatus >= 400) {
          return Promise.resolve(jsonResponse({ detail: 'Alleen een Beheerder mag dit wijzigen.' }, opties.putStatus))
        }
        return Promise.resolve(
          jsonResponse({ vendor_id: VENDOR_ID, naam: 'Bouwmaat Nederland B.V.', autoboeken_ingeschakeld: body?.ingeschakeld ?? false }),
        )
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

/** De sectie leeft binnen de Beheerder-rol-gate van InstellingenScreen — hier testen we de
 * sectie zelf, met administraties als prop (zelfde patroon als AccorderingInstellingen). */
async function renderMetAdministratie() {
  const gebruiker = userEvent.setup()
  render(<LeverancierAutoboeken administraties={[{ id: ADMINISTRATIE_ID, naam: 'Testklant B.V.' }]} />)
  await kiesAdministratie(gebruiker, 'Administratie voor automatisch boeken', 'Testklant B.V.')
  return gebruiker
}

/** Punt 13 (opruimrun 28-08): de administratie-kiezer is een doorzoekbare combobox — kiezen =
 * veld openen en de optie aanklikken (i.p.v. userEvent.selectOptions op een <select>). */
async function kiesAdministratie(gebruiker: ReturnType<typeof userEvent.setup>, label: string, naam: string) {
  await gebruiker.click(await screen.findByLabelText(label))
  await gebruiker.click(await screen.findByRole('option', { name: naam }))
}

describe('LeverancierAutoboeken — opt-in per leverancier (Beheerder)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('laadt de leverancierslijst pas na administratie-keuze en toont de stand per leverancier', async () => {
    installFetchMock({})
    const gebruiker = userEvent.setup()
    render(<LeverancierAutoboeken administraties={[{ id: ADMINISTRATIE_ID, naam: 'Testklant B.V.' }]} />)

    // Nog geen keuze → geen fetch van de leverancierslijst.
    expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes('/leveranciers-autoboeken'))).toHaveLength(0)

    await kiesAdministratie(gebruiker, 'Administratie voor automatisch boeken', 'Testklant B.V.')
    await waitFor(() => expect(screen.getByText('Bouwmaat Nederland B.V.')).toBeInTheDocument())
    expect(screen.getByRole('checkbox', { name: 'Automatisch boeken voor Bouwmaat Nederland B.V.' })).not.toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Automatisch boeken voor Technische Unie' })).toBeChecked()
    // De uitlegregel (default UIT, Beheerder-only, chip "automatisch") staat onder de tabel.
    expect(screen.getByText(/Standaard staat automatisch boeken UIT/)).toBeInTheDocument()
  })

  it('checkbox aanzetten opent de bevestigingsdialoog en PUT pas na bevestigen (optimistische update)', async () => {
    const putAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ putAanroepen })
    const gebruiker = await renderMetAdministratie()

    await waitFor(() => expect(screen.getByText('Bouwmaat Nederland B.V.')).toBeInTheDocument())
    const checkbox = screen.getByRole('checkbox', { name: 'Automatisch boeken voor Bouwmaat Nederland B.V.' })
    await gebruiker.click(checkbox)

    // Serieuze bevestigtekst mét de leveranciersnaam; nog géén PUT en de checkbox nog uit.
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(
      screen.getByText(/Facturen van Bouwmaat Nederland B\.V\. worden na extractie automatisch geboekt/),
    ).toBeInTheDocument()
    expect(screen.getByText(/De controles blijven blokkerend\. Weet je het zeker\?/)).toBeInTheDocument()
    expect(putAanroepen).toHaveLength(0)
    expect(checkbox).not.toBeChecked()

    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(putAanroepen).toHaveLength(1)
    expect(putAanroepen[0].url).toBe(
      `/administraties/${ADMINISTRATIE_ID}/leveranciers/${VENDOR_ID}/autoboeken-instelling`,
    )
    expect(putAanroepen[0].body).toEqual({ ingeschakeld: true })
    await waitFor(() => expect(checkbox).toBeChecked())
  })

  it('uitzetten toont de kortere tekst en PUT ingeschakeld:false', async () => {
    const putAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ putAanroepen })
    const gebruiker = await renderMetAdministratie()

    await waitFor(() => expect(screen.getByText('Technische Unie')).toBeInTheDocument())
    await gebruiker.click(screen.getByRole('checkbox', { name: 'Automatisch boeken voor Technische Unie' }))

    expect(screen.getByText(/Automatisch boeken wordt uitgeschakeld voor Technische Unie/)).toBeInTheDocument()
    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))

    await waitFor(() => expect(putAanroepen).toHaveLength(1))
    expect(putAanroepen[0].url).toContain(`/leveranciers/${TWEEDE_VENDOR_ID}/autoboeken-instelling`)
    expect(putAanroepen[0].body).toEqual({ ingeschakeld: false })
  })

  it('annuleren sluit de dialoog zonder aanroep en laat de checkbox ongewijzigd', async () => {
    const putAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ putAanroepen })
    const gebruiker = await renderMetAdministratie()

    await waitFor(() => expect(screen.getByText('Bouwmaat Nederland B.V.')).toBeInTheDocument())
    const checkbox = screen.getByRole('checkbox', { name: 'Automatisch boeken voor Bouwmaat Nederland B.V.' })
    await gebruiker.click(checkbox)
    await gebruiker.click(screen.getByRole('button', { name: 'Annuleren' }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(putAanroepen).toHaveLength(0)
    expect(checkbox).not.toBeChecked()
  })

  it('een fout bij de PUT (bv. 403 niet-Beheerder) blijft in de dialoog zichtbaar, checkbox blijft uit', async () => {
    installFetchMock({ putStatus: 403 })
    const gebruiker = await renderMetAdministratie()

    await waitFor(() => expect(screen.getByText('Bouwmaat Nederland B.V.')).toBeInTheDocument())
    const checkbox = screen.getByRole('checkbox', { name: 'Automatisch boeken voor Bouwmaat Nederland B.V.' })
    await gebruiker.click(checkbox)
    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))

    await waitFor(() =>
      expect(within(screen.getByRole('dialog')).getByText('Alleen een Beheerder mag dit wijzigen.')).toBeInTheDocument(),
    )
    expect(checkbox).not.toBeChecked()
  })

  it('toont een duidelijke melding als er nog geen leveranciers gesynchroniseerd zijn', async () => {
    installFetchMock({ leveranciers: [] })
    await renderMetAdministratie()

    await waitFor(() => expect(screen.getByText(/Nog geen leveranciers bekend/)).toBeInTheDocument())
  })
})

// Blok A bundel 10-09: administratie-schakelaar AAN → uitzonderingenlijst (chips per stand, Uitzonderen… mét verplichte
// reden, Vrijgeven); de kale switch alleen bij schakelaar UIT.
function installLerenMock(aanroepen: { url: string; body: unknown }[], opties: { uitzonderStatus?: number } = {}) {
  const leveranciers = [
    { vendor_id: VENDOR_ID, naam: 'Bouwmaat Nederland B.V.', autoboeken_ingeschakeld: false, stand: 'leert', reeks: 2, drempel: 3, bron: null, gereset_op: null, uitzondering_reden: null },
    { vendor_id: TWEEDE_VENDOR_ID, naam: 'Technische Unie', autoboeken_ingeschakeld: true, stand: 'boekt_automatisch', reeks: 7, drempel: 3, bron: 'systeem', gereset_op: null, uitzondering_reden: null },
    { vendor_id: 'dddddddd-0000-0000-0000-000000000004', naam: 'Labo Derva', autoboeken_ingeschakeld: false, stand: 'uitgezonderd', reeks: 0, drempel: 3, bron: null, gereset_op: null, uitzondering_reden: 'buitenlandse btw, altijd handwerk' },
    { vendor_id: 'eeeeeeee-0000-0000-0000-000000000005', naam: 'Transip B.V.', autoboeken_ingeschakeld: true, stand: 'handmatig_aan', reeks: 1, drempel: 3, bron: 'mens', gereset_op: null, uitzondering_reden: null },
  ]
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/leveranciers-autoboeken') && (!init || init.method === undefined)) return Promise.resolve(jsonResponse({ leveranciers }))
      if (url.endsWith('/autoboeken-uitzonderen') && init?.method === 'POST') {
        const body = JSON.parse(String(init.body)) as { reden: string }
        aanroepen.push({ url, body })
        if (opties.uitzonderStatus === 422) return Promise.resolve(jsonResponse({ detail: 'Reden is verplicht.' }, 422))
        return Promise.resolve(jsonResponse({ ...leveranciers[0], autoboeken_ingeschakeld: false, stand: 'uitgezonderd', uitzondering_reden: body.reden }))
      }
      if (url.endsWith('/autoboeken-vrijgeven') && init?.method === 'POST') {
        aanroepen.push({ url, body: null })
        return Promise.resolve(jsonResponse({ ...leveranciers[2], stand: 'boekt_automatisch', bron: 'systeem', autoboeken_ingeschakeld: true, uitzondering_reden: null }))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

describe('LeverancierAutoboeken — uitzonderingenlijst als de administratie-schakelaar aan staat (blok A 10-09)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('toont per leverancier een stand-chip (leert n/3 · boekt automatisch · uitgezonderd mét reden-title · handmatig aan) en GEEN switches', async () => {
    installLerenMock([])
    render(<LeverancierAutoboeken administraties={[{ id: ADMINISTRATIE_ID, naam: 'Testklant B.V.' }]} vasteAdministratieId={ADMINISTRATIE_ID} administratieLerenAan />)
    await waitFor(() => expect(screen.getByText('Bouwmaat Nederland B.V.')).toBeInTheDocument())
    expect(screen.getByTestId('leverancier-autoboeken')).toHaveAttribute('data-modus', 'uitzonderingen')
    expect(screen.getByText('leert (2/3)')).toBeInTheDocument()
    expect(screen.getByText('boekt automatisch')).toBeInTheDocument()
    expect(screen.getByText('uitgezonderd')).toHaveAttribute('title', 'buitenlandse btw, altijd handwerk')
    expect(screen.getByText('handmatig aan')).toBeInTheDocument()
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0)
    // Acties: Uitzonderen… op niet-uitgezonderde rijen, Vrijgeven op de uitgezonderde.
    expect(screen.getAllByRole('button', { name: 'Uitzonderen…' })).toHaveLength(3)
    expect(screen.getAllByRole('button', { name: 'Vrijgeven' })).toHaveLength(1)
    // Zoekveld filtert op naam.
    await userEvent.setup().type(screen.getByLabelText('Zoek leverancier'), 'labo')
    expect(screen.queryByText('Bouwmaat Nederland B.V.')).not.toBeInTheDocument()
    expect(screen.getByText('Labo Derva')).toBeInTheDocument()
  })

  it('Uitzonderen… opent een dialoog; zonder reden is de knop uitgeschakeld (geen POST); mét reden → POST {reden} → chip "uitgezonderd"', async () => {
    const aanroepen: { url: string; body: unknown }[] = []
    installLerenMock(aanroepen)
    const gebruiker = userEvent.setup()
    render(<LeverancierAutoboeken administraties={[]} vasteAdministratieId={ADMINISTRATIE_ID} administratieLerenAan />)
    await waitFor(() => expect(screen.getByText('Bouwmaat Nederland B.V.')).toBeInTheDocument())
    await gebruiker.click(within(screen.getByTestId(`leverancier-rij-${VENDOR_ID}`)).getByRole('button', { name: 'Uitzonderen…' }))
    const dialoog = await screen.findByTestId('uitzonder-dialoog')
    expect(dialoog).toHaveTextContent('Uitzonderen — Bouwmaat Nederland B.V.')
    expect(within(dialoog).getByRole('button', { name: 'Uitzonderen' })).toBeDisabled()
    await gebruiker.type(within(dialoog).getByLabelText('Reden'), 'wisselende projecten per factuur')
    await gebruiker.click(within(dialoog).getByRole('button', { name: 'Uitzonderen' }))
    await waitFor(() => expect(screen.queryByTestId('uitzonder-dialoog')).not.toBeInTheDocument())
    expect(aanroepen).toEqual([{ url: `/administraties/${ADMINISTRATIE_ID}/leveranciers/${VENDOR_ID}/autoboeken-uitzonderen`, body: { reden: 'wisselende projecten per factuur' } }])
    const rij = screen.getByTestId(`leverancier-rij-${VENDOR_ID}`)
    expect(within(rij).getByText('uitgezonderd')).toHaveAttribute('title', 'wisselende projecten per factuur')
    expect(within(rij).getByRole('button', { name: 'Vrijgeven' })).toBeInTheDocument()
  })

  it('Vrijgeven → POST …/autoboeken-vrijgeven → nieuwe stand uit de server (direct "boekt automatisch" als de reeks al aan de drempel zit)', async () => {
    const aanroepen: { url: string; body: unknown }[] = []
    installLerenMock(aanroepen)
    const gebruiker = userEvent.setup()
    render(<LeverancierAutoboeken administraties={[]} vasteAdministratieId={ADMINISTRATIE_ID} administratieLerenAan />)
    await waitFor(() => expect(screen.getByText('Labo Derva')).toBeInTheDocument())
    await gebruiker.click(screen.getByRole('button', { name: 'Vrijgeven' }))
    await waitFor(() => expect(aanroepen).toHaveLength(1))
    expect(aanroepen[0].url).toBe(`/administraties/${ADMINISTRATIE_ID}/leveranciers/dddddddd-0000-0000-0000-000000000004/autoboeken-vrijgeven`)
    const rij = screen.getByTestId('leverancier-rij-dddddddd-0000-0000-0000-000000000004')
    await waitFor(() => expect(within(rij).getByText('boekt automatisch')).toBeInTheDocument())
    expect(within(rij).getByRole('button', { name: 'Uitzonderen…' })).toBeInTheDocument()
  })

  it('422 op uitzonderen blijft in de dialoog zichtbaar', async () => {
    installLerenMock([], { uitzonderStatus: 422 })
    const gebruiker = userEvent.setup()
    render(<LeverancierAutoboeken administraties={[]} vasteAdministratieId={ADMINISTRATIE_ID} administratieLerenAan />)
    await waitFor(() => expect(screen.getByText('Bouwmaat Nederland B.V.')).toBeInTheDocument())
    await gebruiker.click(within(screen.getByTestId(`leverancier-rij-${VENDOR_ID}`)).getByRole('button', { name: 'Uitzonderen…' }))
    const dialoog = await screen.findByTestId('uitzonder-dialoog')
    await gebruiker.type(within(dialoog).getByLabelText('Reden'), 'x')
    await gebruiker.click(within(dialoog).getByRole('button', { name: 'Uitzonderen' }))
    expect(await within(dialoog).findByText('Reden is verplicht.')).toBeInTheDocument()
  })

  it('schakelaar UIT (oude flow): switches blijven, geen Uitzonderen/Vrijgeven; standVan leidt de stand af zonder server-veld', async () => {
    installLerenMock([])
    render(<LeverancierAutoboeken administraties={[]} vasteAdministratieId={ADMINISTRATIE_ID} />)
    await waitFor(() => expect(screen.getByText('Bouwmaat Nederland B.V.')).toBeInTheDocument())
    expect(screen.getByTestId('leverancier-autoboeken')).toHaveAttribute('data-modus', 'opt-in')
    expect(screen.getAllByRole('checkbox').length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: 'Uitzonderen…' })).not.toBeInTheDocument()
    expect(standVan({ vendor_id: 'v', naam: null, autoboeken_ingeschakeld: true }, false)).toBe('handmatig_aan')
    expect(standVan({ vendor_id: 'v', naam: null, autoboeken_ingeschakeld: true }, true)).toBe('boekt_automatisch')
    expect(standVan({ vendor_id: 'v', naam: null, autoboeken_ingeschakeld: false }, true)).toBe('leert')
    expect(standVan({ vendor_id: 'v', naam: null, autoboeken_ingeschakeld: false, stand: 'uitgezonderd' }, true)).toBe('uitgezonderd')
  })
})
