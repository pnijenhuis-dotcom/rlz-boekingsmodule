// Mini-voorraad-tab (opdracht 06-09; mockup mini-voorraad.html blok 2 + ⑧): lijst mét vlag "nieuw — controleer
// naam", "Naam bevestigen" wijzigt alleen de weergavenaam, Voorraadlog = append-only uitklap mét bron-link,
// beschadiging = gebeurtenis mét VERPLICHT project, Beheerder archiveert (nooit verwijderen). Er is nergens
// een corrigeer-/samenvoeg-knop of stand-invoer. Gemockte API volgens CONTRACT_F.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../auth/AuthContext'
import { ToastProvider } from '../ui/basis'
import { MINI_VOORRAAD_LEEG_TEKST, MINI_VOORRAAD_UIT_TEKST, MiniVoorraadTab } from './MiniVoorraadTab'
import type { MiniProductDto, MutatieDto } from './miniVoorraadApi'

const ADM = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOC = 'dddddddd-0000-0000-0000-000000000004'
const PROJECT = 'eeeeeeee-0000-0000-0000-000000000005'

function fakeAccessToken(rol: string): string {
  const payload = btoa(JSON.stringify({ sub: 'gebruiker-id', rol })).replace(/\+/g, '-').replace(/\//g, '_')
  return `kop.${payload}.handtekening`
}

function product(over: Partial<MiniProductDto>): MiniProductDto {
  return {
    id: 'p-stapelbok',
    administratie_id: ADM,
    vendor_id: 'v-huvanco',
    leverancier_naam: 'Huvanco',
    artikelcode: '560140.4',
    omschrijving: 'Stapelbok 1,25x0,85',
    weergavenaam: 'Stapelbok 1,25×0,85',
    eenheid: 'st',
    nieuw_controleren: false,
    gearchiveerd: false,
    stand: '96',
    laatste_mutatie_op: '2026-09-04T09:00:00Z',
    aangemaakt_op: '2026-08-01T09:00:00Z',
    ...over,
  }
}

const STAPELBOK = product({})
const VORK = product({
  id: 'p-vork',
  vendor_id: 'v-wola',
  leverancier_naam: 'Wola b.v.',
  artikelcode: null,
  omschrijving: 'Kanaalplaatvork speciaal',
  weergavenaam: null,
  nieuw_controleren: true,
  stand: '6',
})

const LOG: MutatieDto[] = [
  {
    id: 'm1',
    soort: 'instroom',
    aantal: '24',
    datum: '2026-09-04',
    document_id: DOC,
    document_referentie: '260630',
    document_leverancier: 'Huvanco',
    boek_cyclus: 1,
    project_id: PROJECT,
    project_naam: '26127 Tilburg',
    gemeld_door_naam: null,
    toelichting: null,
    aangemaakt_op: '2026-09-04T09:00:00Z',
  },
  {
    id: 'm2',
    soort: 'beschadiging',
    aantal: '-4',
    datum: '2026-09-02',
    document_id: null,
    document_referentie: null,
    document_leverancier: null,
    boek_cyclus: null,
    project_id: PROJECT,
    project_naam: '26120 Eindhoven',
    gemeld_door_naam: 'Joost Uitvoerder',
    toelichting: 'gevallen bij het lossen',
    aangemaakt_op: '2026-09-02T15:00:00Z',
  },
]

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

interface Opties {
  items?: MiniProductDto[]
  uit?: boolean
}

function stubFetch(rol: string, opties: Opties = {}) {
  const aangeroepen: { url: string; method: string; body?: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      aangeroepen.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined })
      if (url === '/auth/token/vernieuwen') return Promise.resolve(json({ access_token: fakeAccessToken(rol) }))
      if (url.startsWith(`/mini-voorraad/${ADM}/producten?`)) {
        if (opties.uit) return Promise.resolve(json({ detail: 'Mini-voorraad staat uit voor deze administratie' }, 409))
        const items = opties.items ?? [STAPELBOK, VORK]
        return Promise.resolve(json({ items, totaal: items.length, pagina: 1, per_pagina: 25, nieuw_controleren: items.filter((p) => p.nieuw_controleren).length, ingeschakeld: true }))
      }
      if (url.startsWith(`/mini-voorraad/${ADM}/producten/p-stapelbok/log`)) return Promise.resolve(json({ items: LOG, totaal: 2, pagina: 1, per_pagina: 25 }))
      if (url.endsWith('/naam-bevestigen') && method === 'POST') return Promise.resolve(json({ ...VORK, weergavenaam: 'Kanaalplaatvork', nieuw_controleren: false }))
      if (url.endsWith('/archiveren') && method === 'POST') return Promise.resolve(json({ ...STAPELBOK, gearchiveerd: true }))
      if (url === `/mini-voorraad/${ADM}/beschadigingen` && method === 'POST') return Promise.resolve(json({ ...LOG[1], id: 'm-nieuw' }))
      if (url === `/administraties/${ADM}/projecten`) return Promise.resolve(json({ projecten: [{ id: PROJECT, naam: '26127 Tilburg (Heijmans)' }] }))
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
  return aangeroepen
}

