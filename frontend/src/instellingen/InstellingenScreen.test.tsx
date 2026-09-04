import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../auth/AuthContext'
import { resetMijnToegangCache } from '../auth/useMijnToegang'
import { INSTELLINGEN_SECTIES, InstellingenScreen, zichtbareSecties } from './InstellingenScreen'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

/** Alleen de payload moet kloppen — decodeerJwtPayload() verifieert geen handtekening (puur
 * UI-weergave, zie api/client.ts). Header/signature-delen zijn dummy's. */
function fakeAccessToken(rol: string): string {
  const payload = btoa(JSON.stringify({ sub: 'gebruiker-id', rol })).replace(/\+/g, '-').replace(/\//g, '_')
  return `kop.${payload}.handtekening`
}

function administratie(overrides: Record<string, unknown> = {}) {
  return {
    id: ADMINISTRATIE_ID,
    naam: 'Testklant B.V.',
    boeken_ingeschakeld: false,
    project_verplicht: false,
    is_vastgoed: false,
    verkoop_autoboeken_ingeschakeld: false,
    ai_extractie_ingeschakeld: true,
    uren_meerwerk_ingeschakeld: false,
    uren_dagmax_uren: '12',
    afdelingen_ingeschakeld: false,
    voorraad_ingeschakeld: false,
    eigenaar_gebruiker_id: null,
    gearchiveerd_op: null,
    ...overrides,
  }
}

/** v3 (01-09): de instellingen leven op de detailPAGINA /instellingen/administraties/{id} — ⚙ (of de
 * rij) navigeert erheen; `tab` kiest daarna de tab (default Algemeen). */
async function openDetail(naam: string, tab?: string) {
  await waitFor(() => expect(screen.getAllByText(naam).length).toBeGreaterThan(0))
  fireEvent.click(screen.getByRole('button', { name: `Instellingen van ${naam}` }))
  const detail = await screen.findByTestId('administratie-detail')
  if (tab) fireEvent.click(within(detail).getByRole('tab', { name: tab }))
  return detail
}

function installFetchMock(opties: {
  rol: string
  administraties?: unknown[]
  killSwitch?: boolean
  duplicaatNoodrem?: boolean
  intakeAi?: boolean
  ibanAccordeurs?: string[]
  putAanroepen?: { url: string; body: unknown }[]
  /** Odoo-adapter blok E: antwoord op GET /administraties/{id}/odoo (default 404 = geen koppeling). */
  odooStand?: unknown
  /** Blok A 04-09: antwoord op GET …/odoo/mapping (default = lege mapping). */
  odooMapping?: Record<string, unknown>
  /** Blok B 04-09: overrides op /uren/kantoor/mijn-toegang (o.a. `administraties_met_catalogus`). */
  mijnToegang?: Record<string, unknown>
}) {
  const administraties = opties.administraties ?? [administratie()]
  let killSwitch = opties.killSwitch ?? true
  let duplicaatNoodrem = opties.duplicaatNoodrem ?? true
  let intakeAi = opties.intakeAi ?? false
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url === '/auth/token/vernieuwen' && init?.method === 'POST') {
        return Promise.resolve(jsonResponse({ access_token: fakeAccessToken(opties.rol) }))
      }
      if (url === '/instellingen/administraties' || url === '/instellingen/administraties?inclusief_gearchiveerd=true') {
        return Promise.resolve(jsonResponse({ administraties }))
      }
      // Odoo-adapter blok E (03-09): stand, herprobe, sync en knipdatum.
      if (url.endsWith('/odoo') && (!init || init.method === undefined)) {
        return Promise.resolve(opties.odooStand ? jsonResponse(opties.odooStand) : jsonResponse({ detail: 'geen Odoo-koppeling' }, 404))
      }
      if (url.endsWith('/odoo') && init?.method === 'PUT') {
        const body = JSON.parse(String(init.body))
        opties.putAanroepen?.push({ url, body })
        return Promise.resolve(jsonResponse({ groen: true, rapport: { ledgers: 'ok', boeken: 'ok' }, company_naam: 'Universal Steigerbouw', versie: '19.0', lock_dates: {} }))
      }
      if (url.endsWith('/odoo/sync') && init?.method === 'POST') {
        opties.putAanroepen?.push({ url, body: null })
        return Promise.resolve(jsonResponse({ run_id: 'run-9', onderdelen: { ledgers: { status: 'klaar', aangemaakt: 3, bijgewerkt: 209 }, taxrates: { status: 'klaar', aangemaakt: 0, bijgewerkt: 14 } } }))
      }
      if (url.endsWith('/odoo/leesbron') && init?.method === 'PUT') {
        const body = JSON.parse(String(init.body))
        opties.putAanroepen?.push({ url, body })
        return Promise.resolve(jsonResponse({ ...(opties.odooStand as Record<string, unknown>), voorraad_knip_datum: body.voorraad_knip_datum }))
      }
      if (url.endsWith('/archiveren') && init?.method === 'POST') {
        opties.putAanroepen?.push({ url, body: null })
        return Promise.resolve(jsonResponse({ gearchiveerd_op: '2026-08-30T10:00:00Z', credential_ingetrokken: true, open_documenten: 2 }))
      }
      if (url.endsWith('/dearchiveren') && init?.method === 'POST') {
        const body = JSON.parse(String(init.body)) as { webservice_username: string; wachtwoord: string }
        opties.putAanroepen?.push({ url, body: { webservice_username: body.webservice_username } })
        if (body.webservice_username === 'rood') {
          return Promise.resolve(jsonResponse({ detail: { bericht: 'Rechten-probe niet groen (Vendors=403) — niets gewijzigd', rapporten: { 'rlz-1': { Vendors: '403' } } } }, 422))
        }
        return Promise.resolve(jsonResponse({ rapport: { Ledgers: 'ok' } }))
      }
      // Eerste-sync (wizard-nazorg 27-08): herstart vanaf de rij + status-poll.
      if (url.endsWith('/eerste-sync') && init?.method === 'POST') {
        opties.putAanroepen?.push({ url, body: null })
        return Promise.resolve(jsonResponse({ run_id: 'run-2', status: 'wachtrij', onderdelen: null, aangevraagd_op: null, beeindigd_op: null, fout_reden: null }, 202))
      }
      if (url.endsWith('/eerste-sync/status')) {
        return Promise.resolve(jsonResponse({ run_id: 'run-2', status: 'bezig', onderdelen: null, aangevraagd_op: null, beeindigd_op: null, fout_reden: null }))
      }
      if (url === '/instellingen/boeken-kill-switch' && (!init || init.method === undefined)) {
        return Promise.resolve(jsonResponse({ ingeschakeld: killSwitch }))
      }
      if (url === '/instellingen/duplicaat-autoafvoer' && (!init || init.method === undefined)) {
        return Promise.resolve(jsonResponse({ ingeschakeld: duplicaatNoodrem }))
      }
      if (url === '/instellingen/duplicaat-autoafvoer' && init?.method === 'PUT') {
        const body = JSON.parse(String(init.body)) as { ingeschakeld: boolean }
        duplicaatNoodrem = body.ingeschakeld
        opties.putAanroepen?.push({ url, body })
        return Promise.resolve(jsonResponse({ ingeschakeld: duplicaatNoodrem }))
      }
      if (url === '/instellingen/intake-ai' && (!init || init.method === undefined)) {
        return Promise.resolve(jsonResponse({ ingeschakeld: intakeAi }))
      }
      if (url === '/instellingen/ai-kosten' && (!init || init.method === undefined)) {
        return Promise.resolve(
          jsonResponse({
            maand: '2026-08',
            verbruik_eur: '12.34',
            limiet_eur: '100.00',
            percentage: 12,
            waarschuwing_80: false,
            limiet_bereikt: false,
            geblokkeerd: false,
            extracties_template_maand: 7,
            extracties_ai_maand: 12,
            templates_actief: 2,
          }),
        )
      }
      if (url === '/instellingen/ai-kosten-limiet' && init?.method === 'PUT') {
        const body = JSON.parse(String(init.body)) as { maandlimiet_eur: string }
        opties.putAanroepen?.push({ url, body })
        return Promise.resolve(
          jsonResponse({
            maand: '2026-08',
            verbruik_eur: '12.34',
            limiet_eur: body.maandlimiet_eur,
            percentage: 12,
            waarschuwing_80: false,
            limiet_bereikt: false,
            geblokkeerd: false,
          }),
        )
      }
      if (url === '/instellingen/intake-ai' && init?.method === 'PUT') {
        const body = JSON.parse(String(init.body)) as { ingeschakeld: boolean }
        intakeAi = body.ingeschakeld
        opties.putAanroepen?.push({ url, body })
        return Promise.resolve(jsonResponse({ ingeschakeld: intakeAi }))
      }
      if (url === '/instellingen/boeken-kill-switch' && init?.method === 'PUT') {
        const body = JSON.parse(String(init.body)) as { ingeschakeld: boolean }
        killSwitch = body.ingeschakeld
        opties.putAanroepen?.push({ url, body })
        return Promise.resolve(jsonResponse({ ingeschakeld: killSwitch }))
      }
      if (url.endsWith('/boeken-instelling') && init?.method === 'PUT') {
        const body = JSON.parse(String(init.body)) as unknown
        opties.putAanroepen?.push({ url, body })
        return Promise.resolve(jsonResponse(body))
      }
      if (url.endsWith('/is-vastgoed') && init?.method === 'PATCH') {
        const body = JSON.parse(String(init.body)) as { is_vastgoed: boolean }
        opties.putAanroepen?.push({ url, body })
        return Promise.resolve(
          jsonResponse({ is_vastgoed: body.is_vastgoed, verkoop_autoboeken_ingeschakeld: false, verkoop_autoboeken_uitgezet: !body.is_vastgoed }),
        )
      }
      if (url.endsWith('/verkoop-autoboeken-instelling') && init?.method === 'PUT') {
        const body = JSON.parse(String(init.body)) as unknown
        opties.putAanroepen?.push({ url, body })
        return Promise.resolve(jsonResponse(body))
      }
      if (url.endsWith('/omzet-autoboeken-instelling') && init?.method === 'PUT') {
        const body = JSON.parse(String(init.body))
        opties.putAanroepen?.push({ url, body })
        return Promise.resolve(jsonResponse(body))
      }
      if (url.endsWith('/afdelingen-instelling') && init?.method === 'PUT') {
        const body = JSON.parse(String(init.body))
        opties.putAanroepen?.push({ url, body })
        return Promise.resolve(jsonResponse(body))
      }
      if (url.endsWith('/afdelingen') && (!init || init.method === undefined)) {
        return Promise.resolve(
          jsonResponse({
            ingeschakeld: true,
            afdelingen: [
              { id: 'alg', naam: 'Algemeen', is_terugval: true, actief: true, route: [], staande_goedkeuringen: 0, gearchiveerd_op: null },
            ],
          }),
        )
      }
      if (url.endsWith('/accordering/kandidaten')) return Promise.resolve(jsonResponse({ kandidaten: [] }))
      if (url.endsWith('/accordering/instellingen')) return Promise.resolve(jsonResponse({ ingeschakeld: false, lagen: [] }))
      if (url.endsWith('/accordering/staande-regels')) return Promise.resolve(jsonResponse({ regels: [] }))
      // v3: de tab "Boeken & AI" toont de leverancier-autoboeken van déze administratie.
      if (url.endsWith('/leveranciers-autoboeken')) return Promise.resolve(jsonResponse({ leveranciers: [] }))
      if (url.endsWith('/doorbelasting-instelling')) return Promise.resolve(jsonResponse({ ingeschakeld: false }))
      // Blok B (01-09): kandidaten-motor — stand-chip + lege lijst.
      if (url === '/instellingen/autoboeken/stand') {
        return Promise.resolve(jsonResponse({ kandidaten: 3, actief: 1, heroverwegen: 0, verborgen: 0, administraties_met_kandidaten: 2, drempel: 5, laatste_run_op: '2026-09-01T06:00:00Z' }))
      }
      if (url.startsWith('/instellingen/autoboeken/kandidaten')) {
        return Promise.resolve(jsonResponse({ rijen: [], totaal: 0, pagina: 1, per_pagina: 25, tellers: { kandidaten: 3, actief: 1, heroverwegen: 0, verborgen: 0, administraties_met_kandidaten: 2, drempel: 5, laatste_run_op: '2026-09-01T06:00:00Z' } }))
      }
      if (url.endsWith('/project-instelling') && init?.method === 'PUT') {
        const body = JSON.parse(String(init.body)) as unknown
        opties.putAanroepen?.push({ url, body })
        return Promise.resolve(jsonResponse(body))
      }
      if (url.endsWith('/medewerkers')) {
        return Promise.resolve(
          jsonResponse({ medewerkers: [{ id: 'eeeeeeee-0000-0000-0000-000000000009', naam: 'M. de Boer' }] }),
        )
      }
      if (url.endsWith('/iban-accordeurs') && (!init || init.method === undefined)) {
        return Promise.resolve(jsonResponse({ accordeurs: opties.ibanAccordeurs ?? [] }))
      }
      if (url.endsWith('/iban-accordeurs') && init?.method === 'PUT') {
        const body = JSON.parse(String(init.body)) as unknown
        opties.putAanroepen?.push({ url, body })
        return Promise.resolve(jsonResponse(body))
      }
      if (url.endsWith('/eigenaar') && init?.method === 'PUT') {
        const body = JSON.parse(String(init.body)) as unknown
        opties.putAanroepen?.push({ url, body })
        return Promise.resolve(jsonResponse(body))
      }
      // Blok B 31-08: B+P-toegang tot de Materiaalcatalogus — scope-lijst + mijn-toegang +
      // de fetches die MateriaalCatalogusBeheer zelf doet.
      if (url === '/uren/kantoor/mijn-toegang') {
        return Promise.resolve(
          jsonResponse({
            heeft_meerwerk_recht: true,
            administraties_met_opt_in: [ADMINISTRATIE_ID],
            aantal_administraties_in_scope: 3,
            is_beheerder: opties.rol === 'beheerder',
            heeft_veldwerkerbeheer_recht: false,
            is_beheerder_of_bp: opties.rol === 'beheerder' || opties.rol === 'boekhouding_projecten',
          }),
        )
      }
      if (url === '/auth/administraties') {
        return Promise.resolve(jsonResponse({ administraties: [{ id: ADMINISTRATIE_ID, naam: 'Testklant B.V.' }] }))
      }
      if (url.includes('/materiaal/') && url.includes('/leveranciers')) {
        return Promise.resolve(jsonResponse([]))
      }
      if (url.endsWith('/crediteuren')) {
        return Promise.resolve(jsonResponse({ crediteuren: [] }))
      }
      // Beveiliging-sectie (kantoor-passkeys, besluit 0020) — voor élke kantoor-rol.
      // D2 (01-09): weekmail-voorkeur op de Beveiliging-pagina.
      if (url === '/auth/mijn/digest' && (!init || init.method === undefined)) return Promise.resolve(jsonResponse({ opt_out: false }))
      if (url === '/auth/mijn/digest' && init?.method === 'PUT') {
        const body = JSON.parse(String(init.body))
        opties.putAanroepen?.push({ url, body })
        return Promise.resolve(jsonResponse(body))
      }
      if (url === '/auth/mijn/apparaten') {
        return Promise.resolve(jsonResponse({ apparaten: [] }))
      }
            ...(opties.mijnToegang ?? {}),
      if (url === '/auth/webauthn/config') {
        return Promise.resolve(jsonResponse({ dev_stub: false, rp_id: 'localhost' }))
      }
      if (url === '/auth/apparaten/kantoor') {
        return Promise.resolve(jsonResponse({ apparaten: [] }))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

/** v3 (01-09): geen landing — /instellingen redirect naar het eerste zichtbare nav-item; de secties
 * leven op `/instellingen/<sectie>`, administratie-detail op `/instellingen/administraties/<id>`.
 * Tests renderen standaard de subpagina die ze toetsen. */
function renderScherm(pad = '/instellingen/administraties') {
  return render(
    <MemoryRouter initialEntries={[pad]}>
      <AuthProvider>
        <Routes>
          <Route path="/" element={<div>WERKVOORRAAD-SCHERM</div>} />
          <Route path="/gebruikers" element={<div>GEBRUIKERS-SCHERM</div>} />
          <Route path="/crediteuren" element={<div>CREDITEUREN-SCHERM</div>} />
          <Route path="/instellingen" element={<InstellingenScreen />} />
          <Route path="/instellingen/administraties/:administratieId" element={<InstellingenScreen />} />
          <Route path="/instellingen/:sectie" element={<InstellingenScreen />} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('InstellingenScreen — rolgedrag (design-pass taak 3)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('een niet-Beheerder ziet alléén de Beveiliging-sectie (eigen passkeys, besluit 0020) — nav toont alleen dat item, lege groepen geen kop', async () => {
    installFetchMock({ rol: 'boekhouding' })
    renderScherm('/instellingen')
    expect(await screen.findByRole('heading', { name: /Beveiliging — passkeys/ })).toBeInTheDocument()
    expect(screen.queryByText('Administraties')).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /Boeken platformbreed/ })).not.toBeInTheDocument()
    const nav = screen.getByRole('navigation', { name: 'Instellingen' })
    expect(within(nav).getAllByRole('link')).toHaveLength(1)
    expect(within(nav).getByText('Kantoor')).toBeInTheDocument()
    expect(within(nav).queryByText('Platform')).not.toBeInTheDocument()
  })

  it('v3 (01-09, herziet D2): een Beheerder landt zónder tussenstop op Administraties; de settings-nav staat erbij mét stand-chips en Gebruikers → /gebruikers', async () => {
    installFetchMock({ rol: 'beheerder', administraties: [administratie({ naam: 'Kempen Facilities B.V.' })] })
    renderScherm('/instellingen')
    await waitFor(() => expect(screen.getAllByText('Kempen Facilities B.V.').length).toBeGreaterThan(0))
    expect(screen.getByTestId('administraties-v2')).toBeInTheDocument()
    expect(screen.queryByText('Openen →')).not.toBeInTheDocument()
    const nav = screen.getByRole('navigation', { name: 'Instellingen' })
    for (const titel of ['Administraties', 'Klant-accordering', 'Autoboeken', 'Doorbelasting', 'Boeken platformbreed', 'Intake-AI & kosten', 'Beveiliging', 'Materiaalcatalogus']) {
      expect(within(nav).getByRole('link', { name: new RegExp(titel) })).toBeInTheDocument()
    }
    expect(within(nav).getByRole('link', { name: /Gebruikers & toegang/ })).toHaveAttribute('href', '/gebruikers')
    expect(within(nav).getByRole('link', { name: /Administraties/ })).toHaveAttribute('aria-current', 'page')
    // Stand-chips (mockup: teller, aan/uit, %).
    expect(within(nav).getByRole('link', { name: /Boeken platformbreed/ })).toHaveTextContent('aan')
    expect(within(nav).getByRole('link', { name: /Intake-AI & kosten/ })).toHaveTextContent('12%')
    expect(within(nav).getByRole('link', { name: /Administraties/ })).toHaveTextContent('1')
    expect(within(nav).getByRole('link', { name: /Autoboeken/ })).toHaveTextContent('3')
    expect(screen.queryByText('WERKVOORRAAD-SCHERM')).not.toBeInTheDocument()
  })

  it('redirect-sweep oude URL\'s (v3): hash/query-deep-links → sectie, crediteuren → Inzicht, gebruikers → /gebruikers, ?administratie= → detailpagina, onbekend → landing', async () => {
    const gevallen: [string, () => Promise<unknown>][] = [
      ['/instellingen?sectie=doorbelasting', () => screen.findByRole('heading', { name: 'Doorbelasting' })],
      ['/instellingen#boeken', () => screen.findByRole('checkbox', { name: 'Boeken platformbreed' })],
      ['/instellingen/crediteuren', () => screen.findByText('CREDITEUREN-SCHERM')],
      ['/instellingen#crediteuren', () => screen.findByText('CREDITEUREN-SCHERM')],
      ['/instellingen/gebruikers', () => screen.findByText('GEBRUIKERS-SCHERM')],
      [`/instellingen?administratie=${ADMINISTRATIE_ID}`, () => screen.findByTestId('administratie-detail')],
      ['/instellingen/bestaat-niet', () => screen.findByTestId('administraties-v2')],
      ['/instellingen', () => screen.findByTestId('administraties-v2')],
    ]
    for (const [pad, verwacht] of gevallen) {
      vi.unstubAllGlobals()
      installFetchMock({ rol: 'beheerder' })
      const r = renderScherm(pad)
      expect(await verwacht()).toBeInTheDocument()
      r.unmount()
    }
  })

  it('zoeker: "accordering test" geeft een administratie-specifieke deep-link naar de detailpagina-tab (deterministische registry)', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({ rol: 'beheerder', administraties: [administratie({ naam: 'Testklant B.V.' })] })
    renderScherm('/instellingen/boeken')
    await screen.findByRole('checkbox', { name: 'Boeken platformbreed' })
    const zoek = screen.getByRole('combobox', { name: 'Zoek instelling' })
    await gebruiker.type(zoek, 'accordering test')
    const res = await screen.findByTestId('instellingen-zoekresultaten')
    expect(within(res).getByText('Klant-accordering — Testklant B.V.')).toBeInTheDocument()
    expect(within(res).getByText('Klant-accordering — alle administraties')).toBeInTheDocument()
    await gebruiker.click(within(res).getByText('Klant-accordering — Testklant B.V.'))
    const detail = await screen.findByTestId('administratie-detail')
    expect(within(detail).getByRole('tab', { name: 'Klant-accordering' })).toHaveAttribute('aria-selected', 'true')
  })

  it('detailpagina: tabs volgen de toon-regel (Voorraad/Uren alleen bij opt-in, Doorbelasting bij bron óf doel) en de kop draagt de acties', async () => {
    installFetchMock({
      rol: 'beheerder',
      administraties: [
        administratie({ naam: 'Kaal B.V.' }),
        administratie({ id: 'bbbbbbbb-0000-0000-0000-000000000002', naam: 'Vol B.V.', voorraad_ingeschakeld: true, uren_meerwerk_ingeschakeld: true, doorbelasting_doel: true }),
      ],
    })
    renderScherm()
    let detail = await openDetail('Kaal B.V.')
    expect(within(detail).getAllByRole('tab').map((t) => t.textContent)).toEqual(['Algemeen', 'Boeken & AI', 'Klant-accordering'])
    expect(within(detail).getByRole('button', { name: 'Schrijftest voor Kaal B.V.' })).toBeInTheDocument()
    expect(within(detail).getByRole('button', { name: 'Webservice-gegevens van Kaal B.V.' })).toBeInTheDocument()
    expect(within(detail).getByRole('button', { name: 'Archiveren Kaal B.V.' })).toBeInTheDocument()
    fireEvent.click(within(detail).getByRole('link', { name: 'Administraties' }))
    detail = await openDetail('Vol B.V.')
    expect(within(detail).getAllByRole('tab').map((t) => t.textContent)).toEqual([
      'Algemeen',
      'Boeken & AI',
      'Klant-accordering',
      'Doorbelasting',
      'Uren & materiaal',
      'Voorraad',
    ])
  })

  it('detailpagina (Algemeen) toont "IBAN-accordeurs" mét accordeur-chip en wijzig-dialoog, zonder foutbanner', async () => {
    installFetchMock({
      rol: 'beheerder',
      administraties: [administratie({ naam: 'Kempen Facilities B.V.' })],
      ibanAccordeurs: ['eeeeeeee-0000-0000-0000-000000000009'],
    })
    renderScherm()
    await openDetail('Kempen Facilities B.V.')
    expect(screen.getByText('IBAN-accordeurs')).toBeInTheDocument()
    await waitFor(() => expect(screen.getAllByText('M. de Boer').length).toBeGreaterThan(0))
    await userEvent.setup().click(screen.getByRole('button', { name: /IBAN-accordeurs van Kempen Facilities B\.V\. wijzigen/ }))
    const accordeurCheckbox = await screen.findByRole('checkbox', { name: /M\. de Boer/ })
    expect(accordeurCheckbox).toBeChecked()
    expect(screen.queryByText(/Kon instellingen niet laden/)).not.toBeInTheDocument()
    expect(screen.queryByText(/accordeurs niet te laden/)).not.toBeInTheDocument()
  })

  it('toont naast het AI-verbruiksblok de extractie-teller per bron (template vs AI) + actieve templates (01-09)', async () => {
    installFetchMock({ rol: 'beheerder' })
    renderScherm('/instellingen/intake-ai')

    const teller = await screen.findByTestId('extractie-template-teller')
    expect(teller.textContent).toContain('7 via template')
    expect(teller.textContent).toContain('12 via AI')
    expect(teller.textContent).toContain('2 actieve templates')
    expect(teller.textContent).toContain('geen AI-aanroep, geen data naar buiten')
  })

  it('toont de terugval op de beheerder(s) bij een lege accordeur-set', async () => {
    installFetchMock({ rol: 'beheerder', ibanAccordeurs: [] })
    renderScherm()
    await openDetail('Testklant B.V.')
    expect(await screen.findByText(/beheerders \(terugval\)/)).toBeInTheDocument()
  })
})

