import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../auth/AuthContext'
import { InstellingenScreen } from './InstellingenScreen'

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

/** v2 (30-08): de instellingen leven in de detail-dialoog — ⚙ (of de rij) opent 'm eerst. */
async function openDetail(naam: string) {
  await waitFor(() => expect(screen.getAllByText(naam).length).toBeGreaterThan(0))
  fireEvent.click(screen.getByRole('button', { name: `Instellingen van ${naam}` }))
  return await screen.findByTestId('administratie-detail')
}

function installFetchMock(opties: {
  rol: string
  administraties?: unknown[]
  killSwitch?: boolean
  intakeAi?: boolean
  ibanAccordeurs?: string[]
  putAanroepen?: { url: string; body: unknown }[]
}) {
  const administraties = opties.administraties ?? [administratie()]
  let killSwitch = opties.killSwitch ?? true
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
      // Beveiliging-sectie (kantoor-passkeys, besluit 0020) — voor élke kantoor-rol.
      if (url === '/auth/mijn/apparaten') {
        return Promise.resolve(jsonResponse({ apparaten: [] }))
      }
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

/** D2 (besluit 25-08): Instellingen is een landing met sectiekaarten; de secties leven op
 * `/instellingen/<sectie>`. Tests renderen standaard de subpagina die ze toetsen. */
function renderScherm(pad = '/instellingen/administraties') {
  return render(
    <MemoryRouter initialEntries={[pad]}>
      <AuthProvider>
        <Routes>
          <Route path="/" element={<div>WERKVOORRAAD-SCHERM</div>} />
          <Route path="/gebruikers" element={<div>GEBRUIKERS-SCHERM</div>} />
          <Route path="/instellingen" element={<InstellingenScreen />} />
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

  it('een niet-Beheerder ziet alléén de Beveiliging-sectie (eigen passkeys, besluit 0020)', async () => {
    installFetchMock({ rol: 'boekhouding' })
    renderScherm('/instellingen')
    expect(await screen.findByRole('heading', { name: /Beveiliging — passkeys/ })).toBeInTheDocument()
    expect(screen.queryByText('Administraties')).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /Boeken platformbreed/ })).not.toBeInTheDocument()
  })

  it('een Beheerder landt op sectiekaarten (D2, besluit 25-08) en opent daaruit de administraties-subpagina', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({ rol: 'beheerder', administraties: [administratie({ naam: 'Kempen Facilities B.V.' })] })
    renderScherm('/instellingen')
    expect(await screen.findByRole('link', { name: /Administraties/ })).toHaveAttribute('href', '/instellingen/administraties')
    for (const titel of ['Beveiliging', 'Boeken & platform', 'Intake-AI & kosten', 'Klant-accordering', 'Autoboeken', 'Doorbelasting']) {
      expect(screen.getByRole('heading', { name: titel })).toBeInTheDocument()
    }
    expect(screen.getByRole('link', { name: /Gebruikers & toegang/ })).toHaveAttribute('href', '/gebruikers')
    expect(await screen.findByText('boeken kan')).toBeInTheDocument()
    expect(screen.queryByTestId('administraties-v2')).not.toBeInTheDocument()
    await gebruiker.click(screen.getByRole('link', { name: /Administraties/ }))
    await waitFor(() => expect(screen.getAllByText('Kempen Facilities B.V.').length).toBeGreaterThan(0))
    expect(screen.getByTestId('administraties-v2')).toBeInTheDocument()
    expect(screen.queryByText('WERKVOORRAAD-SCHERM')).not.toBeInTheDocument()
  })

  it('deep-links naar oude secties redirecten naar de subpagina (D2)', async () => {
    installFetchMock({ rol: 'beheerder' })
    renderScherm('/instellingen?sectie=doorbelasting')
    expect(await screen.findByRole('heading', { name: 'Doorbelasting' })).toBeInTheDocument()
    vi.unstubAllGlobals()
    installFetchMock({ rol: 'beheerder' })
    renderScherm('/instellingen#boeken')
    expect(await screen.findByRole('heading', { name: 'Boeken platformbreed' })).toBeInTheDocument()
  })

  it('detail-dialoog toont "IBAN-wissel accorderen door" mét accordeur-chip en wijzig-dialoog, zonder foutbanner', async () => {
    installFetchMock({
      rol: 'beheerder',
      administraties: [administratie({ naam: 'Kempen Facilities B.V.' })],
      ibanAccordeurs: ['eeeeeeee-0000-0000-0000-000000000009'],
    })
    renderScherm()
    await openDetail('Kempen Facilities B.V.')
    expect(screen.getByText('IBAN-wissel accorderen door')).toBeInTheDocument()
    await waitFor(() => expect(screen.getAllByText('M. de Boer').length).toBeGreaterThan(0))
    await userEvent.setup().click(screen.getByRole('button', { name: /IBAN-accordeurs van Kempen Facilities B\.V\. wijzigen/ }))
    const accordeurCheckbox = await screen.findByRole('checkbox', { name: /M\. de Boer/ })
    expect(accordeurCheckbox).toBeChecked()
    expect(screen.queryByText(/Kon instellingen niet laden/)).not.toBeInTheDocument()
    expect(screen.queryByText(/accordeurs niet te laden/)).not.toBeInTheDocument()
  })

  it('toont de terugval op de beheerder(s) bij een lege accordeur-set', async () => {
    installFetchMock({ rol: 'beheerder', ibanAccordeurs: [] })
    renderScherm()
    await openDetail('Testklant B.V.')
    expect(await screen.findByText(/beheerders \(terugval\)/)).toBeInTheDocument()
  })
})

