import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../auth/AuthContext'
import { VoorraadScreen } from './VoorraadScreen'
import { aantal, bronLabel, signaalTekst, type GroepAansluitingDto, type VoorraadRegelDto } from './voorraadApi'

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

const REGEL_RLZ: VoorraadRegelDto = {
  id: 'r-rlz',
  document_id: null,
  rlz_document_id: '11111111-aaaa-4aaa-8aaa-000000000001',
  rlz_referentie: '50212273',
  richting: 'uit',
  bron: 'rlz_verkoop',
  datum: '2026-08-28',
  relatie_naam: 'Bouwbedr.Gebr. Kanters BV',
  artikeltekst: 'Steigerbuis 4 mtr incl. tube-connect (550100.210)',
  aantal: '610.000',
  eenheid: null,
  prijs: '20.1000',
  netto_bedrag: '12261.00',
  artikelgroep_id: 'g1',
  artikelgroep_naam: 'Koppelingen 48mm',
  normalisatie_status: 'onzeker',
  normalisatie_zekerheid: '0.610',
}
const REGEL_APP: VoorraadRegelDto = {
  ...REGEL_RLZ,
  id: 'r-app',
  document_id: 'doc-1',
  rlz_document_id: null,
  rlz_referentie: null,
  richting: 'in',
  bron: 'inkoop_veldvoorstel',
  relatie_naam: 'Scafom B.V.',
  artikeltekst: 'KOP.DR.48/48 SW22 gegalv.',
  normalisatie_status: 'niet_genormaliseerd',
  normalisatie_zekerheid: null,
  artikelgroep_id: null,
  artikelgroep_naam: null,
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
      if (pad === `/administraties/${ADMIN}/voorraad/groepen` && method === 'POST') {
        return Promise.resolve(jsonResponse({ id: 'g-nieuw', naam: 'Steigerbuis 4m', eenheid: 'st', tolerantie_pct: '1.00', actief: true }, 201))
      }
      if (pad === `/administraties/${ADMIN}/voorraad/groepen`) {
        if (opties.uit) return Promise.resolve(jsonResponse([]))
        return Promise.resolve(jsonResponse(AANSLUITING.groepen.map((g) => ({ id: g.artikelgroep_id, naam: g.naam, eenheid: 'st', tolerantie_pct: '1.00', actief: true }))))
      }
      if (pad === `/administraties/${ADMIN}/voorraad/tellingen`) return Promise.resolve(new Response(null, { status: 204 }))
      if (pad === `/administraties/${ADMIN}/voorraad/regels`) {
        const status = new URL(url, 'http://x').searchParams.get('normalisatie_status')
        const alle = [REGEL_RLZ, REGEL_APP]
        return Promise.resolve(jsonResponse(status ? alle.filter((r) => r.normalisatie_status === status) : alle))
      }
      if (pad.endsWith('/dagstanden')) return Promise.resolve(jsonResponse([{ datum: '2026-08-28', inkoop: '0', verkoop: '610', stand: '820' }]))
      if (pad === `/administraties/${ADMIN}/voorraad/normalisatie/corrigeer`) return Promise.resolve(jsonResponse({ herrekend: 3 }))
      if (pad.endsWith('/tolerantie')) return Promise.resolve(new Response(null, { status: 204 }))
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

describe('VoorraadScreen — blok A herkomst + blok B dialogen', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('drill-down toont per regel de herkomst: RLZ-verkoopfactuur (geen documentlink) vs app-document (link)', async () => {
    stubFetch()
    renderScherm()
    await screen.findByTestId('aansluiting-tabel')
    const gebruiker = userEvent.setup()
    await gebruiker.click(screen.getByRole('button', { name: 'Koppelingen 48mm' }))
    const detail = await screen.findByTestId('groep-detail')
    expect(detail).toHaveTextContent('RLZ-verkoopfactuur 50212273')
    expect(within(detail).queryByRole('link', { name: /RLZ-verkoopfactuur/ })).toBeNull()
    expect(within(detail).getByRole('link', { name: 'inkoopfactuur (scan) →' })).toHaveAttribute('href', `/documenten/${ADMIN}/doc-1`)
    // Bron per kolom benoemt sinds blok A óók de RLZ-leesroute.
    expect(screen.getByText(/verkoop = verkoopfactuurregels \(interne registratie\)/)).toBeInTheDocument()
  })

  it('"+ nieuwe artikelgroep…" opent een dialoog (geen window.prompt): aanmaken = POST groepen + POST corrigeer', async () => {
    const aangeroepen = stubFetch()
    const prompt = vi.fn()
    vi.stubGlobal('prompt', prompt)
    renderScherm()
    await screen.findByTestId('aansluiting-tabel')
    const gebruiker = userEvent.setup()
    await gebruiker.click(screen.getByRole('button', { name: /normaliseren/ }))
    const paneel = await screen.findByTestId('normalisatie-paneel')
    await gebruiker.selectOptions(within(paneel).getAllByRole('combobox')[0], '__nieuw__')
    const dialoog = await screen.findByTestId('nieuwe-groep-dialoog')
    expect(prompt).not.toHaveBeenCalled()
    // Leeg opslaan = validatie in de dialoog, geen request.
    await gebruiker.click(within(dialoog).getByRole('button', { name: 'Aanmaken en corrigeren' }))
    expect(dialoog).toHaveTextContent('Geef de artikelgroep een naam.')
    await gebruiker.type(within(dialoog).getByLabelText('Naam'), 'Steigerbuis 4m')
    await gebruiker.clear(within(dialoog).getByLabelText('Tolerantie (%)'))
    await gebruiker.type(within(dialoog).getByLabelText('Tolerantie (%)'), '2,5')
    await gebruiker.click(within(dialoog).getByRole('button', { name: 'Aanmaken en corrigeren' }))
    await waitFor(() => expect(aangeroepen.some((a) => a.method === 'POST' && a.pad.endsWith('/normalisatie/corrigeer'))).toBe(true))
    const post = aangeroepen.find((a) => a.method === 'POST' && a.pad.endsWith('/voorraad/groepen'))!
    expect(post.body).toEqual({ naam: 'Steigerbuis 4m', eenheid: 'st', tolerantie_pct: '2.5' })
    const corr = aangeroepen.find((a) => a.method === 'POST' && a.pad.endsWith('/normalisatie/corrigeer'))!
    expect(corr.body).toEqual({ regel_id: 'r-app', artikelgroep_id: 'g-nieuw', uitgesloten: false })
    expect(await screen.findByText(/Artikelgroep "Steigerbuis 4m" aangemaakt/)).toBeInTheDocument()
    expect(screen.queryByTestId('nieuwe-groep-dialoog')).toBeNull()
  })

  it('Tolerantie → dialoog met huidige waarde, opslaan = PUT …/tolerantie; ongeldig = melding zonder request', async () => {
    const aangeroepen = stubFetch()
    renderScherm()
    await screen.findByTestId('aansluiting-tabel')
    const gebruiker = userEvent.setup()
    await gebruiker.click(screen.getAllByRole('button', { name: 'Tolerantie' })[0])
    const dialoog = await screen.findByTestId('tolerantie-dialoog')
    expect(dialoog).toHaveTextContent('Tolerantie — Koppelingen 48mm')
    const veld = within(dialoog).getByLabelText('Tolerantie (%)')
    expect(veld).toHaveValue('1')
    await gebruiker.clear(veld)
    await gebruiker.type(veld, '150')
    await gebruiker.click(within(dialoog).getByRole('button', { name: 'Opslaan' }))
    expect(dialoog).toHaveTextContent('tussen 0 en 100')
    expect(aangeroepen.some((a) => a.method === 'PUT')).toBe(false)
    await gebruiker.clear(veld)
    await gebruiker.type(veld, '2,5')
    await gebruiker.click(within(dialoog).getByRole('button', { name: 'Opslaan' }))
    await waitFor(() => expect(aangeroepen.some((a) => a.method === 'PUT' && a.pad.endsWith('/tolerantie'))).toBe(true))
    expect(aangeroepen.find((a) => a.method === 'PUT')!.body).toEqual({ tolerantie_pct: '2.5' })
    expect(await screen.findByText(/Tolerantie voor Koppelingen 48mm gezet op 2,5%/)).toBeInTheDocument()
  })
})

