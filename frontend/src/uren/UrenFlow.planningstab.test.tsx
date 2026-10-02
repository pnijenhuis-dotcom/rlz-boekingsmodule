/** Run B 02-10 punt 26 — planningstab UITVOERDER (Peter: "het tabje mijn uren moeten we vervangen door tabje planning …
 * alle geplande projecten van die dag … links swipen een dag terug … rechts swipen in de toekomst"): tab alleen voor de
 * uitvoerder (ZZP'er ongewijzigd), lijst mét project/opdrachtgever/plaats/ploeg/transport-icoon, swipe + pijlen + vandaag,
 * tik = projectkaart mét "+ Uren", offline = laatst geladen dag mét chip, deep-link ?planning=JJJJ-Wnn → maandag. */
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider, useAuth } from '../auth/AuthContext'
import { dagKop, swipeRichting, transportLabel } from './DagPlanningView'
import { UrenFlow } from './UrenFlow'
import { isoDatumVan, isoWeekVan, schuifDag, weekDagen } from './urenApi'

function NaLogin({ children }: { children: React.ReactNode }) {
  const { status } = useAuth()
  return status === 'ingelogd' ? <>{children}</> : null
}

const ADM = 'aaaaaaaa-0000-0000-0000-000000000001'
const P1 = 'cccccccc-0000-0000-0000-000000000001'
const P2 = 'cccccccc-0000-0000-0000-000000000002'
const VANDAAG = isoDatumVan(new Date())
const GISTEREN = schuifDag(VANDAAG, -1)
const MORGEN = schuifDag(VANDAAG, 1)

function fakeToken(claims: Record<string, unknown>): string {
  return `kop.${btoa(JSON.stringify(claims))}.handtekening`
}
function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function project(over: Record<string, unknown>) {
  return {
    datum: VANDAAG,
    administratie_id: ADM,
    administratie_naam: 'Universal Steigerbouw',
    project_id: P1,
    project_naam: '26014 Eindhoven (BAM)',
    opdrachtgever: 'BAM',
    werknummer_opdrachtgever: 'W-4711',
    plaats: 'Eindhoven, Kennedylaan 2',
    ploeg: [
      { gebruiker_id: 'u-1', naam: 'Ben v. Dijk', dagdeel: 'heel', is_uitvoerder: true },
      { gebruiker_id: 'u-2', naam: 'Milan K.', dagdeel: 'half', is_uitvoerder: false },
    ],
    gereserveerd: false,
    transport: { soort: 'levering', tijdstip: '07:30:00', status: 'bevestigd' },
    werkopdrachten: [{ groep_id: 'wo-1', tekst: 'Steiger 3 zijden, 2e laag', afwijkend: false }],
    ...over,
  }
}

// Node 22+ schaduwt window.localStorage in jsdom met een lege experimental global — in-memory vervanger (patroon
// standCache.test.ts); de dagplanning-cache (offline-chip) leeft in localStorage.
function inMemoryOpslag(): Storage {
  const opslag = new Map<string, string>()
  return {
    getItem: (sleutel: string) => opslag.get(sleutel) ?? null,
    setItem: (sleutel: string, waarde: string) => void opslag.set(sleutel, String(waarde)),
    removeItem: (sleutel: string) => void opslag.delete(sleutel),
    clear: () => opslag.clear(),
    key: (i: number) => [...opslag.keys()][i] ?? null,
    get length() {
      return opslag.size
    },
  }
}
beforeAll(() => {
  Object.defineProperty(window, 'localStorage', { configurable: true, value: inMemoryOpslag() })
})

const stand: { rol: string; offline: boolean; perDag: Record<string, unknown[]>; gevraagd: string[] } = {
  rol: 'uitvoerder',
  offline: false,
  perDag: {},
  gevraagd: [],
}

