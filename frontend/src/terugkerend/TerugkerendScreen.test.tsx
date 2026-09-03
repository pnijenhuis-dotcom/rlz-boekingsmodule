import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../auth/AuthContext'
import { TerugkerendSignaal } from '../document/TerugkerendSignaal'
import { TerugkerendScreen } from './TerugkerendScreen'
import type { HerberekenRunDto, KantoorLijstDto, KantoorRijDto } from './terugkerendApi'

// Inzicht › Terugkerende facturen KANTOORBREED (design-ronde 03-09 blok B1, mockup inzicht-kantoorbreed
// paneel 1 ①②③): één lijst over alle administraties (server sorteert/pagineert), chips + facetten +
// zoekveld, één handeling per rij (navragen-conceptmail / naar de boeking) + ⋯-menu (snooze/afmelden),
// "⟳ Herbereken alles" als achtergrondrun met status-poll. De client formatteert alleen.

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function fakeAccessToken(rol: string): string {
  const payload = btoa(JSON.stringify({ sub: 'gebruiker-id', rol })).replace(/\+/g, '-').replace(/\//g, '_')
  return `kop.${payload}.handtekening`
}

const ADMIN_A = 'aaaaaaaa-0000-0000-0000-000000000001'
const ADMIN_B = 'bbbbbbbb-0000-0000-0000-000000000002'
const RUN_ID = 'cccccccc-0000-0000-0000-000000000003'

const basis = {
  patroon: 'maand' as const,
  interval_dagen: 30,
  aantal_facturen: 4,
  vorige_datum: null,
  vorige_bedrag: null,
  snooze_tot: null,
  afgemeld_op: null,
  berekend_op: '2026-09-03T05:00:00Z',
}
const ODIDO: KantoorRijDto = {
  ...basis,
  administratie_id: ADMIN_A,
  administratie_naam: 'Kempen Facilities B.V.',
  vendor_id: 'v-odido',
  leverancier: 'Odido Zakelijk',
  soort: 'ontbreekt',
  status: 'aandacht',
  laatste_datum: '2026-07-28',
  laatste_bedrag: '214.50',
  laatste_document_id: 'doc-odido',
  verwacht_op: '2026-08-28',
  uiterlijk_op: '2026-09-08',
  dagen_te_laat: 6,
  prijsstijging_pct: null,
}
const LABO: KantoorRijDto = {
  ...basis,
  administratie_id: ADMIN_B,
  administratie_naam: 'Universal Steigerbouw B.V.',
  vendor_id: 'v-labo',
  leverancier: 'Labo Derva B.V.',
  soort: 'prijsstijging',
  status: 'aandacht',
  laatste_datum: '2026-09-01',
  laatste_bedrag: '1240.00',
  laatste_document_id: 'doc-labo',
  vorige_bedrag: '1087.72',
  vorige_datum: '2026-08-01',
  verwacht_op: '2026-10-01',
  uiterlijk_op: '2026-10-12',
  dagen_te_laat: null,
  prijsstijging_pct: '14.00',
}
const LIJST: KantoorLijstDto = {
  rijen: [ODIDO, LABO],
  totaal: 2,
  pagina: 1,
  per_pagina: 25,
  administraties_in_selectie: 2,
  tellers: { ontbrekend: 4, prijsstijging: 2, administraties: 3 },
  facetten: {
    status: { aandacht: 6, gesnoozed: 1, afgemeld: 0, alle: 7 },
    administraties: [
      { administratie_id: ADMIN_A, naam: 'Kempen Facilities B.V.', aantal: 1 },
      { administratie_id: ADMIN_B, naam: 'Universal Steigerbouw B.V.', aantal: 1 },
    ],
  },
}

function run(status: HerberekenRunDto['status'], extra: Partial<HerberekenRunDto> = {}): HerberekenRunDto {
  return {
    run_id: RUN_ID,
    status,
    aangevraagd_op: '2026-09-03T08:00:00Z',
    gestart_op: null,
    klaar_op: null,
    aantal_administraties: 3,
    aantal_verwerkt: 0,
    aantal_fouten: 0,
    foutreden: null,
    resultaat: null,
    ...extra,
  }
}

function stubFetch(rol = 'boekhouding', opties: { runStatussen?: HerberekenRunDto[] } = {}) {
  const aangeroepen: { pad: string; method: string; body: unknown }[] = []
  const statussen = [...(opties.runStatussen ?? [])]
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      aangeroepen.push({ pad: url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined })
      if (url === '/auth/token/vernieuwen') return Promise.resolve(jsonResponse({ access_token: fakeAccessToken(rol) }))
      if (url === '/auth/administraties') {
        return Promise.resolve(
          jsonResponse({ administraties: [{ id: ADMIN_A, naam: 'Kempen Facilities B.V.' }, { id: ADMIN_B, naam: 'Universal Steigerbouw B.V.' }] }),
        )
      }
      if (url.startsWith('/terugkerend/signalen?')) return Promise.resolve(jsonResponse(LIJST))
      if (url === '/terugkerend/herbereken/laatste') return Promise.resolve(jsonResponse(null))
      if (url === '/terugkerend/herbereken' && method === 'POST') return Promise.resolve(jsonResponse(run('wachtend'), 202))
      if (url === `/terugkerend/herbereken/${RUN_ID}`) return Promise.resolve(jsonResponse(statussen.shift() ?? run('klaar', { aantal_verwerkt: 3 })))
      if (url.endsWith('/conceptmail')) {
        return Promise.resolve(
          jsonResponse({
            ontvanger_e_mail: null,
            leverancier: 'Odido Zakelijk',
            administratie_naam: 'Kempen Facilities B.V.',
            onderwerp: 'Vraag over de factuur voor augustus 2026 — Kempen Facilities B.V.',
            tekst: 'Beste Odido Zakelijk,\n\nDe factuur voor augustus 2026 hebben wij nog niet ontvangen.',
          }),
        )
      }
      if (url.endsWith('/conceptmail/versturen')) return Promise.resolve(jsonResponse({ verzonden_aan: (JSON.parse(String(init?.body)) as { naar: string }).naar }))
      if (url.endsWith('/snooze') || url.endsWith('/afmelden')) return Promise.resolve(new Response(null, { status: 204 }))
      if (url.endsWith('/terugkerend-instelling')) return Promise.resolve(jsonResponse({ prijsstijging_pct: '5' }))
      if (url.endsWith('/terugkerend-signaal')) {
        return Promise.resolve(jsonResponse({ prijsstijging_pct: '20.00', vorige_bedrag: '100.00', vorige_datum: '2026-03-02', laatste_bedrag: '120.00', patroon: 'maand', leverancier: 'Ziggo Zakelijk' }))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
  return aangeroepen
}

function renderScherm(pad = '/terugkerend', pollMs = 5) {
  return render(
    <MemoryRouter initialEntries={[pad]}>
      <AuthProvider>
        <TerugkerendScreen pollMs={pollMs} />
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('TerugkerendScreen (kantoorbreed)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('toont chips, één rij per signaal mét de juiste handeling, administratie-link en de voet; facet en zoekterm gaan naar de server', async () => {
    const aangeroepen = stubFetch()
    renderScherm()
    const tabel = await screen.findByTestId('terugkerend-tabel')
    expect(screen.getByTestId('chip-ontbrekend')).toHaveTextContent('4 ontbrekend')
    expect(screen.getByTestId('chip-prijsstijging')).toHaveTextContent('2 prijsstijging')
    // Eerste lijst-call: default facet "aandacht nodig", geen administratie, pagina 1.
    const eerste = aangeroepen.find((a) => a.pad.startsWith('/terugkerend/signalen?'))!
    expect(eerste.pad).toBe('/terugkerend/signalen?pagina=1&status=aandacht')
    const rijen = within(tabel).getAllByTestId('terugkerend-rij')
    expect(rijen).toHaveLength(2)
    // Ontbreekt-rij: ritme-subregel, signaal-chip, primaire actie "Navragen bij leverancier…".
    expect(within(rijen[0]).getByText('Odido Zakelijk')).toBeInTheDocument()
    expect(within(rijen[0]).getByText(/maandelijks · laatst 28-07 · € 214,50/)).toBeInTheDocument()
    expect(within(rijen[0]).getByText('verwacht ± 28-08 — 6 dagen te laat')).toBeInTheDocument()
    expect(within(rijen[0]).getByRole('button', { name: 'Navragen bij Odido Zakelijk' })).toBeInTheDocument()
    expect(within(rijen[0]).getByRole('link', { name: 'Kempen Facilities B.V.' })).toHaveAttribute('href', `/?administratie=${ADMIN_A}`)
    // Prijsstijging-rij: "Naar de boeking →" = deep-link naar het document in zijn administratie.
    expect(within(rijen[1]).getByText('prijs +14% t.o.v. vorige factuur')).toBeInTheDocument()
    expect(within(rijen[1]).getByRole('link', { name: 'Naar de boeking van Labo Derva B.V.' })).toHaveAttribute('href', `/?administratie=${ADMIN_B}&document=doc-labo`)
    expect(within(rijen[1]).queryByRole('button', { name: /Navragen/ })).toBeNull()
    expect(screen.getByTestId('terugkerend-voet')).toHaveTextContent(/1 van 1/)
    expect(screen.getByTestId('terugkerend-voet')).toHaveTextContent(/2 signalen over 2 administraties/)
    // Status-facet → server-side filter in de URL; zoekterm → q.
    await userEvent.selectOptions(screen.getByLabelText('Status'), 'gesnoozed')
    await waitFor(() => expect(aangeroepen.some((a) => a.pad === '/terugkerend/signalen?pagina=1&status=gesnoozed')).toBe(true))
    await userEvent.type(screen.getByLabelText('Zoek leverancier'), 'odi')
    await waitFor(() => expect(aangeroepen.some((a) => a.pad === '/terugkerend/signalen?pagina=1&status=gesnoozed&q=odi')).toBe(true))
  })

  it('deep-link ?administratie_id=X vult het administratie-facet voor (filter, geen poort)', async () => {
    const aangeroepen = stubFetch()
    renderScherm(`/terugkerend?administratie_id=${ADMIN_A}`)
    await screen.findByTestId('terugkerend-tabel')
    expect(aangeroepen.find((a) => a.pad.startsWith('/terugkerend/signalen?'))!.pad).toBe(`/terugkerend/signalen?pagina=1&status=aandacht&administratie_id=${ADMIN_A}`)
    // Legacy-param `administratie` werkt ook nog (oude links in mail/tijdlijn).
    cleanup()
    vi.unstubAllGlobals()
    const opnieuw = stubFetch()
    renderScherm(`/terugkerend?administratie=${ADMIN_B}`)
    await waitFor(() => expect(opnieuw.some((a) => a.pad === `/terugkerend/signalen?pagina=1&status=aandacht&administratie_id=${ADMIN_B}`)).toBe(true))
  })

  it('⋯-menu: snooze 30 d en afmelden POSTen naar de bestaande per-administratie-routes', async () => {
    const aangeroepen = stubFetch()
    renderScherm()
    const tabel = await screen.findByTestId('terugkerend-tabel')
    await userEvent.click(within(tabel).getByRole('button', { name: 'Meer acties Odido Zakelijk' }))
    const menu = await screen.findByRole('menu')
    await userEvent.click(within(menu).getByRole('menuitem', { name: 'Snooze 30 d' }))
    await waitFor(() => expect(aangeroepen.some((a) => a.pad === `/administraties/${ADMIN_A}/terugkerend/v-odido/snooze`)).toBe(true))
    const snooze = aangeroepen.find((a) => a.pad.endsWith('/v-odido/snooze'))!
    expect(snooze.method).toBe('POST')
    expect((snooze.body as { tot: string }).tot).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    await userEvent.click(within(tabel).getByRole('button', { name: 'Meer acties Labo Derva B.V.' }))
    await userEvent.click(within(await screen.findByRole('menu')).getByRole('menuitem', { name: 'Afmelden per leverancier' }))
    await waitFor(() => expect(aangeroepen.some((a) => a.pad === `/administraties/${ADMIN_B}/terugkerend/v-labo/afmelden`)).toBe(true))
    expect(aangeroepen.find((a) => a.pad.endsWith('/v-labo/afmelden'))?.body).toEqual({ afgemeld: true })
  })

  it('Navragen bij leverancier…: concept van de server, mens vult ontvanger in en verstuurt expliciet; uitkomst zichtbaar', async () => {
    const aangeroepen = stubFetch()
    renderScherm()
    const tabel = await screen.findByTestId('terugkerend-tabel')
    await userEvent.click(within(tabel).getByRole('button', { name: 'Navragen bij Odido Zakelijk' }))
    const dialoog = await screen.findByTestId('conceptmail-dialoog')
    expect(aangeroepen.some((a) => a.pad === `/terugkerend/${ADMIN_A}/v-odido/conceptmail` && a.method === 'GET')).toBe(true)
    const onderwerp = await within(dialoog).findByLabelText('Onderwerp')
    expect(onderwerp).toHaveValue('Vraag over de factuur voor augustus 2026 — Kempen Facilities B.V.')
    expect(within(dialoog).getByLabelText('Tekst')).toHaveValue('Beste Odido Zakelijk,\n\nDe factuur voor augustus 2026 hebben wij nog niet ontvangen.')
    expect(within(dialoog).getByText(/geen e-mailadres; vul het zelf in/)).toBeInTheDocument()
    // Zonder ontvanger kan er niets weg.
    expect(within(dialoog).getByRole('button', { name: 'Versturen' })).toBeDisabled()
    await userEvent.type(within(dialoog).getByLabelText('Aan'), 'facturatie@odido.nl')
    await userEvent.clear(onderwerp)
    await userEvent.type(onderwerp, 'Aangepast onderwerp')
    await userEvent.click(within(dialoog).getByRole('button', { name: 'Versturen' }))
    await waitFor(() => expect(aangeroepen.some((a) => a.pad.endsWith('/v-odido/conceptmail/versturen'))).toBe(true))
    const post = aangeroepen.find((a) => a.pad.endsWith('/conceptmail/versturen'))!
    expect(post.method).toBe('POST')
    expect(post.body).toEqual({ naar: 'facturatie@odido.nl', onderwerp: 'Aangepast onderwerp', tekst: 'Beste Odido Zakelijk,\n\nDe factuur voor augustus 2026 hebben wij nog niet ontvangen.' })
    expect(await within(dialoog).findByTestId('navraag-verzonden')).toHaveTextContent('Verstuurd aan facturatie@odido.nl')
    expect(within(dialoog).queryByRole('button', { name: 'Versturen' })).toBeNull()
  })

  it('⟳ Herbereken alles: 202 + pollen tot klaar (voortgang zichtbaar), daarna lijst verversen; fout blijft zichtbaar', async () => {
    const aangeroepen = stubFetch('boekhouding', {
      runStatussen: [run('bezig', { aantal_verwerkt: 1 }), run('klaar', { aantal_verwerkt: 3, klaar_op: '2026-09-03T08:01:00Z' })],
    })
    renderScherm()
    await screen.findByTestId('terugkerend-tabel')
    const lijstCallsVoor = aangeroepen.filter((a) => a.pad.startsWith('/terugkerend/signalen?')).length
    await userEvent.click(screen.getByRole('button', { name: '⟳ Herbereken alles' }))
    await waitFor(() => expect(aangeroepen.some((a) => a.pad === '/terugkerend/herbereken' && a.method === 'POST')).toBe(true))
    const stand = await screen.findByTestId('herbereken-stand')
    await waitFor(() => expect(stand).toHaveTextContent('Herberekening bezig: 1 van 3 administraties'))
    await waitFor(() => expect(stand).toHaveTextContent('3 administraties herberekend'))
    // Klaar → de lijst wordt opnieuw opgehaald; knop weer bruikbaar.
    await waitFor(() => expect(aangeroepen.filter((a) => a.pad.startsWith('/terugkerend/signalen?')).length).toBeGreaterThan(lijstCallsVoor))
    expect(screen.getByRole('button', { name: '⟳ Herbereken alles' })).toBeEnabled()

    // Fout-run: reden zichtbaar, geen stille dood.
    cleanup()
    vi.unstubAllGlobals()
    stubFetch('boekhouding', { runStatussen: [run('fout', { foutreden: 'RuntimeError: database weg' })] })
    renderScherm()
    await screen.findByTestId('terugkerend-tabel')
    await userEvent.click(screen.getByRole('button', { name: '⟳ Herbereken alles' }))
    expect(await screen.findByText('De kantoorbrede herberekening is mislukt.')).toBeInTheDocument()
    expect(screen.getByText(/database weg/)).toBeInTheDocument() // technische details (FoutMelding), nooit stil
  })

  it('Beheerder ziet de drempel-instelling alleen mét één administratie in het facet (PUT terugkerend-instelling)', async () => {
    const aangeroepen = stubFetch('beheerder')
    renderScherm(`/terugkerend?administratie_id=${ADMIN_A}`)
    const invoer = await screen.findByLabelText('Drempel prijsstijging')
    await userEvent.type(invoer, '5')
    await userEvent.click(screen.getByRole('button', { name: 'Opslaan' }))
    await waitFor(() => expect(aangeroepen.some((a) => a.pad === `/administraties/${ADMIN_A}/terugkerend-instelling` && a.method === 'PUT')).toBe(true))
    expect(aangeroepen.find((a) => a.pad.endsWith('/terugkerend-instelling'))?.body).toEqual({ prijsstijging_pct: '5' })
    cleanup()
    vi.unstubAllGlobals()
    stubFetch('beheerder')
    renderScherm('/terugkerend')
    await screen.findByTestId('terugkerend-tabel')
    expect(screen.queryByLabelText('Drempel prijsstijging')).toBeNull()
  })
})

describe('TerugkerendSignaal (controlescherm-chip)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('toont de prijsstijging-chip mét vorige factuur en link naar het kantoorbrede overzicht (facet voorgevuld); niet-inkoop = niets', async () => {
    stubFetch()
    const { rerender } = render(
      <MemoryRouter>
        <TerugkerendSignaal administratieId={ADMIN_A} documentId="doc-1" status="te_controleren" soort="inkoopfactuur" boekvoorstelVersie={0} />
      </MemoryRouter>,
    )
    expect(await screen.findByText('Prijsstijging +20%')).toBeInTheDocument()
    expect(screen.getByText(/t\.o\.v\./)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Alle terugkerende facturen/ })).toHaveAttribute('href', `/terugkerend?administratie_id=${ADMIN_A}`)
    rerender(
      <MemoryRouter>
        <TerugkerendSignaal administratieId={ADMIN_A} documentId="doc-1" status="te_controleren" soort="verkoopfactuur" boekvoorstelVersie={0} />
      </MemoryRouter>,
    )
    expect(screen.queryByText(/Prijsstijging/)).toBeNull()
  })
})
