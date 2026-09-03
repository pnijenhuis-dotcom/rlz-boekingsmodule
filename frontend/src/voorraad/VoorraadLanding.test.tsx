import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../auth/AuthContext'
import { VoorraadScreen } from './VoorraadScreen'
import { detailPad, verschilTekst, type VoorraadVerschilRijDto, type VoorraadVerschillenLijstDto } from './voorraadApi'

// Inzicht › Voorraad kantoorbreed (design-ronde 03-09 blok B3, mockup inzicht-kantoorbreed.html ⑤): `/voorraad`
// opent de lijst van artikelgroepen buiten tolerantie over alle voorraad-administraties (zwaarste eerst), met
// chip, facet Administratie (leeg = alle), zoekveld, "Bekijk regels →" naar het bestaande detail mét
// voorgefilterde groep/periode, en de voet "‹ 1 van n › · N groepen over M administraties".

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const A = 'aaaaaaaa-0000-0000-0000-000000000001'
const B = 'bbbbbbbb-0000-0000-0000-000000000002'

function rij(over: Partial<VoorraadVerschilRijDto>): VoorraadVerschilRijDto {
  return {
    administratie_id: A,
    administratie_naam: 'Universal Verkoop B.V.',
    artikelgroep_id: 'g1',
    naam: 'Koppelingen 48mm',
    eenheid: 'st',
    tolerantie_pct: '1.00',
    theoretisch: '1000.000',
    systeemstand: '912.000',
    telling_datum: '2026-08-28',
    verschil: '-88.000',
    verschil_pct: '-8.80',
    zwaarte: 'rood',
    tot: '2026-09-03',
    ...over,
  }
}

const RIJEN: VoorraadVerschilRijDto[] = [
  rij({ administratie_id: B, administratie_naam: 'BWC Steigers B.V.', artikelgroep_id: 'g9', naam: 'Liften', verschil: '60.000', verschil_pct: '30.00' }),
  rij({}),
  rij({ artikelgroep_id: 'g2', naam: 'Steigerbuis 3m', systeemstand: '985.000', verschil: '-15.000', verschil_pct: '-1.50', zwaarte: 'oranje' }),
]

function lijst(rijen: VoorraadVerschilRijDto[], over: Partial<VoorraadVerschillenLijstDto> = {}): VoorraadVerschillenLijstDto {
  return {
    rijen,
    totaal: rijen.length,
    pagina: 1,
    per_pagina: 25,
    tellers: { groepen: 3, administraties: 2, administraties_met_voorraad: 2 },
    facetten: [
      { id: A, naam: 'Universal Verkoop B.V.', aantal: 2 },
      { id: B, naam: 'BWC Steigers B.V.', aantal: 1 },
    ],
    van: '2026-01-01',
    tot: '2026-09-03',
    ...over,
  }
}

function stubFetch(opties: { leeg?: boolean; geenOptIn?: boolean } = {}) {
  const aangeroepen: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      aangeroepen.push(url)
      const u = new URL(url, 'http://x')
      if (url === '/auth/token/vernieuwen') return Promise.resolve(new Response(null, { status: 401 }))
      if (url === '/auth/administraties') return Promise.resolve(jsonResponse({ administraties: [{ id: A, naam: 'Universal Verkoop B.V.' }] }))
      if (u.pathname === '/voorraad/verschillen') {
        if (opties.geenOptIn) {
          return Promise.resolve(jsonResponse(lijst([], { tellers: { groepen: 0, administraties: 0, administraties_met_voorraad: 0 }, facetten: [] })))
        }
        if (opties.leeg) return Promise.resolve(jsonResponse(lijst([], { tellers: { groepen: 0, administraties: 0, administraties_met_voorraad: 2 } })))
        const facet = u.searchParams.get('administratie_id')
        const q = (u.searchParams.get('q') ?? '').toLowerCase()
        let sel = RIJEN
        if (facet) sel = sel.filter((r) => r.administratie_id === facet)
        if (q) sel = sel.filter((r) => r.naam.toLowerCase().includes(q))
        return Promise.resolve(jsonResponse(lijst(sel)))
      }
      // Detail per administratie (bestaande routes), minimaal gemockt voor de doorklik.
      if (u.pathname === `/administraties/${A}/voorraad/aansluiting`) {
        return Promise.resolve(
          jsonResponse({
            administratie_id: A,
            van: '2026-01-01',
            tot: '2026-09-03',
            groepen: [
              {
                artikelgroep_id: 'g2',
                naam: 'Steigerbuis 3m',
                eenheid: 'st',
                tolerantie_pct: '1.00',
                begin: '0',
                inkoop: '1200',
                verkoop: '200',
                theoretisch: '1000',
                systeemstand: '985',
                telling_datum: '2026-08-28',
                verschil: '-15',
                verschil_pct: '-1.50',
                signaal: 'onderzoeken',
                onzeker_pct: '0',
                regels_in: 1,
                regels_uit: 1,
              },
            ],
            niet_genormaliseerd_in: 0,
            niet_genormaliseerd_uit: 0,
            onzeker_totaal: 0,
            regels_totaal: 2,
            dienst_regels: 0,
            transport_regels: 0,
            bronnen: { inkoop: 'i', verkoop: 'v', systeemstand: 's' },
          }),
        )
      }
      if (u.pathname === `/administraties/${A}/voorraad/groepen`) return Promise.resolve(jsonResponse([]))
      if (u.pathname === `/administraties/${A}/voorraad/regels`) return Promise.resolve(jsonResponse({ rijen: [], totaal: 0, pagina: 1, per_pagina: 25 }))
      if (u.pathname.endsWith('/dagstanden')) return Promise.resolve(jsonResponse([]))
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
  return aangeroepen
}

