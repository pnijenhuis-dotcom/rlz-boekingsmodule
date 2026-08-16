import { render, screen, waitFor } from '@testing-library/react'
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
    ...overrides,
  }
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
      if (url === '/instellingen/administraties') {
        return Promise.resolve(jsonResponse({ administraties }))
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
      if (url.endsWith('/verkoop-autoboeken-instelling') && init?.method === 'PUT') {
        const body = JSON.parse(String(init.body)) as unknown
        opties.putAanroepen?.push({ url, body })
        return Promise.resolve(jsonResponse(body))
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

function renderScherm() {
  return render(
    <MemoryRouter initialEntries={['/instellingen']}>
      <AuthProvider>
        <Routes>
          <Route path="/" element={<div>WERKVOORRAAD-SCHERM</div>} />
          <Route path="/instellingen" element={<InstellingenScreen />} />
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
    renderScherm()

    expect(await screen.findByRole('heading', { name: /Beveiliging — passkeys/ })).toBeInTheDocument()
    expect(screen.queryByText('Administraties')).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /kill switch/i })).not.toBeInTheDocument()
  })

  it('een Beheerder ziet de administraties-lijst en de kill switch', async () => {
    installFetchMock({ rol: 'beheerder', administraties: [administratie({ naam: 'Kempen Facilities B.V.' })] })
    renderScherm()

    await waitFor(() => expect(screen.getAllByText('Kempen Facilities B.V.').length).toBeGreaterThan(0))
    expect(screen.getByRole('heading', { name: /kill switch/i })).toBeInTheDocument()
    expect(screen.queryByText('WERKVOORRAAD-SCHERM')).not.toBeInTheDocument()
  })

  it('rendert de administratielijst mét het veld "IBAN-wissel accorderen door" zonder foutbanner', async () => {
    // Regressie op de data-load-bug (browserreview 2026-07-15): de hele pagina viel om op
    // "Kon instellingen niet laden" doordat /instellingen/* buiten de dev-proxy viel — deze
    // test dekt de render-kant (volledige happy path incl. de accordeur-cel); de proxy-kant
    // zelf dekt instellingenApi.test.ts.
    installFetchMock({
      rol: 'beheerder',
      administraties: [administratie({ naam: 'Kempen Facilities B.V.' })],
      ibanAccordeurs: ['eeeeeeee-0000-0000-0000-000000000009'],
    })
    renderScherm()

    await waitFor(() => expect(screen.getAllByText('Kempen Facilities B.V.').length).toBeGreaterThan(0))
    expect(screen.getByText('IBAN-wissel accorderen door')).toBeInTheDocument()
    // De accordeur-cel toont de medewerker als aangevinkte accordeur…
    const accordeurCheckbox = await screen.findByRole('checkbox', { name: /M\. de Boer/ })
    expect(accordeurCheckbox).toBeChecked()
    // …en nergens een foutbanner of laad-fout.
    expect(screen.queryByText(/Kon instellingen niet laden/)).not.toBeInTheDocument()
    expect(screen.queryByText(/accordeurs niet te laden/)).not.toBeInTheDocument()
  })

  it('toont de terugval op de beheerder(s) bij een lege accordeur-set', async () => {
    installFetchMock({ rol: 'beheerder', ibanAccordeurs: [] })
    renderScherm()

    await waitFor(() => expect(screen.getAllByText('Testklant B.V.').length).toBeGreaterThan(0))
    expect(await screen.findByText(/valt terug op de beheerder\(s\)/)).toBeInTheDocument()
  })
})

