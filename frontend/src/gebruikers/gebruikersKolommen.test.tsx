/** Blok 2 vervolgrun 10-09 avond — regressievangnet tegen kolom-implosie op Gebruikers & toegang
 * (kliktest Peter 10-09: kop "BE…", slot-/sleutel-iconen over elkaar, actiekolom pakt alle breedte).
 *
 * EERLIJK OVER WAT DIT TOETST: jsdom kent geen layout, dus deze test meet géén pixels. Hij bewaakt
 *  (1) de bron: elke kolom een geheel px-minimum, som per tab, beschikbare breedte uit dezelfde bron
 *      (Shell.css/components.css-constanten) — past de som op 1440 (Peters kliktest-breedte)? Op 1170
 *      past géén van de drie tabellen (824 px netto); dáár is de geborgde uitkomst interne scroll in
 *      `.tabel-scroll` mét sticky actiekolom, nooit een kolom onder zijn minimum;
 *  (2) de render: `<col>` in px uit de bron, élke `<th>` draagt het minimum als inline `min-width`, de
 *      tabel `min-width` = de som, koppen letterlijk uit de bron (nooit afgekapt: CSS nowrap, geen
 *      ellipsis — als tekst getoetst in `styles/gebruikersCss.test.ts`);
 *  (3) de actiekolom: hooguit één zichtbare knop + ⋯ (UX-norm "één primaire knop + ⋯").
 * De échte pixels (één regel chips, geen interne scroll op 1440) meet `scripts/overflow_sweep.sh` met
 * `harness-gebruikers.html?breed=1` (+ `&groep=…`) in headless Chrome. */
import { render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../auth/AuthContext'
import { GebruikersScreen } from './GebruikersScreen'
import {
  GEBRUIKERS_KOLOMMEN,
  beschikbareBreedte,
  minimaleTabelbreedte,
  type GebruikersTab,
} from './gebruikersKolommen'

const TABS: GebruikersTab[] = ['kantoor', 'veldwerkers', 'accordeurs']

describe('gebruikersKolommen — de bron', () => {
  it('elke kolom heeft een geheel px-minimum ≥ 100 (acties ≥ 150: één knop + ⋯) en een unieke sleutel', () => {
    for (const tab of TABS) {
      const sleutels = new Set<string>()
      for (const k of GEBRUIKERS_KOLOMMEN[tab]) {
        expect(Number.isInteger(k.minPx), `${tab}.${k.sleutel}`).toBe(true)
        expect(k.minPx, `${tab}.${k.sleutel} te smal`).toBeGreaterThanOrEqual(k.sleutel === 'acties' ? 150 : 100)
        expect(sleutels.has(k.sleutel), `${tab}: dubbele sleutel ${k.sleutel}`).toBe(false)
        sleutels.add(k.sleutel)
      }
      expect(GEBRUIKERS_KOLOMMEN[tab].at(-1)?.sleutel).toBe('acties')
    }
  })

  it('de tabel-min-width is exact de som van de kolomminima', () => {
    for (const tab of TABS) {
      const som = GEBRUIKERS_KOLOMMEN[tab].reduce((s, k) => s + k.minPx, 0)
      expect(minimaleTabelbreedte(tab)).toBe(som)
    }
  })

  it('beschikbare breedte = viewport − zijbalk 236 − content-padding 2×34 − panel-padding 2×20 − rand 2: 1170 → 824, 1440 → 1094', () => {
    expect(beschikbareBreedte(1170)).toBe(824)
    expect(beschikbareBreedte(1440)).toBe(1094)
  })

  it.each(TABS)('op 1440 past de %s-tabel zonder interne scroll: som van de minima ≤ beschikbare breedte', (tab) => {
    expect(minimaleTabelbreedte(tab), `${tab}: ${minimaleTabelbreedte(tab)} > ${beschikbareBreedte(1440)}`).toBeLessThanOrEqual(
      beschikbareBreedte(1440),
    )
  })

  it.each(TABS)(
    'op 1170 past de %s-tabel NIET zonder interne scroll (documenteerd feit, geen wens) — de tabel-min-width = som borgt dat geen kolom onder zijn minimum komt',
    (tab) => {
      // Zou dit ooit wél passen (kolommen geschrapt/versmald), dan mag deze assertie omgekeerd worden — hij
      // staat hier zodat het rapport "1170 = interne scroll" nooit stil veroudert.
      expect(minimaleTabelbreedte(tab)).toBeGreaterThan(beschikbareBreedte(1170))
      // Het tekort blijft kleiner dan één kolom: de sticky actiekolom blijft altijd in beeld, alleen de
      // rest-kolom(men) schuiven weg.
      expect(minimaleTabelbreedte(tab) - beschikbareBreedte(1170)).toBeLessThan(Math.max(...GEBRUIKERS_KOLOMMEN[tab].map((k) => k.minPx)) * 2)
    },
  )
})

/* --- render: colgroup/th/table dragen de bron ------------------------------------------------- */

const EIGEN_ID = 'aaaaaaaa-0000-0000-0000-00000000000a'
const ADMINISTRATIE_ID = 'dddddddd-0000-0000-0000-00000000000d'

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

function fakeAccessToken(): string {
  const payload = btoa(JSON.stringify({ sub: EIGEN_ID, rol: 'beheerder' })).replace(/\+/g, '-').replace(/\//g, '_')
  return `kop.${payload}.handtekening`
}

function gebruiker(overrides: Record<string, unknown>) {
  return {
    id: 'bbbbbbbb-0000-0000-0000-00000000000b',
    naam: 'Demi de Vries',
    e_mail: 'demi@ak-nijenhuis.nl',
    rol: 'boekhouding',
    status: 'actief',
    administratie_ids: [ADMINISTRATIE_ID],
    heeft_totp: true,
    aantal_passkeys: 2,
    open_uitnodiging_verloopt_op: null,
    open_herstel_verloopt_op: null,
    staande_goedkeuringen: 0,
    geblokkeerd_op: null,
    geblokkeerd_door_naam: null,
    half_geactiveerd: false,
    ...overrides,
  }
}

function installMock(gebruikers: unknown[]) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url === '/auth/token/vernieuwen' && init?.method === 'POST') return Promise.resolve(jsonResponse({ access_token: fakeAccessToken() }))
      if (url.startsWith('/auth/gebruikers?')) return Promise.resolve(jsonResponse({ gebruikers }))
      if (url === '/auth/administraties') return Promise.resolve(jsonResponse({ administraties: [{ id: ADMINISTRATIE_ID, naam: 'Molenhof Beheer B.V.' }] }))
      if (url === '/uren/beheer/veldgebruikers') return Promise.resolve(jsonResponse([]))
      if (url.includes('/apparaten')) return Promise.resolve(jsonResponse({ apparaten: [] }))
      return Promise.resolve(jsonResponse({ gebruiker_ids: [] }))
    }),
  )
}