function installMock() {
  vi.stubGlobal(
    'fetch',
    vi.fn((invoer: RequestInfo | URL) => {
      const url = String(invoer)
      const pad = url.split('?')[0]
      if (pad === '/auth/token/vernieuwen') return Promise.resolve(jsonResponse({ access_token: fakeToken({ rol: stand.rol, sub: 'veld-1' }) }))
      if (pad === '/auth/administraties') return Promise.resolve(jsonResponse({ administraties: [{ id: ADM, naam: 'Universal Steigerbouw' }] }))
      if (pad === '/uren/uitvoerder/te-keuren' || pad === '/uren/uitvoerder/projecten') return Promise.resolve(jsonResponse([]))
      if (pad === '/uren/uitvoerder/dagplanning') {
        const datum = new URLSearchParams(url.split('?')[1]).get('datum') ?? ''
        stand.gevraagd.push(datum)
        if (stand.offline) return Promise.reject(new TypeError('Failed to fetch'))
        return Promise.resolve(jsonResponse(stand.perDag[datum] ?? []))
      }
      if (pad === `/uren/uitvoerder/projecten/${ADM}/${P1}`)
        return Promise.resolve(
          jsonResponse({
            administratie_id: ADM, project_id: P1, project_naam: '26014 Eindhoven (BAM)', opdrachtgever: 'BAM', werknummer_opdrachtgever: 'W-4711',
            soort_werk: 'steigerbouw', contract_m2: null, gebouwd_m2: '0', looptijd_van: null, looptijd_tot: null, huurtijd_omschrijving: null,
            doorlopende_huur_omschrijving: null, documenten: [], meerwerk: [],
          }),
        )
      if (pad === '/uren/dossier') return Promise.resolve(jsonResponse({ documenten: [], aantal_ontbrekend: 0, aantal_verlopen: 0, aantal_ter_controle: 0, aantal_verloopt_binnenkort: 0, aantal_aanwezig: 0, aantal_verplicht: 0, geblokkeerd: false, herinneringen_teller: 0, herinneringen_max: 3 }))
      if (pad === '/uren/zzp/weken-overzicht' || pad === '/uren/zzp/week-projecten' || pad === '/uren/zzp/planning') return Promise.resolve(jsonResponse([]))
      if (pad === '/uren/zzp/weekstaat') return Promise.resolve(jsonResponse({ weekstaat: null, doorfactureren_standaard: true }))
      if (pad === '/uren/zzp/omschrijving-chips') return Promise.resolve(jsonResponse({ chips: ['opbouwen'] }))
      if (pad === '/uren/stempels') return Promise.resolve(jsonResponse([]))
      return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
    }),
  )
}

function renderFlow(pad = '/accordeur') {
  return render(
    <MemoryRouter initialEntries={[pad]}>
      <AuthProvider>
        <NaLogin>
          <UrenFlow wisselThema={() => {}} uitloggen={() => Promise.resolve()} />
        </NaLogin>
      </AuthProvider>
    </MemoryRouter>,
  )
}

async function naarPlanning() {
  renderFlow()
  await waitFor(() => expect(screen.getByTestId('tab-planning')).toBeInTheDocument())
  await userEvent.click(screen.getByTestId('tab-planning'))
  await waitFor(() => expect(screen.getByTestId('dagplanning')).toBeInTheDocument())
}

function swipe(dx: number) {
  const lijst = screen.getByTestId('dagplanning-lijst')
  fireEvent.pointerDown(lijst, { pointerId: 1, clientX: 200, clientY: 300 })
  fireEvent.pointerUp(lijst, { pointerId: 1, clientX: 200 + dx, clientY: 305 })
}

beforeEach(() => {
  stand.rol = 'uitvoerder'
  stand.offline = false
  stand.gevraagd = []
  stand.perDag = {
    [VANDAAG]: [project({}), project({ project_id: P2, project_naam: '26021 Tilburg (Heijmans)', opdrachtgever: 'Heijmans', plaats: 'Tilburg', ploeg: [], gereserveerd: true, transport: null, werkopdrachten: [] })],
    [GISTEREN]: [project({ datum: GISTEREN, transport: null })],
    [MORGEN]: [],
  }
  localStorage.clear()
  installMock()
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  sessionStorage.clear()
  localStorage.clear()
})

describe('pure helpers', () => {
  it('swipeRichting: links = terug, rechts = vooruit, kort of vooral verticaal = niets', () => {
    expect(swipeRichting(-80, 5)).toBe('terug')
    expect(swipeRichting(80, -5)).toBe('vooruit')
    expect(swipeRichting(-30, 0)).toBeNull()
    expect(swipeRichting(60, 90)).toBeNull()
  })
  it('transportLabel en dagKop', () => {
    expect(transportLabel({ soort: 'levering', tijdstip: '07:30:00' })).toBe('transport gepland: 07:30 · levering')
    expect(transportLabel({ soort: 'retour', tijdstip: null })).toBe('transport gepland: retour')
    expect(dagKop('2026-10-05')).toMatch(/ma.*5.*okt/)
  })
})

