/** Detacheerder-filters veld-app (opdracht Peter 04-09 blok A): werklijst = alleen handelingen (A3, "✓ Alles is
 * bij" + "Ook zonder werk"), weken-eerst (A2), projecten per week (A1) mét de uitwijk "+ ander project"
 * (doorzoekbaar) en de weekstaat-lookup zónder koppeling (C1). */
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider, useAuth } from '../auth/AuthContext'
import { UrenFlow } from './UrenFlow'

/** In de app mount AccordeurApp de UrenFlow pas ná 'ingelogd' (rol bekend) — hier hetzelfde. */
function NaLogin({ children }: { children: React.ReactNode }) {
  const { status } = useAuth()
  return status === 'ingelogd' ? <>{children}</> : null
}

const ADM = 'aaaaaaaa-0000-0000-0000-000000000001'
const MILAN = 'bbbbbbbb-0000-0000-0000-000000000001'
const STEFAN = 'bbbbbbbb-0000-0000-0000-000000000002'
const EINDHOVEN = 'cccccccc-0000-0000-0000-000000000001'
const TILBURG = 'cccccccc-0000-0000-0000-000000000002'

function fakeToken(claims: Record<string, unknown>): string {
  return `kop.${btoa(JSON.stringify(claims))}.handtekening`
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const MILAN_KAART = { gebruiker_id: MILAN, naam: 'Milan K.', aantal_projecten: 2, open_weken: 1, laatste_invoer: null, te_doen: 2 }
const STEFAN_KAART = { gebruiker_id: STEFAN, naam: 'Stefan B.', aantal_projecten: 1, open_weken: 0, laatste_invoer: '2026-08-31', te_doen: 0 }

const WEEK = {
  jaar: 2026,
  weeknummer: 36,
  maandag: '2026-08-31',
  zondag: '2026-09-06',
  is_huidige: true,
  geplande_projecten: 2,
  te_doen: 2,
  status: 'open',
  totaal_uren: '0',
  totaal_m2: '0',
}

const PROJECT_IN_WEEK = {
  administratie_id: ADM,
  administratie_naam: 'Universal Steigerbouw',
  project_id: EINDHOVEN,
  project_naam: '26014 Eindhoven (BAM)',
  soort_werk: 'steigerbouw',
  gepland: true,
  geplande_dagen: 2,
  status: 'nieuw',
  te_doen: true,
  weekstaat_id: null,
  dagen_ingevuld: 0,
  totaal_uren: '0',
  totaal_m2: '0',
  ingediend_op: null,
  goedgekeurd_door_naam: null,
  afgekeurd_door_naam: null,
  afkeur_reden: null,
}

const KEUZE = [
  { administratie_id: ADM, administratie_naam: 'Universal Steigerbouw', project_id: EINDHOVEN, project_naam: '26014 Eindhoven (BAM)', soort_werk: 'steigerbouw' },
  { administratie_id: ADM, administratie_naam: 'Universal Steigerbouw', project_id: TILBURG, project_naam: '26021 Tilburg (Heijmans)', soort_werk: 'demontage' },
]

function installMock(zzpers: () => unknown[]): string[] {
  const aangeroepen: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((invoer: RequestInfo | URL) => {
      const url = String(invoer)
      const pad = url.split('?')[0]
      aangeroepen.push(url)
      switch (pad) {
        case '/auth/token/vernieuwen':
          return Promise.resolve(jsonResponse({ access_token: fakeToken({ rol: 'detacheerder', sub: 'deta-1' }) }))
        case '/auth/administraties':
          return Promise.resolve(jsonResponse({ administraties: [] }))
        case '/uren/detacheerder/zzpers':
          return Promise.resolve(jsonResponse(zzpers()))
        case '/uren/zzp/weken-overzicht':
          return Promise.resolve(jsonResponse([WEEK]))
        case '/uren/zzp/week-projecten':
          return Promise.resolve(jsonResponse([PROJECT_IN_WEEK]))
        case '/uren/zzp/projecten-keuze':
          return Promise.resolve(jsonResponse(KEUZE))
        case '/uren/zzp/weekstaat':
          return Promise.resolve(jsonResponse({ weekstaat: null }))
        default:
          return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
      }
    }),
  )
  return aangeroepen
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

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  sessionStorage.clear()
})

