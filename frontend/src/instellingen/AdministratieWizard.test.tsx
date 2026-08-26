import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AdministratieWizard } from './AdministratieWizard'
import { SchrijftestDialog, WebserviceGegevensDialog } from './KoppelingDialogen'

/** Administratie toevoegen via de UI (feedbackronde 26-08 punt 5): wizard-flow, probe-fout mét
 * rapport (niets opgeslagen), eerste-sync-status per onderdeel, webservice-dialoog, schrijftest. */

const ADMIN_A = '11111111-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const ADMIN_B = '22222222-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
const NIEUW_ID = 'cccccccc-0000-0000-0000-000000000003'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function installMock(opties: { aanmaakStatus?: number; syncStatussen?: unknown[]; posts?: { url: string; body: unknown }[] }) {
  const syncStatussen = [...(opties.syncStatussen ?? [])]
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null
      if (init?.method === 'POST' || init?.method === 'PUT') opties.posts?.push({ url, body })
      if (url.endsWith('/verbinding-testen')) {
        if (body?.wachtwoord === 'fout') return Promise.resolve(jsonResponse({ detail: { bericht: 'Reeleezee weigert deze login (HTTP 401) — controleer webservice-gebruiker en wachtwoord', rapporten: {} } }, 422))
        return Promise.resolve(
          jsonResponse({
            administraties: [
              { rlz_admin_id: ADMIN_A, naam: 'Nieuwe Klant B.V.', al_aangesloten: false },
              { rlz_admin_id: ADMIN_B, naam: 'Universal Steigerbouw B.V.', al_aangesloten: true },
            ],
          }),
        )
      }
      if (url.endsWith('/aanmaken')) {
        if (opties.aanmaakStatus === 422) {
          return Promise.resolve(
            jsonResponse({ detail: { bericht: 'Rechten-probe niet groen — niets opgeslagen. Nieuwe Klant B.V.: TaxRates=403', rapporten: { [ADMIN_A]: { Administrations: 'ok', TaxRates: '403' } } } }, 422),
          )
        }
        return Promise.resolve(
          jsonResponse({ administraties: [{ id: NIEUW_ID, naam: 'Nieuwe Klant B.V.', rlz_admin_id: ADMIN_A, probe: { Administrations: 'ok' }, sync_run_id: 'run-1' }] }, 201),
        )
      }
      if (url.endsWith('/eerste-sync/status')) {
        const volgende = syncStatussen.length > 1 ? syncStatussen.shift() : syncStatussen[0]
        return Promise.resolve(jsonResponse(volgende ?? { run_id: null, status: 'geen', onderdelen: null, aangevraagd_op: null, beeindigd_op: null, fout_reden: null }))
      }
      if (url.endsWith('/webservice-gegevens')) {
        if (body?.wachtwoord === 'rood') {
          return Promise.resolve(jsonResponse({ detail: { bericht: 'Rechten-probe niet groen (Projects=403) — niets gewijzigd', rapporten: { x: { Administrations: 'ok', Projects: '403' } } } }, 422))
        }
        return Promise.resolve(jsonResponse({ rapport: { Administrations: 'ok', Ledgers: 'ok' } }))
      }
      if (url.endsWith('/schrijftest')) {
        return Promise.resolve(
          jsonResponse({
            uitkomst: 'ok',
            referentie: 'TEST-ONB-20260826-1400',
            document_id: 'dddddddd-0000-0000-0000-000000000004',
            stappen: [
              { stap: 'admin-pin', status: 'ok', detail: null },
              { stap: 'put', status: 'ok', detail: "crediteur 'X', kosten-GB 4000, € 1,21" },
              { stap: 'boeken (17)', status: 'ok', detail: 'Status 2' },
              { stap: 'storno (19)', status: 'ok', detail: 'terug naar concept (Status 1)' },
            ],
          }),
        )
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

afterEach(() => vi.unstubAllGlobals())

const KLAAR = {
  run_id: 'run-1',
  status: 'fout', // één onderdeel mislukt → run op fout, de rest wél klaar
  onderdelen: {
    ledgers: { status: 'klaar', aangemaakt: 412, bijgewerkt: 0 },
    taxrates: { status: 'klaar', aangemaakt: 22, bijgewerkt: 0 },
    vendors: { status: 'klaar', aangemaakt: 5, bijgewerkt: 0 },
    projects: { status: 'klaar', aangemaakt: 0, bijgewerkt: 0 },
    payment_accounts: { status: 'fout', fout: 'RlzApiError: 403' },
  },
  aangevraagd_op: '2026-08-26T12:00:00Z',
  beeindigd_op: '2026-08-26T12:01:00Z',
  fout_reden: 'Niet alle onderdelen gelukt: payment_accounts — zie details per onderdeel',
}

describe('AdministratieWizard', () => {
  it('stap 1 → 2 → 3: verbinding testen, al-aangesloten uitgeschakeld, aansluiten, status per onderdeel', async () => {
    const posts: { url: string; body: unknown }[] = []
    installMock({ posts, syncStatussen: [KLAAR] })
    const onAangemaakt = vi.fn()
    render(<AdministratieWizard open onSluiten={() => {}} onAangemaakt={onAangemaakt} />)

    fireEvent.change(screen.getByLabelText('Webservice-gebruiker'), { target: { value: 'ws_nijenhuis' } })
    fireEvent.change(screen.getByLabelText('Wachtwoord'), { target: { value: 'geheim' } })
    fireEvent.click(screen.getByRole('button', { name: /Verbinding testen/ }))

    await waitFor(() => expect(screen.getByText('Administratie toevoegen — stap 2 van 3')).toBeInTheDocument())
    expect(screen.getByText('Nieuwe Klant B.V.')).toBeInTheDocument()
    const alAangesloten = screen.getByLabelText('Aansluiten Universal Steigerbouw B.V.')
    expect(alAangesloten).toBeDisabled()
    expect(screen.getByText('al aangesloten')).toBeInTheDocument()
    // Eén aansluitbare administratie → alvast aangevinkt; de RLZ-id is vooringevuld, nooit typbaar.
    expect(screen.getByLabelText('Aansluiten Nieuwe Klant B.V.')).toBeChecked()
    expect(screen.getByText(`RLZ-id ${ADMIN_A}`)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Aansluiten \(1\)/ }))
    await waitFor(() => expect(screen.getByText('Administratie toevoegen — stap 3 van 3')).toBeInTheDocument())
    const aanmaak = posts.find((p) => p.url.endsWith('/aanmaken'))
    expect(aanmaak?.body).toEqual({ webservice_username: 'ws_nijenhuis', wachtwoord: 'geheim', rlz_admin_ids: [ADMIN_A] })
    // Eerste sync per onderdeel, incl. een zichtbaar mislukt onderdeel.
    await waitFor(() => expect(screen.getByText(/412 nieuw/)).toBeInTheDocument())
    expect(screen.getByText('RlzApiError: 403')).toBeInTheDocument()
    expect(screen.getByText(/Niet alle onderdelen gelukt/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sync opnieuw starten' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Sluiten' }))
    expect(onAangemaakt).toHaveBeenCalledTimes(1)
  })

  it('login geweigerd = duidelijke fout op stap 1 (niets opgeslagen)', async () => {
    installMock({})
    render(<AdministratieWizard open onSluiten={() => {}} onAangemaakt={() => {}} />)
    fireEvent.change(screen.getByLabelText('Webservice-gebruiker'), { target: { value: 'ws' } })
    fireEvent.change(screen.getByLabelText('Wachtwoord'), { target: { value: 'fout' } })
    fireEvent.click(screen.getByRole('button', { name: /Verbinding testen/ }))
    await waitFor(() => expect(screen.getByText(/weigert deze login \(HTTP 401\)/)).toBeInTheDocument())
    expect(screen.getByText('Administratie toevoegen — stap 1 van 3')).toBeInTheDocument()
  })

  it('rode rechten-probe bij aansluiten toont het rapport per endpoint en blijft op stap 2', async () => {
    installMock({ aanmaakStatus: 422 })
    render(<AdministratieWizard open onSluiten={() => {}} onAangemaakt={() => {}} />)
    fireEvent.change(screen.getByLabelText('Webservice-gebruiker'), { target: { value: 'ws' } })
    fireEvent.change(screen.getByLabelText('Wachtwoord'), { target: { value: 'geheim' } })
    fireEvent.click(screen.getByRole('button', { name: /Verbinding testen/ }))
    await waitFor(() => expect(screen.getByLabelText('Aansluiten Nieuwe Klant B.V.')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /Aansluiten \(1\)/ }))
    await waitFor(() => expect(screen.getByText(/Rechten-probe niet groen — niets opgeslagen/)).toBeInTheDocument())
    expect(screen.getByText(/TaxRates ✗ \(403\)/)).toBeInTheDocument()
    expect(screen.getByText('Administratie toevoegen — stap 2 van 3')).toBeInTheDocument()
  })
})