describe('planningstab uitvoerder (run B 02-10 punt 26)', () => {
  it('uitvoerder: tab "Planning" i.p.v. "Mijn uren"; lijst van vandaag mét project, opdrachtgever · plaats, ploeg, transport-icoon en reservering', async () => {
    await naarPlanning()
    expect(screen.queryByTestId('tab-mijn-uren')).toBeNull()
    expect(screen.getByTestId('dagplanning-datum')).toHaveTextContent('vandaag')
    const kaarten = await screen.findAllByTestId('dagplanning-project')
    expect(kaarten).toHaveLength(2)
    expect(within(kaarten[0]).getByText('26014 Eindhoven (BAM)')).toBeInTheDocument()
    expect(within(kaarten[0]).getByText('BAM · Eindhoven, Kennedylaan 2')).toBeInTheDocument()
    expect(within(kaarten[0]).getByTestId('dagplanning-ploeg')).toHaveTextContent('Ben v. Dijk, Milan K. (½)')
    expect(within(kaarten[0]).getByTestId('transport-icoon')).toHaveAttribute('aria-label', 'transport gepland: 07:30 · levering')
    expect(within(kaarten[0]).getByText('2 man')).toBeInTheDocument()
    expect(within(kaarten[0]).getByText(/Steiger 3 zijden/)).toBeInTheDocument()
    // Reservering zonder ploeg: zichtbaar als "gereserveerd", geen vrachtwagen.
    expect(within(kaarten[1]).getByTestId('dagplanning-ploeg')).toHaveTextContent('gereserveerd — ploeg volgt')
    expect(within(kaarten[1]).queryByTestId('transport-icoon')).toBeNull()
    expect(stand.gevraagd).toEqual([VANDAAG])
  })

  it("ZZP'er: ongewijzigd — geen dagplanningstab, wél de weektab 'Planning' naast 'Mijn weken'", async () => {
    stand.rol = 'zzper'
    renderFlow()
    await waitFor(() => expect(screen.getByText('⏱ Mijn weken')).toBeInTheDocument())
    expect(screen.queryByTestId('tab-planning')).toBeNull()
    expect(screen.getByText('📅 Planning')).toBeInTheDocument()
  })

  it('swipe links = dag terug (planning van gisteren geladen), "vandaag" springt terug, swipe rechts en pijl = dag vooruit (leeg = melding)', async () => {
    await naarPlanning()
    await screen.findAllByTestId('dagplanning-project')
    swipe(-120)
    await waitFor(() => expect(stand.gevraagd).toContain(GISTEREN))
    expect(screen.getByTestId('dagplanning-datum')).toHaveTextContent(dagKop(GISTEREN))
    expect(screen.getByTestId('dag-vandaag')).toBeInTheDocument()
    await userEvent.click(screen.getByTestId('dag-vandaag'))
    await waitFor(() => expect(screen.getByTestId('dagplanning-datum')).toHaveTextContent('vandaag'))
    swipe(120)
    await waitFor(() => expect(stand.gevraagd).toContain(MORGEN))
    expect(await screen.findByTestId('dagplanning-leeg')).toHaveTextContent('Geen werk gepland')
    // Een korte of verticale beweging is geen swipe.
    const aantal = stand.gevraagd.length
    swipe(-20)
    expect(stand.gevraagd.length).toBe(aantal)
    await userEvent.click(screen.getByTestId('dag-terug'))
    await waitFor(() => expect(screen.getByTestId('dagplanning-datum')).toHaveTextContent('vandaag'))
  })

  it('tik op een project = bestaande projectkaart mét "+ Uren" (weekstaat van die dag) en "Meerwerk melden"; terug = Planning', async () => {
    await naarPlanning()
    const kaarten = await screen.findAllByTestId('dagplanning-project')
    await userEvent.click(kaarten[0])
    await waitFor(() => expect(screen.getByText('‹ Planning')).toBeInTheDocument())
    expect(await screen.findByText('+ Meerwerk melden')).toBeInTheDocument()
    await userEvent.click(screen.getByTestId('projectkaart-plus-uren'))
    const { weeknummer } = isoWeekVan(new Date())
    await waitFor(() =>
      expect(
        (vi.mocked(fetch).mock.calls as unknown as [string][]).some(([u]) => String(u).startsWith('/uren/zzp/weekstaat') && String(u).includes(`project_id=${P1}`) && String(u).includes(`weeknummer=${weeknummer}`)),
      ).toBe(true),
    )
  })

  it('weekoverzicht "Mijn uren" blijft bereikbaar als tekstlink onder de dagplanning', async () => {
    await naarPlanning()
    await userEvent.click(screen.getByTestId('link-mijn-uren'))
    await waitFor(() => expect((vi.mocked(fetch).mock.calls as unknown as [string][]).some(([u]) => String(u).startsWith('/uren/zzp/weken-overzicht'))).toBe(true))
  })

  it('offline: laatst geladen dag uit de cache mét chip "offline — stand van …"; zonder cache een fout mét Opnieuw proberen', async () => {
    await naarPlanning()
    await screen.findAllByTestId('dagplanning-project')
    stand.offline = true
    await userEvent.click(screen.getByTestId('dag-vooruit'))
    expect(await screen.findByText('Opnieuw proberen')).toBeInTheDocument() // morgen nooit geladen → eerlijke fout
    await userEvent.click(screen.getByTestId('dag-terug'))
    expect(await screen.findByTestId('chip-offline')).toHaveTextContent(/offline — stand van \d{2}:\d{2}/)
    expect(screen.getAllByTestId('dagplanning-project')).toHaveLength(2)
  })

  it('deep-link ?planning=JJJJ-Wnn landt voor de uitvoerder op de dagplanning van de maandag van die week', async () => {
    const { jaar, weeknummer } = isoWeekVan(new Date())
    const maandag = weekDagen(jaar, weeknummer)[0].datum
    stand.perDag[maandag] = stand.perDag[maandag] ?? []
    renderFlow(`/accordeur?planning=${jaar}-W${weeknummer}`)
    await waitFor(() => expect(screen.getByTestId('dagplanning')).toBeInTheDocument())
    await waitFor(() => expect(stand.gevraagd).toContain(maandag))
    expect(screen.getByTestId('dagplanning-datum')).toHaveTextContent(dagKop(maandag))
  })
})
