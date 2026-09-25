import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { WerkvoorraadScreen } from './WerkvoorraadScreen'

/** Feedbackrun A blok 8 (FV-20, Peter 25-09): "Alle" toonde niet alles. Nu: "Open (N)" = kantoorwerk (ongewijzigde
 * semantiek), "Alles (N)" = server-side `groep=alles` (kantoor ∪ wachten op anderen ∪ afgehandeld, 200 per pagina, élke
 * rij mét statuschip), en een zoekterm schakelt de lijst óók op alles (`groep=alles&q=`) — de Exact-factuur op "wachten
 * op anderen" is dan vindbaar. */

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function document(overrides: Record<string, unknown>) {
  return {
    id: 'bbbbbbbb-0000-0000-0000-000000000002',
    bestandsnaam: 'factuur.pdf',
    soort: 'inkoopfactuur',
    status: 'te_controleren',
    bron: 'upload',
    mogelijk_duplicaat_van: null,
    toegewezen_aan: null,
    aangemaakt_op: '2026-09-20T10:00:00Z',
    laatst_gewijzigd_op: '2026-09-20T10:00:00Z',
    automatisch_geboekt: false,
    ...overrides,
  }
}

const WERK = document({ id: 'bbbbbbbb-0000-0000-0000-000000000002', bestandsnaam: 'werk.pdf', leverancier: 'Bouwmaat' })
const EXACT = document({
  id: 'cccccccc-0000-0000-0000-000000000003',
  bestandsnaam: 'exact-abonnement.pdf',
  leverancier: 'Exact Online B.V.',
  status: 'ter_accordering',
  accordeur_aan_de_beurt: { gebruiker_id: 'dddddddd-0000-0000-0000-000000000009', naam: 'S. Bakker', laag: 2 },
})
const GEBOEKT = document({
  id: 'eeeeeeee-0000-0000-0000-000000000004',
  bestandsnaam: 'floor-26219.pdf',
  leverancier: 'Floor Bouwliftenservice',
  status: 'geboekt',
  geboekt_in_rlz: { systeem: 'rlz', boekstuknummer: 'RLZ-04-00003305', memoriaal_boekstuknummer: null, vindplaats_hint: null },
})

const GROEPEN = { kantoor: 1, wachten: 1, afgehandeld: 1, alles: 3 }
const AFGEHANDELD = { verwijderd: 0, afgewezen: 0, samengevoegd: 0, afgevoerd_duplicaat: 0, geboekt: 1, totaal: 1 }

