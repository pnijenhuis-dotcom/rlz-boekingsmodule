// Klant-accordering, kantoorbreed (Peter 18-09 live meegekeken): zoekveld + teller, filterchips uit het overzicht,
// samenvatting per regel zónder openklappen, deeplink ?administratie= klapt de juiste regel open, en de melding "Geen
// klant-accordeurs" draagt twee acties (uitnodigen → Gebruikers & toegang voorgevuld; bestaande accordeur koppelen via de
// bestaande scope-route).
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AccorderingInstellingen, administratieMatcht, samenvattingTekst } from './AccorderingInstellingen'

vi.mock('../auth/AuthContext', () => ({
  useAuthOptioneel: () => ({ rol: 'beheerder' }),
}))

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const ADMINS = [
  { id: 'a-blow', naam: 'BLOW B.V.' },
  { id: 'a-bouw', naam: 'Bouwadvies Oost Nederland B.V.' },
  { id: 'a-uni', naam: 'Universal Steigerbouw Nederland B.V.' },
]

function installMock(state: { scopePosts: string[] }) {
  vi.stubGlobal(
    'fetch',
    vi.fn((invoer: RequestInfo | URL, init?: RequestInit) => {
      const pad = String(invoer).split('?')[0]
      if (pad === '/accordering/overzicht')
        return Promise.resolve(
          jsonResponse({
            administraties: [
              { administratie_id: 'a-blow', naam: 'BLOW B.V.', ingeschakeld: true, lagen: 1, leverancier_routes: 0, accordeurs: 0 },
              { administratie_id: 'a-bouw', naam: 'Bouwadvies Oost Nederland B.V.', ingeschakeld: true, lagen: 3, leverancier_routes: 1, accordeurs: 4 },
              { administratie_id: 'a-uni', naam: 'Universal Steigerbouw Nederland B.V.', ingeschakeld: false, lagen: 0, leverancier_routes: 0, accordeurs: 2 },
            ],
          }),
        )
      if (pad.endsWith('/accordering/instellingen')) return Promise.resolve(jsonResponse({ ingeschakeld: true, lagen: [] }))
      if (pad.endsWith('/accordering/kandidaten')) return Promise.resolve(jsonResponse({ kandidaten: [] }))
      if (pad.endsWith('/accordering/staande-regels')) return Promise.resolve(jsonResponse({ regels: [], uitzonderingen: [] }))
      if (pad.endsWith('/accordering/leverancier-routes')) return Promise.resolve(jsonResponse({ routes: [] }))
      if (pad.endsWith('/crediteuren')) return Promise.resolve(jsonResponse({ crediteuren: [] }))
      if (pad === '/accordering/accordeur-kandidaten')
        return Promise.resolve(jsonResponse({ kandidaten: [{ id: 'g-sophia', naam: 'Sophia' }, { id: 'g-dir', naam: 'D. Directeur' }] }))
      if (pad.startsWith('/auth/gebruikers/') && pad.endsWith('/scope') && init?.method === 'POST') {
        state.scopePosts.push(`${pad} ${String(init.body)}`)
        return Promise.resolve(new Response(null, { status: 204 }))
      }
      return Promise.resolve(jsonResponse({ detail: `onbekend pad ${pad}` }, 404))
    }),
  )
}

function LocatieSpion() {
  const loc = useLocation()
  return <div data-testid="locatie">{loc.pathname + loc.search}</div>
}

