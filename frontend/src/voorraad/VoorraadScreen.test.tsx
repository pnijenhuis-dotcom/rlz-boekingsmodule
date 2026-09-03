import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../auth/AuthContext'
import { VoorraadScreen } from './VoorraadScreen'
import {
  aantal,
  bronLabel,
  classificatieBronLabel,
  signaalTekst,
  type ArtikelcodeDto,
  type DienstTekstDto,
  type GroepAansluitingDto,
  type VoorraadRegelDto,
} from './voorraadApi'

// Mockup voorraad-aansluiting.html §1 (blok D 28-08): tabel per artikelgroep met bron per kolom,
// signaal op tolerantie, prominente "Niet genormaliseerd"-teller, telling-invoer; opt-in uit = leesbare
// melding. Cijfers komen uit de backend — de client formatteert alleen. Sinds B3 (03-09) is dit het
// DETAIL per administratie achter `?administratie=`; regels/diensten/codes komen gepagineerd binnen.

function pagina<T>(rijen: T[], totaal = rijen.length) {
  return { rijen, totaal, pagina: 1, per_pagina: 25 }
}

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
  dienst_regels: 110,
  transport_regels: 25,
  bronnen: {
    inkoop: 'inkoopfacturen (AI-gescand, extern document)',
    verkoop: 'verkoopfactuurregels (interne registratie)',
    systeemstand: 'handmatige telling per datum',
    diensten: 'dienst-/transportregels (soort-label)',
  },
}

const DIENSTEN: DienstTekstDto[] = [
  {
    voorbeeld_regel_id: 'r-km',
    artikeltekst: 'Verreden kilometers',
    artikeltekst_norm: 'verreden kilometers',
    vendor_id: null,
    relatie_naam: null,
    soort: 'transport',
    bron: 'regel',
    richtingen: 'uit',
    regels: 370,
    som_aantal: '12480.000',
    som_netto: '9984.00',
  },
  {
    voorbeeld_regel_id: 'r-huur',
    artikeltekst: 'Huur lift week 12',
    artikeltekst_norm: 'huur lift week 12',
    vendor_id: 'v1',
    relatie_naam: 'Scafom B.V.',
    soort: 'dienst',
    bron: 'regel',
    richtingen: 'in',
    regels: 3,
    som_aantal: '3.000',
    som_netto: '1200.00',
  },
]

const CODES: ArtikelcodeDto[] = [
  {
    id: 'k1',
    richting: 'uit',
    vendor_id: null,
    relatie_naam: null,
    code: '550100.210',
    soort: 'artikel',
    artikelgroep_id: 'g2',
    artikelgroep_naam: 'Steigerbuis 3m',
    zekerheid: '0.600',
    bron: 'ai',
    voorbeeld_tekst: 'Steigerbuis 4 mtr incl. tube-connect (550100.210)',
    regels: 41,
    teksten: 2,
  },
  {
    id: 'k2',
    richting: 'in',
    vendor_id: 'v1',
    relatie_naam: 'Scafom B.V.',
    code: '1002-3',
    soort: 'artikel',
    artikelgroep_id: 'g1',
    artikelgroep_naam: 'Koppelingen 48mm',
    zekerheid: '1.000',
    bron: 'handmatig',
    voorbeeld_tekst: 'KOP.DR.48/48 (art. 1002-3)',
    regels: 4,
    teksten: 1,
  },
]

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
  artikelcode: '550100.210',
  soort: 'artikel',
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
  artikelcode: null,
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
        const statussen = status ? status.split(',') : null
        const alle = [REGEL_RLZ, REGEL_APP]
        return Promise.resolve(jsonResponse(pagina(statussen ? alle.filter((r) => statussen.includes(r.normalisatie_status)) : alle)))
      }
      if (pad.endsWith('/dagstanden')) return Promise.resolve(jsonResponse([{ datum: '2026-08-28', inkoop: '0', verkoop: '610', stand: '820' }]))
      if (pad === `/administraties/${ADMIN}/voorraad/normalisatie/corrigeer`) return Promise.resolve(jsonResponse({ herrekend: 3 }))
      if (pad === `/administraties/${ADMIN}/voorraad/diensten`) return Promise.resolve(jsonResponse(pagina(DIENSTEN)))
      if (pad === `/administraties/${ADMIN}/voorraad/artikelcodes`) return Promise.resolve(jsonResponse(pagina(CODES)))
      if (pad.endsWith('/artikelcodes/k1/corrigeer')) return Promise.resolve(jsonResponse({ herrekend: 41 }))
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
    // Het verschil-signaal is sinds B3 (03-09) een link naar de verdachte regels.
    expect(within(buis).getByRole('button', { name: /-8,8% — onderzoeken bekijk regels/ })).toBeInTheDocument()
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
    await gebruiker.selectOptions(within(paneel).getByLabelText('Corrigeer KOP.DR.48/48 SW22 gegalv.'), '__nieuw__')
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
    expect(corr.body).toEqual({ regel_id: 'r-app', artikelgroep_id: 'g-nieuw', soort: 'artikel' })
    expect(await screen.findByText(/artikelgroep "Steigerbuis 4m" aangemaakt/)).toBeInTheDocument()
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

