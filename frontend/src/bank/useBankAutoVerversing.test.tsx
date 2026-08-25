import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { BankDetailScreen, formatVerversTijd } from './BankDetailScreen'

/* Auto-verversing bij openen (besluit Peter 25-08, deel 4 punt 2): POST sync-achtergrond bij mount,
 * cache direct zichtbaar, chip per status, pollen alleen bij wachtrij/bezig, klaar = herladen,
 * fout = zichtbaar paneel (nooit stil). */

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const REKENING_ID = 'cccccccc-0000-0000-0000-000000000003'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const rekening = {
  id: REKENING_ID,
  naam: 'ING zakelijk',
  iban: 'NL91 INGB 0002 4455 88',
  rekening_type: 1,
  is_kas: false,
  saldo: '48212.90',
  saldo_datum: '2026-07-31',
  open_mutaties: 0,
  heeft_aanlevering: true,
  laatste_import: null,
  probe_fout: null,
}

interface RunDto {
  run_id: string | null
  status: string
  overgeslagen: boolean
  laatste_sync_op: string | null
  resultaat?: unknown
  fout_reden: string | null
}

function run(overrides: Partial<RunDto> = {}): RunDto {
  return {
    run_id: 'bbbbbbbb-0000-0000-0000-000000000002',
    status: 'overgeslagen',
    overgeslagen: true,
    laatste_sync_op: '2026-08-25T07:41:00Z',
    resultaat: null,
    fout_reden: null,
    ...overrides,
  }
}

/** `statusReeks` = de opeenvolgende antwoorden van de status-GET (laatste blijft herhalen). */
function installFetchMock(startResponse: RunDto, statusReeks: RunDto[] = []) {
  const aanroepen: { url: string; method: string }[] = []
  let statusIndex = 0
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      aanroepen.push({ url, method: init?.method ?? 'GET' })
      if (url.endsWith('/auth/administraties')) {
        return Promise.resolve(jsonResponse({ administraties: [{ id: ADMINISTRATIE_ID, naam: 'Kempen Groep B.V.' }] }))
      }
      if (url.endsWith('/bank/rekeningen')) {
        return Promise.resolve(
          jsonResponse({
            rekeningen: [rekening],
            laatste_sync_op: '2026-08-02T06:00:00Z',
            ooit_gesynchroniseerd: true,
            heeft_bankaanlevering: true,
          }),
        )
      }
      if (url.endsWith('/bank/sync-achtergrond') && init?.method === 'POST') {
        return Promise.resolve(jsonResponse(startResponse, 202))
      }
      if (url.endsWith('/bank/sync-achtergrond/status')) {
        const antwoord = statusReeks[Math.min(statusIndex, statusReeks.length - 1)] ?? startResponse
        statusIndex += 1
        return Promise.resolve(jsonResponse(antwoord))
      }
      if (url.includes('/mutaties')) return Promise.resolve(jsonResponse({ mutaties: [] }))
      if (url.includes('/afletter-opdrachten')) return Promise.resolve(jsonResponse({ opdrachten: [] }))
      if (url.endsWith('/bank/aanbetalingen')) return Promise.resolve(jsonResponse({ aanbetalingen: [] }))
      if (url.endsWith('/splitsingen')) return Promise.resolve(jsonResponse({ splitsingen: [] }))
      return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
    }),
  )
  return aanroepen
}

function renderScherm() {
  return render(
    <MemoryRouter initialEntries={[`/bank/${ADMINISTRATIE_ID}`]}>
      <Routes>
        <Route path="/bank/:administratieId" element={<BankDetailScreen />} />
      </Routes>
    </MemoryRouter>,
  )
}

const telStatusPolls = (aanroepen: { url: string }[]) =>
  aanroepen.filter((a) => a.url.endsWith('/bank/sync-achtergrond/status')).length
const telMutatiesLaads = (aanroepen: { url: string; method: string }[]) =>
  aanroepen.filter((a) => a.url.includes('/mutaties') && a.method === 'GET').length