describe('InstellingenScreen — toggle-flow (Beheerder)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('een toggle-klik (in de dialoog) opent een bevestigingsdialoog en wijzigt pas na bevestigen; afwijking = chip in de tabel', async () => {
    const gebruiker = userEvent.setup()
    const putAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ rol: 'beheerder', administraties: [administratie({ naam: 'BLOW B.V.', boeken_ingeschakeld: false })], putAanroepen })
    renderScherm()
    await waitFor(() => expect(screen.getAllByText('BLOW B.V.').length).toBeGreaterThan(0))
    expect(screen.getByText('Boeken UIT (afwijking)')).toBeInTheDocument()
    await openDetail('BLOW B.V.')
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
    await openDetail('BLOW B.V.')
    const projectToggle = screen.getByRole('checkbox', { name: 'Project verplicht voor BLOW B.V.' })
    await gebruiker.click(projectToggle)
    expect(screen.getByText(/Project wordt verplicht bij boeken/)).toBeInTheDocument()
    await gebruiker.click(screen.getByRole('button', { name: 'Annuleren' }))
    expect(screen.queryByText(/Project wordt verplicht bij boeken/)).not.toBeInTheDocument()
    expect(putAanroepen).toHaveLength(0)
    expect(projectToggle).not.toBeChecked()
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

  it('eigenaar kiezen (in de dialoog) vraagt bevestiging en PUT de eigenaar (krijgt vragen)', async () => {
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

  it('toont "+ Administratie toevoegen", de koppelstand als sync-chip/in de dialoog zonder wachtwoord en 🧪 per rij', async () => {
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
    await openDetail('Testklant B.V.')
    expect(screen.getByText('ws_nijenhuis')).toHaveClass('chip', 'ok')
    expect(screen.getByRole('button', { name: /Webservice-gegevens van Testklant B\.V\./ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Sluiten' }))
    fireEvent.click(screen.getByRole('button', { name: '+ Administratie toevoegen' }))
    expect(await screen.findByText('Administratie toevoegen — stap 1 van 3')).toBeInTheDocument()
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

describe('InstellingenScreen — afdelingen (blok A 28-08)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('toggle aan (in de dialoog) → bevestiging benoemt de consequenties, bevestigen = PUT /afdelingen-instelling; beheer verschijnt in de dialoog', async () => {
    const gebruiker = userEvent.setup()
    const putAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ rol: 'beheerder', administraties: [administratie({ naam: 'Kempen Facilities B.V.', afdelingen_ingeschakeld: false })], putAanroepen })
    renderScherm()
    await openDetail('Kempen Facilities B.V.')
    expect(screen.queryByTestId(`afdelingen-${ADMINISTRATIE_ID}`)).toBeNull()
    await gebruiker.click(screen.getByRole('checkbox', { name: 'Afdelingen van toepassing voor Kempen Facilities B.V.' }))
    expect(screen.getByText(/afdeling verplicht/)).toBeInTheDocument()
    expect(screen.getByText(/"Algemeen" ontstaat automatisch/)).toBeInTheDocument()
    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await waitFor(() => expect(putAanroepen).toHaveLength(1))
    expect(putAanroepen[0]).toEqual({ url: `/administraties/${ADMINISTRATIE_ID}/afdelingen-instelling`, body: { ingeschakeld: true } })
    expect(await screen.findByTestId(`afdelingen-${ADMINISTRATIE_ID}`)).toBeInTheDocument()
    expect(await screen.findByText('Algemeen')).toBeInTheDocument()
  })

  it('toggle al aan → chip "Afdelingen" in de tabel en beheer in de dialoog', async () => {
    installFetchMock({ rol: 'beheerder', administraties: [administratie({ afdelingen_ingeschakeld: true })] })
    renderScherm()
    expect(await screen.findByText('Afdelingen')).toBeInTheDocument()
    await openDetail('Testklant B.V.')
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

  it('toont per rij meta, module-/afwijkings-chips en de sync-chip; defaults zonder chip; oude kolommen weg', async () => {
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