describe('VoorraadScreen — v2 soort-label, dienst-inzage (§3) en codes-inzage (§4)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('toont de rij "Diensten & transport" met tellers; de inzage lijst per tekst mét aantallen en bron, en corrigeert dienst → artikel via de voorbeeldregel', async () => {
    const aangeroepen = stubFetch()
    renderScherm()
    const rij = await screen.findByTestId('diensten-rij')
    expect(within(rij).getByText('110 dienst · 25 transport')).toBeInTheDocument()
    await userEvent.click(within(rij).getByRole('button', { name: /als dienst geclassificeerd \(135\)/ }))
    const paneel = await screen.findByTestId('dienst-inzage')
    expect(within(paneel).getByText(/Verreden kilometers/)).toBeInTheDocument()
    expect(within(paneel).getByText('370')).toBeInTheDocument()
    expect(within(paneel).getAllByText('regex (automatisch)')).toHaveLength(2)
    expect(within(paneel).getByText('transport')).toBeInTheDocument()
    // Correctie: de huur-regel is tóch een artikel → POST corrigeer op de voorbeeldregel mét soort artikel + groep.
    await userEvent.selectOptions(within(paneel).getByLabelText('Corrigeer dienst Huur lift week 12'), 'g1')
    await waitFor(() => expect(aangeroepen.some((a) => a.pad.endsWith('/normalisatie/corrigeer') && a.method === 'POST')).toBe(true))
    const post = aangeroepen.find((a) => a.pad.endsWith('/normalisatie/corrigeer'))
    expect(post?.body).toEqual({ regel_id: 'r-huur', soort: 'artikel', artikelgroep_id: 'g1' })
    expect(await screen.findByText(/Correctie toegepast op 3 regels/)).toBeInTheDocument()
  })

  it('normalisatie-paneel biedt dienst/transport i.p.v. "uitsluiten" en stuurt het soort-label mee', async () => {
    const aangeroepen = stubFetch()
    renderScherm()
    const rij = await screen.findByTestId('niet-genormaliseerd-rij')
    await userEvent.click(within(rij).getByRole('button', { name: /normaliseren/ }))
    const paneel = await screen.findByTestId('normalisatie-paneel')
    const select = await within(paneel).findByLabelText('Corrigeer KOP.DR.48/48 SW22 gegalv.')
    expect(within(select).queryByText(/uitsluiten/)).toBeNull()
    await userEvent.selectOptions(select, '__transport__')
    await waitFor(() => expect(aangeroepen.some((a) => a.pad.endsWith('/normalisatie/corrigeer'))).toBe(true))
    expect(aangeroepen.find((a) => a.pad.endsWith('/normalisatie/corrigeer'))?.body).toEqual({ regel_id: 'r-app', soort: 'transport', artikelgroep_id: null })
  })

  it('codes-inzage toont code → groep per richting mét bron/zekerheid (AI-voorstel vs handmatig) en corrigeert per code', async () => {
    const aangeroepen = stubFetch()
    renderScherm()
    const rij = await screen.findByTestId('diensten-rij')
    await userEvent.click(within(rij).getByRole('button', { name: 'artikelcodes' }))
    const paneel = await screen.findByTestId('codes-inzage')
    expect(within(paneel).getByText('550100.210')).toBeInTheDocument()
    expect(within(paneel).getByText(/AI-voorstel \(60%\)/)).toBeInTheDocument()
    expect(within(paneel).getByText('handmatig bevestigd')).toBeInTheDocument()
    expect(within(paneel).getByText(/verkoop · eigen verkoop/)).toBeInTheDocument()
    expect(within(paneel).getByText(/inkoop · Scafom B.V./)).toBeInTheDocument()
    await userEvent.selectOptions(within(paneel).getByLabelText('Corrigeer code 550100.210'), 'g1')
    await waitFor(() => expect(aangeroepen.some((a) => a.pad.endsWith('/artikelcodes/k1/corrigeer'))).toBe(true))
    expect(aangeroepen.find((a) => a.pad.endsWith('/artikelcodes/k1/corrigeer'))?.body).toEqual({ soort: 'artikel', artikelgroep_id: 'g1' })
    expect(await screen.findByText(/Correctie toegepast op 41 regels met code 550100.210 \(verkoop\)/)).toBeInTheDocument()
  })

  it('drill-down toont de artikelcode bij de regel', async () => {
    stubFetch()
    renderScherm()
    const tabel = await screen.findByTestId('aansluiting-tabel')
    await userEvent.click(within(tabel).getByRole('button', { name: 'Koppelingen 48mm' }))
    const detail = await screen.findByTestId('groep-detail')
    expect(within(detail).getByText('code 550100.210')).toBeInTheDocument()
  })
})