function renderScherm(pad: string) {
  return render(
    <MemoryRouter initialEntries={[pad]}>
      <AuthProvider>
        <GebruikersScreen />
      </AuthProvider>
    </MemoryRouter>,
  )
}

afterEach(() => vi.unstubAllGlobals())

function toetsTabel(tabel: HTMLElement, tab: GebruikersTab) {
  const kolommen = GEBRUIKERS_KOLOMMEN[tab]
  expect(tabel).toHaveClass('gebruikers-tabel')
  expect(tabel.style.minWidth).toBe(`${minimaleTabelbreedte(tab)}px`)
  const cols = Array.from(tabel.querySelectorAll<HTMLTableColElement>('colgroup col'))
  expect(cols.map((c) => c.style.width)).toEqual(kolommen.map((k) => `${k.minPx}px`))
  expect(cols.map((c) => c.className)).toEqual(kolommen.map((k) => `kol-${k.sleutel}`))
  const ths = Array.from(tabel.querySelectorAll<HTMLTableCellElement>('thead th'))
  expect(ths).toHaveLength(kolommen.length)
  ths.forEach((th, i) => {
    expect(th.style.minWidth, `${tab} kop ${i}`).toBe(`${kolommen[i].minPx}px`)
    expect(th.textContent, `${tab} kop ${i} letterlijk uit de bron`).toBe(kolommen[i].kop)
  })
  expect(ths.at(-1)).toHaveClass('acties')
  // Elke datarij heeft precies zoveel cellen als kolommen — geen verdwaalde extra kolom buiten de bron.
  for (const rij of tabel.querySelectorAll('tbody tr')) {
    expect(rij.querySelectorAll('td')).toHaveLength(kolommen.length)
  }
}

