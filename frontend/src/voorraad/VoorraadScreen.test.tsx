import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../auth/AuthContext'
import { VoorraadScreen } from './VoorraadScreen'
import { aantal, signaalTekst, type GroepAansluitingDto } from './voorraadApi'

// Mockup voorraad-aansluiting.html §1 (blok D 28-08): tabel per artikelgroep met bron per kolom,
// signaal op tolerantie, prominente "Niet genormaliseerd"-teller, telling-invoer; opt-in uit = leesbare
// melding. Cijfers komen uit de backend — de client formatteert alleen.

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const ADMIN = 'aaaaaaaa-0000-0000-0000-000000000001'

function groep(over: Partial<GroepAansluitingDto>): GroepAansluitingDto {
  return {
    artikelgroep_id: 'g1',
    naam: 'Koppelingen 48mm',
    eenheid: 'st',
    tolerantie_pct: '1.00',
    begin: '1240.000',
    inkoop: '3600.000',
    verkoop: '3410.000',
    theoretisch: '1430.000',
    systeemstand: '1428.000',
    telling_datum: '2026-08-28',
    verschil: '-2.000',
    verschil_pct: '-0.14',
    signaal: 'binnen_tolerantie',
    onzeker_pct: '0.00',
    regels_in: 4,
    regels_uit: 9,
    ...over,
  }
}

const AANSLUITING = {
  administratie_id: ADMIN,
  van: '2026-01-01',
  tot: '2026-08-28',
  groepen: [
    groep({}),
    groep({ artikelgroep_id: 'g2', naam: 'Steigerbuis 3m', begin: '820', inkoop: '1200', verkoop: '1020', theoretisch: '1000', systeemstand: '912', verschil: '-88', verschil_pct: '-8.80', signaal: 'onderzoeken', onzeker_pct: '35.00' }),
    groep({ artikelgroep_id: 'g3', naam: 'Vlonders alu 2,5m', systeemstand: null, telling_datum: null, verschil: null, verschil_pct: null, signaal: 'geen_telling' }),
  ],
  niet_genormaliseerd_in: 212,
  niet_genormaliseerd_uit: 37,
  onzeker_totaal: 3,
  regels_totaal: 400,
  bronnen: {
    inkoop: 'inkoopfacturen (AI-gescand, extern document)',
    verkoop: 'verkoopfactuurregels (interne registratie)',
    systeemstand: 'handmatige telling per datum',
  },
}

