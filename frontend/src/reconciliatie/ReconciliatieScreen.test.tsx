import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../auth/AuthContext'
import { ReconciliatieScreen } from './ReconciliatieScreen'
import type { BevindingDto, BevindingenLijstDto, ReconciliatieRunDto } from './reconciliatieApi'

// Inzicht › Reconciliatie KANTOORBREED (opdracht 06-09 blok C, mockup inzicht-kantoorbreed ①②③⑨):
// één lijst over alle administraties (server sorteert/pagineert), chips + facetten + zoekveld, één
// handeling per rij (accepteren / gezien / toch tonen) mét VERPLICHTE inhoudelijke reden, en
// "▶ Nu draaien" als achtergrondrun met status-poll (Beheerder). De client formatteert alleen.

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

const AFWIJKING: BevindingDto = {
  id: 'r1',
  run_id: RUN_ID,
  blok: 'bank',
  soort: 'afwijking',
  administratie_id: ADMIN_A,
  administratie_naam: 'Kempen Facilities B.V.',
  vingerafdruk: 'bank:mut-1',
  tekst: 'record=aaaaaaaa-1111-2222-3333-444444444444 mutatie=bbbbbbbb-1111-2222-3333-444444444444 soort=aflettering_teruggedraaid_in_rlz [vaf:bank:mut-1]: OpenAmount=1240.00',
  titel: 'Aflettering teruggedraaid in RLZ — Shell · € 1.240,00 · 01-09-2026',
  wat: 'Wij letterden de bankmutatie van 01-09-2026 (Shell, € 1.240,00) af; in RLZ staat er weer € 1.240,00 open.',
  doe: 'Letter opnieuw af in het bankscherm, of accepteer met reden.',
  details: [
    { label: 'vingerafdruk', waarde: 'bank:mut-1' },
    { label: 'RLZ-mutatie', waarde: 'bbbbbbbb-1111-2222-3333-444444444444' },
    { label: 'ruwe regel', waarde: 'record=aaaaaaaa-1111-2222-3333-444444444444 mutatie=bbbbbbbb-1111-2222-3333-444444444444 soort=aflettering_teruggedraaid_in_rlz [vaf:bank:mut-1]: OpenAmount=1240.00' },
  ],
  sinds: '2026-09-05T05:00:00Z',
  nieuw: true,
  acceptatie: null,
  gezien: null,
  detail: { afwijking_soort: 'open_in_rlz', bron: 'bank' },
  doel_pad: `/?administratie=${ADMIN_A}&document=doc-1`,
}
const LET_OP: BevindingDto = {
  id: 'r2',
  run_id: RUN_ID,
  blok: 'doorbelasting',
  soort: 'let_op',
  administratie_id: ADMIN_B,
  administratie_naam: 'Universal Steigerbouw B.V.',
  vingerafdruk: 'db:concept-7',
  tekst: 'LET-OP     opruim-kandidaat [gestorneerd] verkoop_bron cccccccc-1111-2222-3333-444444444444 in administratie bbbbbbbb-0000-0000-0000-000000000002',
  titel: 'Achtergebleven concept in RLZ — Universal Steigerbouw B.V.',
  wat: 'Een verkoop-concept in de bron-administratie van een gestorneerde doorbelasting (ref 24713188) staat nog in Reeleezee — het telt nergens mee, maar vervuilt de administratie.',
  doe: "Opruimen is klikwerk in Reeleezee (de app verwijdert nooit); 'Gezien' met reden haalt 'm uit de teller.",
  details: [{ label: 'vingerafdruk', waarde: 'db:concept-7' }],
  sinds: '2026-09-04T05:00:00Z',
  nieuw: false,
  acceptatie: null,
  gezien: null,
  detail: { reden: 'concept blijft staan na storno' },
  doel_pad: `/doorbelasting/${ADMIN_B}/doc-2`,
}
const FOUT: BevindingDto = {
  id: 'r3',
  run_id: RUN_ID,
  blok: 'run',
  soort: 'fout',
  administratie_id: null,
  administratie_naam: null,
  vingerafdruk: 'run:502',
  tekst: 'FOUT       omzet-reconciliatie viel om: Reeleezee niet bereikbaar (502)',
  titel: 'Controle omzet viel om',
  wat: 'Het blok omzet is niet gedraaid: Reeleezee niet bereikbaar (502).',
  doe: 'Niets is gecontroleerd in dit blok; de volgende run probeert opnieuw. Blijft het, dan is het een storing.',
  details: [{ label: 'vingerafdruk', waarde: 'run:502' }],
  sinds: '2026-09-05T05:00:00Z',
  nieuw: false,
  acceptatie: null,
  gezien: null,
  detail: null,
  doel_pad: null,
}