function renderMet(pad = '/instellingen/accordering') {
  return render(
    <MemoryRouter initialEntries={[pad]}>
      <Routes>
        <Route
          path="/instellingen/accordering"
          element={
            <>
              <AccorderingInstellingen administraties={ADMINS} />
              <LocatieSpion />
            </>
          }
        />
        <Route path="/gebruikers" element={<LocatieSpion />} />
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('AccorderingInstellingen — zoekveld, filters, samenvatting, deeplink (Peter 18-09)', () => {
  it('pure helpers: zoekmatch diakriet-loos en samenvattingstekst', () => {
    expect(administratieMatcht('Bouwadvies Oost Nederland B.V.', 'bouw oost')).toBe(true)
    expect(administratieMatcht('Bouwadvies Oost Nederland B.V.', 'blow')).toBe(false)
    expect(administratieMatcht('Café Zé', 'cafe ze')).toBe(true)
    expect(samenvattingTekst({ administratie_id: 'x', naam: 'x', ingeschakeld: true, lagen: 2, leverancier_routes: 1, accordeurs: 3 })).toBe(
      'aan · 2 lagen · 1 route · 3 accordeurs',
    )
    expect(samenvattingTekst({ administratie_id: 'x', naam: 'x', ingeschakeld: false, lagen: 0, leverancier_routes: 0, accordeurs: 0 })).toBe(
      'uit · geen accordeur',
    )
  })

  it('zoekt op naam mét teller, zet de term in ?zoek= en filtert op de chips uit het overzicht', async () => {
    installMock({ scopePosts: [] })
    renderMet()
    expect(await screen.findByText('Accordering aan (2)')).toBeInTheDocument()
    expect(screen.getByText('Met leveranciersroute (1)')).toBeInTheDocument()
    expect(screen.getByText('Zonder accordeur (1)')).toBeInTheDocument()
    // Samenvatting per regel zonder openklappen.
    const samenvattingen = screen.getAllByTestId('accordering-samenvatting').map((el) => el.textContent)
    expect(samenvattingen[1]).toContain('aan · 3 lagen · 1 route · 4 accordeurs')
    expect(samenvattingen[0]).toContain('geen accordeur')
    expect(samenvattingen[0]).toContain('actie nodig')

    await userEvent.type(screen.getByTestId('accordering-zoekveld'), 'blow')
    expect(screen.getByTestId('accordering-zoek-teller')).toHaveTextContent('1 van 3')
    expect(screen.getAllByTestId('accordering-administratie')).toHaveLength(1)
    expect(screen.getByTestId('locatie')).toHaveTextContent('?zoek=blow')

    await userEvent.clear(screen.getByTestId('accordering-zoekveld'))
    await userEvent.click(screen.getByRole('tab', { name: /Zonder accordeur/ }))
    expect(screen.getAllByTestId('accordering-administratie')).toHaveLength(1)
    expect(screen.getByText('BLOW B.V.')).toBeInTheDocument()
    expect(screen.getByTestId('locatie')).toHaveTextContent('filter=zonder')

    await userEvent.type(screen.getByTestId('accordering-zoekveld'), 'zzz')
    expect(screen.getByTestId('accordering-zoek-leeg')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'wis zoekveld en filter' }))
    expect(screen.getAllByTestId('accordering-administratie')).toHaveLength(3)
  })

  it('deeplink ?administratie= klapt die regel open en laadt haar direct', async () => {
    installMock({ scopePosts: [] })
    renderMet('/instellingen/accordering?administratie=a-bouw')
    const regels = await screen.findAllByTestId('accordering-administratie')
    const bouw = regels.find((r) => r.getAttribute('data-administratie') === 'a-bouw') as HTMLDetailsElement
    expect(bouw.open).toBe(true)
    expect(regels.filter((r) => (r as HTMLDetailsElement).open)).toHaveLength(1)
    expect(await within(bouw).findByText('Leveranciersroutes')).toBeInTheDocument()
  })

  it('"Geen klant-accordeurs" draagt uitnodigen (→ Gebruikers & toegang voorgevuld) en koppelen (bestaande scope-route)', async () => {
    const state = { scopePosts: [] as string[] }
    installMock(state)
    renderMet('/instellingen/accordering?administratie=a-blow')
    const melding = await screen.findByTestId('geen-accordeurs-melding')
    const uitnodigen = within(melding).getByTestId('accordeur-uitnodigen')
    expect(uitnodigen).toHaveAttribute('href', '/gebruikers?groep=accordeurs&uitnodig=accordeur&administratie=a-blow')

    await userEvent.click(within(melding).getByTestId('accordeur-koppelen'))
    const dialoog = await screen.findByTestId('koppel-accordeur-dialoog')
    await userEvent.click(await within(dialoog).findByLabelText('Toegang voor Sophia'))
    await waitFor(() => expect(state.scopePosts).toHaveLength(1))
    expect(state.scopePosts[0]).toContain('/auth/gebruikers/g-sophia/scope')
    expect(state.scopePosts[0]).toContain('"administratie_id":"a-blow"')
    expect(await within(dialoog).findByText('al gekoppeld')).toBeInTheDocument()

    await userEvent.click(within(dialoog).getByRole('button', { name: 'Sluiten' }))
    await userEvent.click(uitnodigen)
    expect(screen.getByTestId('locatie')).toHaveTextContent('/gebruikers?groep=accordeurs&uitnodig=accordeur&administratie=a-blow')
  })
})
