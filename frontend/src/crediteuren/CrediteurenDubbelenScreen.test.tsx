// Crediteuren-dubbelen schaalbaar (blok B13 07-09): kantoorbrede lijst mét classificatie-chip per cluster en teller
// "N twijfelclusters"; knop "Eenduidige clusters automatisch afhandelen (N)" opent een dialoog mét dry-run-preview
// (aantallen per administratie) en POST daarna dry_run=false; "Voorkeur kiezen…" (radio, geen RLZ-toets) POST voorkeur +
// verliezers; ⋯-menu op het paneel: CSV-export via fetch+blob en "Afgehandeld tonen" mét terugdraaien (reden verplicht);
// "Geen dubbel — afmelden" vraagt een reden. Geen RLZ-werklijst-paneel meer.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CrediteurenDubbelenScreen } from './CrediteurenDubbelenScreen'
import type { AfhandelingenDto, AutoRunDto, ClusterDetailDto, ClusterDto, LijstDto } from './api'

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
  eenduidig: true,
  classificatie_reden: 'eenduidig: identieke naam, geen conflicterend KvK/btw, verliezer(s) hooguit 2 boeking(en) (≤ 3)',
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
  eenduidig: false,
  classificatie_reden: 'twijfel: verschillend KvK-nummer',
}

const LIJST: LijstDto = {
  rijen: [LABO_CLUSTER, HK_CLUSTER],
  totaal: 2,
  pagina: 1,
  per_pagina: 25,
  tellers: { clusters: 1, eenduidig: 1, administraties: 2 },
  facetten: {
    administraties: [
      { administratie_id: ADM, naam: 'Kempen Facilities B.V.', aantal: 1 },
      { administratie_id: ADM2, naam: 'Universal Steigerbouw B.V.', aantal: 1 },
    ],
    sleutels: { btw_nummer: 1, naam: 1 },
  },
}

const DETAIL: ClusterDetailDto = {
  administratie_id: ADM,
  administratie_naam: 'Kempen Facilities B.V.',
  crediteuren: LABO_CLUSTER.crediteuren,
  voorkeur_suggestie: LABO_BV,
  eenduidig: true,
  classificatie_reden: LABO_CLUSTER.classificatie_reden,
}

const PREVIEW: AutoRunDto = {
  run_id: 'run-1',
  dry_run: true,
  eenduidig: 1,
  twijfel: 1,
  afgehandeld: 0,
  fouten: 0,
  administraties: [
    {
      administratie_id: ADM,
      administratie_naam: 'Kempen Facilities B.V.',
      eenduidig: 1,
      twijfel: 0,
      afgehandeld: 0,
      fouten: 0,
      voorbeelden: [{ cluster_id: LABO_CLUSTER.cluster_id, voorkeur_naam: 'Labo Derva B.V.', verliezer_namen: ['Labo Derva'], reden: LABO_CLUSTER.classificatie_reden, afgehandeld: false, fout: null }],
    },
    { administratie_id: ADM2, administratie_naam: 'Universal Steigerbouw B.V.', eenduidig: 0, twijfel: 1, afgehandeld: 0, fouten: 0, voorbeelden: [] },
  ],
}