function run(status: ReconciliatieRunDto['status'], extra: Partial<ReconciliatieRunDto> = {}): ReconciliatieRunDto {
  return {
    run_id: RUN_ID,
    status,
    bron: 'handmatig',
    aangevraagd_op: '2026-09-06T08:00:00Z',
    gestart_op: null,
    afgerond_op: null,
    exit_code: null,
    samenvatting: null,
    fout_reden: null,
    mail_status: null,
    mail_detail: null,
    ...extra,
  }
}

function lijst(rijen: BevindingDto[] = [AFWIJKING, LET_OP, FOUT], extra: Partial<BevindingenLijstDto> = {}): BevindingenLijstDto {
  return {
    rijen,
    totaal: rijen.length,
    pagina: 1,
    per_pagina: 25,
    administraties_in_selectie: 2,
    tellers: { afwijkingen: 3, let_op: 2, fouten: 1, geaccepteerd: 4, uitgesloten: 1, gezien: 0, administraties: 2 },
    facetten: {
      soort: { aandacht: 6, afwijking: 3, let_op: 2, fout: 1, geaccepteerd: 4, uitgesloten: 1, gezien: 0, alle: 11 },
      administraties: [
        { administratie_id: ADMIN_A, naam: 'Kempen Facilities B.V.', aantal: 1 },
        { administratie_id: ADMIN_B, naam: 'Universal Steigerbouw B.V.', aantal: 1 },
      ],
    },
    laatste_run: run('klaar', { afgerond_op: '2026-09-06T04:12:00Z', exit_code: 1, mail_status: 'verzonden' }),
    ...extra,
  }
}

interface StubOpties {
  runStatussen?: ReconciliatieRunDto[]
  lijstAntwoord?: BevindingenLijstDto | (() => BevindingenLijstDto)
  actieStatus?: number
  actieDetail?: string
}

function stubFetch(rol = 'boekhouding', opties: StubOpties = {}) {
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
          jsonResponse({
            administraties: [
              { id: ADMIN_A, naam: 'Kempen Facilities B.V.' },
              { id: ADMIN_B, naam: 'Universal Steigerbouw B.V.' },
            ],
          }),
        )
      }
      if (url.startsWith('/reconciliatie/bevindingen?')) {
        const antwoord = typeof opties.lijstAntwoord === 'function' ? opties.lijstAntwoord() : opties.lijstAntwoord
        return Promise.resolve(jsonResponse(antwoord ?? lijst()))
      }
      if (url === '/reconciliatie/run/laatste') return Promise.resolve(jsonResponse(null))
      if (url === '/reconciliatie/run' && method === 'POST') return Promise.resolve(jsonResponse(run('wachtend'), 202))
      if (url === `/reconciliatie/run/${RUN_ID}`) {
        return Promise.resolve(jsonResponse(statussen.shift() ?? run('klaar', { afgerond_op: '2026-09-06T08:01:00Z', exit_code: 0, mail_status: 'niet_nodig' })))
      }
      if (url === '/reconciliatie/instelling') return Promise.resolve(jsonResponse({ gezien_dagen: method === 'PUT' ? 21 : 14 }))
      if (url.startsWith('/reconciliatie/bevindingen/')) {
        if (opties.actieStatus) return Promise.resolve(jsonResponse({ detail: opties.actieDetail ?? 'Mislukt' }, opties.actieStatus))
        return Promise.resolve(jsonResponse({ id: url.split('/')[3] }))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
  return aangeroepen
}