describe('InstellingenScreen — rol×sectie-matrix (blok B 31-08, fail-closed)', () => {
  beforeEach(() => {
    resetMijnToegangCache()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    resetMijnToegangCache()
  })

  it('zichtbareSecties is fail-closed: materiaal is de enige B+P-uitzondering, onbekende rol ziet alleen Beveiliging', () => {
    const paden = (rol: string | null) => zichtbareSecties(rol).map((k) => k.pad)
    expect(paden('beheerder')).toEqual(INSTELLINGEN_SECTIES.map((k) => k.pad))
    expect(paden('boekhouding_projecten')).toEqual(['beveiliging', 'materiaal'])
    expect(paden('boekhouding')).toEqual(['beveiliging'])
    expect(paden('toekomstige_rol')).toEqual(['beveiliging'])
    expect(paden(null)).toEqual(['beveiliging'])
    // Vangnet op het vangnet: de matrix loopt over de échte nav-lijst (v3: 9 items, Crediteuren → Inzicht).
    expect(INSTELLINGEN_SECTIES.length).toBeGreaterThanOrEqual(9)
  })

  it('B+P landt (v3) direct op de Materiaalcatalogus; de nav toont precies twee items (Beveiliging + Materiaalcatalogus)', async () => {
    installFetchMock({ rol: 'boekhouding_projecten' })
    renderScherm('/instellingen')
    expect(await screen.findByRole('heading', { name: 'Materiaalcatalogus' })).toBeInTheDocument()
    const nav = screen.getByRole('navigation', { name: 'Instellingen' })
    expect(within(nav).getAllByRole('link').map((l) => l.textContent)).toEqual(['Beveiliging', 'Materiaalcatalogus'])
    expect(screen.queryByText('Boeken platformbreed')).not.toBeInTheDocument()
    expect(screen.queryByText('Administraties')).not.toBeInTheDocument()
  })

  it('B+P bereikt /instellingen/materiaal mét de scope-administraties (casus Haci)', async () => {
    installFetchMock({ rol: 'boekhouding_projecten' })
    renderScherm('/instellingen/materiaal')
    expect(await screen.findByRole('heading', { name: /Materiaalcatalogus \(transport/ })).toBeInTheDocument()
    // De administratie-kiezer draagt de scope-administratie uit /auth/administraties.
    expect(await screen.findByDisplayValue('Testklant B.V.')).toBeInTheDocument()
  })

  it('élke andere beheer-sectie (en de detailpagina) valt voor B+P fail-closed terug op de eigen landing (Materiaalcatalogus)', async () => {
    // 'gebruikers' uitgezonderd: dat item redirect extern naar /gebruikers (eigen rol-gate).
    const beheerSecties = INSTELLINGEN_SECTIES.filter((k) => k.beheerder && k.pad !== 'materiaal' && k.pad !== 'gebruikers')
    expect(beheerSecties.length).toBeGreaterThan(5)
    for (const pad of [...beheerSecties.map((k) => `/instellingen/${k.pad}`), `/instellingen/administraties/${ADMINISTRATIE_ID}`]) {
      vi.unstubAllGlobals()
      resetMijnToegangCache()
      installFetchMock({ rol: 'boekhouding_projecten' })
      const r = renderScherm(pad)
      expect(await screen.findByRole('heading', { name: /Materiaalcatalogus \(transport/ })).toBeInTheDocument()
      expect(screen.queryByRole('heading', { name: /Boeken platformbreed/ })).not.toBeInTheDocument()
      expect(screen.queryByTestId('administratie-detail')).not.toBeInTheDocument()
      r.unmount()
    }
  })

  it('boekhouding blijft óók op /instellingen/materiaal op Beveiliging (fail-closed)', async () => {
    installFetchMock({ rol: 'boekhouding' })
    renderScherm('/instellingen/materiaal')
    expect(await screen.findByRole('heading', { name: /Beveiliging — passkeys/ })).toBeInTheDocument()
    expect(screen.queryByText(/Materiaalcatalogus \(transport/)).not.toBeInTheDocument()
  })
})

describe('InstellingenScreen — toggle-flow (Beheerder)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('een toggle-klik (op de detailpagina) opent een bevestigingsdialoog en wijzigt pas na bevestigen; afwijking = chip in de tabel', async () => {
    const gebruiker = userEvent.setup()
    const putAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ rol: 'beheerder', administraties: [administratie({ naam: 'BLOW B.V.', boeken_ingeschakeld: false })], putAanroepen })
    renderScherm()
    await waitFor(() => expect(screen.getAllByText('BLOW B.V.').length).toBeGreaterThan(0))
    expect(screen.getByText('Boeken UIT (afwijking)')).toBeInTheDocument()
    await openDetail('BLOW B.V.', 'Boeken & AI')
    // Op naam, nooit op checkbox-index.
    const boekenToggle = screen.getByRole('checkbox', { name: 'Boeken ingeschakeld voor BLOW B.V.' })
    await gebruiker.click(boekenToggle)
    expect(screen.getByText(/Boeken wordt ingeschakeld voor "BLOW B.V."/)).toBeInTheDocument()
    expect(putAanroepen).toHaveLength(0)
    expect(boekenToggle).not.toBeChecked()
    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await waitFor(() => expect(putAanroepen).toHaveLength(1))
    expect(putAanroepen[0].url).toContain(`/administraties/${ADMINISTRATIE_ID}/boeken-instelling`)
    expect(putAanroepen[0].body).toEqual({ ingeschakeld: true })
    await waitFor(() => expect(screen.getByRole('checkbox', { name: 'Boeken ingeschakeld voor BLOW B.V.' })).toBeChecked())
  })

  it('vastgoed-koppeling: consequentie-dialoog + PATCH; autoboeken volgt de koppeling — geen aparte schakelaar (v2 30-08)', async () => {
    const gebruiker = userEvent.setup()
    const putAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({
      rol: 'beheerder',
      administraties: [
        administratie({ naam: 'Rubicon Investments B.V.' }),
        administratie({ id: 'aaaaaaaa-0000-0000-0000-000000000002', naam: 'Molenhof B.V.', is_vastgoed: true, verkoop_autoboeken_ingeschakeld: true }),
      ],
      putAanroepen,
    })
    renderScherm()
    await waitFor(() => expect(screen.getAllByText('Molenhof B.V.').length).toBeGreaterThan(0))
    expect(screen.getByText('Vastgoed + autoboeken')).toBeInTheDocument()
    expect(screen.queryByRole('checkbox', { name: /Autoboeken Vastly-verkoop/ })).not.toBeInTheDocument()
    await openDetail('Rubicon Investments B.V.')
    expect(screen.queryByRole('checkbox', { name: /Autoboeken Vastly-verkoop/ })).not.toBeInTheDocument()
    await gebruiker.click(screen.getByRole('checkbox', { name: 'Vastgoed-koppeling voor Rubicon Investments B.V.' }))
    expect(screen.getByText(/factuur_geboekt- en factuur_gestorneerd-events naar Vastly gaan per direct lopen/)).toBeInTheDocument()
    expect(screen.getByText(/autoboeken volgt de koppeling/)).toBeInTheDocument()
    expect(putAanroepen).toHaveLength(0)
    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await waitFor(() => expect(putAanroepen).toHaveLength(1))
    expect(putAanroepen[0].url).toBe(`/administraties/${ADMINISTRATIE_ID}/is-vastgoed`)
    expect(putAanroepen[0].body).toEqual({ is_vastgoed: true })
  })

  it('annuleren sluit de bevestiging zonder een aanroep te doen en laat de toggle ongewijzigd', async () => {
    const gebruiker = userEvent.setup()
    const putAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ rol: 'beheerder', administraties: [administratie({ naam: 'BLOW B.V.', project_verplicht: false })], putAanroepen })
    renderScherm()
    await openDetail('BLOW B.V.', 'Boeken & AI')
    const projectToggle = screen.getByRole('checkbox', { name: 'Project verplicht voor BLOW B.V.' })
    await gebruiker.click(projectToggle)
    expect(screen.getByText(/Project wordt verplicht bij boeken/)).toBeInTheDocument()
    await gebruiker.click(screen.getByRole('button', { name: 'Annuleren' }))
    expect(screen.queryByText(/Project wordt verplicht bij boeken/)).not.toBeInTheDocument()
    expect(putAanroepen).toHaveLength(0)
    expect(projectToggle).not.toBeChecked()
  })

  it('"Duplicaten automatisch afvoeren" is een platformbrede noodrem op Instellingen › Boeken (blok A1 04-09): standaard aan, uit = bevestiging + PUT', async () => {
    const gebruiker = userEvent.setup()
    const putAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ rol: 'beheerder', duplicaatNoodrem: true, putAanroepen })
    renderScherm('/instellingen/boeken')
    const noodrem = await screen.findByRole('checkbox', { name: 'Duplicaten automatisch afvoeren' })
    expect(noodrem).toBeChecked()
    expect(screen.getByText('aan — duplicaten worden afgevoerd')).toBeInTheDocument()
    await gebruiker.click(noodrem)
    expect(screen.getByText(/NOODREM: duplicaten automatisch afvoeren gaat platformbreed UIT/)).toBeInTheDocument()
    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await waitFor(() => expect(putAanroepen).toHaveLength(1))
    expect(putAanroepen[0].url).toBe('/instellingen/duplicaat-autoafvoer')
    expect(putAanroepen[0].body).toEqual({ ingeschakeld: false })
    expect(await screen.findByText('uit — noodrem actief')).toBeInTheDocument()
  })

  it('de administratie-detailpagina heeft geen toggle "Duplicaten automatisch afvoeren" meer (per-administratie-opt-in vervallen)', async () => {
    installFetchMock({ rol: 'beheerder', administraties: [administratie({ naam: 'BLOW B.V.' })] })
    renderScherm()
    await openDetail('BLOW B.V.', 'Boeken & AI')
    expect(screen.queryByRole('checkbox', { name: /Duplicaat-afvoer automatisch voor/ })).not.toBeInTheDocument()
  })

  it('"Boeken platformbreed" (D4: aan = boeken kan, uit = boeken staat plat) vraagt ook een bevestiging', async () => {
    const gebruiker = userEvent.setup()
    const putAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ rol: 'beheerder', killSwitch: true, putAanroepen })
    renderScherm('/instellingen/boeken')
    const killSwitchToggle = await screen.findByRole('checkbox', { name: 'Boeken platformbreed' })
    expect(screen.getByText('aan — boeken kan')).toBeInTheDocument()
    expect(screen.queryByText(/kill switch/i)).not.toBeInTheDocument()
    await gebruiker.click(killSwitchToggle)
    expect(screen.getByText(/boeken staat per direct plat voor ALLE administraties/)).toBeInTheDocument()
    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await waitFor(() => expect(putAanroepen).toHaveLength(1))
    expect(putAanroepen[0].url).toBe('/instellingen/boeken-kill-switch')
    expect(putAanroepen[0].body).toEqual({ ingeschakeld: false })
  })

  it('de intake-AI-toggle (AVG-gate) vraagt bevestiging en PUT naar /instellingen/intake-ai', async () => {
    const gebruiker = userEvent.setup()
    const putAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ rol: 'beheerder', intakeAi: false, putAanroepen })
    renderScherm('/instellingen/intake-ai')
    const intakeAiToggle = await screen.findByRole('checkbox', { name: 'Intake-AI ingeschakeld' })
    expect(intakeAiToggle).not.toBeChecked()
    await gebruiker.click(intakeAiToggle)
    expect(screen.getByText(/naar de Claude API \(platform-brede AVG-gate\)/)).toBeInTheDocument()
    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await waitFor(() => expect(putAanroepen).toHaveLength(1))
    expect(putAanroepen[0].url).toBe('/instellingen/intake-ai')
    expect(putAanroepen[0].body).toEqual({ ingeschakeld: true })
    await waitFor(() => expect(screen.getByRole('checkbox', { name: 'Intake-AI ingeschakeld' })).toBeChecked())
  })

  it('eigenaar kiezen (op de detailpagina) vraagt bevestiging en PUT de eigenaar (krijgt vragen)', async () => {
    const gebruiker = userEvent.setup()
    const putAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ rol: 'beheerder', putAanroepen })
    renderScherm()
    await openDetail('Testklant B.V.')
    await waitFor(() => expect(screen.getByLabelText('Eigenaar van Testklant B.V.')).not.toBeDisabled())
    await gebruiker.selectOptions(screen.getByLabelText('Eigenaar van Testklant B.V.'), 'eeeeeeee-0000-0000-0000-000000000009')
    expect(screen.getByText(/M\. de Boer wordt eigenaar van "Testklant B\.V\."/)).toBeInTheDocument()
    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await waitFor(() => expect(putAanroepen).toHaveLength(1))
    expect(putAanroepen[0].url).toBe(`/administraties/${ADMINISTRATIE_ID}/eigenaar`)
    expect(putAanroepen[0].body).toEqual({ eigenaar_gebruiker_id: 'eeeeeeee-0000-0000-0000-000000000009' })
  })
})

