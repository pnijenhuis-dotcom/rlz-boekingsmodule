// Crediteuren-dubbelen v2 (design-ronde 03-09, mockup crediteuren-dubbelen-v2.html): kantoorbrede lijst mét chips,
// facetten en tellers; "Voorkeur kiezen & rest archiveren…" opent de dialoog mét kaartgegevens, blokkeert op open
// posten ("eerst afletteren") en toont ná bevestigen de werklijst-melding; "Geen dubbel — afmelden" vraagt een reden.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CrediteurenDubbelenScreen } from './CrediteurenDubbelenScreen'
import type { ClusterDetailDto, ClusterDto, LijstDto, WerklijstDto } from './api'

const ADM = 'aaaaaaaa-0000-0000-0000-000000000001'
const ADM2 = 'aaaaaaaa-0000-0000-0000-000000000002'
const LABO_BV = 'bbbbbbbb-0000-0000-0000-000000000001'
const LABO = 'bbbbbbbb-0000-0000-0000-000000000002'
const HK1 = 'cccccccc-0000-0000-0000-000000000001'
const HK2 = 'cccccccc-0000-0000-0000-000000000002'

const LABO_CLUSTER: ClusterDto = {
  cluster_id: `${ADM}:btw_nummer:BE0424612847`,
  administratie_id: ADM,
  administratie_naam: 'Kempen Facilities B.V.',
  soort: 'btw_nummer',
  sleutel: 'BE0424612847',
  sleutels: [
    { soort: 'btw_nummer', sleutel: 'BE0424612847' },
    { soort: 'naam', sleutel: 'labo derva' },
  ],
  chips: ['zelfde btw-nummer', 'naam ≈'],
  crediteuren: [
    { vendor_id: LABO, naam: 'Labo Derva', btw_nummer: null, kvk_nummer: null, ibans: [], aantal_boekingen: 2, laatst_geboekt: '2026-08-12' },
    { vendor_id: LABO_BV, naam: 'Labo Derva B.V.', btw_nummer: 'BE0424612847', kvk_nummer: null, ibans: ['BE68539007547034'], aantal_boekingen: 14, laatst_geboekt: '2026-09-01' },
  ],
  aantal_boekingen: 16,
  laatst_geboekt: '2026-09-01',
  kvk_verschilt: false,
  afmelden_primair: false,
  voorkeur_suggestie: LABO_BV,
  klaargezet: null,
}

const HK_CLUSTER: ClusterDto = {
  cluster_id: `${ADM2}:naam:hello kitchen`,
  administratie_id: ADM2,
  administratie_naam: 'Universal Steigerbouw B.V.',
  soort: 'naam',
  sleutel: 'hello kitchen',
  sleutels: [{ soort: 'naam', sleutel: 'hello kitchen' }],
  chips: ['naam ≈', 'verschillend KvK — géén dubbel'],
  crediteuren: [
    { vendor_id: HK1, naam: 'Hello Kitchen (Duiven)', btw_nummer: null, kvk_nummer: '11111111', ibans: [], aantal_boekingen: 0, laatst_geboekt: null },
    { vendor_id: HK2, naam: 'Hello Kitchen Son', btw_nummer: null, kvk_nummer: '22222222', ibans: [], aantal_boekingen: 1, laatst_geboekt: '2026-09-02' },
  ],
  aantal_boekingen: 1,
  laatst_geboekt: '2026-09-02',
  kvk_verschilt: true,
  afmelden_primair: true,
  voorkeur_suggestie: HK2,
  klaargezet: null,
}

const LIJST: LijstDto = {
  rijen: [LABO_CLUSTER, HK_CLUSTER],
  totaal: 2,
  pagina: 1,
  per_pagina: 25,
  tellers: { clusters: 2, klaargezet: 0, administraties: 2 },
  facetten: {
    administraties: [
      { administratie_id: ADM, naam: 'Kempen Facilities B.V.', aantal: 1 },
      { administratie_id: ADM2, naam: 'Universal Steigerbouw B.V.', aantal: 1 },
    ],
    sleutels: { btw_nummer: 1, naam: 1 },
  },
}