function renderScherm(pad = '/reconciliatie', pollMs = 5) {
  return render(
    <MemoryRouter initialEntries={[pad]}>
      <AuthProvider>
        <ReconciliatieScreen pollMs={pollMs} />
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('ReconciliatieScreen (kantoorbreed)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('toont chips, één rij per bevinding mét blok/sinds/deep-link en de voet; facet en zoekterm gaan naar de server', async () => {
    const aangeroepen = stubFetch()
    renderScherm()
    const tabel = await screen.findByTestId('reconciliatie-tabel')
    expect(screen.getByTestId('chip-afwijkingen')).toHaveTextContent('3 afwijkingen')
    expect(screen.getByTestId('chip-let-op')).toHaveTextContent('2 let-op')
    expect(screen.getByTestId('chip-fouten')).toHaveTextContent('1 fouten')
    // Eerste lijst-call: default facet "aandacht nodig", geen administratie, pagina 1.
    expect(aangeroepen.find((a) => a.pad.startsWith('/reconciliatie/bevindingen?'))!.pad).toBe(
      '/reconciliatie/bevindingen?pagina=1&soort=aandacht',
    )
    const rijen = within(tabel).getAllByTestId('reconciliatie-rij')
    expect(rijen).toHaveLength(3)
    // Afwijking: administratie-link, blok, LEESBARE titel (vet) + wat + doe (blok A8, 07-09), chip "nieuw", deep-link.
    expect(within(rijen[0]).getByRole('link', { name: 'Kempen Facilities B.V.' })).toHaveAttribute('href', `/?administratie=${ADMIN_A}`)
    expect(within(rijen[0]).getByText('Bank')).toBeInTheDocument()
    expect(within(rijen[0]).getByTestId('bevinding-titel')).toHaveTextContent('Aflettering teruggedraaid in RLZ — Shell · € 1.240,00 · 01-09-2026')
    expect(within(rijen[0]).getByTestId('bevinding-titel').querySelector('strong')).toHaveTextContent('Aflettering teruggedraaid in RLZ')
    expect(within(rijen[0]).getByTestId('bevinding-wat')).toHaveTextContent('Wij letterden de bankmutatie van 01-09-2026 (Shell, € 1.240,00) af')
    expect(within(rijen[0]).getByTestId('bevinding-doe')).toHaveTextContent('→ Letter opnieuw af in het bankscherm, of accepteer met reden.')
    // De ruwe CLI-regel mét GUID's staat NIET in titel/wat/doe, alleen in de uitklap "details".
    for (const id of ['bevinding-titel', 'bevinding-wat', 'bevinding-doe']) {
      expect(within(rijen[0]).getByTestId(id)).not.toHaveTextContent(/record=|\[vaf:/)
    }
    const uitklap = within(rijen[0]).getByTestId('bevinding-details')
    expect(within(uitklap).getByText(/^record=aaaaaaaa/)).toBeInTheDocument()
    expect(uitklap).not.toHaveAttribute('open')
    expect(within(uitklap).getByText('RLZ-mutatie')).toBeInTheDocument()
    expect(within(uitklap).getByText('bbbbbbbb-1111-2222-3333-444444444444')).toBeInTheDocument()
    expect(within(uitklap).getByText(/soort=aflettering_teruggedraaid_in_rlz \[vaf:bank:mut-1\]/)).toBeInTheDocument()
    await userEvent.click(within(uitklap).getByText('details'))
    expect(uitklap).toHaveAttribute('open')
    expect(within(rijen[0]).getByTestId('chip-nieuw')).toHaveTextContent('nieuw')
    expect(within(rijen[0]).getByRole('link', { name: /Naar het document/ })).toHaveAttribute('href', `/?administratie=${ADMIN_A}&document=doc-1`)
    // Let-op: eigen actie + eigen deep-link-tekst.
    expect(within(rijen[1]).getByRole('button', { name: /^Gezien:/ })).toBeInTheDocument()
    expect(within(rijen[1]).getByRole('link', { name: /Naar het document van/ })).toHaveTextContent('Naar de doorbelasting →')
    // Administratie-loze blokfout: geen knop, wél handelingsperspectief; leesbare titel.
    expect(within(rijen[2]).getByText('—')).toBeInTheDocument()
    expect(within(rijen[2]).getByTestId('bevinding-titel')).toHaveTextContent('Controle omzet viel om')
    expect(within(rijen[2]).getByText(/credentials\/RLZ-bereikbaarheid/)).toBeInTheDocument()
    expect(within(rijen[2]).queryByRole('button')).toBeNull()
    expect(screen.getByTestId('reconciliatie-voet')).toHaveTextContent(/1 van 1/)
    expect(screen.getByTestId('reconciliatie-voet')).toHaveTextContent(/3 bevindingen over 2 administraties/)
    // Soort-facet → server-side filter in de URL; zoekterm → q.
    await userEvent.selectOptions(screen.getByLabelText('Soort'), 'geaccepteerd')
    await waitFor(() => expect(aangeroepen.some((a) => a.pad === '/reconciliatie/bevindingen?pagina=1&soort=geaccepteerd')).toBe(true))
    await userEvent.type(screen.getByLabelText('Zoek bevinding'), 'bank')
    await waitFor(() => expect(aangeroepen.some((a) => a.pad === '/reconciliatie/bevindingen?pagina=1&soort=geaccepteerd&q=bank')).toBe(true))
  })

  it('deep-link ?administratie_id=X vult het administratie-facet voor (filter, geen poort)', async () => {
    const aangeroepen = stubFetch()
    renderScherm(`/reconciliatie?administratie_id=${ADMIN_A}`)
    await screen.findByTestId('reconciliatie-tabel')
    expect(aangeroepen.find((a) => a.pad.startsWith('/reconciliatie/bevindingen?'))!.pad).toBe(
      `/reconciliatie/bevindingen?pagina=1&soort=aandacht&administratie_id=${ADMIN_A}`,
    )
  })

  it('accepteren is Beheerder-werk: Boekhouding ziet alleen de hint, geen "Nu draaien" en geen vervaltermijn', async () => {
    stubFetch('boekhouding')
    renderScherm()
    const tabel = await screen.findByTestId('reconciliatie-tabel')
    expect(within(tabel).queryByRole('button', { name: /^Afwijking accepteren:/ })).toBeNull()
    expect(within(tabel).getByText('Beheerder accepteert')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '▶ Nu draaien' })).toBeNull()
    expect(screen.queryByLabelText("'Gezien' vervalt na (dagen)")).toBeNull()
  })

  it('Accepteren…: reden verplicht en inhoudelijk (< 5 tekens = knop uit), POST mét administratie_id + reden; de geaccepteerde rij verdwijnt direct uit "aandacht nodig"', async () => {
    // Server-stand vóór en ná accepteren (bugfix 07-09: de lijst volgt de live acceptatie, geen nieuwe run nodig).
    const naAccepteren = lijst([LET_OP, FOUT], { totaal: 2, tellers: { afwijkingen: 2, let_op: 2, fouten: 1, geaccepteerd: 5, uitgesloten: 1, gezien: 0, administraties: 2 } })
    let geaccepteerd = false
    const aangeroepen = stubFetch('beheerder', { lijstAntwoord: () => (geaccepteerd ? naAccepteren : lijst()) })
    renderScherm()
    const tabel = await screen.findByTestId('reconciliatie-tabel')
    expect(within(tabel).getAllByTestId('reconciliatie-rij')).toHaveLength(3)
    await userEvent.click(within(tabel).getByRole('button', { name: 'Afwijking accepteren: Aflettering teruggedraaid in RLZ — Shell · € 1.240,00 · 01-09-2026' }))
    const dialoog = await screen.findByTestId('reden-dialoog')
    // De dialoog toont de leesbare titel + wat, niet de ruwe CLI-regel.
    expect(within(dialoog).getByTestId('reden-dialoog-bevinding')).toHaveTextContent('Aflettering teruggedraaid in RLZ')
    expect(within(dialoog).getByTestId('reden-dialoog-bevinding')).toHaveTextContent('Wij letterden de bankmutatie')
    expect(within(dialoog).queryByText(/record=aaaaaaaa/)).toBeNull()
    const bevestig = within(dialoog).getByRole('button', { name: 'Accepteren' })
    expect(bevestig).toBeDisabled()
    await userEvent.type(within(dialoog).getByLabelText('Reden'), 'ok')
    expect(bevestig).toBeDisabled()
    expect(within(dialoog).getByText(/minimaal 5 tekens/)).toBeInTheDocument()
    await userEvent.type(within(dialoog).getByLabelText('Reden'), ' — handmatig gecorrigeerd in Reeleezee')
    expect(bevestig).toBeEnabled()
    geaccepteerd = true // vanaf de POST antwoordt de server met de live-stand (rij is geaccepteerd)
    await userEvent.click(bevestig)
    await waitFor(() => expect(aangeroepen.some((a) => a.pad === '/reconciliatie/bevindingen/r1/accepteren')).toBe(true))
    const post = aangeroepen.find((a) => a.pad === '/reconciliatie/bevindingen/r1/accepteren')!
    expect(post.method).toBe('POST')
    expect(post.body).toEqual({ administratie_id: ADMIN_A, reden: 'ok — handmatig gecorrigeerd in Reeleezee' })
    // Na succes: dialoog dicht, de lijst opnieuw opgehaald en de geaccepteerde rij is WEG uit "aandacht nodig"
    // (geen client-side filter dat 'm vasthoudt); de teller-chip volgt de server.
    await waitFor(() => expect(screen.queryByTestId('reden-dialoog')).toBeNull())
    expect(aangeroepen.filter((a) => a.pad.startsWith('/reconciliatie/bevindingen?')).length).toBeGreaterThan(1)
    await waitFor(() => expect(within(screen.getByTestId('reconciliatie-tabel')).getAllByTestId('reconciliatie-rij')).toHaveLength(2))
    expect(screen.queryByText('Aflettering teruggedraaid in RLZ — Shell · € 1.240,00 · 01-09-2026')).toBeNull()
    expect(screen.getByTestId('chip-afwijkingen')).toHaveTextContent('2 afwijkingen')
  })

  it('zonder leesbare laag (oude server) valt de rij terug op de CLI-regel', async () => {
    const oud = { ...AFWIJKING, titel: '', wat: '', doe: '', details: [] }
    stubFetch('boekhouding', { lijstAntwoord: lijst([oud]) })
    renderScherm()
    const tabel = await screen.findByTestId('reconciliatie-tabel')
    expect(within(tabel).getByTestId('bevinding-titel')).toHaveTextContent(/^record=aaaaaaaa/)
    expect(within(tabel).queryByTestId('bevinding-details')).toBeNull()
  })

  it('Gezien…: let-op-melding tijdelijk wegleggen; een serverfout blijft zichtbaar in de dialoog', async () => {
    const aangeroepen = stubFetch('boekhouding')
    renderScherm()
    const tabel = await screen.findByTestId('reconciliatie-tabel')
    await userEvent.click(within(tabel).getByRole('button', { name: /^Gezien:/ }))
    const dialoog = await screen.findByTestId('reden-dialoog')
    await userEvent.type(within(dialoog).getByLabelText('Reden'), 'concept opgeruimd in Reeleezee')
    await userEvent.click(within(dialoog).getByRole('button', { name: 'Gezien' }))
    await waitFor(() => expect(aangeroepen.some((a) => a.pad === '/reconciliatie/bevindingen/r2/gezien')).toBe(true))
    expect(aangeroepen.find((a) => a.pad === '/reconciliatie/bevindingen/r2/gezien')!.body).toEqual({
      administratie_id: ADMIN_B,
      reden: 'concept opgeruimd in Reeleezee',
    })

    // Serverfout (bv. 409): niets stils — de reden blijft staan en de fout komt in beeld.
    cleanup()
    vi.unstubAllGlobals()
    stubFetch('boekhouding', { actieStatus: 409, actieDetail: 'Deze bevinding is al geaccepteerd' })
    renderScherm()
    await userEvent.click(within(await screen.findByTestId('reconciliatie-tabel')).getByRole('button', { name: /^Gezien:/ }))
    const tweede = await screen.findByTestId('reden-dialoog')
    await userEvent.type(within(tweede).getByLabelText('Reden'), 'concept opgeruimd')
    await userEvent.click(within(tweede).getByRole('button', { name: 'Gezien' }))
    expect(await within(tweede).findByText(/al geaccepteerd/)).toBeInTheDocument()
  })

  it('"Toch tonen" op een weggelegde melding gaat via dezelfde reden-dialoog naar gezien-intrekken', async () => {
    const gezienRij: BevindingDto = {
      ...LET_OP,
      id: 'r9',
      soort: 'gezien',
      gezien: { reden: 'wacht op de klant', gezien_op: '2026-09-04T09:00:00Z', vervalt_op: '2026-09-18T09:00:00Z', gezien_door_naam: 'Barbara' },
    }
    const aangeroepen = stubFetch('boekhouding', { lijstAntwoord: lijst([gezienRij]) })
    renderScherm('/reconciliatie?soort=gezien')
    const tabel = await screen.findByTestId('reconciliatie-tabel')
    expect(within(tabel).getByText(/gezien: wacht op de klant · Barbara/)).toBeInTheDocument()
    await userEvent.click(within(tabel).getByRole('button', { name: /^Toch tonen:/ }))
    const dialoog = await screen.findByTestId('reden-dialoog')
    await userEvent.type(within(dialoog).getByLabelText('Reden'), 'klant heeft geantwoord')
    await userEvent.click(within(dialoog).getByRole('button', { name: 'Toch tonen' }))
    await waitFor(() => expect(aangeroepen.some((a) => a.pad === '/reconciliatie/bevindingen/r9/gezien-intrekken')).toBe(true))
  })

  it('▶ Nu draaien (Beheerder): 202 + pollen tot klaar met zichtbare stand; fout blijft zichtbaar', async () => {
    const aangeroepen = stubFetch('beheerder', {
      runStatussen: [run('bezig'), run('klaar', { afgerond_op: '2026-09-06T08:01:00Z', exit_code: 0, mail_status: 'niet_nodig' })],
    })
    renderScherm()
    await screen.findByTestId('reconciliatie-tabel')
    const lijstCallsVoor = aangeroepen.filter((a) => a.pad.startsWith('/reconciliatie/bevindingen?')).length
    await userEvent.click(screen.getByRole('button', { name: '▶ Nu draaien' }))
    await waitFor(() => expect(aangeroepen.some((a) => a.pad === '/reconciliatie/run' && a.method === 'POST')).toBe(true))
    const stand = await screen.findByTestId('reconciliatie-stand')
    await waitFor(() => expect(stand).toHaveTextContent('Reconciliatie bezig…'))
    await waitFor(() => expect(stand).toHaveTextContent(/exit 0 · mail: niet nodig/))
    await waitFor(() => expect(aangeroepen.filter((a) => a.pad.startsWith('/reconciliatie/bevindingen?')).length).toBeGreaterThan(lijstCallsVoor))
    expect(screen.getByRole('button', { name: '▶ Nu draaien' })).toBeEnabled()

    // Fout-run: reden zichtbaar, geen stille dood.
    cleanup()
    vi.unstubAllGlobals()
    stubFetch('beheerder', { runStatussen: [run('fout', { fout_reden: 'RlzFout: 401 op Kempen Facilities' })] })
    renderScherm()
    await screen.findByTestId('reconciliatie-tabel')
    await userEvent.click(screen.getByRole('button', { name: '▶ Nu draaien' }))
    expect(await screen.findByText('De reconciliatie-run is mislukt.')).toBeInTheDocument()
    expect(screen.getByText(/401 op Kempen Facilities/)).toBeInTheDocument()
  })

  it("Beheerder zet de vervaltermijn van 'Gezien' in de voet (GET vult voor, PUT slaat op)", async () => {
    const aangeroepen = stubFetch('beheerder')
    renderScherm()
    const invoer = await screen.findByLabelText("'Gezien' vervalt na (dagen)")
    await waitFor(() => expect(invoer).toHaveValue('14'))
    await userEvent.clear(invoer)
    await userEvent.type(invoer, '21')
    await userEvent.click(screen.getByRole('button', { name: 'Opslaan' }))
    await waitFor(() => expect(aangeroepen.some((a) => a.pad === '/reconciliatie/instelling' && a.method === 'PUT')).toBe(true))
    expect(aangeroepen.find((a) => a.method === 'PUT')!.body).toEqual({ gezien_dagen: 21 })
  })

  it('lege stand: nog nooit gedraaid → uitleg + (Beheerder) knop om er nu één te starten', async () => {
    stubFetch('beheerder', { lijstAntwoord: lijst([], { totaal: 0, administraties_in_selectie: 0, laatste_run: null }) })
    renderScherm()
    const leeg = await screen.findByTestId('reconciliatie-leeg')
    expect(leeg).toHaveTextContent('Nog geen run.')
    expect(within(leeg).getByRole('button', { name: 'Nu een run starten' })).toBeInTheDocument()
  })
})