describe('InstellingenScreen — bulkbediening administraties (fase 3 modernisering 15-08)', () => {
  const TWEEDE_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('rijselectie toont de bulkbalk; "Boeken aan" vraagt één bevestiging en PUT per administratie', async () => {
    const gebruiker = userEvent.setup()
    const putAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({
      rol: 'beheerder',
      administraties: [administratie({ naam: 'Kempen Facilities B.V.' }), administratie({ id: TWEEDE_ID, naam: 'Molenhof Beheer B.V.' })],
      putAanroepen,
    })
    renderScherm()
    await waitFor(() => expect(screen.getAllByText('Kempen Facilities B.V.').length).toBeGreaterThan(0))
    expect(screen.queryByRole('toolbar', { name: 'Bulk-bediening' })).not.toBeInTheDocument()
    await gebruiker.click(screen.getByRole('checkbox', { name: 'Selecteer Kempen Facilities B.V.' }))
    await gebruiker.click(screen.getByRole('checkbox', { name: 'Selecteer Molenhof Beheer B.V.' }))
    expect(screen.getByRole('toolbar', { name: 'Bulk-bediening' })).toBeInTheDocument()
    expect(screen.getByText('2 geselecteerd')).toBeInTheDocument()
    await gebruiker.click(screen.getByRole('button', { name: 'Boeken aan' }))
    expect(putAanroepen).toHaveLength(0)
    expect(screen.getByText(/Bulkactie: Boeken AAN/)).toBeInTheDocument()
    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await waitFor(() => expect(putAanroepen).toHaveLength(2))
    expect(putAanroepen.map((p) => p.url).sort()).toEqual([
      `/administraties/${ADMINISTRATIE_ID}/boeken-instelling`,
      `/administraties/${TWEEDE_ID}/boeken-instelling`,
    ])
    expect(putAanroepen.every((p) => (p.body as { ingeschakeld: boolean }).ingeschakeld)).toBe(true)
    await waitFor(() => expect(screen.queryByRole('toolbar', { name: 'Bulk-bediening' })).not.toBeInTheDocument())
  })

  it('"alles selecteren" selecteert alle rijen; selectie wissen haalt de balk weg', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({
      rol: 'beheerder',
      administraties: [administratie({ naam: 'Kempen Facilities B.V.' }), administratie({ id: TWEEDE_ID, naam: 'Molenhof Beheer B.V.' })],
    })
    renderScherm()
    await waitFor(() => expect(screen.getAllByText('Kempen Facilities B.V.').length).toBeGreaterThan(0))
    await gebruiker.click(screen.getByRole('checkbox', { name: 'Alle administraties selecteren' }))
    expect(screen.getByText('2 geselecteerd')).toBeInTheDocument()
    await gebruiker.click(screen.getByRole('button', { name: '✕ selectie wissen' }))
    expect(screen.queryByRole('toolbar', { name: 'Bulk-bediening' })).not.toBeInTheDocument()
  })

  it('een deels mislukte bulkactie toont de mislukte administraties zichtbaar (niets stil)', async () => {
    const gebruiker = userEvent.setup()
    const putAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({
      rol: 'beheerder',
      administraties: [administratie({ naam: 'Kempen Facilities B.V.' }), administratie({ id: TWEEDE_ID, naam: 'Molenhof Beheer B.V.' })],
      putAanroepen,
    })
    const basisFetch = globalThis.fetch
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url === `/administraties/${TWEEDE_ID}/boeken-instelling` && init?.method === 'PUT') {
          return Promise.resolve(new Response(JSON.stringify({ detail: 'geen RLZ-credentials' }), { status: 409, headers: { 'Content-Type': 'application/json' } }))
        }
        return (basisFetch as typeof fetch)(url as string, init)
      }),
    )
    renderScherm()
    await waitFor(() => expect(screen.getAllByText('Kempen Facilities B.V.').length).toBeGreaterThan(0))
    await gebruiker.click(screen.getByRole('checkbox', { name: 'Alle administraties selecteren' }))
    await gebruiker.click(screen.getByRole('button', { name: 'Boeken aan' }))
    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await waitFor(() => expect(screen.getByText(/Niet alles gelukt/)).toBeInTheDocument())
    expect(screen.getByText(/Molenhof Beheer B\.V\.: geen RLZ-credentials/)).toBeInTheDocument()
    expect(putAanroepen.some((p) => p.url === `/administraties/${ADMINISTRATIE_ID}/boeken-instelling`)).toBe(true)
  })
})