function renderTab() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <ToastProvider>
          <MiniVoorraadTab administratieId={ADM} />
        </ToastProvider>
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('MiniVoorraadTab', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('toont per product naam (weergavenaam of factuurtekst), subregel leverancier · code, stand en de vlag "nieuw — controleer naam"; nergens stand-invoer of samenvoegen', async () => {
    stubFetch('boekhouding')
    renderTab()
    const tabel = await screen.findByTestId('mini-voorraad-tabel')
    const rijen = within(tabel).getAllByTestId('mini-voorraad-rij')
    expect(rijen).toHaveLength(2)
    const stapelbok = rijen[0]
    expect(stapelbok).toHaveTextContent('Stapelbok 1,25×0,85')
    expect(stapelbok).toHaveTextContent('Huvanco · code 560140.4')
    expect(stapelbok).toHaveTextContent('factuurtekst: Stapelbok 1,25x0,85')
    expect(stapelbok).toHaveTextContent('96')
    expect(within(stapelbok).queryByRole('button', { name: /Naam bevestigen/ })).not.toBeInTheDocument()
    const vork = rijen[1]
    expect(vork).toHaveTextContent('Kanaalplaatvork speciaal')
    expect(vork).toHaveTextContent('Wola b.v. · geen code')
    expect(within(vork).getByTestId('chip-nieuw')).toHaveTextContent('nieuw — controleer naam')
    expect(within(vork).getByRole('button', { name: 'Naam bevestigen: Kanaalplaatvork speciaal' })).toBeInTheDocument()
    // Tabkop-teller (④): signaal mét actie.
    expect(screen.getByTestId('chip-nieuw-controleer')).toHaveTextContent('1 nieuw — controleer')
    // ⑧: geen mens-manipulatie.
    expect(screen.queryByText(/samenvoeg/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/corrigeer/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Telling/ })).not.toBeInTheDocument()
    expect(within(tabel).queryByRole('spinbutton')).not.toBeInTheDocument()
  })

  it('"Naam bevestigen" opent een dialoog mét de factuurtekst als referentie en stuurt alleen de weergavenaam', async () => {
    const gebruiker = userEvent.setup()
    const aangeroepen = stubFetch('boekhouding')
    renderTab()
    await gebruiker.click(await screen.findByRole('button', { name: 'Naam bevestigen: Kanaalplaatvork speciaal' }))
    const dialoog = await screen.findByTestId('naam-dialoog')
    expect(dialoog).toHaveTextContent('factuurtekst: Kanaalplaatvork speciaal')
    const veld = within(dialoog).getByLabelText('Weergavenaam')
    expect(veld).toHaveValue('Kanaalplaatvork speciaal')
    await gebruiker.clear(veld)
    await gebruiker.type(veld, 'Kanaalplaatvork')
    await gebruiker.click(within(dialoog).getByRole('button', { name: 'Naam bevestigen' }))
    await waitFor(() => expect(aangeroepen.some((a) => a.url === `/mini-voorraad/${ADM}/producten/p-vork/naam-bevestigen` && a.method === 'POST')).toBe(true))
    const post = aangeroepen.find((a) => a.url.endsWith('/p-vork/naam-bevestigen'))!
    expect(post.body).toEqual({ weergavenaam: 'Kanaalplaatvork' })
    expect(await screen.findByText('Naam bevestigd: Kanaalplaatvork.')).toBeInTheDocument()
  })

  it('"Voorraadlog ▸" klapt het append-only log uit: datum · getekend aantal · soort · bron-link naar het document · project · gemeld door', async () => {
    const gebruiker = userEvent.setup()
    stubFetch('boekhouding')
    renderTab()
    await gebruiker.click(await screen.findByRole('button', { name: 'Voorraadlog van Stapelbok 1,25×0,85' }))
    const log = await screen.findByTestId('voorraadlog')
    const regels = within(log).getAllByTestId('voorraadlog-regel')
    expect(regels).toHaveLength(2)
    expect(regels[0]).toHaveTextContent('04-09')
    expect(regels[0]).toHaveTextContent('+24')
    expect(regels[0]).toHaveTextContent('instroom')
    const link = within(regels[0]).getByRole('link', { name: /Naar het document/ })
    expect(link).toHaveAttribute('href', `/documenten/${ADM}/${DOC}`)
    expect(link).toHaveTextContent('inkoopfactuur 260630 (Huvanco)')
    expect(regels[0]).toHaveTextContent('project 26127 Tilburg')
    expect(regels[1]).toHaveTextContent('−4')
    expect(regels[1]).toHaveTextContent('beschadiging')
    expect(regels[1]).toHaveTextContent('gemeld door Joost Uitvoerder')
    expect(regels[1]).toHaveTextContent('gevallen bij het lossen')
    expect(within(regels[1]).queryByRole('link')).not.toBeInTheDocument()
  })

  it('"Beschadiging melden…" (⋯-menu) eist een project: zonder project geen POST; mét project gaat wie/waar/wanneer/hoeveel mee', async () => {
    const gebruiker = userEvent.setup()
    const aangeroepen = stubFetch('boekhouding')
    renderTab()
    await gebruiker.click(await screen.findByRole('button', { name: 'Meer acties voor Stapelbok 1,25×0,85' }))
    await gebruiker.click(await screen.findByRole('menuitem', { name: 'Beschadiging melden…' }))
    const dialoog = await screen.findByTestId('beschadiging-dialoog')
    expect(dialoog).toHaveTextContent('huidige stand 96')
    await gebruiker.type(within(dialoog).getByLabelText(/Aantal beschadigd/), '4')
    await gebruiker.click(within(dialoog).getByRole('button', { name: 'Beschadiging vastleggen' }))
    expect(await within(dialoog).findByText('Kies het project waar de beschadiging is ontstaan.')).toBeInTheDocument()
    expect(aangeroepen.some((a) => a.url.endsWith('/beschadigingen'))).toBe(false)

    const combobox = within(dialoog).getByRole('combobox', { name: /Project/ })
    await gebruiker.click(combobox)
    await gebruiker.type(combobox, 'Tilburg')
    await gebruiker.click(await screen.findByRole('option', { name: /26127 Tilburg/ }))
    await gebruiker.click(within(dialoog).getByRole('button', { name: 'Beschadiging vastleggen' }))
    await waitFor(() => expect(aangeroepen.some((a) => a.url === `/mini-voorraad/${ADM}/beschadigingen` && a.method === 'POST')).toBe(true))
    const post = aangeroepen.find((a) => a.url.endsWith('/beschadigingen'))!
    expect(post.body).toMatchObject({ product_id: 'p-stapelbok', aantal: '4', project_id: PROJECT, toelichting: null })
    expect(String((post.body as { datum: string }).datum)).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(await screen.findByText(/Beschadiging vastgelegd voor Stapelbok/)).toBeInTheDocument()
  })

  it('Beheerder ziet "Archiveren…" in het ⋯-menu, reden ≥ 5 tekens verplicht; een niet-Beheerder ziet het niet', async () => {
    const gebruiker = userEvent.setup()
    const aangeroepen = stubFetch('beheerder')
    renderTab()
    await gebruiker.click(await screen.findByRole('button', { name: 'Meer acties voor Stapelbok 1,25×0,85' }))
    await gebruiker.click(await screen.findByRole('menuitem', { name: 'Archiveren…' }))
    const dialoog = await screen.findByTestId('archiveer-dialoog')
    expect(dialoog).toHaveTextContent('er wordt niets verwijderd')
    const knop = within(dialoog).getByRole('button', { name: 'Archiveren' })
    expect(knop).toBeDisabled()
    await gebruiker.type(within(dialoog).getByLabelText('Reden'), 'kort')
    expect(knop).toBeDisabled()
    await gebruiker.type(within(dialoog).getByLabelText('Reden'), ' — eenmalige inkoop')
    await gebruiker.click(knop)
    await waitFor(() => expect(aangeroepen.some((a) => a.url.endsWith('/p-stapelbok/archiveren') && a.method === 'POST')).toBe(true))
    expect(aangeroepen.find((a) => a.url.endsWith('/p-stapelbok/archiveren'))!.body).toEqual({ reden: 'kort — eenmalige inkoop' })
    expect(await screen.findByText(/gearchiveerd — stand en voorraadlog blijven bewaard/)).toBeInTheDocument()
  })

  it('een niet-Beheerder ziet in het ⋯-menu wél "Beschadiging melden…" maar géén "Archiveren…"', async () => {
    const gebruiker = userEvent.setup()
    stubFetch('boekhouding')
    renderTab()
    // Wachten tot de rol bekend is (AuthProvider ververst stil): pas dan is het menu representatief.
    await screen.findByTestId('mini-voorraad-tabel')
    await gebruiker.click(await screen.findByRole('button', { name: 'Meer acties voor Stapelbok 1,25×0,85' }))
    await screen.findByRole('menuitem', { name: 'Beschadiging melden…' })
    expect(screen.queryByRole('menuitem', { name: 'Archiveren…' })).not.toBeInTheDocument()
  })

  it('opt-in uit (409) = leesbare uitleg; geen producten = uitleg dat producten bij het boeken ontstaan', async () => {
    stubFetch('boekhouding', { uit: true })
    const { unmount } = renderTab()
    expect(await screen.findByTestId('mini-voorraad-uit')).toHaveTextContent(MINI_VOORRAAD_UIT_TEKST)
    unmount()
    vi.unstubAllGlobals()
    stubFetch('boekhouding', { items: [] })
    renderTab()
    expect(await screen.findByTestId('mini-voorraad-leeg')).toHaveTextContent(MINI_VOORRAAD_LEEG_TEKST)
  })
})
