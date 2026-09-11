// RLZ-check als knop (nachtrun 10/11-09 blok 1): knop → POST /administraties/{id}/rlz-check → resultaat per
// leesroute (stand, letterlijk RLZ-antwoord, RLZ-recht), regel "Administraties die deze login ziet" mét markering
// van het eigen id, "Sync opnieuw starten" alleen bij groen + rode eerste sync, 404/503 leesbaar.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AdministratieInstellingenDto, EersteSyncRunDto } from '../api/types'
import type { RlzCheckResultaatDto } from './instellingenApi'
import { RlzCheck, rlzCheckFoutTekst, rlzCheckIsGroen } from './RlzCheck'
import { ApiError } from '../api/client'

const RLZ_ID = '2f916ef0-44aa-46d3-88f2-1b2e225e7f44'

function administratie(overrides: Partial<AdministratieInstellingenDto> = {}): AdministratieInstellingenDto {
  return {
    id: 'aaaaaaaa-0000-0000-0000-000000000001',
    naam: 'Baard beheer & management',
    boeken_ingeschakeld: true,
    project_verplicht: false,
    ai_extractie_ingeschakeld: true,
    eigenaar_gebruiker_id: null,
    is_vastgoed: false,
    verkoop_autoboeken_ingeschakeld: false,
    uren_meerwerk_ingeschakeld: false,
    uren_dagmax_uren: '12',
    afdelingen_ingeschakeld: false,
    voorraad_ingeschakeld: false,
    mini_voorraad_ingeschakeld: false,
    rlz_admin_id: RLZ_ID,
    webservice_username: 'ws-baard',
    ...overrides,
  }
}

const RODE_SYNC: EersteSyncRunDto = {
  run_id: 'r1',
  status: 'fout',
  onderdelen: { ledgers: { status: 'fout', fout: 'Reeleezee weigert GET Ledgers (HTTP 403) — leesrecht Grootboek. RLZ zegt: "Actie niet toegestaan"' } },
  aangevraagd_op: '2026-09-10T11:59:00Z',
  beeindigd_op: '2026-09-10T11:59:20Z',
  fout_reden: 'Niet alle onderdelen gelukt: ledgers',
}

const BAARD_ROOD: RlzCheckResultaatDto = {
  rapport: { Administrations: 'ok', Ledgers: '403', TaxRates: 'ok', Vendors: '403', SalesInvoices: '403', PaymentAccounts: 'ok' },
  meldingen: {
    Ledgers: 'HTTP 403 — {"Message":"Actie niet toegestaan bij huidige gebruikersrechten","ExceptionMessage":null}',
    Vendors: 'HTTP 403 — {"Message":"Actie niet toegestaan bij huidige gebruikersrechten","ExceptionMessage":null}',
    SalesInvoices: 'HTTP 403 — (leeg antwoord)',
  },
  rechten: {
    Administrations: 'de webservice-gebruiker moet aan deze administratie gekoppeld zijn (RLZ › Instellingen › Gebruikers)',
    Ledgers: 'leesrecht Grootboek/Financieel (rekeningschema) voor de webservice-gebruiker op deze administratie',
    TaxRates: 'leesrecht Btw-tarieven (Financieel) voor de webservice-gebruiker op deze administratie',
    Vendors: 'leesrecht Relaties › Crediteuren voor de webservice-gebruiker op deze administratie',
    SalesInvoices: 'facturatiemodule afgenomen + leesrecht Verkoop (een 403 hier = module niet afgenomen, geen blokkade)',
    PaymentAccounts: 'leesrecht Bank/Kas (betaalrekeningen) voor de webservice-gebruiker op deze administratie',
  },
  administraties_zichtbaar: [
    { id: RLZ_ID, naam: 'Baard beheer & management' },
    { id: '49051ac9-0000-0000-0000-000000000002', naam: 'Box Beheer B.V.' },
  ],
  administraties_fout: null,
  rlz_admin_id: RLZ_ID,
}

const GROEN: RlzCheckResultaatDto = {
  ...BAARD_ROOD,
  rapport: { Administrations: 'ok', Ledgers: 'ok', TaxRates: 'ok', Vendors: 'ok', SalesInvoices: '403', PaymentAccounts: 'ok' },
  meldingen: { SalesInvoices: 'HTTP 403 — (leeg antwoord)' },
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function mockFetch(handler: (url: string, init?: RequestInit) => Response | Promise<Response>) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => Promise.resolve(handler(String(input), init)))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderCheck(a = administratie(), onHerlaad = vi.fn()) {
  render(
    <RlzCheck administratie={a} onHerlaad={onHerlaad} titel="Webservice-gegevens" uitleg="Login van de RLZ-webservice.">
      <span className="chip ok">{a.webservice_username}</span>
    </RlzCheck>,
  )
  return onHerlaad
}