describe('InstellingenScreen — koppeling Reeleezee (feedbackronde 26-08 punt 5)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('toont "+ Administratie toevoegen", de koppelstand als sync-chip/op de detailpagina zonder wachtwoord en 🧪 per rij', async () => {
    installFetchMock({
      rol: 'beheerder',
      administraties: [
        administratie({ webservice_username: 'ws_nijenhuis', probe_groen: true, rlz_admin_id: 'rlz-1', laatste_sync_op: '2026-08-30T04:14:00Z' }),
        administratie({ id: 'bbbbbbbb-0000-0000-0000-000000000002', naam: 'Zonder Login B.V.' }),
      ],
    })
    renderScherm('/instellingen/administraties')
    await waitFor(() => expect(screen.getByRole('button', { name: '+ Administratie toevoegen' })).toBeInTheDocument())
    expect(await screen.findByText('geen credentials')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /Schrijftest voor/ })).toHaveLength(2)
    const detail = await openDetail('Testklant B.V.')
    expect(screen.getByText('ws_nijenhuis')).toHaveClass('chip', 'ok')
    expect(screen.getByRole('button', { name: /Webservice-gegevens van Testklant B\.V\./ })).toBeInTheDocument()
    fireEvent.click(within(detail).getByRole('link', { name: 'Administraties' }))
    fireEvent.click(await screen.findByRole('button', { name: '+ Administratie toevoegen' }))
    expect(await screen.findByText('Administratie toevoegen — stap 1 van 4')).toBeInTheDocument()
  })

  it('wizard-nazorg 27-08: mislukte eerste sync = rode sync-chip + subrij mét foutreden en herstartknop (zelfde endpoint); groen of nooit = niets', async () => {
    const putAanroepen: { url: string; body: unknown }[] = []
    const fout = {
      run_id: 'run-1',
      status: 'fout',
      onderdelen: { ledgers: { status: 'klaar', aangemaakt: 412, bijgewerkt: 0 }, vendors: { status: 'fout', fout: 'RlzApiError: 403 Forbidden op Vendors' } },
      aangevraagd_op: '2026-08-27T09:00:00Z',
      beeindigd_op: '2026-08-27T09:01:00Z',
      fout_reden: 'Niet alle onderdelen gelukt: vendors — zie details per onderdeel',
    }
    const klaar = { ...fout, run_id: 'run-0', status: 'klaar', fout_reden: null }
    installFetchMock({
      rol: 'beheerder',
      putAanroepen,
      administraties: [
        administratie({ naam: 'Bouwadvies Oost Nederland B.V.', webservice_username: 'ws_boon', probe_groen: true, rlz_admin_id: 'rlz-boon', eerste_sync: fout }),
        administratie({ id: 'bbbbbbbb-0000-0000-0000-000000000002', naam: 'Groene Klant B.V.', eerste_sync: klaar }),
        administratie({ id: 'bbbbbbbb-0000-0000-0000-000000000003', naam: 'Oude Klant B.V.', eerste_sync: null }),
      ],
    })
    renderScherm('/instellingen/administraties')
    const knop = await screen.findByRole('button', { name: 'Sync opnieuw starten voor Bouwadvies Oost Nederland B.V.' })
    expect(screen.getByText('⚠ sync-fout')).toBeInTheDocument()
    expect(screen.getByText('Niet alle onderdelen gelukt: vendors — zie details per onderdeel')).toBeInTheDocument()
    expect(screen.getByText('RlzApiError: 403 Forbidden op Vendors')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /Sync opnieuw starten voor/ })).toHaveLength(1)
    expect(screen.queryByTestId('eerste-sync-bbbbbbbb-0000-0000-0000-000000000002')).not.toBeInTheDocument()
    fireEvent.click(knop)
    await waitFor(() => expect(putAanroepen.some((p) => p.url === `/instellingen/administraties/${ADMINISTRATIE_ID}/eerste-sync`)).toBe(true))
    await waitFor(() => expect(screen.queryByRole('button', { name: /Sync opnieuw starten voor Bouwadvies/ })).not.toBeInTheDocument())
    expect(screen.getByTestId('eerste-sync-rlz-boon')).toHaveTextContent('wachtrij')
  })
})

