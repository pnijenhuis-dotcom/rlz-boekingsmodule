/** Beheer › Veldwerkers (veldwerkers-run 14-09, besluiten Peter 14-09 punt 1+2): kantoorbrede pagina mét
 * administratie als FILTER (nooit poort), URL-state, dossier-kolom uit de bestaande DTO, één primaire knop + ⋯,
 * lege stand = actie, leesbare 403 voor wie het recht 'veldwerkerbeheer' mist. Plus de nav-/route-helpers
 * (`auth/rollen.ts`) — er is geen Shell-nav-guard-test, dus de fail-closed-regel staat hier. */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { magVeldwerkersRoute, toontVeldwerkersNav } from '../auth/rollen'
import { VELDWERKERS_KOLOMMEN, minimaleVeldwerkersTabelbreedte } from './veldwerkersKolommen'
import { filterVeldwerkers, sorteerVeldwerkers, VeldwerkersScreen } from './VeldwerkersScreen'
import type { VeldgebruikerDto } from '../meerwerk/meerwerkApi'

const ADMIN_A = 'aaaaaaaa-0000-0000-0000-00000000000a'
const ADMIN_B = 'bbbbbbbb-0000-0000-0000-00000000000b'
const ZZP_ID = '11111111-0000-0000-0000-000000000011'
const ZZP2_ID = '22222222-0000-0000-0000-000000000022'
const UITV_ID = '33333333-0000-0000-0000-000000000033'
const DETA_ID = '44444444-0000-0000-0000-000000000044'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function dossier(overrides: Record<string, unknown> = {}) {
  return {
    administratie_id: ADMIN_B,
    administratie_naam: 'Universal Steigerbouw',
    aantal_verplicht: 6,
    aantal_aanwezig: 6,
    aantal_ontbrekend: 0,
    aantal_verlopen: 0,
    aantal_verloopt_binnenkort: 0,
    aantal_ter_controle: 0,
    compleet: true,
    geblokkeerd: false,
    ...overrides,
  }
}

function veld(overrides: Record<string, unknown>): VeldgebruikerDto {
  return {
    gebruiker_id: ZZP_ID,
    naam: 'Milan K.',
    e_mail: 'milan@test.local',
    rol: 'zzper',
    status: 'actief',
    projecten: [],
    zzpers: [],
    crediteuren: [],
    uren_afwijking_aantal: 0,
    uren_afwijking_som: '0',
    dossiers: [dossier()],
    administratie_ids: [ADMIN_B],
    ...overrides,
  } as unknown as VeldgebruikerDto
}

/** Vier veldwerkers: ZZP'er compleet (A+B), ZZP'er 2 ontbreken + verlopen (B), uitvoerder ter controle (A), detacheerder (B). */
function standaardSet(): VeldgebruikerDto[] {
  return [
    veld({ administratie_ids: [ADMIN_A, ADMIN_B] }),
    veld({
      gebruiker_id: ZZP2_ID,
      naam: 'Thijs H.',
      e_mail: 'thijs@test.local',
      dossiers: [dossier({ aantal_aanwezig: 3, aantal_ontbrekend: 2, aantal_verlopen: 1, compleet: false })],
    }),
    veld({
      gebruiker_id: UITV_ID,
      naam: 'Stefan B.',
      e_mail: 'stefan@test.local',
      rol: 'uitvoerder',
      administratie_ids: [ADMIN_A],
      dossiers: [dossier({ administratie_id: ADMIN_A, aantal_ter_controle: 1 })],
    }),
    veld({
      gebruiker_id: DETA_ID,
      naam: 'Karin S.',
      e_mail: 'karin@bureau.local',
      rol: 'detacheerder',
      dossiers: [],
      zzpers: [{ gebruiker_id: ZZP_ID, naam: 'Milan K.', uurtarief: '51.00' }],
    }),
  ]
}