const ADMINISTRATIE = {
  id: NIEUW_ID,
  naam: 'Nieuwe Klant B.V.',
  boeken_ingeschakeld: false,
  project_verplicht: false,
  ai_extractie_ingeschakeld: false,
  eigenaar_gebruiker_id: null,
  is_vastgoed: false,
  verkoop_autoboeken_ingeschakeld: false,
  uren_meerwerk_ingeschakeld: false,
  uren_dagmax_uren: '12',
  rlz_admin_id: ADMIN_A,
  webservice_username: 'ws_oud',
  probe_groen: true,
}

describe('WebserviceGegevensDialog', () => {
  it('toont alleen de gebruikersnaam (nooit een wachtwoord) en slaat op ná groene probe', async () => {
    const posts: { url: string; body: unknown }[] = []
    installMock({ posts })
    const onGewijzigd = vi.fn()
    render(<WebserviceGegevensDialog administratie={ADMINISTRATIE} onSluiten={() => {}} onGewijzigd={onGewijzigd} />)
    expect(screen.getByText(/Huidige webservice-gebruiker: ws_oud \(wachtwoord aanwezig, niet uitleesbaar\)/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Nieuw wachtwoord'), { target: { value: 'nieuw-geheim' } })
    fireEvent.click(screen.getByRole('button', { name: 'Testen en opslaan' }))
    await waitFor(() => expect(screen.getByText('Opgeslagen — rechten-probe groen.')).toBeInTheDocument())
    expect(posts[0].url).toContain(`/instellingen/administraties/${NIEUW_ID}/webservice-gegevens`)
    expect(onGewijzigd).toHaveBeenCalled()
  })

  it('rode probe = fout mét rapport, niets gewijzigd', async () => {
    installMock({})
    render(<WebserviceGegevensDialog administratie={ADMINISTRATIE} onSluiten={() => {}} onGewijzigd={() => {}} />)
    fireEvent.change(screen.getByLabelText('Nieuw wachtwoord'), { target: { value: 'rood' } })
    fireEvent.click(screen.getByRole('button', { name: 'Testen en opslaan' }))
    await waitFor(() => expect(screen.getByText(/niet groen \(Projects=403\) — niets gewijzigd/)).toBeInTheDocument())
    expect(screen.getByText('HTTP 403')).toBeInTheDocument()
  })
})

describe('SchrijftestDialog', () => {
  it('voert de schrijftest pas na een expliciete klik uit en toont elke stap', async () => {
    const posts: { url: string; body: unknown }[] = []
    installMock({ posts })
    render(<SchrijftestDialog administratie={ADMINISTRATIE} onSluiten={() => {}} />)
    expect(posts).toHaveLength(0)
    fireEvent.click(screen.getByRole('button', { name: 'Schrijftest uitvoeren' }))
    await waitFor(() => expect(screen.getByText('schrijftest geslaagd')).toBeInTheDocument())
    expect(posts[0].url).toContain(`/instellingen/administraties/${NIEUW_ID}/schrijftest`)
    expect(screen.getByText(/storno \(19\):/)).toBeInTheDocument()
    expect(screen.getByText(/TEST-ONB-20260826-1400/)).toBeInTheDocument()
  })
})