describe('InstellingenScreen — blok Boekhoud-backend (Odoo-adapter blok E, 03-09)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  const ODOO_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
  const ODOO_STAND = {
    company_id: 1,
    company_naam: 'Universal Steigerbouw',
    odoo_url: 'https://universal-steigers.odoo.com',
    api_gebruiker: 'n-module',
    api_key_verloopt_op: null,
    probe_groen: true,
    probe_op: '2026-09-03T20:14:00Z',
    alleen_lezen: false,
    voorraad_knip_datum: null,
    probe_rapport: { ledgers: 'ok', taxrates: 'ok', vendors: 'ok', journals: 'ok', facturen: 'ok', boeken: 'ok' },
    stamgegevens: { ledgers: 212, taxrates: 14, vendors: 380, projects: 6 },
    laatste_sync_op: '2026-09-03T05:00:00Z',
    overgangsdatum: '2026-10-01',
    rlz_admin_id_voor_overstap: 'rlz-us',
  }

  it('RLZ-administratie: paarse chip Reeleezee + RLZ-id, webservice- en eerste-sync-rij ín het blok, leesbron "n.v.t." + "Odoo koppelen…" (ingang B) opent de koppelvorm-stap', async () => {
    installFetchMock({ rol: 'beheerder', administraties: [administratie({ webservice_username: 'ws_nijenhuis', probe_groen: true, rlz_admin_id: 'rlz-1' })] })
    renderScherm()
    const detail = await openDetail('Testklant B.V.')
    expect(within(detail).getByTestId('backend-blok-kop')).toHaveTextContent('Boekhoud-backend')
    const backend = within(detail).getByTestId('backend-rlz')
    expect(within(backend).getByText('Reeleezee')).toHaveClass('text-purple')
    expect(within(backend).getByText('RLZ-id rlz-1')).toBeInTheDocument()
    expect(within(detail).getByText('ws_nijenhuis')).toHaveClass('chip', 'ok')
    expect(within(detail).getByText('Eerste sync')).toBeInTheDocument()
    expect(within(detail).getByText('n.v.t.')).toBeInTheDocument()
    // RLZ-kopacties blijven.
    expect(within(detail).getByRole('button', { name: 'Schrijftest voor Testklant B.V.' })).toBeInTheDocument()
    expect(within(detail).getByRole('button', { name: 'Webservice-gegevens van Testklant B.V.' })).toBeInTheDocument()
    fireEvent.click(within(detail).getByRole('button', { name: 'Odoo koppelen aan Testklant B.V.' }))
    expect(await screen.findByText('Odoo koppelen — Testklant B.V. — stap 1 van 5')).toBeInTheDocument()
    expect(screen.getByLabelText('Volledige backend')).toBeChecked()
    expect(screen.getByLabelText('Alleen-lezen leesbron')).toBeInTheDocument()
    // Netjes sluiten: een open Radix-dialoog bij unmount laat een focus-scope-timer achter (flaky teardown).
    fireEvent.click(screen.getByRole('button', { name: 'Annuleren' }))
    await waitFor(() => expect(screen.queryByTestId('odoo-koppel-dialoog')).not.toBeInTheDocument())
  })

  it('Odoo-administratie: tabel-chip "Odoo" + probe-sync-chip zonder "geen credentials"; blok mét company, probe groen, sleutel, stamgegevens en "⟳ Sync nu"; géén Schrijftest/Webservice-knoppen', async () => {
    const putAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({
      rol: 'beheerder',
      putAanroepen,
      odooStand: ODOO_STAND,
      administraties: [
        administratie({
          id: ODOO_ID,
          naam: 'Universal Steigerbouw B.V.',
          boekhoud_backend: 'odoo',
          odoo_company_id: 1,
          odoo_company_naam: 'Universal Steigerbouw',
          odoo_url: 'https://universal-steigers.odoo.com',
          odoo_probe_groen: true,
          odoo_probe_op: '2026-09-03T20:14:00Z',
          odoo_alleen_lezen: false,
          laatste_sync_op: '2026-09-03T05:00:00Z',
        }),
      ],
    })
    renderScherm()
    await waitFor(() => expect(screen.getAllByText('Universal Steigerbouw B.V.').length).toBeGreaterThan(0))
    expect(screen.getByText('Odoo')).toHaveClass('text-purple')
    expect(screen.queryByText('geen credentials')).not.toBeInTheDocument()
    expect(screen.getByText(/✓ \d\d:\d\d/)).toBeInTheDocument()
    // Geen RLZ-schrijftest in de tabel voor een Odoo-administratie.
    expect(screen.queryByRole('button', { name: /Schrijftest voor/ })).not.toBeInTheDocument()

    const detail = await openDetail('Universal Steigerbouw B.V.')
    expect(within(detail).queryByRole('button', { name: /Schrijftest voor/ })).not.toBeInTheDocument()
    expect(within(detail).queryByRole('button', { name: /Webservice-gegevens van/ })).not.toBeInTheDocument()
    expect(within(detail).getByRole('button', { name: 'Archiveren Universal Steigerbouw B.V.' })).toBeInTheDocument()
    const backend = within(detail).getByTestId('backend-odoo')
    expect(backend).toHaveTextContent('universal-steigers.odoo.com · company Universal Steigerbouw (1)')
    await waitFor(() => expect(backend).toHaveTextContent('overgestapt per 01-10-2026 (voorheen RLZ-id rlz-us)'))
    expect(within(detail).getByText(/✓ probe groen · 03-09 \d\d:\d\d/)).toBeInTheDocument()
    expect(within(detail).getByText(/•••• ingesteld \(n-module\) · verloopt niet/)).toBeInTheDocument()
    expect(within(detail).getByTestId('odoo-stamgegevens')).toHaveTextContent('grootboek 212 · btw 14 · relaties 380 · projecten 6 · laatst gesynct 03-09')
    expect(within(detail).getByText('n.v.t. — volledige backend')).toBeInTheDocument()
    expect(within(detail).queryByText('Odoo koppelen…')).not.toBeInTheDocument()
    expect(within(detail).getByRole('button', { name: 'Odoo API-sleutel wijzigen voor Universal Steigerbouw B.V.' })).toBeInTheDocument()
    expect(within(detail).getByRole('button', { name: 'Odoo-verbinding opnieuw testen voor Universal Steigerbouw B.V.' })).toBeInTheDocument()

    fireEvent.click(within(detail).getByRole('button', { name: 'Odoo-stamgegevens nu synchroniseren voor Universal Steigerbouw B.V.' }))
    await waitFor(() => expect(putAanroepen.some((p) => p.url === `/administraties/${ODOO_ID}/odoo/sync`)).toBe(true))
    expect(await screen.findByTestId('odoo-sync-uitkomst')).toHaveTextContent('3 nieuw · 209 bijgewerkt')

    fireEvent.click(within(detail).getByRole('button', { name: 'Odoo-verbinding opnieuw testen voor Universal Steigerbouw B.V.' }))
    await waitFor(() => expect(putAanroepen.some((p) => p.url === `/administraties/${ODOO_ID}/odoo` && JSON.stringify(p.body) === '{}')).toBe(true))
    expect(await screen.findByText('Probe groen — alle onderdelen ok.')).toBeInTheDocument()
  })

  it('RLZ-administratie mét Odoo-leesbron: chip "Odoo · leesbron", regel "verkoop-uitstroom vanaf 01-09-2026 (knip)", knipdatum wijzigen = PUT …/odoo/leesbron', async () => {
    const putAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({
      rol: 'beheerder',
      putAanroepen,
      odooStand: { ...ODOO_STAND, company_id: 3, company_naam: 'Universal Verkoop', alleen_lezen: true, voorraad_knip_datum: '2026-09-01', overgangsdatum: null, rlz_admin_id_voor_overstap: null },
      administraties: [
        administratie({
          naam: 'Universal Verkoop B.V.',
          webservice_username: 'ws_uv',
    // Blok A 04-09: zonder mapping-rijen alleen de tekst, geen knop.
    await waitFor(() => expect(within(detail).getByTestId('odoo-mapping-stand')).toHaveTextContent('geen mapping — nieuwe Odoo-administratie zonder RLZ-verleden'))
    expect(within(detail).queryByRole('button', { name: /Rekening-mapping bekijken/ })).not.toBeInTheDocument()
          probe_groen: true,
          rlz_admin_id: 'rlz-uv',
          odoo_alleen_lezen: true,
          odoo_company_id: 3,
          odoo_company_naam: 'Universal Verkoop',
          odoo_voorraad_knip_datum: '2026-09-01',
        }),
      ],
    })
    renderScherm()
    await waitFor(() => expect(screen.getAllByText('Universal Verkoop B.V.').length).toBeGreaterThan(0))
    expect(screen.getByText('Odoo · leesbron')).toHaveClass('text-purple')
    const detail = await openDetail('Universal Verkoop B.V.')
    // Backend blijft Reeleezee (notitie ⑤) — de RLZ-kopacties staan er gewoon.
    expect(within(detail).getByTestId('backend-rlz')).toHaveTextContent('Reeleezee')
    expect(within(detail).getByRole('button', { name: 'Schrijftest voor Universal Verkoop B.V.' })).toBeInTheDocument()
    const leesbron = within(detail).getByTestId('leesbron-odoo')
    expect(leesbron).toHaveTextContent('verkoop-uitstroom vanaf 01-09-2026 (knip)')
    await waitFor(() => expect(leesbron).toHaveTextContent('company Universal Verkoop (3)'))
    fireEvent.click(within(leesbron).getByRole('button', { name: 'Knipdatum wijzigen voor Universal Verkoop B.V.' }))
    const dialoog = await screen.findByTestId('knipdatum-dialoog')
    fireEvent.change(within(dialoog).getByLabelText('Knipdatum'), { target: { value: '2026-10-01' } })
    fireEvent.click(within(dialoog).getByRole('button', { name: 'Knipdatum opslaan' }))
    await waitFor(() => expect(putAanroepen).toContainEqual({ url: `/administraties/${ADMINISTRATIE_ID}/odoo/leesbron`, body: { voorraad_knip_datum: '2026-10-01' } }))
  })
})