function installMock(opties: { veld?: unknown[]; status?: number; aanroepen?: { method: string; url: string; body: unknown }[] } = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      opties.aanroepen?.push({ method: init?.method ?? 'GET', url, body: init?.body ? JSON.parse(String(init.body)) : undefined })
      if (url === '/uren/beheer/veldgebruikers') {
        if (opties.status && opties.status !== 200) return Promise.resolve(jsonResponse({ detail: 'Geen recht op veldwerkerbeheer.' }, opties.status))
        return Promise.resolve(jsonResponse(opties.veld ?? standaardSet()))
      }
      if (url === '/auth/administraties') {
        return Promise.resolve(
          jsonResponse({
            administraties: [
              { id: ADMIN_A, naam: 'BLOW B.V.' },
              { id: ADMIN_B, naam: 'Universal Steigerbouw', uren_meerwerk_ingeschakeld: true },
            ],
          }),
        )
      }
      if (url.startsWith('/uren/beheer/detacheerderkoppelingen')) return Promise.resolve(jsonResponse({}))
      return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
    }),
  )
}

function LocatieProbe() {
  const locatie = useLocation()
  return <div data-testid="locatie">{`${locatie.pathname}${locatie.search}`}</div>
}

function renderScherm(pad = '/veldwerkers') {
  return render(
    <MemoryRouter initialEntries={[pad]}>
      <Routes>
        <Route
          path="/veldwerkers"
          element={
            <>
              <VeldwerkersScreen />
              <LocatieProbe />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('nav-/route-helpers (auth/rollen.ts) — fail-closed', () => {
  it('route-allowlist = de kantoorrollen; veld-/accordeur-/onbekende rollen niet', () => {
    expect(magVeldwerkersRoute('beheerder')).toBe(true)
    expect(magVeldwerkersRoute('boekhouding_projecten')).toBe(true)
    expect(magVeldwerkersRoute('boekhouding')).toBe(true)
    expect(magVeldwerkersRoute('klant_accordeur')).toBe(false)
    expect(magVeldwerkersRoute('zzper')).toBe(false)
    expect(magVeldwerkersRoute('toekomstige_rol')).toBe(false)
    expect(magVeldwerkersRoute(null)).toBe(false)
  })

  it('nav-item: Beheerder altijd; andere kantoorrol alleen mét bewezen recht; geen toegang-data = niet tonen', () => {
    expect(toontVeldwerkersNav('beheerder', undefined)).toBe(true)
    expect(toontVeldwerkersNav('beheerder', null)).toBe(true)
    expect(toontVeldwerkersNav('boekhouding_projecten', { heeft_veldwerkerbeheer_recht: true })).toBe(true)
    expect(toontVeldwerkersNav('boekhouding', { heeft_veldwerkerbeheer_recht: true })).toBe(true)
    expect(toontVeldwerkersNav('boekhouding_projecten', { heeft_veldwerkerbeheer_recht: false })).toBe(false)
    expect(toontVeldwerkersNav('boekhouding_projecten', {})).toBe(false)
    expect(toontVeldwerkersNav('boekhouding_projecten', undefined)).toBe(false)
    expect(toontVeldwerkersNav('boekhouding_projecten', null)).toBe(false)
    // Een recht-vlag op een niet-kantoorrol opent niets (de rol-allowlist wint).
    expect(toontVeldwerkersNav('klant_accordeur', { heeft_veldwerkerbeheer_recht: true })).toBe(false)
  })
})

describe('filter + sortering (pure)', () => {
  it('filtert op administratie (scope-lijst, ontbrekend veld = zonder scope), dossier onvolledig en zoekterm', () => {
    const set = standaardSet()
    expect(filterVeldwerkers(set, { administratieId: ADMIN_A, alleenDossierOnvolledig: false, zoekterm: '' }).map((v) => v.naam)).toEqual(['Milan K.', 'Stefan B.'])
    expect(filterVeldwerkers(set, { administratieId: '', alleenDossierOnvolledig: true, zoekterm: '' }).map((v) => v.naam)).toEqual(['Thijs H.', 'Stefan B.'])
    expect(filterVeldwerkers(set, { administratieId: '', alleenDossierOnvolledig: false, zoekterm: 'bureau' }).map((v) => v.naam)).toEqual(['Karin S.'])
    expect(filterVeldwerkers(set, { administratieId: '', alleenDossierOnvolledig: false, zoekterm: 'detacheerder' }).map((v) => v.naam)).toEqual(['Karin S.'])
    const zonderScope = veld({ administratie_ids: undefined })
    expect(filterVeldwerkers([zonderScope], { administratieId: ADMIN_B, alleenDossierOnvolledig: false, zoekterm: '' })).toEqual([])
  })

  it('sorteert urgent bovenaan: rood (ontbreekt/verlopen/geblokkeerd) → oranje (ter controle/binnenkort) → rest alfabetisch', () => {
    expect(sorteerVeldwerkers(standaardSet()).map((v) => v.naam)).toEqual(['Thijs H.', 'Stefan B.', 'Karin S.', 'Milan K.'])
  })
})

describe('VeldwerkersScreen', () => {
  it('rendert de tabel uit de kolommenbron (colgroup px, th-minima, min-width = som), dossier-badges en de voet', async () => {
    installMock()
    renderScherm()
    const tabel = await screen.findByTestId('veldwerkers-tabel')
    expect(tabel.style.minWidth).toBe(`${minimaleVeldwerkersTabelbreedte()}px`)
    const cols = Array.from(tabel.querySelectorAll<HTMLTableColElement>('colgroup col'))
    expect(cols.map((c) => c.style.width)).toEqual(VELDWERKERS_KOLOMMEN.map((k) => `${k.minPx}px`))
    const ths = Array.from(tabel.querySelectorAll<HTMLTableCellElement>('thead th'))
    expect(ths.map((th) => th.textContent)).toEqual(VELDWERKERS_KOLOMMEN.map((k) => k.kop))
    ths.forEach((th, i) => expect(th.style.minWidth).toBe(`${VELDWERKERS_KOLOMMEN[i].minPx}px`))
    for (const rij of tabel.querySelectorAll('tbody tr')) expect(rij.querySelectorAll('td')).toHaveLength(VELDWERKERS_KOLOMMEN.length)

    // Dossier-kolom uit de bestaande DTO; detacheerder = "—" (bureau, geen dossier).
    expect(within(tabel).getByText('compleet')).toBeInTheDocument()
    expect(within(tabel).getByText('2 ontbreken · 1 verlopen')).toBeInTheDocument()
    expect(within(tabel).getByText('1 ter controle')).toBeInTheDocument()
    const detaRij = within(tabel).getByText('Karin S.').closest('tr') as HTMLElement
    expect(within(detaRij).getAllByRole('cell')[3]).toHaveTextContent('—')
    // Urgentie bovenaan.
    const namen = Array.from(tabel.querySelectorAll('tbody tr td:first-child b')).map((b) => b.textContent)
    expect(namen).toEqual(['Thijs H.', 'Stefan B.', 'Karin S.', 'Milan K.'])
    // Koppelingen: bureau-tarief bij de detacheerder, "via bureau" bij de ZZP'er, crediteur-hint.
    expect(within(detaRij).getByText(/Milan K\. · €\s*51,00\/u/)).toBeInTheDocument()
    const milanRij = within(tabel).getByText('Milan K.', { selector: 'b' }).closest('tr') as HTMLElement
    expect(within(milanRij).getByText('via Karin S.')).toBeInTheDocument()
    expect(within(milanRij).getByText('zonder crediteur-koppeling geen factuurmatch')).toBeInTheDocument()
    // Voet + teller.
    expect(screen.getByTestId('veldwerkers-voet')).toHaveTextContent('4 veldwerkers · 2 met onvolledig dossier')
    expect(screen.getByTestId('veldwerkers-teller')).toHaveTextContent('4 veldwerkers')
    expect(screen.getByRole('link', { name: 'Gebruikers & toegang' })).toHaveAttribute('href', '/gebruikers?groep=veldwerkers')
  })

  it('acties: één primaire knop ("Dossier" / "ZZP\'ers") + ⋯-menu per rol', async () => {
    installMock()
    renderScherm()
    const tabel = await screen.findByTestId('veldwerkers-tabel')
    for (const rij of within(tabel).getAllByRole('row').slice(1)) {
      const acties = rij.querySelector('td.acties') as HTMLElement
      const knoppen = within(acties).getAllByRole('button')
      const meer = knoppen.filter((k) => k.getAttribute('aria-haspopup') === 'menu')
      expect(meer).toHaveLength(1)
      expect(knoppen.length - meer.length).toBe(1)
    }
    const milanRij = within(tabel).getByText('Milan K.', { selector: 'b' }).closest('tr') as HTMLElement
    const detaRij = within(tabel).getByText('Karin S.').closest('tr') as HTMLElement
    const uitvRij = within(tabel).getByText('Stefan B.').closest('tr') as HTMLElement
    expect(within(milanRij).getByRole('button', { name: 'Dossier' })).toBeInTheDocument()
    expect(within(detaRij).getByRole('button', { name: "ZZP'ers" })).toBeInTheDocument()

    const ge = userEvent.setup()
    await ge.click(within(milanRij).getByRole('button', { name: 'Meer acties voor Milan K.' }))
    expect((await screen.findAllByRole('menuitem')).map((m) => m.textContent)).toEqual(['Dossier openen…', 'Detacheerder koppelen…', 'Crediteur koppelen…'])
    await ge.keyboard('{Escape}')
    await ge.click(within(uitvRij).getByRole('button', { name: 'Meer acties voor Stefan B.' }))
    expect((await screen.findAllByRole('menuitem')).map((m) => m.textContent)).toEqual(['Dossier openen…'])
    await ge.keyboard('{Escape}')
    await ge.click(within(detaRij).getByRole('button', { name: 'Meer acties voor Karin S.' }))
    expect((await screen.findAllByRole('menuitem')).map((m) => m.textContent)).toEqual(["ZZP'ers koppelen…", 'Crediteur koppelen…', 'Bureau-tarieven…'])
  })

  it('"Detacheerder koppelen…" op een ZZP\'er-rij opent ZzperBureausModal en koppelt via dezelfde route (detacheerder_id + zzper_id)', async () => {
    const aanroepen: { method: string; url: string; body: unknown }[] = []
    installMock({ aanroepen })
    renderScherm()
    const tabel = await screen.findByTestId('veldwerkers-tabel')
    const thijsRij = within(tabel).getByText('Thijs H.').closest('tr') as HTMLElement
    const ge = userEvent.setup()
    await ge.click(within(thijsRij).getByRole('button', { name: 'Meer acties voor Thijs H.' }))
    await ge.click(await screen.findByRole('menuitem', { name: 'Detacheerder koppelen…' }))
    const dialoog = await screen.findByRole('dialog')
    expect(within(dialoog).getByText('Detacheerder van Thijs H.')).toBeInTheDocument()
    await ge.click(within(dialoog).getByRole('checkbox', { name: 'Karin S.' }))
    expect(within(dialoog).getByText('1 erbij')).toBeInTheDocument()
    await ge.click(within(dialoog).getByRole('button', { name: 'Koppelingen opslaan' }))
    await waitFor(() =>
      expect(aanroepen.find((a) => a.method === 'POST' && a.url === '/uren/beheer/detacheerderkoppelingen')?.body).toEqual({
        detacheerder_id: DETA_ID,
        zzper_id: ZZP2_ID,
      }),
    )
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('URL-state: ?filter=dossier_onvolledig&administratie= (de deeplink van de klantpagina) filtert; chip en combobox schrijven terug naar de URL', async () => {
    installMock()
    renderScherm(`/veldwerkers?filter=dossier_onvolledig&administratie=${ADMIN_A}`)
    const tabel = await screen.findByTestId('veldwerkers-tabel')
    // Alleen Stefan B. (A, ter controle) — Thijs (B) en Milan (compleet) vallen weg.
    expect(Array.from(tabel.querySelectorAll('tbody tr td:first-child b')).map((b) => b.textContent)).toEqual(['Stefan B.'])
    expect(screen.getByTestId('veldwerkers-teller')).toHaveTextContent('1 van 4 veldwerkers')
    const chip = screen.getByRole('button', { name: /dossier onvolledig \(2\)/ })
    expect(chip).toHaveAttribute('aria-pressed', 'true')
    // De combobox toont de gefilterde administratie; "alle administraties" wist het filter.
    expect(screen.getByLabelText('Administratie')).toHaveValue('BLOW B.V.')
    const ge = userEvent.setup()
    await ge.click(chip)
    await waitFor(() => expect(screen.getByTestId('locatie')).toHaveTextContent(`/veldwerkers?administratie=${ADMIN_A}`))
    expect(Array.from(tabel.querySelectorAll('tbody tr td:first-child b')).map((b) => b.textContent)).toEqual(['Stefan B.', 'Milan K.'])
    await ge.click(screen.getByRole('button', { name: 'alle administraties' }))
    await waitFor(() => expect(screen.getByTestId('locatie')).toHaveTextContent('/veldwerkers'))
    expect(tabel.querySelectorAll('tbody tr')).toHaveLength(4)
    // Combobox → administratie in de URL; zoekveld → q in de URL.
    await ge.click(screen.getByLabelText('Administratie'))
    await ge.click(await screen.findByRole('option', { name: 'Universal Steigerbouw' }))
    await waitFor(() => expect(screen.getByTestId('locatie')).toHaveTextContent(`administratie=${ADMIN_B}`))
    expect(tabel.querySelectorAll('tbody tr')).toHaveLength(3)
    await ge.type(screen.getByLabelText('Zoek veldwerkers'), 'karin')
    await waitFor(() => expect(screen.getByTestId('locatie')).toHaveTextContent('q=karin'))
    expect(Array.from(tabel.querySelectorAll('tbody tr td:first-child b')).map((b) => b.textContent)).toEqual(['Karin S.'])
  })

  it('lege filterstand = tekst + "Filters wissen"; lege stand zonder veldwerkers = actie "+ Veldwerker uitnodigen"', async () => {
    installMock()
    const { unmount } = renderScherm('/veldwerkers?q=niemand')
    await screen.findByTestId('lege-filterstand')
    expect(screen.getByText('Geen veldwerkers binnen dit filter.')).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Filters wissen' }))
    await waitFor(() => expect(screen.getByTestId('locatie')).toHaveTextContent(/^\/veldwerkers$/))
    await screen.findByTestId('veldwerkers-tabel')
    unmount()

    installMock({ veld: [] })
    renderScherm()
    await screen.findByTestId('lege-stand')
    expect(screen.getAllByRole('button', { name: '+ Veldwerker uitnodigen' }).length).toBeGreaterThanOrEqual(2)
    expect(screen.queryByTestId('veldwerkers-tabel')).not.toBeInTheDocument()
  })

  it('403 (geen Beheerder, geen recht veldwerkerbeheer) = leesbare melding, geen tabel en geen uitnodig-knop', async () => {
    installMock({ status: 403 })
    renderScherm()
    const melding = await screen.findByRole('alert')
    expect(melding).toHaveTextContent("alleen toegankelijk voor de Beheerder of een medewerker met het recht 'veldwerkerbeheer'")
    expect(screen.queryByTestId('veldwerkers-tabel')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '+ Veldwerker uitnodigen' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Opnieuw proberen' })).not.toBeInTheDocument()
  })

  it('andere fout = melding mét "Opnieuw proberen"', async () => {
    installMock({ status: 500 })
    renderScherm()
    const melding = await screen.findByRole('alert')
    expect(melding).toHaveTextContent('De veldwerkers konden niet geladen worden.')
    expect(within(melding).getByRole('button', { name: 'Opnieuw proberen' })).toBeInTheDocument()
  })

  it('"+ Veldwerker uitnodigen" opent de bestaande UitnodigModal in de rolgroep Veldwerker (ZZP\'er standaard)', async () => {
    installMock()
    renderScherm()
    await screen.findByTestId('veldwerkers-tabel')
    await userEvent.setup().click(screen.getByRole('button', { name: '+ Veldwerker uitnodigen' }))
    expect(await screen.findByTestId('uitnodig-rolgroep')).toHaveTextContent("Rolgroep: Veldwerker (ZZP'er · Uitvoerder · Detacheerder)")
    expect((screen.getByLabelText('Rol') as HTMLSelectElement).value).toBe('zzper')
  })
})