describe('RlzCheck — knop "RLZ-check" op de Webservice-gegevens-rij (nachtrun 10/11-09 blok 1)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('toont vóór de klik alleen de rij mét login-chip en de secundaire knop — geen resultaat, geen sync-knop', () => {
    mockFetch(() => json({}, 500))
    renderCheck()
    expect(screen.getByText('Webservice-gegevens')).toBeInTheDocument()
    expect(screen.getByText('ws-baard')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'RLZ-check voor Baard beheer & management' })).toBeEnabled()
    expect(screen.queryByTestId('rlz-check-resultaat')).toBeNull()
    expect(screen.queryByRole('button', { name: /Sync opnieuw starten/ })).toBeNull()
  })

  it('klik = POST /administraties/{id}/rlz-check; rood resultaat per route mét letterlijk RLZ-antwoord en RLZ-recht; SalesInvoices-403 = oranje, geen blokkade', async () => {
    const fetchMock = mockFetch((url) => (url.endsWith('/rlz-check') ? json(BAARD_ROOD) : json({}, 404)))
    const gebruiker = userEvent.setup()
    const onHerlaad = renderCheck(administratie({ eerste_sync: RODE_SYNC }))
    await gebruiker.click(screen.getByRole('button', { name: 'RLZ-check voor Baard beheer & management' }))
    await screen.findByTestId('rlz-check-resultaat')
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/administraties/aaaaaaaa-0000-0000-0000-000000000001/rlz-check')
    expect(init.method).toBe('POST')

    expect(screen.getByTestId('rlz-check-samenvatting')).toHaveTextContent('2 van 6 leesroutes rood')
    const ledgers = within(screen.getByTestId('rlz-check-route-Ledgers'))
    expect(ledgers.getByText('HTTP 403')).toHaveClass('chip', 'blokkerend')
    expect(ledgers.getByText('HTTP 403 — {"Message":"Actie niet toegestaan bij huidige gebruikersrechten","ExceptionMessage":null}')).toBeInTheDocument()
    expect(ledgers.getByText('leesrecht Grootboek/Financieel (rekeningschema) voor de webservice-gebruiker op deze administratie')).toBeInTheDocument()
    const taxrates = within(screen.getByTestId('rlz-check-route-TaxRates'))
    expect(taxrates.getByText('ok')).toHaveClass('chip', 'ok')
    expect(taxrates.getByText('RLZ antwoordt normaal')).toBeInTheDocument()
    expect(within(screen.getByTestId('rlz-check-route-SalesInvoices')).getByText('403 — facturatiemodule niet afgenomen')).toHaveClass('chip', 'afwijking')

    // Rood → géén "Sync opnieuw starten", ook al is de laatste eerste sync rood.
    expect(screen.queryByRole('button', { name: /Sync opnieuw starten/ })).toBeNull()
    expect(onHerlaad).toHaveBeenCalledTimes(1)
  })

  it('regel "Administraties die deze login ziet: N (…)" markeert het eigen rlz_admin_id met "✓ deze administratie"', async () => {
    mockFetch(() => json(BAARD_ROOD))
    const gebruiker = userEvent.setup()
    renderCheck()
    await gebruiker.click(screen.getByRole('button', { name: /RLZ-check voor/ }))
    const regel = await screen.findByTestId('rlz-check-administraties')
    expect(regel).toHaveTextContent('Administraties die deze login ziet: 2')
    expect(regel).toHaveTextContent(`Baard beheer & management · ${RLZ_ID}`)
    expect(regel).toHaveTextContent('Box Beheer B.V. · 49051ac9-0000-0000-0000-000000000002')
    expect(within(regel).getByText('✓ deze administratie')).toHaveClass('chip', 'ok')
  })

  it('eigen id NIET in de lijst = rode markering (verkeerd administratie-id direct zichtbaar)', async () => {
    mockFetch(() => json({ ...GROEN, administraties_zichtbaar: [{ id: 'ander-id', naam: 'Andere B.V.' }] }))
    const gebruiker = userEvent.setup()
    renderCheck()
    await gebruiker.click(screen.getByRole('button', { name: /RLZ-check voor/ }))
    const regel = await screen.findByTestId('rlz-check-administraties')
    expect(regel).toHaveTextContent('Administraties die deze login ziet: 1')
    expect(within(regel).getByText('⚠ eigen id NIET in de lijst')).toHaveClass('chip', 'blokkerend')
  })

  it('Administrations zelf rood: "onbekend" mét de letterlijke RLZ-melding, geen lijst', async () => {
    mockFetch(() =>
      json({
        ...BAARD_ROOD,
        rapport: { ...BAARD_ROOD.rapport, Administrations: '401' },
        administraties_zichtbaar: [],
        administraties_fout: 'HTTP 401 — {"Message":"Unauthorized"}',
      }),
    )
    const gebruiker = userEvent.setup()
    renderCheck()
    await gebruiker.click(screen.getByRole('button', { name: /RLZ-check voor/ }))
    const regel = await screen.findByTestId('rlz-check-administraties')
    expect(regel).toHaveTextContent('Administraties die deze login ziet: onbekend')
    expect(regel).toHaveTextContent('HTTP 401 — {"Message":"Unauthorized"}')
  })

  it('groene check terwijl de eerste sync op RLZ wacht (rechten_onderweg, blok 3 run 11-09): "Sync opnieuw starten" direct beschikbaar', async () => {
    mockFetch((url) => (url.endsWith('/rlz-check') ? json(GROEN) : json({}, 404)))
    const gebruiker = userEvent.setup()
    renderCheck(administratie({ eerste_sync: { ...RODE_SYNC, status: 'rechten_onderweg', fout_reden: null, pogingen: 1, volgende_poging_op: '2026-09-11T12:05:00Z' } }))
    await gebruiker.click(screen.getByRole('button', { name: /RLZ-check voor/ }))
    await screen.findByTestId('rlz-check-resultaat')
    expect(screen.getByRole('button', { name: 'Sync opnieuw starten voor Baard beheer & management' })).toBeEnabled()
  })

  it('groene check ná een rode eerste sync: primaire knop "Sync opnieuw starten" → POST …/eerste-sync, daarna herlaad + status', async () => {
    const fetchMock = mockFetch((url) => {
      if (url.endsWith('/rlz-check')) return json(GROEN)
      if (url.endsWith('/eerste-sync')) return json({ ...RODE_SYNC, status: 'wachtrij', onderdelen: null, fout_reden: null })
      return json({}, 404)
    })
    const gebruiker = userEvent.setup()
    const onHerlaad = renderCheck(administratie({ eerste_sync: RODE_SYNC }))
    await gebruiker.click(screen.getByRole('button', { name: /RLZ-check voor/ }))
    await screen.findByTestId('rlz-check-resultaat')
    expect(screen.getByTestId('rlz-check-samenvatting')).toHaveTextContent('6 leesroutes groen')
    const sync = screen.getByRole('button', { name: 'Sync opnieuw starten voor Baard beheer & management' })
    await gebruiker.click(sync)
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Eerste sync opnieuw gestart'))
    const eersteSyncCall = fetchMock.mock.calls.find(([u]) => String(u).endsWith('/eerste-sync')) as [string, RequestInit]
    expect(eersteSyncCall[0]).toBe('/instellingen/administraties/aaaaaaaa-0000-0000-0000-000000000001/eerste-sync')
    expect(eersteSyncCall[1].method).toBe('POST')
    expect(screen.queryByRole('button', { name: /Sync opnieuw starten/ })).toBeNull()
    expect(onHerlaad).toHaveBeenCalledTimes(2)
  })

  it('groene check zonder rode eerste sync: géén sync-knop (één primaire knop-regel)', async () => {
    mockFetch(() => json(GROEN))
    const gebruiker = userEvent.setup()
    renderCheck(administratie({ eerste_sync: { ...RODE_SYNC, status: 'klaar' } }))
    await gebruiker.click(screen.getByRole('button', { name: /RLZ-check voor/ }))
    await screen.findByTestId('rlz-check-resultaat')
    expect(screen.queryByRole('button', { name: /Sync opnieuw starten/ })).toBeNull()
  })

  it('503 (geen opgeslagen login) en 404 zijn leesbaar; resultaat blijft leeg', async () => {
    mockFetch(() => json({ detail: 'Geen RLZ-credentials voor 2f916ef0' }, 503))
    const gebruiker = userEvent.setup()
    renderCheck()
    await gebruiker.click(screen.getByRole('button', { name: /RLZ-check voor/ }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Geen opgeslagen webservice-login voor deze administratie')
    expect(screen.queryByTestId('rlz-check-resultaat')).toBeNull()
  })

  it('hulpfuncties: groen-regel volgt de backend (SalesInvoices-403 telt niet mee); fouttekst per status', () => {
    expect(rlzCheckIsGroen({ Ledgers: 'ok', SalesInvoices: '403' })).toBe(true)
    expect(rlzCheckIsGroen({ Ledgers: '403', SalesInvoices: '403' })).toBe(false)
    expect(rlzCheckIsGroen({})).toBe(false)
    expect(rlzCheckFoutTekst(new ApiError(404, 'Onbekende administratie: x'))).toMatch(/^Administratie onbekend of geen webservice-login/)
    expect(rlzCheckFoutTekst(new ApiError(503, 'Geen RLZ-credentials'))).toMatch(/^Geen opgeslagen webservice-login/)
    expect(rlzCheckFoutTekst(new ApiError(500, 'Interne fout'))).toBe('Interne fout')
  })
})