describe('InstellingenScreen — weekmail-voorkeur (D2, 01-09)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('élke kantoorrol ziet de weekmail-switch onder Beveiliging; uitzetten PUT opt_out=true zonder bevestiging', async () => {
    const gebruiker = userEvent.setup()
    const putAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ rol: 'boekhouding', putAanroepen })
    renderScherm('/instellingen/beveiliging')
    const paneel = await screen.findByTestId('weekmail-voorkeur')
    const schakelaar = await within(paneel).findByRole('checkbox', { name: 'Weekmail ontvangen' })
    expect(schakelaar).toBeChecked()
    await gebruiker.click(schakelaar)
    await waitFor(() => expect(putAanroepen).toEqual([{ url: '/auth/mijn/digest', body: { opt_out: true } }]))
    await waitFor(() => expect(within(paneel).getByRole('checkbox', { name: 'Weekmail ontvangen' })).not.toBeChecked())
  })
})

describe('InstellingenScreen — omzet-autoboeken (GO Peter 01-09, blok C)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })
describe('InstellingenScreen — rekening-mapping + overgangsdatum (Odoo blok A/C1, 04-09)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  const ODOO_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
  const ODOO_STAND = {
    company_id: 1,
    company_naam: 'Universal Steigerbouw',
    odoo_url: 'https://universal-steigers.odoo.com',
    api_gebruiker: 'n-module',
    api_key_verloopt_op: null,
    probe_groen: true,
    probe_op: '2026-09-03T20:14:00Z',
    alleen_lezen: false,
    voorraad_knip_datum: null,
    probe_rapport: { ledgers: 'ok', boeken: 'ok' },
    stamgegevens: { ledgers: 212, taxrates: 14, vendors: 380, projects: 6 },
    laatste_sync_op: '2026-09-03T05:00:00Z',
    overgangsdatum: '2026-10-01',
    rlz_admin_id_voor_overstap: 'rlz-us',
  }
  const ODOO_MAPPING = {
    grootboek: [
      { soort: 'grootboek', rlz_id: 'gb-4808', rlz_code: '4808', rlz_naam: 'Huur materieel', odoo_id: 11, odoo_code: '480800', odoo_naam: 'Huur materieel', bron: 'code_verlengd', versie: 1, bevestigd_op: '2026-09-04T09:00:00Z', bevestigd_door_naam: 'Peter' },
      { soort: 'grootboek', rlz_id: 'gb-4699', rlz_code: '4699', rlz_naam: 'Diverse algemene kosten', odoo_id: 13, odoo_code: '4699', odoo_naam: 'Diverse algemene kosten', bron: 'zelfde_code', versie: 1, bevestigd_op: '2026-09-04T09:00:00Z', bevestigd_door_naam: 'Peter' },
    ],
    btw: [{ soort: 'btw', rlz_id: 'btw-hoog', rlz_code: null, rlz_naam: 'NL, Hoog Tarief', odoo_id: 21, odoo_code: null, odoo_naam: '21% inkoop', bron: 'tarief', versie: 1, bevestigd_op: '2026-09-04T09:00:00Z', bevestigd_door_naam: 'Peter' }],
    odoo_grootboek: [
      { odoo_id: 11, lokaal_id: '11111111-0000-0000-0000-000000000011', code: '480800', naam: 'Huur materieel' },
      { odoo_id: 12, lokaal_id: '11111111-0000-0000-0000-000000000012', code: '424000', naam: 'Inhuur personeel' },
      { odoo_id: 13, lokaal_id: '11111111-0000-0000-0000-000000000013', code: '4699', naam: 'Diverse algemene kosten' },
    ],
    odoo_btw: [{ odoo_id: 21, lokaal_id: '22222222-0000-0000-0000-000000000021', naam: '21% inkoop', percentage: '0.21', verlegd: false, synthetisch: false }],
    laatst_bevestigd_op: '2026-09-04T09:00:00Z',
    laatst_bevestigd_door_naam: 'Peter',
  }
  const odooAdministratie = () =>
    administratie({
      id: ODOO_ID,
      naam: 'Universal Steigerbouw B.V.',
      boekhoud_backend: 'odoo',
      odoo_company_id: 1,
      odoo_company_naam: 'Universal Steigerbouw',
      odoo_url: 'https://universal-steigers.odoo.com',
      odoo_probe_groen: true,
      odoo_probe_op: '2026-09-03T20:14:00Z',
      odoo_alleen_lezen: false,
      odoo_overgangsdatum: '2026-10-01',
      laatste_sync_op: '2026-09-03T05:00:00Z',
    })

  it('rij "Rekening-mapping": telling + bevestigd door; dialoog in corrigeer-modus, keuze = PUT …/odoo/mapping/{soort}/{rlz_id} → versie-badge v2', async () => {
    const gebruiker = userEvent.setup()
    const putAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ rol: 'beheerder', putAanroepen, odooStand: ODOO_STAND, odooMapping: ODOO_MAPPING, administraties: [odooAdministratie()] })
    renderScherm()
    const detail = await openDetail('Universal Steigerbouw B.V.')
    const rij = within(detail).getByTestId('odoo-mapping-stand')
    await waitFor(() => expect(rij).toHaveTextContent('2 grootboek · 1 btw · bevestigd 04-09'))
    expect(rij).toHaveTextContent('door Peter')

    fireEvent.click(within(detail).getByRole('button', { name: 'Rekening-mapping bekijken of corrigeren voor Universal Steigerbouw B.V.' }))
    const dialoog = await screen.findByTestId('odoo-mapping-dialoog')
    expect(within(dialoog).getByTestId('odoo-mapping-teller')).toHaveTextContent('3 van 3 gekoppeld')
    // Corrigeer-modus: geen filter, wel de geldende waarde + herkomst-chip.
    expect(within(dialoog).queryByLabelText('Alleen nog te kiezen')).not.toBeInTheDocument()
    const rij4808 = within(dialoog).getByTestId('odoo-mapping-rij-grootboek:gb-4808')
    expect(within(rij4808).getByRole('combobox')).toHaveValue('480800 · Huur materieel')
    expect(within(rij4808).getByText('code + 00 — bevestig')).toHaveClass('chip', 'afwijking')
    expect(within(rij4808).queryByText('v2')).not.toBeInTheDocument()

    await gebruiker.click(within(rij4808).getByRole('combobox'))
    await gebruiker.click(screen.getByRole('option', { name: /424000.*Inhuur personeel/ }))
    await waitFor(() => expect(putAanroepen).toContainEqual({ url: `/administraties/${ODOO_ID}/odoo/mapping/grootboek/gb-4808`, body: { odoo_id: 12 } }))
    const rij4808Nieuw = await within(dialoog).findByTestId('odoo-mapping-rij-grootboek:gb-4808')
    await waitFor(() => expect(within(rij4808Nieuw).getByText('v2')).toBeInTheDocument())
    expect(within(rij4808Nieuw).getByRole('combobox')).toHaveValue('424000 · Inhuur personeel')
    expect(within(rij4808Nieuw).getByText('handmatig')).toHaveClass('chip', 'handmatig')
    // De andere rij is ongemoeid (append-only per rij).
    expect(within(within(dialoog).getByTestId('odoo-mapping-rij-grootboek:gb-4699')).queryByText(/^v\d/)).not.toBeInTheDocument()

    fireEvent.click(within(dialoog).getByRole('button', { name: 'Sluiten' }))
    await waitFor(() => expect(screen.queryByTestId('odoo-mapping-dialoog')).not.toBeInTheDocument())
  })

  it('C1 "Overgangsdatum wijzigen…": 409 = servertekst rood + dialoog blijft open, niets gewijzigd; toegestane datum = PUT + dialoog dicht', async () => {
    const putAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ rol: 'beheerder', putAanroepen, odooStand: ODOO_STAND, administraties: [odooAdministratie()] })
    renderScherm()
    const detail = await openDetail('Universal Steigerbouw B.V.')
    const overgang = await within(detail).findByTestId('odoo-overgangsdatum')
    expect(overgang).toHaveTextContent('overgestapt per 01-10-2026')
    fireEvent.click(within(overgang).getByRole('button', { name: 'Overgangsdatum wijzigen voor Universal Steigerbouw B.V.' }))
    const dialoog = await screen.findByTestId('overgangsdatum-dialoog')
    const veld = within(dialoog).getByLabelText('Overgangsdatum') as HTMLInputElement
    expect(veld.value).toBe('2026-10-01')
    expect(within(dialoog).getByText(/Facturen mét factuurdatum vóór deze datum boeken in Reeleezee/)).toBeInTheDocument()
    // Ongewijzigd = niets op te slaan.
    expect(within(dialoog).getByRole('button', { name: 'Overgangsdatum opslaan' })).toBeDisabled()

    // Geblokkeerd: er staat al een Odoo-boeking vóór de nieuwe datum → 409 mét de servertekst, dialoog blijft open.
    fireEvent.change(veld, { target: { value: '2026-11-01' } })
    fireEvent.click(within(dialoog).getByRole('button', { name: 'Overgangsdatum opslaan' }))
    await waitFor(() => expect(within(dialoog).getByTestId('overgangsdatum-fout')).toHaveTextContent('1 factuur is al in Odoo geboekt vóór 01-11-2026: BILL/2026/06/0001 op 05-06-2026'))
    expect(within(dialoog).getByTestId('overgangsdatum-fout')).toHaveTextContent('Niets gewijzigd')
    expect(screen.getByTestId('overgangsdatum-dialoog')).toBeInTheDocument()
    expect(putAanroepen).toContainEqual({ url: `/administraties/${ODOO_ID}/odoo/overgangsdatum`, body: { overgangsdatum: '2026-11-01' } })

    // Toegestaan: op/vóór het oudste boekstuk → 200, dialoog dicht.
    fireEvent.change(veld, { target: { value: '2026-06-01' } })
    fireEvent.click(within(dialoog).getByRole('button', { name: 'Overgangsdatum opslaan' }))
    await waitFor(() => expect(putAanroepen).toContainEqual({ url: `/administraties/${ODOO_ID}/odoo/overgangsdatum`, body: { overgangsdatum: '2026-06-01' } }))
    await waitFor(() => expect(screen.queryByTestId('overgangsdatum-dialoog')).not.toBeInTheDocument())
  })

  it('RLZ-administratie mét Odoo-leesbron toont géén mapping-rij en géén "Overgangsdatum wijzigen…" (alleen bij de volledige backend)', async () => {
    installFetchMock({
      rol: 'beheerder',
      odooStand: { ...ODOO_STAND, company_id: 3, alleen_lezen: true, voorraad_knip_datum: '2026-09-01', overgangsdatum: null, rlz_admin_id_voor_overstap: null },
      administraties: [administratie({ naam: 'Universal Verkoop B.V.', webservice_username: 'ws_uv', probe_groen: true, rlz_admin_id: 'rlz-uv', odoo_alleen_lezen: true, odoo_company_id: 3, odoo_voorraad_knip_datum: '2026-09-01' })],
    })
    renderScherm()
    const detail = await openDetail('Universal Verkoop B.V.')
    await within(detail).findByTestId('leesbron-odoo')
    expect(within(detail).queryByText('Rekening-mapping')).not.toBeInTheDocument()
    expect(within(detail).queryByRole('button', { name: /Overgangsdatum wijzigen/ })).not.toBeInTheDocument()
  })
})


  it('toggle op de detailpagina (tab Boeken & AI) → consequentie-dialoog → PUT /omzet-autoboeken-instelling; chip in de tabel', async () => {
    const gebruiker = userEvent.setup()
    const putAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({
      rol: 'beheerder',
      administraties: [administratie({ naam: 'BLOW B.V.' }), administratie({ id: 'bbbbbbbb-0000-0000-0000-000000000002', naam: 'Al Aan B.V.', omzet_autoboeken_ingeschakeld: true })],
      putAanroepen,
    })
    renderScherm()
    expect(await screen.findByText('Omzet-autoboeken')).toBeInTheDocument()
    await openDetail('BLOW B.V.', 'Boeken & AI')
    await gebruiker.click(screen.getByRole('checkbox', { name: 'Omzet-autoboeken voor BLOW B.V.' }))
    expect(screen.getByText(/verkoopfactuur \+ kostprijsmemoriaal als één transactie/)).toBeInTheDocument()
    expect(screen.getByText(/half-geboekt-geval geeft een alert/)).toBeInTheDocument()
    expect(putAanroepen).toHaveLength(0)
    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await waitFor(() => expect(putAanroepen).toHaveLength(1))
    expect(putAanroepen[0]).toEqual({ url: `/administraties/${ADMINISTRATIE_ID}/omzet-autoboeken-instelling`, body: { ingeschakeld: true } })
    await waitFor(() => expect(screen.getByRole('checkbox', { name: 'Omzet-autoboeken voor BLOW B.V.' })).toBeChecked())
  })
})