describe('voorraadApi — weergave', () => {
  it('bronLabel benoemt de herkomst leesbaar', () => {
    expect(bronLabel({ bron: 'rlz_verkoop', rlz_referentie: '50212273' })).toBe('RLZ-verkoopfactuur 50212273')
    expect(bronLabel({ bron: 'rlz_verkoop', rlz_referentie: null })).toBe('RLZ-verkoopfactuur')
    expect(bronLabel({ bron: 'verkoop_regel', rlz_referentie: null })).toBe('verkoopfactuur (app)')
    expect(bronLabel({ bron: 'inkoop_veldvoorstel', rlz_referentie: null })).toBe('inkoopfactuur (scan)')
  })

  it('signaalTekst en aantal formatteren NL, nooit rekenen', () => {
    expect(signaalTekst(groep({}))).toEqual({ tekst: 'binnen tolerantie', soort: 'ok' })
    expect(signaalTekst(groep({ signaal: 'onderzoeken', verschil_pct: '1.70' }))).toEqual({ tekst: '+1,7% — onderzoeken', soort: 'vlag' })
    expect(signaalTekst(groep({ signaal: 'geen_telling', systeemstand: null }))).toEqual({ tekst: 'nog geen telling', soort: 'geen' })
    expect(aantal('1240.000')).toBe('1.240')
    expect(aantal(null)).toBe('—')
    expect(aantal('2.5000', 2)).toBe('2,5')
  })
})