describe('gebruikers-tabellen dragen de kolomminima uit de bron (render)', () => {
  it('Kantoor: colgroup in px, th min-width, tabel min-width = som; Beveiliging/Status als chips-regel; één knop + ⋯', async () => {
    installMock([
      gebruiker({}),
      gebruiker({
        id: 'ffffffff-0000-0000-0000-00000000000f',
        naam: 'J. Jansen',
        status: 'uitgenodigd',
        heeft_totp: false,
        aantal_passkeys: 0,
        open_uitnodiging_verloopt_op: new Date(Date.now() + 68 * 3600e3).toISOString(),
      }),
    ])
    renderScherm('/gebruikers')
    const tabel = await screen.findByTestId('gebruikers-tabel-kantoor')
    await waitFor(() => expect(within(tabel).getByText('Demi de Vries')).toBeInTheDocument())
    toetsTabel(tabel, 'kantoor')

    // Beveiliging: beide chips in één flex-regel (chips-regel), niet als losse inline-elementen.
    const passkeys = within(tabel).getByText('🔑 2 passkeys')
    expect(passkeys.parentElement).toHaveClass('chips-regel')
    expect(within(passkeys.parentElement as HTMLElement).getByText('🔐 TOTP')).toBeInTheDocument()
    // Status: één badge in de chips-regel, het verloop als detailregel eronder.
    expect(within(tabel).getByText('uitgenodigd').parentElement).toHaveClass('chips-regel')
    expect(within(tabel).getByText(/uitnodiging verloopt over/)).toHaveClass('cel-detail')

    // Actiekolom: per rij hooguit één zichtbare knop (Opnieuw mailen) + de ⋯-knop; niets anders.
    const rijen = within(tabel).getAllByRole('row').slice(1)
    for (const rij of rijen) {
      const acties = rij.querySelector('td.acties') as HTMLElement
      const knoppen = within(acties).getAllByRole('button')
      const meer = knoppen.filter((k) => k.getAttribute('aria-haspopup') === 'menu')
      expect(meer).toHaveLength(1)
      expect(knoppen.length - meer.length).toBeLessThanOrEqual(1)
    }
    expect(within(tabel).getByRole('button', { name: 'Opnieuw mailen' })).toBeInTheDocument()
    expect(within(tabel).queryByRole('button', { name: /E-mail wijzigen/ })).not.toBeInTheDocument()
    expect(within(tabel).queryByRole('button', { name: /Blokkeren/ })).not.toBeInTheDocument()
    expect(within(tabel).queryByRole('button', { name: /Archiveren/ })).not.toBeInTheDocument()
  })

  it('Veldwerkers en Klant-accordeurs: dezelfde behandeling (bron, colgroup, th-minima, ⋯)', async () => {
    installMock([
      gebruiker({ id: 'cccccccc-0000-0000-0000-00000000000c', naam: 'R. de Groot', rol: 'klant_accordeur' }),
      gebruiker({ id: 'eeeeeeee-0000-0000-0000-00000000000e', naam: 'Z. Zzp', rol: 'zzper' }),
    ])
    const { unmount } = renderScherm('/gebruikers?groep=veldwerkers')
    const veld = await screen.findByTestId('gebruikers-tabel-veldwerkers')
    await waitFor(() => expect(within(veld).getByText('Z. Zzp')).toBeInTheDocument())
    toetsTabel(veld, 'veldwerkers')
    expect(within(veld).getByText('actief').parentElement).toHaveClass('chips-regel')
    expect(within(veld).getByRole('button', { name: 'Herstel-link' })).toBeInTheDocument()
    expect(within(veld).getByRole('button', { name: 'Meer acties voor Z. Zzp' })).toHaveAttribute('aria-haspopup', 'menu')
    unmount()

    renderScherm('/gebruikers?groep=accordeurs')
    const acc = await screen.findByTestId('gebruikers-tabel-accordeurs')
    await waitFor(() => expect(within(acc).getByText('R. de Groot')).toBeInTheDocument())
    toetsTabel(acc, 'accordeurs')
    expect(within(acc).getByRole('button', { name: 'Herstel-link' })).toBeInTheDocument()
    expect(within(acc).getByRole('button', { name: 'Meer acties voor R. de Groot' })).toHaveAttribute('aria-haspopup', 'menu')
  })
})