describe('InstellingenScreen — afdelingen (blok A 28-08)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('toggle aan (op de detailpagina, tab Boeken & AI) → bevestiging benoemt de consequenties, bevestigen = PUT /afdelingen-instelling; beheer verschijnt op de pagina', async () => {
    const gebruiker = userEvent.setup()
    const putAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ rol: 'beheerder', administraties: [administratie({ naam: 'Kempen Facilities B.V.', afdelingen_ingeschakeld: false })], putAanroepen })
    renderScherm()
    await openDetail('Kempen Facilities B.V.', 'Boeken & AI')
    expect(screen.queryByTestId(`afdelingen-${ADMINISTRATIE_ID}`)).toBeNull()
    await gebruiker.click(screen.getByRole('checkbox', { name: 'Afdelingen van toepassing voor Kempen Facilities B.V.' }))
    expect(screen.getByText(/afdeling verplicht/)).toBeInTheDocument()
    expect(screen.getByText(/"Algemeen" ontstaat automatisch/)).toBeInTheDocument()
    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await waitFor(() => expect(putAanroepen).toHaveLength(1))
    expect(putAanroepen[0]).toEqual({ url: `/administraties/${ADMINISTRATIE_ID}/afdelingen-instelling`, body: { ingeschakeld: true } })
    const beheer = await screen.findByTestId(`afdelingen-${ADMINISTRATIE_ID}`)
    expect(await within(beheer).findByText('Algemeen')).toBeInTheDocument()
  })

  it('toggle al aan → chip "Afdelingen" in de tabel en beheer op de detailpagina', async () => {
    installFetchMock({ rol: 'beheerder', administraties: [administratie({ afdelingen_ingeschakeld: true })] })
    renderScherm()
    expect(await screen.findByText('Afdelingen')).toBeInTheDocument()
    await openDetail('Testklant B.V.', 'Boeken & AI')
    expect(await screen.findByTestId(`afdelingen-${ADMINISTRATIE_ID}`)).toBeInTheDocument()
    expect(await screen.findByText('Route van de administratie (bestaande config)')).toBeInTheDocument()
  })
})

