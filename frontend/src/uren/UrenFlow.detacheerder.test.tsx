/** Detacheerder-filters veld-app (opdracht Peter 04-09 blok A): werklijst = alleen handelingen (A3, "✓ Alles is
 * bij" + "Ook zonder werk"), weken-eerst (A2), de week als PROJECTKAARTEN (project-eerst, Peter 18-09: gepland ∪ mét regels;
 * per kaart "+ Uren"; "+ Ander project toevoegen aan mijn week" = alle actieve projecten, doorzoekbaar) en de
 * weekstaat-lookup zónder koppeling (C1). */
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

/** 18-09 blok C: de week-projectenlijst draagt óók de niet-geplande actieve projecten (gepland=false, status nieuw). */
const PROJECT_NIET_GEPLAND = {
  ...PROJECT_IN_WEEK,
  project_id: TILBURG,
  project_naam: '26021 Tilburg (Heijmans)',
  soort_werk: 'demontage',
  gepland: false,
  geplande_dagen: 0,
  te_doen: false,
}

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
          // Kaarten = gepland ∪ mét regels (Eindhoven); `alles=true` = de keuzelijst mét óók het niet-geplande Tilburg.
          return Promise.resolve(
            jsonResponse(url.includes('alles=true') ? [PROJECT_IN_WEEK, PROJECT_NIET_GEPLAND] : [PROJECT_IN_WEEK]),
          )
        case '/uren/zzp/weekstaat':
          return Promise.resolve(jsonResponse({ weekstaat: null, doorfactureren_standaard: false }))
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

  it("ZZP'er → weken → projectkaarten (gepland) → + Ander project (alle, doorzoekbaar) → kaart erbij → + Uren mét project al ingevuld", async () => {
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

    // Project-eerst (Peter 18-09): de week = kaarten van geplande projecten (+ mét regels); Tilburg (niet gepland, geen
    // regels) is GEEN kaart — die komt via "+ Ander project toevoegen aan mijn week".
    await userEvent.click(screen.getByText(/Week 36/))
    await waitFor(() => expect(screen.getByText('26014 Eindhoven (BAM)')).toBeInTheDocument())
    expect(aangeroepen.some((u) => u.startsWith(`/uren/zzp/week-projecten?jaar=2026&weeknummer=36&namens=${MILAN}`))).toBe(true)
    expect(screen.getAllByTestId('projectkaart').length).toBe(1)
    expect(screen.getByTestId('chip-gepland')).toBeInTheDocument()
    expect(screen.queryByText('26021 Tilburg (Heijmans)')).not.toBeInTheDocument()
    // Dagbalk: 7 dagen, "+ Uren" per kaart; geen meerwerk-knop voor een detacheerder (alleen een uitvoerder meldt meerwerk).
    expect(screen.getByTestId('dag-ma')).toBeInTheDocument()
    expect(screen.getAllByTestId('plus-uren').length).toBe(1)
    expect(screen.queryByTestId('meerwerk-melden')).not.toBeInTheDocument()
    // Nog geen indienbare staat (status nieuw) → geen "Week indienen".
    expect(screen.queryByTestId('week-indienen')).not.toBeInTheDocument()

    // "+ Ander project": alle actieve projecten (alles=true), de kaarten die er al staan blijven weg, doorzoekbaar.
    await userEvent.click(screen.getByTestId('ander-project'))
    await waitFor(() => expect(screen.getByText('26021 Tilburg (Heijmans)')).toBeInTheDocument())
    expect(aangeroepen.some((u) => u.startsWith('/uren/zzp/week-projecten?jaar=2026&weeknummer=36&alles=true&namens='))).toBe(true)
    expect(screen.queryByText('26014 Eindhoven (BAM)')).not.toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Zoek project'), 'eindh')
    expect(screen.getByText('Geen project gevonden.')).toBeInTheDocument()
    await userEvent.clear(screen.getByLabelText('Zoek project'))
    await userEvent.type(screen.getByLabelText('Zoek project'), 'tilb')
    await userEvent.click(screen.getByText('26021 Tilburg (Heijmans)'))

    // Terug in de week: twee kaarten, Tilburg mét chip "niet gepland".
    await waitFor(() => expect(screen.getAllByTestId('projectkaart').length).toBe(2))
    expect(screen.getByTestId('chip-niet-gepland')).toBeInTheDocument()
    expect(screen.getAllByText(/^260(14|21)/).map((el) => el.textContent)[0]).toContain('26014')

    // "+ Uren" op de Tilburg-kaart, dag ma gekozen → daginvoer mét project én dag al ingevuld (lookup zónder koppeling).
    await userEvent.click(screen.getByTestId('dag-ma'))
    await userEvent.click(screen.getAllByTestId('plus-uren')[1])
    await waitFor(() => expect(screen.getByTestId('doorfactureren-ingeklapt')).toBeInTheDocument())
    expect(
      aangeroepen.some((u) =>
        u.startsWith(`/uren/zzp/weekstaat?administratie_id=${ADM}&project_id=${TILBURG}&jaar=2026&weeknummer=36&namens=${MILAN}`),
      ),
    ).toBe(true)
    expect(screen.getByText(/maandag 31 aug/)).toBeInTheDocument()
    expect(screen.getByText(/26021 Tilburg \(Heijmans\)/)).toBeInTheDocument()
    expect(screen.getByText(/namens Milan K\./)).toBeInTheDocument()
    // 18-09 blok A+B + run A punt 11/12: doorfactureren INGEKLAPT op de projectdefault (hier: Niet) — dropdown pas ná
    // "wijzigen"; m² zit onder "meer" omdat dit geen m²-project is (contract_m2 leeg) en is leeg (null, nooit 0).
    expect(screen.getByTestId('doorfactureren-ingeklapt')).toHaveTextContent('niet doorfactureren')
    expect(screen.getByTestId('doorfactureren-ingeklapt')).toHaveTextContent('standaard voor dit project')
    await userEvent.click(screen.getByTestId('doorfactureren-wijzigen'))
    expect((screen.getByLabelText('Doorfactureren') as HTMLSelectElement).value).toBe('nee')
    expect(screen.queryByLabelText('m² gebouwd (optioneel)')).not.toBeInTheDocument()
    await userEvent.click(screen.getByTestId('meer'))
    expect((screen.getByLabelText('m² gebouwd (optioneel)') as HTMLInputElement).value).toBe('')

    // Terug (‹ Week 36) → de kaart Tilburg staat er nog (per-week-state).
    await userEvent.click(screen.getByText('‹ Week 36'))
    await waitFor(() => expect(screen.getAllByTestId('projectkaart').length).toBe(2))
  })

  it('kaart mét regels toont dagtotaal, weektotaal, laatste omschrijving en "Week indienen"; kaarttitel opent de weekstaat', async () => {
    const CONCEPT = {
      ...PROJECT_NIET_GEPLAND,
      status: 'concept',
      te_doen: true,
      weekstaat_id: 'dddddddd-0000-0000-0000-000000000001',
      dagen_ingevuld: 2,
      totaal_uren: '10',
      totaal_m2: '0',
      dag_uren: { '2026-08-31': '6', '2026-09-01': '4' },
      laatste_omschrijving: 'meegeholpen afbreken',
      dagen_niet_doorfactureren: 1,
      doorfactureren_standaard: false,
      meerwerk_aantal: 0,
    }
    vi.stubGlobal(
      'fetch',
      vi.fn((invoer: RequestInfo | URL) => {
        const url = String(invoer)
        const pad = url.split('?')[0]
        switch (pad) {
          case '/auth/token/vernieuwen':
            return Promise.resolve(jsonResponse({ access_token: fakeToken({ rol: 'detacheerder', sub: 'deta-1' }) }))
          case '/auth/administraties':
            return Promise.resolve(jsonResponse({ administraties: [] }))
          case '/uren/detacheerder/zzpers':
            return Promise.resolve(jsonResponse([MILAN_KAART]))
          case '/uren/zzp/weken-overzicht':
            return Promise.resolve(jsonResponse([WEEK]))
          case '/uren/zzp/week-projecten':
            return Promise.resolve(jsonResponse([PROJECT_IN_WEEK, CONCEPT]))
          case '/uren/zzp/weekstaat':
            return Promise.resolve(jsonResponse({ weekstaat: null, doorfactureren_standaard: false }))
          default:
            return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
        }
      }),
    )
    renderFlow()
    await waitFor(() => expect(screen.getByText('Milan K.')).toBeInTheDocument())
    await userEvent.click(screen.getByText('Milan K.'))
    await waitFor(() => expect(screen.getByText(/Week 36/)).toBeInTheDocument())
    await userEvent.click(screen.getByText(/Week 36/))
    await waitFor(() => expect(screen.getAllByTestId('projectkaart').length).toBe(2))
    // Dagbalk-teller ma = 6 u; kaartmeta op ma: "ma: 6,0 u · week 10,0 u · meegeholpen afbreken".
    await userEvent.click(screen.getByTestId('dag-ma'))
    expect(screen.getByTestId('dag-ma').textContent).toContain('6 u')
    expect(screen.getByText(/ma: 6,0 u · week 10,0 u · meegeholpen afbreken/)).toBeInTheDocument()
    expect(screen.getByTestId('chip-niet-doorfactureren').textContent).toBe('1 dag niet doorfactureren')
    // Week indienen dekt alleen de concept-staat mét uren (1 project, 10 u).
    expect(screen.getByTestId('week-indienen').textContent).toBe('Week indienen (10 u)')
    // Kaarttitel → weekstaat van dat project.
    await userEvent.click(screen.getByLabelText('Weekstaat 26021 Tilburg (Heijmans)'))
    await waitFor(() => expect(screen.getByText(/26021 Tilburg \(Heijmans\) · week 36/)).toBeInTheDocument())
  })
})