/** Serverspiegel van `documenten_lijst`: zonder groep = kantoor + wachten; `groep=alles` = alles, gepagineerd, mét `q`. */
function installFetchMock(aanroepen: string[], opties: { totaal?: number; alles?: unknown[] } = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/auth/administraties')) {
        return Promise.resolve(jsonResponse({ administraties: [{ id: ADMINISTRATIE_ID, naam: 'Universal Steigerbouw' }] }))
      }
      if (url === '/vragen/stand') return Promise.resolve(jsonResponse({ open: 0, aan_mij: 0, blokkeert_boeken: 0, administraties: 0 }))
      if (url.includes('/documenten') && (!init || init.method === undefined)) {
        aanroepen.push(url)
        const params = new URLSearchParams(url.split('?')[1] ?? '')
        if (params.get('groep') === 'alles') {
          const q = (params.get('q') ?? '').toLowerCase()
          const alles = (opties.alles ?? [WERK, EXACT, GEBOEKT]) as { leverancier?: string; bestandsnaam: string }[]
          const treffers = q
            ? alles.filter((d) => `${d.leverancier ?? ''} ${d.bestandsnaam}`.toLowerCase().includes(q))
            : alles
          return Promise.resolve(
            jsonResponse({
              documenten: treffers,
              afgehandeld: AFGEHANDELD,
              groepen: GROEPEN,
              totaal: opties.totaal ?? treffers.length,
              limit: Number(params.get('limit') ?? 200),
              offset: Number(params.get('offset') ?? 0),
            }),
          )
        }
        return Promise.resolve(jsonResponse({ documenten: [WERK, EXACT], afgehandeld: AFGEHANDELD, groepen: GROEPEN }))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

function renderScherm(pad = `/?administratie=${ADMINISTRATIE_ID}&sectie=documenten`) {
  return render(
    <MemoryRouter initialEntries={[pad]}>
      <WerkvoorraadScreen />
    </MemoryRouter>,
  )
}

describe('Blok 8 (FV-20, 25-09) — "Open (N)" en de échte "Alles (N)"', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('het kantoorwerk-filter heet "Open (N)" en "Alles (N)" telt kantoor + wachten + afgehandeld uit de server-tellers', async () => {
    const aanroepen: string[] = []
    installFetchMock(aanroepen)
    renderScherm()

    await waitFor(() => expect(screen.getByText(/werk\.pdf/)).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Open (1)' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Alle \(/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Alles (3)' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Wachten op anderen (1)' })).toBeInTheDocument()
    // Nog niets server-side: alleen de standaardlijst is opgehaald.
    expect(aanroepen.every((u) => !u.includes('groep=alles'))).toBe(true)
  })

  it('"Alles" haalt server-side groep=alles op (limit 200) en toont wachten op anderen én geboekt mét statuschip', async () => {
    const gebruiker = userEvent.setup()
    const aanroepen: string[] = []
    installFetchMock(aanroepen)
    renderScherm()

    await waitFor(() => expect(screen.getByRole('button', { name: 'Alles (3)' })).toBeInTheDocument())
    await gebruiker.click(screen.getByRole('button', { name: 'Alles (3)' }))
    await waitFor(() => expect(screen.getByText(/floor-26219\.pdf/)).toBeInTheDocument())
    expect(aanroepen.some((u) => u.includes('groep=alles') && u.includes('limit=200') && !u.includes('q='))).toBe(true)
    expect(screen.getByText(/exact-abonnement\.pdf/)).toBeInTheDocument()
    // Statuschip op élke rij; de geboekte rij grijs (afgehandeld) mét boekstuk.
    const geboektRij = screen.getByText(/floor-26219\.pdf/).closest('tr') as HTMLElement
    expect(geboektRij).toHaveClass('afgehandeld')
    expect(within(geboektRij).getByText('Geboekt')).toBeInTheDocument()
    const exactRij = screen.getByText(/exact-abonnement\.pdf/).closest('tr') as HTMLElement
    expect(within(exactRij).getByText(/S\. Bakker/)).toBeInTheDocument()
    // De toggle "Toon afgehandelde documenten" is hier niet van toepassing (alles zit er al in).
    expect(screen.queryByLabelText(/Toon afgehandelde documenten/)).not.toBeInTheDocument()
    // Geen paginering bij ≤ 200 rijen.
    expect(screen.queryByTestId('alles-paginering')).not.toBeInTheDocument()
  })

  it('een zoekterm zoekt server-side over alles: de Exact-factuur op "wachten op anderen" is vindbaar; leeg = terug naar Open', async () => {
    const gebruiker = userEvent.setup()
    const aanroepen: string[] = []
    installFetchMock(aanroepen)
    renderScherm()

    await waitFor(() => expect(screen.getByText(/werk\.pdf/)).toBeInTheDocument())
    await gebruiker.type(screen.getByLabelText('Zoek in documenten'), 'exact')
    await waitFor(() => expect(aanroepen.some((u) => u.includes('groep=alles') && u.includes('q=exact'))).toBe(true))
    await waitFor(() => expect(screen.getByText(/exact-abonnement\.pdf/)).toBeInTheDocument())
    expect(screen.queryByText(/werk\.pdf/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Alles (1)' })).toHaveClass('actief')
    const exactRij = screen.getByText(/exact-abonnement\.pdf/).closest('tr') as HTMLElement
    expect(within(exactRij).getByText(/S\. Bakker/)).toBeInTheDocument()

    // Ook geboekt is via zoeken vindbaar.
    await gebruiker.clear(screen.getByLabelText('Zoek in documenten'))
    await gebruiker.type(screen.getByLabelText('Zoek in documenten'), 'floor')
    await waitFor(() => expect(screen.getByText(/floor-26219\.pdf/)).toBeInTheDocument())

    // Leeg zoekveld = terug naar de gekozen groep (Open): de standaardlijst zonder groep=alles.
    await gebruiker.clear(screen.getByLabelText('Zoek in documenten'))
    await waitFor(() => expect(screen.getByText(/werk\.pdf/)).toBeInTheDocument())
    expect(screen.queryByText(/floor-26219\.pdf/)).not.toBeInTheDocument()
    expect(aanroepen[aanroepen.length - 1]).not.toContain('groep=alles')
  })

  it('geen treffer = duidelijke melding "gezocht over alle statussen", nooit "nog geen documenten"', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock([])
    renderScherm()

    await waitFor(() => expect(screen.getByText(/werk\.pdf/)).toBeInTheDocument())
    await gebruiker.type(screen.getByLabelText('Zoek in documenten'), 'bestaat-niet-xyz')
    await waitFor(() => expect(screen.getByTestId('alles-zoek-leeg')).toBeInTheDocument())
    expect(screen.queryByText(/Nog geen documenten/)).not.toBeInTheDocument()
  })

  it('meer dan 200 rijen: pagina-navigatie mét "Rijen a–b van N" en "Volgende 200 →" (offset naar de server)', async () => {
    const gebruiker = userEvent.setup()
    const aanroepen: string[] = []
    installFetchMock(aanroepen, { totaal: 534 })
    renderScherm(`/?administratie=${ADMINISTRATIE_ID}&sectie=documenten&status=__alles`)

    await waitFor(() => expect(screen.getByTestId('alles-paginering')).toBeInTheDocument())
    expect(screen.getByTestId('alles-paginering')).toHaveTextContent('Rijen 1–200 van 534')
    expect(screen.getByRole('button', { name: '← Vorige 200' })).toBeDisabled()
    await gebruiker.click(screen.getByRole('button', { name: 'Volgende 200 →' }))
    await waitFor(() => expect(aanroepen.some((u) => u.includes('groep=alles') && u.includes('offset=200'))).toBe(true))
    await waitFor(() => expect(screen.getByTestId('alles-paginering')).toHaveTextContent('Rijen 201–400 van 534'))
    expect(screen.getByRole('button', { name: '← Vorige 200' })).toBeEnabled()
  })

  it('deeplink ?status=open = het bestaande "Open"-filter (synoniem van alle)', async () => {
    installFetchMock([])
    renderScherm(`/?administratie=${ADMINISTRATIE_ID}&sectie=documenten&status=open`)

    await waitFor(() => expect(screen.getByText(/werk\.pdf/)).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Open (1)' })).toHaveClass('actief')
  })
})