// v2 30-08 (mockup instellingen-administraties-v2): compacte tabel mét chips/sync, detail-dialoog,
// archiveren (nooit verwijderen) + filter "gearchiveerd (N)" + dearchiveren mét nieuwe login.
describe('InstellingenScreen — administraties v2 (30-08)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('toont per rij meta, module-/afwijkings-chips en de sync-chip; aan volgens default = stille ✓-chip (30-08); oude kolommen weg', async () => {
    installFetchMock({
      rol: 'beheerder',
      administraties: [
        administratie({ naam: 'Kempen Facilities B.V.', eigenaar_naam: 'Peter', iban_accordeurs_aantal: 2, is_vastgoed: true, afdelingen_ingeschakeld: true, boeken_ingeschakeld: true }),
        administratie({ id: 'bbbbbbbb-0000-0000-0000-000000000002', naam: 'Meyer BV', boeken_ingeschakeld: true, ai_extractie_ingeschakeld: false, webservice_username: 'ws_m', probe_groen: true, laatste_sync_op: '2026-08-30T04:13:00Z' }),
      ],
    })
    renderScherm()
    await waitFor(() => expect(screen.getAllByText('Kempen Facilities B.V.').length).toBeGreaterThan(0))
    expect(screen.getByText('eigenaar: Peter · 2 IBAN-accordeurs')).toBeInTheDocument()
    expect(screen.getByText('Vastgoed + autoboeken')).toBeInTheDocument()
    expect(screen.getByText('Afdelingen')).toBeInTheDocument()
    expect(screen.getByText('AI-extractie UIT (afwijking)')).toBeInTheDocument()
    expect(screen.queryByText('Boeken UIT (afwijking)')).not.toBeInTheDocument()
    // Werkelijke stand (feedback Peter 30-08): aan volgens default = gedempte ✓-chip, nooit náást een warn-chip.
    expect(screen.getAllByText('Boeken ✓')).toHaveLength(2)
    expect(screen.getAllByText('AI-extractie ✓')).toHaveLength(1)
    expect(screen.getAllByTitle('boeken aan — default')).toHaveLength(2)
    expect(screen.getAllByText('geen credentials')).toHaveLength(1)
    expect(screen.getByText(/✓ \d\d:\d\d/)).toBeInTheDocument()
    expect(screen.queryByText('Autoboeken Vastly-verkoop')).not.toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: 'Boeken ingeschakeld' })).not.toBeInTheDocument()
  })

  it('🗑 archiveren: bevestiging met consequenties, POST, filter "gearchiveerd (N)" met Dearchiveren; dearchiveren = nieuwe login (probe rood = leesbaar, niets gewijzigd, wachtwoord nergens terug)', async () => {
    const gebruiker = userEvent.setup()
    const putAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({
      rol: 'beheerder',
      putAanroepen,
      administraties: [
        administratie({ naam: 'Oude Klant B.V.' }),
        administratie({ id: 'bbbbbbbb-0000-0000-0000-000000000002', naam: 'Weg B.V.', gearchiveerd_op: '2026-08-29T10:00:00Z', gearchiveerd_door_naam: 'Peter', rlz_admin_id: 'rlz-1' }),
      ],
    })
    renderScherm()
    await waitFor(() => expect(screen.getAllByText('Oude Klant B.V.').length).toBeGreaterThan(0))
    expect(screen.queryByText('Weg B.V.')).not.toBeInTheDocument()
    expect(screen.getByText('1 actief')).toBeInTheDocument()
    await gebruiker.click(screen.getByRole('button', { name: 'Archiveren Oude Klant B.V.' }))
    const dialoog = await screen.findByTestId('archiveer-dialoog')
    expect(dialoog).toHaveTextContent(/webservice-login wordt uit de credential-store ingetrokken/)
    expect(dialoog).toHaveTextContent(/niets verwijderd/)
    expect(putAanroepen).toHaveLength(0)
    await gebruiker.click(within(dialoog).getByRole('button', { name: 'Archiveren' }))
    await waitFor(() => expect(putAanroepen.some((p) => p.url === `/instellingen/administraties/${ADMINISTRATIE_ID}/archiveren`)).toBe(true))
    expect(await screen.findByText(/gearchiveerd: webservice-login ingetrokken.*2 open documenten/)).toBeInTheDocument()
    await gebruiker.click(screen.getByRole('button', { name: 'gearchiveerd (1)' }))
    expect(await screen.findByText('Weg B.V.')).toBeInTheDocument()
    expect(screen.getByText(/gearchiveerd 29-08 door Peter/)).toBeInTheDocument()
    await gebruiker.click(screen.getByRole('button', { name: 'Dearchiveren Weg B.V.' }))
    const dearch = await screen.findByTestId('dearchiveer-dialoog')
    await gebruiker.type(within(dearch).getByLabelText('Webservice-gebruiker'), 'rood')
    await gebruiker.type(within(dearch).getByLabelText('Wachtwoord'), 'geheim')
    await gebruiker.click(within(dearch).getByRole('button', { name: 'Probe draaien en terugzetten' }))
    expect(await within(dearch).findByText(/Rechten-probe niet groen/)).toBeInTheDocument()
    expect(putAanroepen.filter((p) => p.url.endsWith('/dearchiveren'))).toEqual([
      { url: '/instellingen/administraties/bbbbbbbb-0000-0000-0000-000000000002/dearchiveren', body: { webservice_username: 'rood' } },
    ])
    expect(JSON.stringify(putAanroepen)).not.toContain('geheim')
  })
})

describe('InstellingenScreen — materiaalcatalogus bij Odoo (Odoo-afrondingsrun 04-09 blok B)', () => {
  /* Besluit Peter 04-09: de catalogus is beschikbaar bij de uren-opt-in ÓF een Odoo-backend ÓF een Odoo-leesbron-
   * koppeling; bestellingen/transport blijven uren-gated. Kiezer op /instellingen/materiaal + rij op tab Algemeen. */
  const ODOO_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
  const LEESBRON_ID = 'cccccccc-0000-0000-0000-000000000003'
  const ODOO_STAND = {
    company_id: 1,
    company_naam: 'Universal Steigerbouw',
    odoo_url: 'https://universal-steigers.odoo.com',
    api_gebruiker: null,
    api_key_verloopt_op: null,
    probe_groen: true,
    probe_op: '2026-09-03T20:14:00Z',
    alleen_lezen: false,
    voorraad_knip_datum: null,
    probe_rapport: {},
    stamgegevens: { ledgers: 1, taxrates: 1, vendors: 1, projects: 1 },
    laatste_sync_op: null,
    overgangsdatum: null,
    rlz_admin_id_voor_overstap: null,
  }
  const odooZonderUren = () =>
    administratie({ id: ODOO_ID, naam: 'Odoo zonder uren B.V.', boekhoud_backend: 'odoo', odoo_company_id: 1, odoo_probe_groen: true, odoo_alleen_lezen: false })

  beforeEach(() => resetMijnToegangCache())
  afterEach(() => vi.unstubAllGlobals())

  it('Beheerder: de administratie-kiezer op /instellingen/materiaal biedt Odoo- en leesbron-administraties zonder uren-opt-in aan, een kale RLZ-administratie niet', async () => {
    installFetchMock({
      rol: 'beheerder',
      administraties: [
        administratie({ naam: 'Kaal RLZ B.V.' }),
        odooZonderUren(),
        administratie({ id: LEESBRON_ID, naam: 'Leesbron B.V.', odoo_alleen_lezen: true }),
      ],
    })
    renderScherm('/instellingen/materiaal')
    expect(await screen.findByRole('heading', { name: /Materiaalcatalogus \(transport/ })).toBeInTheDocument()
    // Eerste administratie mét toegang = de Odoo-administratie; de kale RLZ-administratie staat er niet.
    const kiezer = await screen.findByRole('combobox', { name: 'Administratie' })
    expect(kiezer).toHaveValue('Odoo zonder uren B.V.')
    await userEvent.setup().click(kiezer)
    const opties = (await screen.findAllByRole('option')).map((o) => o.textContent)
    expect(opties.some((t) => t?.includes('Leesbron B.V.'))).toBe(true)
    expect(opties.some((t) => t?.includes('Odoo zonder uren B.V.'))).toBe(true)
    expect(opties.some((t) => t?.includes('Kaal RLZ B.V.'))).toBe(false)
    expect(screen.queryByTestId('materiaal-geen-administratie')).not.toBeInTheDocument()
  })

  it('Beheerder: zonder enige administratie met toegang toont het scherm de lege stand mét uitleg (Uren & meerwerk óf Odoo-koppeling)', async () => {
    installFetchMock({ rol: 'beheerder', administraties: [administratie({ naam: 'Kaal RLZ B.V.' })] })
    renderScherm('/instellingen/materiaal')
    expect(await screen.findByTestId('materiaal-geen-administratie')).toHaveTextContent(/Uren & meerwerk aan heeft óf een Odoo-koppeling/)
    expect(screen.getByRole('combobox', { name: 'Administratie' })).toHaveValue('')
  })

  it('B+P: de kiezer volgt `administraties_met_catalogus` uit mijn-toegang (óók zonder uren-opt-in)', async () => {
    installFetchMock({ rol: 'boekhouding_projecten', mijnToegang: { administraties_met_opt_in: [], administraties_met_catalogus: [ADMINISTRATIE_ID] } })
    renderScherm('/instellingen/materiaal')
    expect(await screen.findByRole('heading', { name: /Materiaalcatalogus \(transport/ })).toBeInTheDocument()
    expect(await screen.findByDisplayValue('Testklant B.V.')).toBeInTheDocument()
  })

  it('B+P: oudere response zonder `administraties_met_catalogus` valt fail-closed terug op de opt-in-lijst', async () => {
    installFetchMock({ rol: 'boekhouding_projecten', mijnToegang: { administraties_met_opt_in: [] } })
    renderScherm('/instellingen/materiaal')
    expect(await screen.findByTestId('materiaal-geen-administratie')).toBeInTheDocument()
  })

  it('detailpagina Algemeen: Odoo-administratie ZONDER uren-opt-in draagt de rij "Materiaalcatalogus" mét link onder het backend-blok; mét opt-in of zonder Odoo niet', async () => {
    installFetchMock({
      rol: 'beheerder',
      odooStand: ODOO_STAND,
      administraties: [
        odooZonderUren(),
        administratie({ id: LEESBRON_ID, naam: 'Odoo met uren B.V.', boekhoud_backend: 'odoo', uren_meerwerk_ingeschakeld: true }),
        administratie({ naam: 'Kaal RLZ B.V.' }),
      ],
    })
    renderScherm()
    let detail = await openDetail('Odoo zonder uren B.V.')
    const link = within(detail).getByTestId('odoo-materiaalcatalogus-link')
    expect(link).toHaveAttribute('href', '/instellingen/materiaal')
    expect(within(detail).getByText('Materiaalcatalogus')).toBeInTheDocument()
    // De toggle-uitleg claimt materiaal niet meer exclusief voor de opt-in.
    expect(within(detail).getByText(/De materiaalcatalogus zelf is óók beschikbaar via een Odoo-koppeling/)).toBeInTheDocument()
    fireEvent.click(within(detail).getByRole('link', { name: 'Administraties' }))
    detail = await openDetail('Odoo met uren B.V.')
    expect(within(detail).queryByTestId('odoo-materiaalcatalogus-link')).not.toBeInTheDocument()
    expect(within(detail).getByRole('tab', { name: 'Uren & materiaal' })).toBeInTheDocument()
    fireEvent.click(within(detail).getByRole('link', { name: 'Administraties' }))
    detail = await openDetail('Kaal RLZ B.V.')
    expect(within(detail).queryByTestId('odoo-materiaalcatalogus-link')).not.toBeInTheDocument()
  })
})