const WERKLIJST_LEEG: WerklijstDto = { regels: [], open: 0, gedaan: 0 }

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function stubFetch(opties: { detail: ClusterDetailDto; archiveerStatus?: number }) {
  const aangeroepen: { pad: string; method: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      aangeroepen.push({ pad: url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined })
      if (url.startsWith('/crediteuren/dubbelen?')) return Promise.resolve(jsonResponse(LIJST))
      if (url === '/crediteuren/werklijst') return Promise.resolve(jsonResponse(WERKLIJST_LEEG))
      if (url.includes('/cluster-detail?')) return Promise.resolve(jsonResponse(opties.detail))
      if (url.endsWith('/archiveer') && method === 'POST') {
        if (opties.archiveerStatus === 409) {
          return Promise.resolve(jsonResponse({ detail: { bericht: '1 open post(en) — eerst afletteren', open_posten: {} } }, 409))
        }
        return Promise.resolve(
          jsonResponse({
            werklijst_id: 'w-1',
            voorkeur_naam: 'Labo Derva B.V.',
            te_archiveren_namen: ['Labo Derva'],
            geheugen_verhuisd: 2,
            kenmerk_verhuisd: false,
            ibans_verhuisd: 0,
            al_klaargezet: false,
            melding: 'klaargezet — archiveer in RLZ: Labo Derva',
          }),
        )
      }
      if (url.endsWith('/afmelden') && method === 'POST') return Promise.resolve(jsonResponse({ afmelding_id: 'a-1' }))
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
  return aangeroepen
}

const DETAIL_SCHOON: ClusterDetailDto = {
  administratie_id: ADM,
  administratie_naam: 'Kempen Facilities B.V.',
  crediteuren: LABO_CLUSTER.crediteuren,
  voorkeur_suggestie: LABO_BV,
  open_posten: { [LABO]: [], [LABO_BV]: [] },
  toets_ok: true,
  toets_fout: null,
}

function renderScherm() {
  return render(
    <MemoryRouter initialEntries={['/crediteuren']}>
      <CrediteurenDubbelenScreen />
    </MemoryRouter>,
  )
}

describe('CrediteurenDubbelenScreen (crediteuren-dubbelen v2, 03-09)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('toont kantoorbreed clusters mét chips, kaartgegevens, teller en facetten; primaire knop per rij volgt de sleutel', async () => {
    stubFetch({ detail: DETAIL_SCHOON })
    renderScherm()
    const tabel = await screen.findByTestId('clusters-tabel')
    expect(screen.getByTestId('clusters-chip')).toHaveTextContent('2 clusters')
    expect(screen.getByText(/over 2 administraties/)).toBeInTheDocument()
    expect(within(tabel).getByText('Labo Derva / Labo Derva B.V.')).toBeInTheDocument()
    expect(within(tabel).getByText('zelfde btw-nummer')).toBeInTheDocument()
    expect(within(tabel).getByText('verschillend KvK — géén dubbel')).toBeInTheDocument()
    expect(within(tabel).getByText(/14 boekingen/)).toBeInTheDocument()
    // btw-cluster: primaire (teal) actie = archiveren; naam-cluster mét verschillend KvK: secundair afmelden.
    expect(within(tabel).getByRole('button', { name: /Voorkeur kiezen & rest archiveren: Labo Derva/ })).toBeInTheDocument()
    expect(within(tabel).getByRole('button', { name: /Geen dubbel — afmelden: Hello Kitchen/ })).toBeInTheDocument()
    expect(within(tabel).queryByRole('button', { name: /Geen dubbel — afmelden: Labo Derva/ })).toBeNull()
    // Facet Sleutel toont de tellers per sleutel.
    const sleutelFacet = screen.getByLabelText('Sleutel') as HTMLSelectElement
    expect(within(sleutelFacet).getByRole('option', { name: 'btw-nummer (1)' })).toBeInTheDocument()
    expect(screen.getByTestId('rlz-werklijst')).toHaveTextContent('Niets klaargezet')
  })

  it('archiveer-dialoog: voorkeur vooringevuld, bevestigen POST voorkeur + overige en toont de werklijst-melding', async () => {
    const aangeroepen = stubFetch({ detail: DETAIL_SCHOON })
    renderScherm()
    const tabel = await screen.findByTestId('clusters-tabel')
    await userEvent.click(within(tabel).getByRole('button', { name: /Voorkeur kiezen & rest archiveren: Labo Derva/ }))
    const dialoog = await screen.findByTestId('archiveer-dialoog')
    const radioBv = (await within(dialoog).findByRole('radio', { name: 'Voorkeur: Labo Derva B.V.' })) as HTMLInputElement
    expect(radioBv.checked).toBe(true)
    expect(within(dialoog).getByText('voorkeur (meest gebruikt)')).toBeInTheDocument()
    expect(within(dialoog).getByText('wordt gearchiveerd')).toBeInTheDocument()
    const bevestig = within(dialoog).getByRole('button', { name: /Klaarzetten: archiveer de andere in RLZ/ })
    await waitFor(() => expect(bevestig).toBeEnabled())
    await userEvent.click(bevestig)
    await waitFor(() => expect(aangeroepen.some((a) => a.pad.endsWith('/archiveer') && a.method === 'POST')).toBe(true))
    const post = aangeroepen.find((a) => a.pad.endsWith('/archiveer'))!
    expect(post.pad).toBe(`/crediteuren/dubbelen/${ADM}/archiveer`)
    expect(post.body).toEqual({ voorkeur_vendor_id: LABO_BV, overige_vendor_ids: [LABO] })
    expect(await screen.findByTestId('archiveer-uitkomst')).toHaveTextContent('klaargezet — archiveer in RLZ: Labo Derva')
  })

  it('archiveer-dialoog: open posten op de te archiveren crediteur blokkeren ("eerst afletteren"); toets mislukt = geen bevestigen', async () => {
    stubFetch({
      detail: {
        ...DETAIL_SCHOON,
        open_posten: { [LABO]: [{ rlz_document_id: 'f-1', referentie: 'F-2026-17', datum: '2026-08-01', open_bedrag: '121.00' }], [LABO_BV]: [] },
      },
    })
    renderScherm()
    const tabel = await screen.findByTestId('clusters-tabel')
    await userEvent.click(within(tabel).getByRole('button', { name: /Voorkeur kiezen & rest archiveren: Labo Derva/ }))
    const dialoog = await screen.findByTestId('archiveer-dialoog')
    const blokkade = await within(dialoog).findByTestId('open-posten-blokkade')
    expect(blokkade).toHaveTextContent('1 open post — eerst afletteren')
    expect(blokkade).toHaveTextContent('F-2026-17')
    expect(blokkade).toHaveTextContent('€ 121,00 open')
    expect(within(dialoog).getByRole('button', { name: /Klaarzetten/ })).toBeDisabled()
    // Andere voorkeur kiezen: dan is Labo Derva B.V. de te archiveren crediteur — zonder open posten → wél toegestaan.
    await userEvent.click(within(dialoog).getByRole('radio', { name: 'Voorkeur: Labo Derva' }))
    expect(within(dialoog).queryByTestId('open-posten-blokkade')).toBeNull()
    expect(within(dialoog).getByRole('button', { name: /Klaarzetten/ })).toBeEnabled()
  })

  it('toets mislukt (RLZ onbereikbaar) = fail-closed: melding + opnieuw toetsen, bevestigen uit', async () => {
    stubFetch({ detail: { ...DETAIL_SCHOON, open_posten: {}, toets_ok: false, toets_fout: 'Open-posten-toets in Reeleezee mislukt: 503' } })
    renderScherm()
    const tabel = await screen.findByTestId('clusters-tabel')
    await userEvent.click(within(tabel).getByRole('button', { name: /Voorkeur kiezen & rest archiveren: Labo Derva/ }))
    const dialoog = await screen.findByTestId('archiveer-dialoog')
    expect(await within(dialoog).findByTestId('toets-mislukt')).toHaveTextContent('eerst opnieuw proberen')
    expect(within(dialoog).getByRole('button', { name: /Klaarzetten/ })).toBeDisabled()
    expect(within(dialoog).getByRole('button', { name: 'Opnieuw toetsen' })).toBeInTheDocument()
  })

  it('afmelden vraagt een reden (verplicht) en POST vendor_ids + reden', async () => {
    const aangeroepen = stubFetch({ detail: DETAIL_SCHOON })
    renderScherm()
    const tabel = await screen.findByTestId('clusters-tabel')
    await userEvent.click(within(tabel).getByRole('button', { name: /Geen dubbel — afmelden: Hello Kitchen/ }))
    const dialoog = await screen.findByTestId('afmeld-dialoog')
    const reden = within(dialoog).getByLabelText('Reden') as HTMLInputElement
    // Vooringevuld bij verschillend KvK; leegmaken = knop uit (reden verplicht).
    expect(reden.value).toContain('KvK')
    await userEvent.clear(reden)
    expect(within(dialoog).getByRole('button', { name: 'Afmelden' })).toBeDisabled()
    await userEvent.type(reden, 'Twee vestigingen, eigen KvK')
    await userEvent.click(within(dialoog).getByRole('button', { name: 'Afmelden' }))
    await waitFor(() => expect(aangeroepen.some((a) => a.pad.endsWith('/afmelden') && a.method === 'POST')).toBe(true))
    const post = aangeroepen.find((a) => a.pad.endsWith('/afmelden'))!
    expect(post.pad).toBe(`/crediteuren/dubbelen/${ADM2}/afmelden`)
    expect(post.body).toEqual({ vendor_ids: [HK1, HK2], reden: 'Twee vestigingen, eigen KvK' })
  })

  it('⋯-menu: bij een btw-cluster staat afmelden in het menu, nooit primair', async () => {
    stubFetch({ detail: DETAIL_SCHOON })
    renderScherm()
    const tabel = await screen.findByTestId('clusters-tabel')
    await userEvent.click(within(tabel).getByRole('button', { name: /Meer acties voor Labo Derva/ }))
    const menu = await screen.findByRole('menu', { name: /Acties voor Labo Derva/ })
    expect(within(menu).getByRole('menuitem', { name: 'Geen dubbel — afmelden…' })).toBeInTheDocument()
    await userEvent.click(within(menu).getByRole('menuitem', { name: 'Geen dubbel — afmelden…' }))
    expect(await screen.findByTestId('afmeld-dialoog')).toBeInTheDocument()
  })
})