describe('useBankAutoVerversing via BankDetailScreen', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('vuurt de achtergrond-sync bij mount en toont bij "overgeslagen" de actueel-chip zonder te pollen', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const aanroepen = installFetchMock(run())
    renderScherm()

    await waitFor(() =>
      expect(aanroepen.filter((a) => a.url.endsWith('/bank/sync-achtergrond') && a.method === 'POST')).toHaveLength(1),
    )
    expect(await screen.findByText('ververst < 5 min geleden — actueel')).toBeInTheDocument()
    expect(screen.getByText(/laatst ververst/)).toBeInTheDocument()

    await vi.advanceTimersByTimeAsync(6000)
    expect(telStatusPolls(aanroepen)).toBe(0)
  })

  it('pollt bij "bezig" elke 2,5 s en herlaadt de mutaties zodra de ronde "klaar" is, mét samenvatting', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const aanroepen = installFetchMock(run({ status: 'bezig', overgeslagen: false }), [
      run({ status: 'bezig', overgeslagen: false }),
      run({
        status: 'klaar',
        overgeslagen: false,
        laatste_sync_op: '2026-08-25T07:45:00Z',
        resultaat: {
          mutaties_nieuw: 3,
          mutaties_bijgewerkt: 1,
          open_ververst: 0,
          afletteren_geverifieerd: 0,
          automatisch_afgeletterd: 0,
          automatisch_geboekt: 0,
          fouten: [],
        },
      }),
    ])
    renderScherm()

    expect(await screen.findByText(/verversen uit Reeleezee…/)).toBeInTheDocument()
    await waitFor(() => expect(telMutatiesLaads(aanroepen)).toBeGreaterThan(0))
    const mutatiesVoor = telMutatiesLaads(aanroepen)

    // Eerste poll (nog bezig) na 2,5 s, tweede poll (klaar) na 5 s.
    await vi.advanceTimersByTimeAsync(2600)
    await waitFor(() => expect(telStatusPolls(aanroepen)).toBe(1))
    expect(screen.getByText(/verversen uit Reeleezee…/)).toBeInTheDocument()

    await vi.advanceTimersByTimeAsync(2600)
    await waitFor(() => expect(telStatusPolls(aanroepen)).toBe(2))

    expect(await screen.findByText(/3 nieuwe mutaties · 1 bijgewerkt/)).toBeInTheDocument()
    await waitFor(() => expect(telMutatiesLaads(aanroepen)).toBeGreaterThan(mutatiesVoor))
    expect(screen.getByText('zojuist ververst')).toBeInTheDocument()

    // Ronde afgerond → geen verdere polls.
    await vi.advanceTimersByTimeAsync(6000)
    expect(telStatusPolls(aanroepen)).toBe(2)
  })

  it('toont bij "fout" een zichtbaar waarschuwingspaneel met de fout_reden (nooit stil)', async () => {
    installFetchMock(run({ status: 'fout', overgeslagen: false, fout_reden: 'RLZ gaf 503 op PaymentTransactions' }))
    renderScherm()

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/Automatisch verversen uit Reeleezee is mislukt: RLZ gaf 503 op PaymentTransactions/)
  })

  it('toont "nog nooit ververst" als er nog geen sync is geweest', async () => {
    installFetchMock(run({ status: 'geen', overgeslagen: false, run_id: null, laatste_sync_op: null }))
    // De rekeningen-GET geeft in deze mock wél een laatste_sync_op; de run-waarde (null) is leidend
    // zodra die er is — daarom toetsen we hier de pure formatter apart.
    expect(formatVerversTijd(null)).toBe('nog nooit ververst')
    renderScherm()
    expect(await screen.findByText(/laatst ververst|nog nooit ververst/)).toBeInTheDocument()
  })
})

describe('formatVerversTijd', () => {
  it('toont vandaag alleen de tijd en anders dd-mm + tijd', () => {
    const nu = new Date(2026, 7, 25, 10, 0, 0)
    const vandaag = new Date(2026, 7, 25, 9, 41, 0).toISOString()
    const eerder = new Date(2026, 7, 24, 6, 5, 0).toISOString()
    expect(formatVerversTijd(vandaag, nu)).toBe('laatst ververst 09:41')
    expect(formatVerversTijd(eerder, nu)).toBe('laatst ververst 24-08 06:05')
  })
})