describe('UrenFlow — detacheerder (planning-gestuurd, 04-09)', () => {
  it('werklijst toont alleen ZZP\'ers met werk; wie bij is staat onder "Ook zonder werk"', async () => {
    installMock(() => [MILAN_KAART, STEFAN_KAART])
    renderFlow()
    await waitFor(() => expect(screen.getByText('Milan K.')).toBeInTheDocument())
    expect(screen.queryByText('Stefan B.')).not.toBeInTheDocument()
    expect(screen.queryByTestId('alles-bij')).not.toBeInTheDocument()
    expect(screen.getByText('1 week open')).toBeInTheDocument()

    await userEvent.click(screen.getByTestId('ook-zonder-werk'))
    expect(screen.getByText('Stefan B.')).toBeInTheDocument()
    expect(screen.getByText('bij')).toBeInTheDocument()
  })

  it('niets te doen voor niemand = "✓ Alles is bij" mét verversknop die opnieuw laadt', async () => {
    let ronde = 0
    const aangeroepen = installMock(() => {
      ronde += 1
      return ronde === 1 ? [STEFAN_KAART] : [MILAN_KAART, STEFAN_KAART]
    })
    renderFlow()
    await waitFor(() => expect(screen.getByTestId('alles-bij')).toBeInTheDocument())
    expect(screen.getByText('Alles is bij')).toBeInTheDocument()
    expect(screen.queryByText('Stefan B.')).not.toBeInTheDocument()

    await userEvent.click(screen.getByText('↻ Verversen'))
    await waitFor(() => expect(screen.getByText('Milan K.')).toBeInTheDocument())
    expect(aangeroepen.filter((u) => u.startsWith('/uren/detacheerder/zzpers')).length).toBe(2)
  })

  it('ZZP\'er → weken (alleen mét planning + deze week) → projecten in die week → "+ ander project" doorzoekbaar → weekstaat zonder koppeling', async () => {
    const aangeroepen = installMock(() => [MILAN_KAART])
    renderFlow()
    await waitFor(() => expect(screen.getByText('Milan K.')).toBeInTheDocument())
    await userEvent.click(screen.getByText('Milan K.'))

    // A2: wekenlijst namens Milan
    await waitFor(() => expect(screen.getByText('Milan K. · weken')).toBeInTheDocument())
    expect(aangeroepen.some((u) => u.startsWith(`/uren/zzp/weken-overzicht?namens=${MILAN}`))).toBe(true)
    expect(screen.getByText(/31 aug – 6 sep · deze week/)).toBeInTheDocument()
    expect(screen.getByText('2 projecten gepland · 2 nog invullen')).toBeInTheDocument()
    expect(screen.getByText('2 nog invullen', { selector: '.acc-chip' })).toBeInTheDocument()

    // A1: projecten in de week = alleen waar ingepland
    await userEvent.click(screen.getByText(/Week 36/))
    await waitFor(() => expect(screen.getByText('26014 Eindhoven (BAM)')).toBeInTheDocument())
    expect(aangeroepen.some((u) => u.startsWith(`/uren/zzp/week-projecten?jaar=2026&weeknummer=36&namens=${MILAN}`))).toBe(true)
    expect(screen.getByText('gepland 2 dagen · nog niets ingevuld')).toBeInTheDocument()
    expect(screen.queryByText('26021 Tilburg (Heijmans)')).not.toBeInTheDocument()

    // Uitwijk: volledige lijst, doorzoekbaar
    await userEvent.click(screen.getByTestId('ander-project'))
    await waitFor(() => expect(screen.getByText('26021 Tilburg (Heijmans)')).toBeInTheDocument())
    expect(screen.getByText('26014 Eindhoven (BAM)')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Zoek project'), 'tilb')
    expect(screen.queryByText('26014 Eindhoven (BAM)')).not.toBeInTheDocument()
    expect(screen.getByText('26021 Tilburg (Heijmans)')).toBeInTheDocument()

    // Weekstaat opent zónder koppeling (lookup geeft null → nieuwe staat, dagen invulbaar)
    await userEvent.click(screen.getByText('26021 Tilburg (Heijmans)'))
    await waitFor(() => expect(screen.getByText(/26021 Tilburg \(Heijmans\) · week 36/)).toBeInTheDocument())
    expect(
      aangeroepen.some((u) =>
        u.startsWith(`/uren/zzp/weekstaat?administratie_id=${ADM}&project_id=${TILBURG}&jaar=2026&weeknummer=36&namens=${MILAN}`),
      ),
    ).toBe(true)
    expect(screen.getAllByText('+ invullen').length).toBe(7)
    expect(screen.getByText(/namens Milan K\./)).toBeInTheDocument()
  })
})