describe('VoorraadScreen — B3 detail achter de landing (03-09)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('deeplink ?groep= opent de drill-down van die groep direct; kruimelpad terug naar de kantoorbrede landing', async () => {
    const aangeroepen = stubFetch()
    render(
      <MemoryRouter initialEntries={[`/voorraad?administratie=${ADMIN}&groep=g2&van=2026-01-01&tot=2026-08-31`]}>
        <AuthProvider>
          <VoorraadScreen />
        </AuthProvider>
      </MemoryRouter>,
    )
    const detail = await screen.findByTestId('groep-detail')
    expect(detail).toHaveTextContent('Steigerbuis 3m — factuurregels')
    const regels = aangeroepen.find((a) => a.pad.includes('/voorraad/regels'))!
    expect(regels.pad).toContain('artikelgroep_id=g2')
    expect(regels.pad).toContain('pagina=1')
    expect(screen.getByRole('link', { name: '← Alle administraties' })).toHaveAttribute('href', '/voorraad')
    expect(screen.getByRole('link', { name: 'Inzicht › Voorraad' })).toHaveAttribute('href', '/voorraad')
  })

  it('klik op het verschil-signaal opent de regels achter dat verschil en zet groep in de URL', async () => {
    stubFetch()
    renderScherm()
    const tabel = await screen.findByTestId('aansluiting-tabel')
    await userEvent.click(within(tabel).getByRole('button', { name: /-8,8% — onderzoeken bekijk regels/ }))
    const detail = await screen.findByTestId('groep-detail')
    expect(detail).toHaveTextContent('Steigerbuis 3m — factuurregels')
  })

  it('normalisatie-paneel haalt één gepagineerde lijst met beide statussen (komma-gescheiden)', async () => {
    const aangeroepen = stubFetch()
    renderScherm()
    const rij = await screen.findByTestId('niet-genormaliseerd-rij')
    await userEvent.click(within(rij).getByRole('button', { name: /normaliseren/ }))
    await screen.findByTestId('normalisatie-paneel')
    await waitFor(() => expect(aangeroepen.some((a) => a.pad.includes('normalisatie_status=niet_genormaliseerd%2Conzeker'))).toBe(true))
    expect(aangeroepen.filter((a) => a.pad.includes('/voorraad/regels')).length).toBe(1)
  })
})

describe('voorraadApi — weergave', () => {
  it('classificatieBronLabel benoemt regex/AI/handmatig/legacy leesbaar', () => {
    expect(classificatieBronLabel('regel')).toBe('regex (automatisch)')
    expect(classificatieBronLabel('ai')).toBe('AI-voorstel')
    expect(classificatieBronLabel('handmatig')).toBe('handmatig bevestigd')
    expect(classificatieBronLabel('legacy')).toMatch(/vóór v2/)
  })

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
