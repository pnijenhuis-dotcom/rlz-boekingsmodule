// Werkvoorraad-kant van de offerte-match (blok B 04-09, ⑤ — duplicaat-patroon): de conditionele
// klantenlijst-kolom "Buiten offerte", het filter + de rij-chip op de documentenlijst en de eigen
// tab "Verplichtingen (offertes)". Alles signaal, nooit een blokkade.

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Klantenlijst } from './Klantenlijst'
import { KlantUpload } from './KlantStanden'
import { WerkvoorraadScreen } from './WerkvoorraadScreen'
import type { KlantRij } from './useWerkvoorraadData'

const ADMIN = 'aaaaaaaa-0000-0000-0000-000000000001'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function klant(overrides: Partial<KlantRij> = {}): KlantRij {
  return {
    administratie_id: ADMIN,
    naam: 'Kempen Facilities B.V.',
    te_controleren: 2,
    klaar_om_te_boeken: 0,
    vragen: 0,
    afgewezen: 0,
    bij_klant: 0,
    iban_wachtend: 0,
    bank_open: 0,
    spiegel_taken: 0,
    ...overrides,
  }
}

function doc(overrides: Record<string, unknown>) {
  return {
    id: 'bbbbbbbb-0000-0000-0000-000000000002',
    bestandsnaam: 'factuur.pdf',
    soort: 'inkoopfactuur',
    status: 'te_controleren',
    bron: 'upload',
    mogelijk_duplicaat_van: null,
    toegewezen_aan: null,
    aangemaakt_op: '2026-09-04T10:00:00Z',
    laatst_gewijzigd_op: '2026-09-04T10:00:00Z',
    automatisch_geboekt: false,
    ...overrides,
  }
}

function installFetch(documenten: unknown[]) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/auth/administraties')) {
        return Promise.resolve(jsonResponse({ administraties: [{ id: ADMIN, naam: 'Kempen Facilities B.V.' }] }))
      }
      if (url.includes('/documenten') && (!init || init.method === undefined)) {
        return Promise.resolve(jsonResponse({ documenten }))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Klantenlijst — kolom "Buiten offerte" (toon-regel: alleen bij data)', () => {
  function toon(klanten: KlantRij[]) {
    return render(
      <MemoryRouter>
        <Klantenlijst klanten={klanten} fout={null} onHerlaad={() => {}} totaalAdministraties={klanten.length} />
      </MemoryRouter>,
    )
  }

  it('geen kolom zolang geen enkele klant een buiten-offerte-signaal heeft', () => {
    toon([klant()])
    expect(screen.queryByText('Buiten offerte')).not.toBeInTheDocument()
  })

  it('kolom mét teller-chip zodra er ergens een signaal staat', () => {
    toon([klant({ buiten_offerte: 3 })])
    expect(screen.getByText('Buiten offerte')).toBeInTheDocument()
    const cel = screen.getByTitle(/buiten de goedgekeurde offerte/i)
    expect(within(cel).getByText('3')).toBeInTheDocument()
    expect(within(cel).getByText('3').className).toContain('afwijking')
  })
})

describe('Documentenlijst — filter + rij-chip offerte-match', () => {
  function renderLijst() {
    return render(
      <MemoryRouter initialEntries={[`/?administratie=${ADMIN}&sectie=documenten`]}>
        <WerkvoorraadScreen />
      </MemoryRouter>,
    )
  }

  it('rij-chip "buiten offerte − € X over" bij een overschrijding; "binnen offerte" bij een treffer', async () => {
    installFetch([
      doc({
        id: 'd-buiten',
        bestandsnaam: 'buiten.pdf',
        verplichting_match: { uitkomst: 'buiten', overschrijding_excl: '3400.00', offertenummer: '26140-OFF-01' },
      }),
      doc({
        id: 'd-binnen',
        bestandsnaam: 'binnen.pdf',
        verplichting_match: { uitkomst: 'binnen', overschrijding_excl: null, offertenummer: '26140-OFF-01' },
      }),
    ])
    renderLijst()

    await waitFor(() => expect(screen.getByText('buiten.pdf')).toBeInTheDocument())
    expect(screen.getByTestId('chip-buiten-offerte')).toHaveTextContent('buiten offerte − € 3.400,00 over')
    expect(screen.getByTestId('chip-binnen-offerte')).toHaveTextContent('binnen offerte')
  })

  it('filterknop "Buiten offerte (N)" verschijnt alleen bij signalen en filtert de lijst', async () => {
    installFetch([
      doc({
        id: 'd-buiten',
        bestandsnaam: 'buiten.pdf',
        verplichting_match: { uitkomst: 'buiten', overschrijding_excl: '3400.00', offertenummer: 'OFF-1' },
      }),
      doc({ id: 'd-schoon', bestandsnaam: 'schoon.pdf' }),
    ])
    renderLijst()

    await waitFor(() => expect(screen.getByText('buiten.pdf')).toBeInTheDocument())
    const knop = screen.getByRole('button', { name: 'Buiten offerte (1)' })
    await userEvent.click(knop)

    await waitFor(() => expect(screen.queryByText('schoon.pdf')).not.toBeInTheDocument())
    expect(screen.getByText('buiten.pdf')).toBeInTheDocument()
  })

  it('geen filterknop zonder signalen (nooit een lege kolom/knop tonen)', async () => {
    installFetch([doc({ id: 'd-schoon', bestandsnaam: 'schoon.pdf' })])
    renderLijst()

    await waitFor(() => expect(screen.getByText('schoon.pdf')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /Buiten offerte/ })).not.toBeInTheDocument()
  })

  it('verplichtingen krijgen een eigen tab en het statuslabel "Klaar voor accordering"', async () => {
    installFetch([
      doc({
        id: 'v-1',
        bestandsnaam: 'confide-offerte.pdf',
        soort: 'verplichting',
        status: 'klaar_om_te_boeken',
        leverancier: 'Confide Bouw B.V.',
      }),
    ])
    renderLijst()

    expect(await screen.findByRole('tab', { name: 'Verplichtingen (offertes) (1)' })).toBeInTheDocument()
    expect(screen.getByText('Klaar voor accordering')).toBeInTheDocument()
    expect(screen.queryByText('Klaar om te boeken')).not.toBeInTheDocument()
  })
})

describe('Klant-upload — documentsoort verplichting', () => {
  it('de soort-select biedt naast factuur en kassarapport ook een verplichting', async () => {
    installFetch([])
    render(
      <MemoryRouter>
        <KlantUpload administratieId={ADMIN} onGeupload={() => {}} />
      </MemoryRouter>,
    )

    const select = screen.getByLabelText('Documentsoort voor upload')
    const opties = within(select).getAllByRole('option').map((o) => (o as HTMLOptionElement).value)
    expect(opties).toEqual(['inkoopfactuur', 'kassarapport', 'verplichting'])
    await userEvent.selectOptions(select, 'verplichting')
    expect(select).toHaveValue('verplichting')
  })
})
