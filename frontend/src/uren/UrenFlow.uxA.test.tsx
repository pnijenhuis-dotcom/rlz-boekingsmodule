/** Veld-app run A — 12 UX-punten (Peter 18-09 "alle punten"; mockup uren-uitvoerder-v3.html), uitvoerder-flow:
 * "Zelfde als gisteren" (bron=kopie), uren als tikknoppen + chips, doorfactureren ingeklapt, "meer" voor m², vergeten
 * dag oranje, week indienen met samenvatting + waarschuwing, terugkoppeling afgekeurd + Aanpassen. */
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider, useAuth } from '../auth/AuthContext'
import { UrenFlow } from './UrenFlow'
import { isoWeekVan, weekDagen } from './urenApi'

function NaLogin({ children }: { children: React.ReactNode }) {
  const { status } = useAuth()
  return status === 'ingelogd' ? <>{children}</> : null
}

const ADM = 'aaaaaaaa-0000-0000-0000-000000000001'
const P1 = 'cccccccc-0000-0000-0000-000000000001'
const P2 = 'cccccccc-0000-0000-0000-000000000002'

function fakeToken(claims: Record<string, unknown>): string {
  return `kop.${btoa(JSON.stringify(claims))}.handtekening`
}
function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

// De week van vandaag, zodat "vandaag" in de dagbalk valt (punt 9 rekent met werkdagen vóór vandaag).
const NU = new Date()
const { jaar, weeknummer } = isoWeekVan(NU)
const DAGEN = weekDagen(jaar, weeknummer)
const VANDAAG_IDX = DAGEN.findIndex((d) => d.datum === `${NU.getFullYear()}-${String(NU.getMonth() + 1).padStart(2, '0')}-${String(NU.getDate()).padStart(2, '0')}`)
const WEEK = { jaar, weeknummer, maandag: DAGEN[0].datum, zondag: DAGEN[6].datum, is_huidige: true, geplande_projecten: 1, te_doen: 1, status: 'open', totaal_uren: '8', totaal_m2: '0' }

function kaart(over: Record<string, unknown>) {
  return {
    administratie_id: ADM,
    administratie_naam: 'Universal Steigerbouw',
    project_id: P1,
    project_naam: '26014 Eindhoven (BAM)',
    soort_werk: 'steigerbouw',
    gepland: true,
    geplande_dagen: 2,
    status: 'concept',
    te_doen: true,
    weekstaat_id: 'ws-1',
    dagen_ingevuld: 1,
    totaal_uren: '8',
    totaal_m2: '0',
    ingediend_op: null,
    goedgekeurd_door_naam: null,
    afgekeurd_door_naam: null,
    afkeur_reden: null,
    dag_uren: { [DAGEN[0].datum]: '8' },
    laatste_omschrijving: 'opbouwen',
    dagen_niet_doorfactureren: 0,
    doorfactureren_standaard: true,
    meerwerk_aantal: 0,
    laatste_regel: { datum: DAGEN[0].datum, uren: '8', m2: '42', opmerking: 'opbouwen', doorfactureren: true },
    dagen_zonder_m2: 0,
    contract_m2: '900',
    ...over,
  }
}

function installMock(opties: { kaarten: unknown[]; puts?: unknown[]; posts?: string[]; chips?: string[] }) {
  vi.stubGlobal(
    'fetch',
    vi.fn((invoer: RequestInfo | URL, init?: RequestInit) => {
      const url = String(invoer)
      const pad = url.split('?')[0]
      if (pad === '/auth/token/vernieuwen') return Promise.resolve(jsonResponse({ access_token: fakeToken({ rol: 'uitvoerder', sub: 'uitv-1' }) }))
      if (pad === '/auth/administraties') return Promise.resolve(jsonResponse({ administraties: [{ id: ADM, naam: 'Universal Steigerbouw' }] }))
      if (pad === '/uren/uitvoerder/te-keuren') return Promise.resolve(jsonResponse([]))
      if (pad === '/uren/uitvoerder/projecten') return Promise.resolve(jsonResponse([]))
      if (pad === '/uren/dossier') return Promise.resolve(jsonResponse({ documenten: [], aantal_ontbrekend: 0, aantal_verlopen: 0, aantal_ter_controle: 0, aantal_verloopt_binnenkort: 0, aantal_aanwezig: 0, aantal_verplicht: 0, geblokkeerd: false, herinneringen_teller: 0, herinneringen_max: 3 }))
      if (pad === '/uren/zzp/weken-overzicht') return Promise.resolve(jsonResponse([WEEK]))
      if (pad === '/uren/zzp/week-projecten') return Promise.resolve(jsonResponse(opties.kaarten))
      if (pad === '/uren/zzp/omschrijving-chips') return Promise.resolve(jsonResponse({ chips: opties.chips ?? ['opbouwen', 'afbreken', 'ombouwen', 'transport', 'overig'] }))
      if (pad === '/uren/zzp/weekstaat') return Promise.resolve(jsonResponse({ weekstaat: null, doorfactureren_standaard: true }))
      if (pad === '/uren/zzp/dag' && init?.method === 'PUT') {
        opties.puts?.push(JSON.parse(String(init.body)))
        return Promise.resolve(jsonResponse({ id: 'ws-1', dagen: [], totaal_uren: '8', totaal_m2: '0', status: 'concept' }))
      }
      if (pad === '/uren/zzp/indienen' && init?.method === 'POST') {
        opties.posts?.push(String(init.body))
        return Promise.resolve(jsonResponse({ id: 'ws-1', status: 'ingediend' }))
      }
      return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
    }),
  )
}

