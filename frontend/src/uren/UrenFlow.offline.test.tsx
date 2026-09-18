/** Run B punt 5 — offline in de veld-app (uitvoerder-flow, fake IndexedDB): netwerk uit bij Opslaan → regel bewaard mét
 * bolletje op kaart en dagbalk + banner; "Nu verzenden"/`online`-event → verzonden, bolletje weg; 409 bevroren → sheet mét
 * beide standen; indienen mét bewaarde regels = melding (online-only). Recept: UrenFlow achter de login-gate + fake JWT. */
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { installeerFakeIndexedDb } from '../api/fakeIndexedDb.testhulp'
import { AuthProvider, useAuth } from '../auth/AuthContext'
import { UrenFlow } from './UrenFlow'
import { isoWeekVan, standaardDag, weekDagen } from './urenApi'
import { bewaarInWachtrij } from './urenOffline'

function NaLogin({ children }: { children: React.ReactNode }) {
  const { status } = useAuth()
  return status === 'ingelogd' ? <>{children}</> : null
}

const ADM = 'aaaaaaaa-0000-0000-0000-000000000001'
const P1 = 'cccccccc-0000-0000-0000-000000000001'
function fakeToken(claims: Record<string, unknown>): string {
  return `kop.${btoa(JSON.stringify(claims))}.handtekening`
}
function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}
const { jaar, weeknummer } = isoWeekVan(new Date())
const DAGEN = weekDagen(jaar, weeknummer)
const DAG = standaardDag(DAGEN)
const WEEK = { jaar, weeknummer, maandag: DAGEN[0].datum, zondag: DAGEN[6].datum, is_huidige: true, geplande_projecten: 1, te_doen: 1, status: 'open', totaal_uren: '8', totaal_m2: '0' }
const KAART = {
  administratie_id: ADM, administratie_naam: 'Universal Steigerbouw', project_id: P1, project_naam: '26014 Eindhoven (BAM)', soort_werk: 'steigerbouw',
  gepland: true, geplande_dagen: 2, status: 'concept', te_doen: true, weekstaat_id: 'ws-1', dagen_ingevuld: 1, totaal_uren: '8', totaal_m2: '0',
  ingediend_op: null, goedgekeurd_door_naam: null, afgekeurd_door_naam: null, afkeur_reden: null, dag_uren: { [DAGEN[0].datum]: '8' },
  laatste_omschrijving: 'opbouwen', dagen_niet_doorfactureren: 0, doorfactureren_standaard: true, meerwerk_aantal: 0, laatste_regel: null,
  dagen_zonder_m2: 0, contract_m2: null,
}

type PutModus = 'ok' | 'netwerk' | 'bevroren'
const modus: { put: PutModus; puts: unknown[]; posts: number } = { put: 'ok', puts: [], posts: 0 }