function renderOp(pad: string) {
  return render(
    <MemoryRouter initialEntries={[pad]}>
      <AuthProvider>
        <Routes>
          <Route path="/voorraad" element={<VoorraadScreen />} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('VoorraadLanding — kantoorbreed (B3.2)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('rendert de lijst zwaarste eerst mét chip, zwaarte-kleur, administratie en voet', async () => {
    stubFetch()
    renderOp('/voorraad')
    const tabel = await screen.findByTestId('verschillen-tabel')
    expect(screen.getByTestId('chip-buiten-tolerantie')).toHaveTextContent('3 buiten tolerantie')
    const rijen = within(tabel).getAllByRole('row').slice(1)
    expect(rijen[0]).toHaveTextContent('Liften')
    expect(rijen[0]).toHaveTextContent('BWC Steigers B.V.')
    expect(rijen[0]).toHaveTextContent('+60 st (+30%)')
    expect(rijen[1]).toHaveTextContent('Koppelingen 48mm')
    expect(rijen[1]).toHaveTextContent('-88 st (-8,8%)')
    expect(rijen[1]).toHaveTextContent('theoretisch 1.000 · telling 912 st')
    expect(rijen[2]).toHaveTextContent('-15 st (-1,5%)')
    // STATUS-kleur naar zwaarte (server bepaalt): rood = danger-badge, oranje = warn-badge.
    expect(within(rijen[1]).getByText(/-8,8%/).className).toMatch(/text-danger/)
    expect(within(rijen[2]).getByText(/-1,5%/).className).toMatch(/text-warn/)
    expect(screen.getByTestId('verschillen-voet')).toHaveTextContent('‹ 1 van 1 › · 3 groepen over 2 administraties')
    // Eén primaire knop per rij.
    expect(within(rijen[0]).getAllByRole('button')).toHaveLength(1)
  })

  it('"Bekijk regels →" opent het bestaande detail per administratie mét voorgefilterde groep en periode', async () => {
    const aangeroepen = stubFetch()
    renderOp('/voorraad')
    const tabel = await screen.findByTestId('verschillen-tabel')
    const buis = within(tabel).getAllByRole('row').slice(1)[2]
    await userEvent.click(within(buis).getByRole('button', { name: 'Bekijk regels →' }))
    const detail = await screen.findByTestId('groep-detail')
    expect(detail).toHaveTextContent('Steigerbuis 3m — factuurregels 2026-01-01 t/m 2026-09-03')
    const regels = aangeroepen.find((u) => u.includes('/voorraad/regels'))!
    expect(regels).toContain('artikelgroep_id=g2')
    expect(regels).toContain('van=2026-01-01')
    expect(regels).toContain('tot=2026-09-03')
  })

  it('facet in de URL (klik vanaf de werkvoorraad-teller) filtert op administratie; "alle administraties" heft het op', async () => {
    const aangeroepen = stubFetch()
    renderOp(`/voorraad?administratie_id=${A}`)
    const tabel = await screen.findByTestId('verschillen-tabel')
    expect(within(tabel).getAllByRole('row').slice(1)).toHaveLength(2)
    expect(screen.queryByText('Liften')).toBeNull()
    expect(aangeroepen.some((u) => u.includes(`administratie_id=${A}`))).toBe(true)
    // Tellers blijven kantoorbreed; de voet meldt het filter.
    expect(screen.getByTestId('verschillen-voet')).toHaveTextContent('3 groepen over 2 administraties · 2 binnen dit filter')
    await userEvent.click(screen.getByRole('button', { name: 'alle administraties' }))
    await waitFor(() => expect(screen.getByText('Liften')).toBeInTheDocument())
  })

  it('zoekveld filtert op artikelgroep via q=', async () => {
    const aangeroepen = stubFetch()
    renderOp('/voorraad')
    await screen.findByTestId('verschillen-tabel')
    await userEvent.type(screen.getByLabelText('Zoek artikelgroep'), 'buis')
    await waitFor(() => expect(screen.queryByText('Liften')).toBeNull())
    expect(screen.getByText('Steigerbuis 3m')).toBeInTheDocument()
    expect(aangeroepen.some((u) => u.includes('q=buis'))).toBe(true)
  })

  it('lege standen: alles binnen tolerantie = groene status-chip; geen opt-in = weg naar Instellingen (lege stand = actie)', async () => {
    stubFetch({ leeg: true })
    renderOp('/voorraad')
    expect(await screen.findByTestId('voorraad-leeg')).toHaveTextContent('Geen artikelgroepen buiten tolerantie')
    expect(screen.getByText('✓ alles binnen tolerantie')).toBeInTheDocument()
    vi.unstubAllGlobals()
    stubFetch({ geenOptIn: true })
    renderOp('/voorraad')
    const leeg = await screen.findByTestId('voorraad-geen-optin')
    expect(within(leeg).getByRole('link', { name: 'Instellingen › Administraties' })).toHaveAttribute('href', '/instellingen/administraties')
  })
})

describe('voorraadApi — kantoorbrede weergave', () => {
  it('verschilTekst en detailPad', () => {
    expect(verschilTekst(rij({}))).toBe('-88 st (-8,8%)')
    expect(verschilTekst(rij({ verschil: '12.000', verschil_pct: '2.40' }))).toBe('+12 st (+2,4%)')
    expect(verschilTekst(rij({ verschil: '3.000', verschil_pct: null }))).toBe('+3 st (theoretisch 0)')
    expect(detailPad(rij({}), '2026-01-01', '2026-09-03')).toBe(`/voorraad?administratie=${A}&groep=g1&van=2026-01-01&tot=2026-09-03`)
  })
})