function stubFetch(opties: { uit?: boolean } = {}) {
  const aangeroepen: { pad: string; method: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      const pad = url.split('?')[0]
      aangeroepen.push({ pad: url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined })
      if (url === '/auth/token/vernieuwen') return Promise.resolve(new Response(null, { status: 401 }))
      if (url === '/auth/administraties') return Promise.resolve(jsonResponse({ administraties: [{ id: ADMIN, naam: 'Universal Verkoop B.V.' }] }))
      if (pad === `/administraties/${ADMIN}/voorraad/aansluiting`) {
        if (opties.uit) return Promise.resolve(jsonResponse({ detail: 'Voorraad bijhouden staat uit voor deze administratie' }, 409))
        return Promise.resolve(jsonResponse(AANSLUITING))
      }
      if (pad === `/administraties/${ADMIN}/voorraad/groepen`) {
        if (opties.uit) return Promise.resolve(jsonResponse([]))
        return Promise.resolve(jsonResponse(AANSLUITING.groepen.map((g) => ({ id: g.artikelgroep_id, naam: g.naam, eenheid: 'st', tolerantie_pct: '1.00', actief: true }))))
      }
      if (pad === `/administraties/${ADMIN}/voorraad/tellingen`) return Promise.resolve(new Response(null, { status: 204 }))
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
  return aangeroepen
}

function renderScherm() {
  return render(
    <MemoryRouter initialEntries={[`/voorraad?administratie=${ADMIN}`]}>
      <AuthProvider>
        <VoorraadScreen />
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('VoorraadScreen', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('toont per artikelgroep Begin/Inkoop/Verkoop/Theoretisch/Systeemstand/Verschil + signaal, en de prominente niet-genormaliseerd-rij', async () => {
    stubFetch()
    renderScherm()
    const tabel = await screen.findByTestId('aansluiting-tabel')
    const rijen = within(tabel).getAllByRole('row')
    const koppelingen = rijen.find((r) => within(r).queryByText('Koppelingen 48mm'))!
    expect(koppelingen).toHaveTextContent('1.240')
    expect(koppelingen).toHaveTextContent('3.600')
    expect(koppelingen).toHaveTextContent('3.410')
    expect(koppelingen).toHaveTextContent('1.430')
    expect(koppelingen).toHaveTextContent('1.428')
    expect(koppelingen).toHaveTextContent('-2')
    expect(koppelingen).toHaveTextContent('✓ binnen tolerantie')
    const buis = rijen.find((r) => within(r).queryByText('Steigerbuis 3m'))!
    expect(buis).toHaveTextContent('⚑ -8,8% — onderzoeken')
    expect(buis).toHaveTextContent('35% van de regels is onzeker genormaliseerd')
    const vlonders = rijen.find((r) => within(r).queryByText('Vlonders alu 2,5m'))!
    expect(vlonders).toHaveTextContent('nog geen telling')
    const niet = screen.getByTestId('niet-genormaliseerd-rij')
    expect(niet).toHaveTextContent('212 regels')
    expect(niet).toHaveTextContent('37 regels')
    expect(within(niet).getByRole('button', { name: /normaliseren \(249 \+ 3 onzeker\)/ })).toBeInTheDocument()
    // Bron per kolom zichtbaar (mockup-beslispunt 2).
    expect(screen.getByText(/inkoop = inkoopfacturen \(AI-gescand, extern document\)/)).toBeInTheDocument()
  })

  it('opt-in uit (409) → leesbare melding met de weg naar Instellingen, geen lege tabel', async () => {
    stubFetch({ uit: true })
    renderScherm()
    expect(await screen.findByTestId('voorraad-uit')).toHaveTextContent('Voorraad bijhouden staat uit')
    expect(screen.queryByTestId('aansluiting-tabel')).toBeNull()
  })

  it('Telling… → invoer per groep, opslaan = POST /voorraad/tellingen (systeemstand fase 1)', async () => {
    const aangeroepen = stubFetch()
    renderScherm()
    await screen.findByTestId('aansluiting-tabel')
    const gebruiker = userEvent.setup()
    await gebruiker.click(screen.getAllByRole('button', { name: 'Telling…' })[0])
    const paneel = screen.getByTestId('telling-invoer')
    expect(paneel).toHaveTextContent('Telling — Koppelingen 48mm')
    await gebruiker.type(within(paneel).getByLabelText('Telling aantal'), '1430')
    await gebruiker.click(within(paneel).getByRole('button', { name: 'Telling opslaan' }))
    await waitFor(() => expect(aangeroepen.some((a) => a.method === 'POST' && a.pad.endsWith('/voorraad/tellingen'))).toBe(true))
    const post = aangeroepen.find((a) => a.method === 'POST' && a.pad.endsWith('/voorraad/tellingen'))!
    expect(post.body).toMatchObject({ artikelgroep_id: 'g1', aantal: '1430' })
    expect(await screen.findByText(/Telling voor Koppelingen 48mm/)).toBeInTheDocument()
  })
})

describe('voorraadApi — weergave', () => {
  it('signaalTekst en aantal formatteren NL, nooit rekenen', () => {
    expect(signaalTekst(groep({}))).toEqual({ tekst: 'binnen tolerantie', soort: 'ok' })
    expect(signaalTekst(groep({ signaal: 'onderzoeken', verschil_pct: '1.70' }))).toEqual({ tekst: '+1,7% — onderzoeken', soort: 'vlag' })
    expect(signaalTekst(groep({ signaal: 'geen_telling', systeemstand: null }))).toEqual({ tekst: 'nog geen telling', soort: 'geen' })
    expect(aantal('1240.000')).toBe('1.240')
    expect(aantal(null)).toBe('—')
    expect(aantal('2.5000', 2)).toBe('2,5')
  })
})