function installMock() {
  vi.stubGlobal(
    'fetch',
    vi.fn((invoer: RequestInfo | URL, init?: RequestInit) => {
      const pad = String(invoer).split('?')[0]
      if (pad === '/auth/token/vernieuwen') return Promise.resolve(jsonResponse({ access_token: fakeToken({ rol: 'uitvoerder', sub: 'uitv-1' }) }))
      if (pad === '/auth/administraties') return Promise.resolve(jsonResponse({ administraties: [{ id: ADM, naam: 'Universal Steigerbouw' }] }))
      if (pad === '/uren/uitvoerder/te-keuren' || pad === '/uren/uitvoerder/projecten') return Promise.resolve(jsonResponse([]))
      if (pad === '/uren/dossier') return Promise.resolve(jsonResponse({ documenten: [], aantal_ontbrekend: 0, aantal_verlopen: 0, aantal_ter_controle: 0, aantal_verloopt_binnenkort: 0, aantal_aanwezig: 0, aantal_verplicht: 0, geblokkeerd: false, herinneringen_teller: 0, herinneringen_max: 3 }))
      if (pad === '/uren/zzp/weken-overzicht') return Promise.resolve(jsonResponse([WEEK]))
      if (pad === '/uren/zzp/week-projecten') return Promise.resolve(jsonResponse([KAART]))
      if (pad === '/uren/zzp/omschrijving-chips') return Promise.resolve(jsonResponse({ chips: ['opbouwen', 'afbreken', 'overig'] }))
      if (pad === '/uren/zzp/weekstaat') return Promise.resolve(jsonResponse({ weekstaat: null, doorfactureren_standaard: true }))
      if (pad === '/uren/zzp/dag' && init?.method === 'PUT') {
        if (modus.put === 'netwerk') return Promise.reject(new TypeError('Failed to fetch'))
        if (modus.put === 'bevroren')
          return Promise.resolve(jsonResponse({ detail: { code: 'weekstaat_bevroren', detail: 'De week is ingediend.', status: 'ingediend', server_regel: { uren: '6', m2: null, opmerking: 'ombouwen', doorfactureren: true } } }, 409))
        modus.puts.push(JSON.parse(String(init.body)))
        return Promise.resolve(jsonResponse({ id: 'ws-1', dagen: [], totaal_uren: '8', totaal_m2: '0', status: 'concept' }))
      }
      if (pad === '/uren/zzp/indienen' && init?.method === 'POST') {
        modus.posts += 1
        return Promise.resolve(jsonResponse({ id: 'ws-1', status: 'ingediend' }))
      }
      return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${String(invoer)}` }, 500))
    }),
  )
}

function renderFlow() {
  render(
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

let fake: ReturnType<typeof installeerFakeIndexedDb>
beforeEach(() => {
  fake = installeerFakeIndexedDb()
  modus.put = 'ok'
  modus.puts = []
  modus.posts = 0
  installMock()
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  fake.herstel()
  sessionStorage.clear()
})

const bewaardePayload = { administratie_id: ADM, project_id: P1, jaar, weeknummer, datum: DAG.datum, uren: '8', m2: null, doorfactureren: true, opmerking: 'opbouwen', namens_zzper_id: null }

describe('Veld-app offline (run B punt 5)', () => {
  it('netwerk uit bij Opslaan: regel bewaard, bolletje op kaart en dagbalk, banner; indienen = melding', async () => {
    modus.put = 'netwerk'
    await naarWeek()
    await userEvent.click(screen.getByTestId('plus-uren'))
    await waitFor(() => expect(screen.getByTestId('tik-8')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('tik-8'))
    await userEvent.click(screen.getByRole('button', { name: 'Opslaan' }))
    await waitFor(() => expect(screen.getByTestId('offline-banner')).toBeInTheDocument())
    expect(screen.getByTestId('offline-banner')).toHaveTextContent('1 regel nog niet verzonden')
    expect(within(screen.getByTestId('projectkaart')).getByTestId('chip-niet-verzonden')).toBeInTheDocument()
    expect(screen.getByTestId(`offline-dot-${DAG.naam}`)).toBeInTheDocument()
    // De lokale uren tellen mee in de dagbalk (8 u op de gekozen dag) en de regel staat in IndexedDB.
    expect(screen.getByTestId(`dag-${DAG.naam}`)).toHaveTextContent('8 u')
    expect(fake.data.get('rlz-uren-offline')?.get('wachtrij')?.size).toBeGreaterThan(1)
    // Indienen blijft online-only: eerst de bewaarde regel weg.
    await userEvent.click(screen.getByTestId('week-indienen'))
    await userEvent.click(screen.getByTestId('indien-bevestig'))
    await waitFor(() => expect(screen.getByText(/Indienen kan pas als de bewaarde regel verzonden is/)).toBeInTheDocument())
    expect(modus.posts).toBe(0)
  })

  it('"Nu verzenden" mét netwerk: PUT met de bewaarde regel, bolletje en banner weg', async () => {
    await bewaarInWachtrij(bewaardePayload)
    modus.put = 'netwerk'
    await naarWeek()
    await waitFor(() => expect(screen.getByTestId('offline-banner')).toBeInTheDocument())
    modus.put = 'ok'
    await userEvent.click(screen.getByTestId('offline-verzenden'))
    await waitFor(() => expect(modus.puts.length).toBe(1))
    expect(modus.puts[0]).toMatchObject({ uren: '8', datum: DAG.datum, project_id: P1 })
    await waitFor(() => expect(screen.queryByTestId('offline-banner')).not.toBeInTheDocument())
    expect(screen.queryByTestId('chip-niet-verzonden')).not.toBeInTheDocument()
    expect(screen.getByText('Bewaarde regel verzonden.')).toBeInTheDocument()
  })

  it('`online`-event verzendt de wachtrij vanzelf', async () => {
    await bewaarInWachtrij(bewaardePayload)
    modus.put = 'netwerk'
    await naarWeek()
    await waitFor(() => expect(screen.getByTestId('offline-banner')).toBeInTheDocument())
    modus.put = 'ok'
    act(() => {
      window.dispatchEvent(new Event('online'))
    })
    await waitFor(() => expect(modus.puts.length).toBe(1))
    await waitFor(() => expect(screen.queryByTestId('offline-banner')).not.toBeInTheDocument())
  })

  it('409 bevroren bij het openen van de app = sheet mét beide standen; "Stand van kantoor houden" haalt de regel weg', async () => {
    await bewaarInWachtrij(bewaardePayload)
    modus.put = 'bevroren'
    renderFlow()
    const sheet = await screen.findByTestId('offline-conflict')
    expect(within(sheet).getByTestId('conflict-server')).toHaveTextContent('6,0 u · ombouwen')
    expect(within(sheet).getByTestId('conflict-mijn')).toHaveTextContent('8,0 u · opbouwen')
    expect(sheet).toHaveTextContent(`Week ${weeknummer} is ingediend`)
    await userEvent.click(within(sheet).getByTestId('conflict-server-houden'))
    await waitFor(() => expect(screen.queryByTestId('offline-conflict')).not.toBeInTheDocument())
    // De regel is uit de wachtrij (index leeg), er is niets overschreven (geen geslaagde PUT).
    await waitFor(() => expect(fake.data.get('rlz-uren-offline')?.get('wachtrij')?.get('__index__')).toBe('[]'))
    expect(modus.puts.length).toBe(0)
  })
})