describe('InstellingenScreen — toggle-flow (Beheerder)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('een toggle-klik opent een bevestigingsdialoog en wijzigt pas na bevestigen', async () => {
    const gebruiker = userEvent.setup()
    const putAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({
      rol: 'beheerder',
      administraties: [administratie({ naam: 'BLOW B.V.', boeken_ingeschakeld: false })],
      putAanroepen,
    })
    renderScherm()

    await waitFor(() => expect(screen.getAllByText('BLOW B.V.').length).toBeGreaterThan(0))
    // Op naam, nooit op checkbox-index: de IBAN-accordeur-kolom voegt per rij checkboxes toe
    // en zou een index-selectie stil naar de verkeerde toggle laten wijzen.
    const boekenToggle = screen.getByRole('checkbox', { name: 'Boeken ingeschakeld voor BLOW B.V.' })

    await gebruiker.click(boekenToggle)

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText(/Boeken wordt ingeschakeld voor "BLOW B.V."/)).toBeInTheDocument()
    expect(putAanroepen).toHaveLength(0)
    expect(boekenToggle).not.toBeChecked()

    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(putAanroepen).toHaveLength(1)
    expect(putAanroepen[0].url).toContain(`/administraties/${ADMINISTRATIE_ID}/boeken-instelling`)
    expect(putAanroepen[0].body).toEqual({ ingeschakeld: true })
    await waitFor(() => expect(boekenToggle).toBeChecked())
  })

  it('verkoop-autoboeken: schakelaar alleen bij vastgoed-administraties, bevestigen PUT de instelling', async () => {
    const gebruiker = userEvent.setup()
    const putAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({
      rol: 'beheerder',
      administraties: [
        administratie({ naam: 'Rubicon Investments B.V.', is_vastgoed: true }),
        administratie({ id: 'aaaaaaaa-0000-0000-0000-000000000002', naam: 'BLOW B.V.' }),
      ],
      putAanroepen,
    })
    renderScherm()

    await waitFor(() => expect(screen.getAllByText('Rubicon Investments B.V.').length).toBeGreaterThan(0))
    // Niet-vastgoed heeft géén schakelaar in deze kolom (VASTLY-VERKOOP bestaat daar niet).
    expect(
      screen.queryByRole('checkbox', { name: 'Autoboeken Vastly-verkoop voor BLOW B.V.' }),
    ).not.toBeInTheDocument()

    const toggle = screen.getByRole('checkbox', { name: 'Autoboeken Vastly-verkoop voor Rubicon Investments B.V.' })
    await gebruiker.click(toggle)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText(/boeken voortaan automatisch zodra álles groen is/)).toBeInTheDocument()
    expect(putAanroepen).toHaveLength(0)

    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(putAanroepen).toHaveLength(1)
    expect(putAanroepen[0].url).toContain(`/administraties/${ADMINISTRATIE_ID}/verkoop-autoboeken-instelling`)
    expect(putAanroepen[0].body).toEqual({ ingeschakeld: true })
    await waitFor(() => expect(toggle).toBeChecked())
  })

  it('annuleren sluit de dialoog zonder een aanroep te doen en laat de toggle ongewijzigd', async () => {
    const gebruiker = userEvent.setup()
    const putAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({
      rol: 'beheerder',
      administraties: [administratie({ naam: 'BLOW B.V.', project_verplicht: false })],
      putAanroepen,
    })
    renderScherm()

    await waitFor(() => expect(screen.getAllByText('BLOW B.V.').length).toBeGreaterThan(0))
    const projectToggle = screen.getByRole('checkbox', { name: 'Project verplicht voor BLOW B.V.' })

    await gebruiker.click(projectToggle)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    await gebruiker.click(screen.getByRole('button', { name: 'Annuleren' }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(putAanroepen).toHaveLength(0)
    expect(projectToggle).not.toBeChecked()
  })

  it('de globale kill switch vraagt ook een bevestiging', async () => {
    const gebruiker = userEvent.setup()
    const putAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ rol: 'beheerder', killSwitch: true, putAanroepen })
    renderScherm()

    // De heading rendert al vóórdat de Promise.all met instellingen-data terug is — wacht dus op
    // de checkbox zelf (die pas ná het laden bestaat), anders is deze test een race/flake.
    const killSwitchToggle = await screen.findByRole('checkbox', { name: 'Globale kill switch' })
    await gebruiker.click(killSwitchToggle)

    expect(screen.getByText(/stopgezet, ongeacht de toggle per administratie/)).toBeInTheDocument()
    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))

    await waitFor(() => expect(putAanroepen).toHaveLength(1))
    expect(putAanroepen[0].url).toBe('/instellingen/boeken-kill-switch')
    expect(putAanroepen[0].body).toEqual({ ingeschakeld: false })
  })
  it('de intake-AI-toggle (AVG-gate) vraagt bevestiging en PUT naar /instellingen/intake-ai', async () => {
    const gebruiker = userEvent.setup()
    const putAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ rol: 'beheerder', intakeAi: false, putAanroepen })
    renderScherm()

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

  it('eigenaar kiezen vraagt bevestiging en PUT de eigenaar (krijgt vragen)', async () => {
    const gebruiker = userEvent.setup()
    const putAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ rol: 'beheerder', putAanroepen })
    renderScherm()

    await waitFor(() => expect(screen.getByLabelText('Eigenaar van Testklant B.V.')).toBeInTheDocument())
    await waitFor(() => expect(screen.getByLabelText('Eigenaar van Testklant B.V.')).not.toBeDisabled())
    await gebruiker.selectOptions(
      screen.getByLabelText('Eigenaar van Testklant B.V.'),
      'eeeeeeee-0000-0000-0000-000000000009',
    )

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
      administraties: [
        administratie({ naam: 'Kempen Facilities B.V.' }),
        administratie({ id: TWEEDE_ID, naam: 'Molenhof Beheer B.V.' }),
      ],
      putAanroepen,
    })
    renderScherm()

    await waitFor(() => expect(screen.getAllByText('Kempen Facilities B.V.').length).toBeGreaterThan(0))
    // Zonder selectie geen bulkbalk.
    expect(screen.queryByRole('toolbar', { name: 'Bulk-bediening' })).not.toBeInTheDocument()

    await gebruiker.click(screen.getByRole('checkbox', { name: 'Selecteer Kempen Facilities B.V.' }))
    await gebruiker.click(screen.getByRole('checkbox', { name: 'Selecteer Molenhof Beheer B.V.' }))
    expect(screen.getByRole('toolbar', { name: 'Bulk-bediening' })).toBeInTheDocument()
    expect(screen.getByText('2 geselecteerd')).toBeInTheDocument()

    await gebruiker.click(screen.getByRole('button', { name: 'Boeken aan' }))
    // Eén bevestigingsdialoog per bulkactie — nog niets uitgevoerd vóór bevestigen.
    expect(putAanroepen).toHaveLength(0)
    expect(screen.getByText(/Bulkactie: Boeken AAN/)).toBeInTheDocument()

    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await waitFor(() => expect(putAanroepen).toHaveLength(2))
    expect(putAanroepen.map((p) => p.url).sort()).toEqual([
      `/administraties/${ADMINISTRATIE_ID}/boeken-instelling`,
      `/administraties/${TWEEDE_ID}/boeken-instelling`,
    ])
    expect(putAanroepen.every((p) => (p.body as { ingeschakeld: boolean }).ingeschakeld)).toBe(true)
    // Selectie is gewist na de actie.
    await waitFor(() => expect(screen.queryByRole('toolbar', { name: 'Bulk-bediening' })).not.toBeInTheDocument())
  })

  it('"alles selecteren" selecteert alle rijen; selectie wissen haalt de balk weg', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({
      rol: 'beheerder',
      administraties: [
        administratie({ naam: 'Kempen Facilities B.V.' }),
        administratie({ id: TWEEDE_ID, naam: 'Molenhof Beheer B.V.' }),
      ],
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
      administraties: [
        administratie({ naam: 'Kempen Facilities B.V.' }),
        administratie({ id: TWEEDE_ID, naam: 'Molenhof Beheer B.V.' }),
      ],
      putAanroepen,
    })
    // Tweede administratie faalt op de PUT.
    const basisFetch = globalThis.fetch
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url === `/administraties/${TWEEDE_ID}/boeken-instelling` && init?.method === 'PUT') {
          return Promise.resolve(
            new Response(JSON.stringify({ detail: 'geen RLZ-credentials' }), {
              status: 409,
              headers: { 'Content-Type': 'application/json' },
            }),
          )
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
    // De geslaagde administratie is wél doorgevoerd.
    expect(putAanroepen.some((p) => p.url === `/administraties/${ADMINISTRATIE_ID}/boeken-instelling`)).toBe(true)
  })
})