const AFHANDELINGEN: AfhandelingenDto = {
  regels: [
    {
      id: 'afh-1',
      administratie_id: ADM,
      administratie_naam: 'Kempen Facilities B.V.',
      bron: 'auto',
      voorkeur_vendor_id: LABO_BV,
      voorkeur_naam: 'Labo Derva B.V.',
      verliezers: [{ vendor_id: LABO, naam: 'Labo Derva' }],
      sleutels: [{ soort: 'naam', sleutel: 'labo derva' }],
      classificatie_reden: LABO_CLUSTER.classificatie_reden,
      geheugen_verhuisd: 2,
      kenmerk_verhuisd: false,
      ibans_verhuisd: 0,
      boekvoorstellen_hervertaald: 1,
      afgehandeld_op: '2026-09-07T10:00:00Z',
      teruggedraaid_op: null,
      teruggedraaid_reden: null,
    },
  ],
  actief: 1,
  teruggedraaid: 0,
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function stubFetch() {
  const aangeroepen: { pad: string; method: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      aangeroepen.push({ pad: url, method, body })
      if (url.startsWith('/crediteuren/dubbelen?')) return Promise.resolve(jsonResponse(LIJST))
      if (url === '/crediteuren/dubbelen/auto-afhandelen' && method === 'POST') {
        const echt: AutoRunDto = {
          ...PREVIEW,
          dry_run: false,
          afgehandeld: 1,
          administraties: PREVIEW.administraties.map((a) => (a.eenduidig ? { ...a, afgehandeld: a.eenduidig } : a)),
        }
        return Promise.resolve(jsonResponse(body.dry_run ? PREVIEW : echt))
      }
      if (url.includes('/cluster-detail?')) return Promise.resolve(jsonResponse(DETAIL))
      if (url.endsWith('/afhandelen') && method === 'POST') {
        return Promise.resolve(
          jsonResponse({
            afhandeling_id: 'afh-2',
            voorkeur_naam: 'Labo Derva B.V.',
            verliezer_namen: ['Labo Derva'],
            geheugen_verhuisd: 2,
            kenmerk_verhuisd: false,
            ibans_verhuisd: 0,
            boekvoorstellen_hervertaald: 0,
            melding: 'afgehandeld — Labo Derva is in de module onbruikbaar; voorkeur Labo Derva B.V.',
          }),
        )
      }
      if (url.endsWith('/afmelden') && method === 'POST') return Promise.resolve(jsonResponse({ afmelding_id: 'a-1' }))
      if (url === '/crediteuren/afhandelingen') return Promise.resolve(jsonResponse(AFHANDELINGEN))
      if (url.endsWith('/terugdraaien') && method === 'POST') {
        return Promise.resolve(jsonResponse({ ...AFHANDELINGEN.regels[0], teruggedraaid_op: '2026-09-07T11:00:00Z', teruggedraaid_reden: body.reden }))
      }
      if (url === '/crediteuren/opruimlijst.csv') {
        return Promise.resolve(new Response('administratie;voorkeur;verliezer\r\n', { status: 200, headers: { 'Content-Type': 'text/csv; charset=utf-8' } }))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
  return aangeroepen
}

function renderScherm() {
  return render(
    <MemoryRouter initialEntries={['/crediteuren']}>
      <CrediteurenDubbelenScreen />
    </MemoryRouter>,
  )
}

describe('CrediteurenDubbelenScreen (crediteuren-dubbelen schaalbaar, B13 07-09)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('toont clusters mét classificatie-chip, teller twijfelclusters, auto-knop mét aantal en géén RLZ-werklijst-paneel', async () => {
    stubFetch()
    renderScherm()
    const tabel = await screen.findByTestId('clusters-tabel')
    expect(screen.getByTestId('clusters-chip')).toHaveTextContent('1 twijfelcluster')
    expect(screen.getByText(/over 2 administraties/)).toBeInTheDocument()
    expect(screen.getByTestId('auto-knop')).toHaveTextContent('Eenduidige clusters automatisch afhandelen (1)')
    expect(within(tabel).getByText('Labo Derva / Labo Derva B.V.')).toBeInTheDocument()
    const chips = within(tabel).getAllByTestId('classificatie-chip')
    expect(chips[0]).toHaveTextContent('eenduidig — systeem')
    expect(chips[1]).toHaveTextContent('twijfel — mens')
    expect(within(tabel).getByText(/verschillend KvK-nummer/)).toBeInTheDocument()
    // Primaire actie: "Voorkeur kiezen…" bij het eenduidige cluster; afmelden bij verschillend KvK.
    expect(within(tabel).getByRole('button', { name: /Voorkeur kiezen: Labo Derva/ })).toBeInTheDocument()
    expect(within(tabel).getByRole('button', { name: /Geen dubbel — afmelden: Hello Kitchen/ })).toBeInTheDocument()
    expect(screen.queryByTestId('rlz-werklijst')).toBeNull()
    expect(screen.queryByText(/klaargezet/)).toBeNull()
    // Classificatie-facet.
    const facet = screen.getByLabelText('Classificatie') as HTMLSelectElement
    expect(within(facet).getByRole('option', { name: 'Twijfel (mens) (1)' })).toBeInTheDocument()
  })

  it('auto-afhandelen: dialoog laadt dry-run-preview per administratie, bevestigen POST dry_run=false en toont de uitkomst', async () => {
    const aangeroepen = stubFetch()
    renderScherm()
    await userEvent.click(await screen.findByTestId('auto-knop'))
    const dialoog = await screen.findByTestId('auto-dialoog')
    const preview = await within(dialoog).findByTestId('auto-preview')
    expect(preview).toHaveTextContent('1 cluster eenduidig over 1 administratie')
    expect(preview).toHaveTextContent('1 twijfel blijft voor u')
    expect(within(preview).getByText('Kempen Facilities B.V.')).toBeInTheDocument()
    // Preview = dry_run:true; niets gewijzigd.
    const dry = aangeroepen.filter((a) => a.pad === '/crediteuren/dubbelen/auto-afhandelen')
    expect(dry).toHaveLength(1)
    expect(dry[0].body).toEqual({ dry_run: true, administratie_id: null })
    const bevestig = within(dialoog).getByRole('button', { name: 'Afhandelen (1)' })
    await userEvent.click(bevestig)
    await waitFor(() => expect(aangeroepen.filter((a) => a.pad === '/crediteuren/dubbelen/auto-afhandelen')).toHaveLength(2))
    const echt = aangeroepen.filter((a) => a.pad === '/crediteuren/dubbelen/auto-afhandelen')[1]
    expect(echt.body).toEqual({ dry_run: false, administratie_id: null })
    expect(await screen.findByTestId('afhandel-uitkomst')).toHaveTextContent('1 cluster automatisch afgehandeld over 1 administratie')
  })

  it('voorkeur kiezen: dialoog zonder RLZ-toets, voorkeur vooringevuld, POST voorkeur + verliezers en toont de melding', async () => {
    const aangeroepen = stubFetch()
    renderScherm()
    const tabel = await screen.findByTestId('clusters-tabel')
    await userEvent.click(within(tabel).getByRole('button', { name: /Voorkeur kiezen: Labo Derva/ }))
    const dialoog = await screen.findByTestId('afhandel-dialoog')
    const radioBv = (await within(dialoog).findByRole('radio', { name: 'Voorkeur: Labo Derva B.V.' })) as HTMLInputElement
    expect(radioBv.checked).toBe(true)
    expect(within(dialoog).getByText('wordt onbruikbaar in de module')).toBeInTheDocument()
    expect(await within(dialoog).findByTestId('detail-classificatie')).toHaveTextContent('eenduidig')
    expect(within(dialoog).queryByText(/eerst afletteren/)).toBeNull()
    const bevestig = within(dialoog).getByRole('button', { name: /Afhandelen: de andere wordt onbruikbaar/ })
    await waitFor(() => expect(bevestig).toBeEnabled())
    await userEvent.click(bevestig)
    await waitFor(() => expect(aangeroepen.some((a) => a.pad.endsWith('/afhandelen') && a.method === 'POST')).toBe(true))
    const post = aangeroepen.find((a) => a.pad.endsWith('/afhandelen'))!
    expect(post.pad).toBe(`/crediteuren/dubbelen/${ADM}/afhandelen`)
    expect(post.body).toEqual({ voorkeur_vendor_id: LABO_BV, verliezer_vendor_ids: [LABO] })
    expect(await screen.findByTestId('afhandel-uitkomst')).toHaveTextContent('afgehandeld — Labo Derva is in de module onbruikbaar')
  })

  it('⋯-menu op het paneel: CSV-export via fetch (geen navigatie) en "Afgehandeld tonen" mét terugdraaien (reden verplicht)', async () => {
    const aangeroepen = stubFetch()
    const createObjectURL = vi.fn(() => 'blob:opruimlijst')
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL })
    renderScherm()
    await screen.findByTestId('clusters-tabel')
    await userEvent.click(screen.getByRole('button', { name: 'Meer acties voor crediteuren' }))
    const menu = await screen.findByRole('menu', { name: 'Acties voor crediteuren' })
    await userEvent.click(within(menu).getByRole('menuitem', { name: 'Exporteer RLZ-opruimlijst (CSV)' }))
    await waitFor(() => expect(aangeroepen.some((a) => a.pad === '/crediteuren/opruimlijst.csv')).toBe(true))
    await waitFor(() => expect(createObjectURL).toHaveBeenCalled())

    await userEvent.click(screen.getByRole('button', { name: 'Meer acties voor crediteuren' }))
    await userEvent.click(within(await screen.findByRole('menu', { name: 'Acties voor crediteuren' })).getByRole('menuitem', { name: 'Afgehandeld tonen (terugdraaien)' }))
    const paneel = await screen.findByTestId('afgehandeld-paneel')
    expect(await within(paneel).findByText('Labo Derva B.V.')).toBeInTheDocument()
    expect(within(paneel).getByText('systeem')).toBeInTheDocument()
    await userEvent.click(within(paneel).getByRole('button', { name: /Terugdraaien: Labo Derva B.V./ }))
    const dialoog = await screen.findByTestId('terugdraai-dialoog')
    expect(within(dialoog).getByRole('button', { name: 'Terugdraaien' })).toBeDisabled()
    await userEvent.type(within(dialoog).getByLabelText('Reden'), 'Toch twee bedrijven')
    await userEvent.click(within(dialoog).getByRole('button', { name: 'Terugdraaien' }))
    await waitFor(() => expect(aangeroepen.some((a) => a.pad === '/crediteuren/afhandelingen/afh-1/terugdraaien' && a.method === 'POST')).toBe(true))
    expect(aangeroepen.find((a) => a.pad.endsWith('/terugdraaien'))!.body).toEqual({ reden: 'Toch twee bedrijven' })
  })

  it('afmelden vraagt een reden (verplicht) en POST vendor_ids + reden', async () => {
    const aangeroepen = stubFetch()
    renderScherm()
    const tabel = await screen.findByTestId('clusters-tabel')
    await userEvent.click(within(tabel).getByRole('button', { name: /Geen dubbel — afmelden: Hello Kitchen/ }))
    const dialoog = await screen.findByTestId('afmeld-dialoog')
    const reden = within(dialoog).getByLabelText('Reden') as HTMLInputElement
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

  it('⋯-rijmenu: bij een eenduidig cluster staat afmelden in het menu, nooit primair', async () => {
    stubFetch()
    renderScherm()
    const tabel = await screen.findByTestId('clusters-tabel')
    await userEvent.click(within(tabel).getByRole('button', { name: /Meer acties voor Labo Derva/ }))
    const menu = await screen.findByRole('menu', { name: /Acties voor Labo Derva/ })
    expect(within(menu).getByRole('menuitem', { name: 'Geen dubbel — afmelden…' })).toBeInTheDocument()
    await userEvent.click(within(menu).getByRole('menuitem', { name: 'Geen dubbel — afmelden…' }))
    expect(await screen.findByTestId('afmeld-dialoog')).toBeInTheDocument()
  })
})