function renderFlow() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <NaLogin>
          <UrenFlow wisselThema={() => {}} uitloggen={() => Promise.resolve()} />
        </NaLogin>
      </AuthProvider>
    </MemoryRouter>,
  )
}

async function naarWeek() {
  renderFlow()
  await waitFor(() => expect(screen.getByTestId('tab-mijn-uren')).toBeInTheDocument())
  await userEvent.click(screen.getByTestId('tab-mijn-uren'))
  await waitFor(() => expect(screen.getByText(new RegExp(`Week ${weeknummer}`))).toBeInTheDocument())
  await userEvent.click(screen.getByText(new RegExp(`Week ${weeknummer}`)))
  await waitFor(() => expect(screen.getAllByTestId('projectkaart').length).toBeGreaterThan(0))
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  sessionStorage.clear()
})

describe('Veld-app run A (uitvoerder)', () => {
  it('kaart: één primaire "+ Uren", "Zelfde als gisteren" en "Meerwerk melden" als tekstlinks; kopie = PUT mét bron=kopie en de laatste regel', async () => {
    const puts: Record<string, unknown>[] = []
    installMock({ kaarten: [kaart({})], puts })
    await naarWeek()
    const k = screen.getByTestId('projectkaart')
    expect(within(k).getAllByRole('button', { name: '+ Uren' }).length).toBe(1)
    expect(within(k).getByTestId('zelfde-als-gisteren')).toHaveClass('acc-tekstlink')
    expect(within(k).getByTestId('meerwerk-melden')).toHaveClass('acc-tekstlink')
    await userEvent.click(screen.getByTestId(`dag-${DAGEN[Math.max(VANDAAG_IDX, 1)].naam}`))
    await userEvent.click(within(k).getByTestId('zelfde-als-gisteren'))
    await waitFor(() => expect(puts.length).toBe(1))
    expect(puts[0]).toMatchObject({ bron: 'kopie', uren: '8', m2: '42', opmerking: 'opbouwen', doorfactureren: true, project_id: P1 })
  })

  it('+ Uren: tikknoppen 4·6·8·10 en −/+ per half uur, chips als omschrijving, doorfactureren ingeklapt, m² direct op een m²-project', async () => {
    const puts: Record<string, unknown>[] = []
    installMock({ kaarten: [kaart({})], puts })
    await naarWeek()
    await userEvent.click(screen.getByTestId('plus-uren'))
    await waitFor(() => expect(screen.getByTestId('tik-8')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('tik-8'))
    expect(screen.getByTestId('uren-stand')).toHaveTextContent('8 u')
    await userEvent.click(screen.getByRole('button', { name: 'Half uur meer' }))
    expect(screen.getByTestId('uren-stand')).toHaveTextContent('8,5 u')
    await userEvent.click(screen.getByRole('button', { name: 'Half uur minder' }))
    await userEvent.click(screen.getByTestId('chip-afbreken'))
    // m²-project (contract_m2 900): m² direct zichtbaar, geen "meer".
    expect(screen.queryByTestId('meer')).not.toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('m² gebouwd (optioneel)'), '12')
    expect(screen.getByTestId('doorfactureren-ingeklapt')).toHaveTextContent('doorfactureren')
    expect(screen.queryByLabelText('Doorfactureren')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Opslaan' }))
    await waitFor(() => expect(puts.length).toBe(1))
    expect(puts[0]).toMatchObject({ uren: '8', opmerking: 'afbreken', m2: '12', doorfactureren: true })
    expect(puts[0]).not.toHaveProperty('bron')
  })

  it('overig-chip opent een vrij tekstveld; "ander aantal…" pas een toetsenbord', async () => {
    const puts: Record<string, unknown>[] = []
    installMock({ kaarten: [kaart({ contract_m2: null })], puts })
    await naarWeek()
    await userEvent.click(screen.getByTestId('plus-uren'))
    await waitFor(() => expect(screen.getByTestId('chip-overig')).toBeInTheDocument())
    expect(screen.queryByLabelText('Uren (ander aantal)')).not.toBeInTheDocument()
    await userEvent.click(screen.getByText('ander aantal…'))
    await userEvent.type(screen.getByLabelText('Uren (ander aantal)'), '7.5')
    await userEvent.click(screen.getByTestId('chip-overig'))
    await userEvent.type(screen.getByLabelText('Omschrijving (vrij)'), 'wachttijd levering')
    await userEvent.click(screen.getByRole('button', { name: 'Opslaan' }))
    await waitFor(() => expect(puts[0]).toMatchObject({ uren: '7.5', opmerking: 'wachttijd levering', m2: null }))
  })

  it('week indienen: samenvatting (dagen · uren · projecten · zonder m² · niet doorfactureren), ontbrekende werkdag als waarschuwing, dan pas POST', async () => {
    const posts: string[] = []
    installMock({
      kaarten: [kaart({ dagen_zonder_m2: 1, dagen_niet_doorfactureren: 1, dag_uren: { [DAGEN[0].datum]: '8' } }), kaart({ project_id: P2, project_naam: '26021 Tilburg (Heijmans)', weekstaat_id: 'ws-2', totaal_uren: '4', dag_uren: { [DAGEN[1].datum]: '4' }, laatste_regel: null })],
      posts,
    })
    await naarWeek()
    await userEvent.click(screen.getByTestId('week-indienen'))
    await waitFor(() => expect(screen.getByTestId('indien-samenvatting')).toBeInTheDocument())
    expect(screen.getByTestId('indien-regel')).toHaveTextContent('2 dagen · 12 u · 2 projecten · 1 regel zonder m² · 1 niet doorfactureren')
    expect(screen.getByTestId('indien-waarschuwing')).toHaveTextContent(/Geen uren op wo/)
    expect(posts.length).toBe(0)
    await userEvent.click(screen.getByTestId('indien-bevestig'))
    await waitFor(() => expect(posts.length).toBe(2))
  })

  it('afgekeurde week: terugkoppeling mét reden en "Aanpassen" opent de weekstaat; goedgekeurd toont ✓', async () => {
    installMock({
      kaarten: [
        kaart({ status: 'corrigeren', te_doen: true, afgekeurd_door_naam: 'R. Yücetaş', afkeur_reden: 'dinsdag was een vrije dag' }),
        kaart({ project_id: P2, project_naam: '26021 Tilburg (Heijmans)', weekstaat_id: 'ws-2', status: 'goedgekeurd', te_doen: false, goedgekeurd_door_naam: 'S. Hasturk' }),
      ],
    })
    await naarWeek()
    expect(screen.getByTestId('terugkoppeling-afgekeurd')).toHaveTextContent('Afgekeurd door R. Yücetaş: "dinsdag was een vrije dag"')
    expect(screen.getByTestId('terugkoppeling-goed')).toHaveTextContent('Goedgekeurd door S. Hasturk')
    await userEvent.click(screen.getByTestId('aanpassen'))
    await waitFor(() => expect(screen.getByText(new RegExp(`26014 Eindhoven \\(BAM\\) · week ${weeknummer}`))).toBeInTheDocument())
  })

  it('vergeten dag: een werkdag vóór vandaag zonder uren krijgt de oranje rand + waarschuwing', async () => {
    if (VANDAAG_IDX < 2) return // ma/di: geen werkdag vóór vandaag zonder uren te construeren
    installMock({ kaarten: [kaart({ dag_uren: { [DAGEN[0].datum]: '8' } })] })
    await naarWeek()
    expect(screen.getByTestId(`dag-${DAGEN[1].naam}`)).toHaveClass('vergeten')
    expect(screen.getByTestId(`dag-${DAGEN[0].naam}`)).not.toHaveClass('vergeten')
    expect(screen.getByTestId('vergeten-dagen')).toHaveTextContent(new RegExp(DAGEN[1].naam))
  })
})
