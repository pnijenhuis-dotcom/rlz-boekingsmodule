import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { LeverancierAutoboeken } from './LeverancierAutoboeken'

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
