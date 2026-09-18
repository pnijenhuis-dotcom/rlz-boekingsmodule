/** Bug 18-09 — chip "14 meerwerk/urenstaten te beoordelen" landde op een lege Meerwerk-pagina. Nu: "Beoordelen" mét tabs
 * Urenstaten (N) · Meerwerk (M); de tellers komen uit dezelfde lijsten als de tabellen; kantoor keurt goed/af (reden
 * verplicht); lege stand = context + actie. */
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MeerwerkScreen } from './MeerwerkScreen'

const ADM = 'aaaaaaaa-0000-0000-0000-000000000001'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const STAAT = (id: string, naam: string, project: string) => ({
  weekstaat_id: id,
  administratie_id: ADM,
  administratie_naam: 'Universal Steigerbouw B.V.',
  zzper_id: `zz-${id}`,
  zzper_naam: naam,
  project_id: `pr-${id}`,
  project_naam: project,
  jaar: 2026,
  weeknummer: 37,
  totaal_uren: '38',
  totaal_m2: '0',
  ingediend_op: '2026-09-15T07:41:00Z',
  ingediend_namens: false,
  ingediend_door_naam: null,
})

function installMock(opties: { staten: unknown[]; laatsteKeuring?: string | null; meerwerk?: unknown[]; posts?: { url: string; body: unknown }[] }) {
  let staten = opties.staten
  vi.stubGlobal(
    'fetch',
    vi.fn((invoer: RequestInfo | URL, init?: RequestInit) => {
      const url = String(invoer)
      if (url === '/auth/administraties') return Promise.resolve(jsonResponse({ administraties: [{ id: ADM, naam: 'Universal Steigerbouw B.V.' }] }))
      if (url.startsWith('/uren/kantoor/weekstaten?')) {
        return Promise.resolve(jsonResponse({ items: staten, laatste_keuring_op: opties.laatsteKeuring ?? null }))
      }
      if (url.startsWith('/uren/kantoor/meerwerk')) return Promise.resolve(jsonResponse(opties.meerwerk ?? []))
      if (url.includes('/uren/kantoor/weekstaten/') && init?.method === 'POST') {
        opties.posts?.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
        const id = url.split('/')[5]
        staten = (staten as { weekstaat_id: string }[]).filter((s) => s.weekstaat_id !== id)
        return Promise.resolve(jsonResponse({ id, status: url.endsWith('goedkeuren') ? 'goedgekeurd' : 'corrigeren' }))
      }
      return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
    }),
  )
}

function renderScherm(pad = `/meerwerk?administratie=${ADM}`) {
  return render(
    <MemoryRouter initialEntries={[pad]}>
      <MeerwerkScreen />
    </MemoryRouter>,
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('Beoordelen — urenstaten & meerwerk op één plek (bug 18-09)', () => {
  it('landt standaard op Urenstaten (N) met de ingediende weekstaten; Meerwerk (M) is de tweede tab', async () => {
    installMock({
      staten: [STAAT('a', 'M. Sanli', '26021 Tilburg (Huvanco)'), STAAT('b', 'R. Yücetaş', '26019 Bennekom (Boon)')],
      meerwerk: [{ id: 'm1', status: 'gemeld', project_id: 'p', project_naam: 'X', omschrijving: 'o', aantal: '1', eenheid: 'm2', datum_uitgevoerd: '2026-09-15', gemeld_door_naam: 'B', in_opdracht_van: null, heeft_foto: false, vraag_tekst: null, vraag_antwoord: null, prijs_per_eenheid: null, bedrag: null, verkoopfactuur_referentie: null }],
    })
    renderScherm()
    await waitFor(() => expect(screen.getByRole('heading', { name: /Beoordelen — Universal Steigerbouw/ })).toBeInTheDocument())
    await waitFor(() => expect(screen.getByTestId('tab-urenstaten')).toHaveTextContent('Urenstaten (2)'))
    await waitFor(() => expect(screen.getByTestId('tab-meerwerk')).toHaveTextContent('Meerwerk (1)'))
    expect(screen.getByTestId('tab-urenstaten')).toHaveAttribute('aria-selected', 'true')
    const tabel = screen.getByTestId('urenstaten-tabel')
    expect(within(tabel).getByText('M. Sanli')).toBeInTheDocument()
    expect(within(tabel).getByText('26019 Bennekom (Boon)')).toBeInTheDocument()
    expect(within(tabel).getAllByRole('button', { name: 'Goedkeuren' }).length).toBe(2)
    // Kolomminima uit één bron: elke kop draagt zijn minimum.
    expect(within(tabel).getByText('Veldwerker')).toHaveStyle({ minWidth: '176px' })
  })

  it('?tab=meerwerk toont de meerwerk-statusfilters; klik op de Urenstaten-tab schakelt terug', async () => {
    installMock({ staten: [STAAT('a', 'M. Sanli', '26021 Tilburg (Huvanco)')] })
    renderScherm(`/meerwerk?administratie=${ADM}&tab=meerwerk`)
    await waitFor(() => expect(screen.getByTestId('tab-meerwerk')).toHaveAttribute('aria-selected', 'true'))
    expect(screen.getByText(/Geen meerwerk in deze status/)).toBeInTheDocument()
    await userEvent.setup().click(screen.getByTestId('tab-urenstaten'))
    await waitFor(() => expect(screen.getByTestId('urenstaten-tabel')).toBeInTheDocument())
  })

  it('goedkeuren POST naar de kantoor-route; afkeuren vraagt een verplichte reden; de lijst vernieuwt', async () => {
    const posts: { url: string; body: unknown }[] = []
    installMock({ staten: [STAAT('a', 'M. Sanli', '26021 Tilburg (Huvanco)'), STAAT('b', 'R. Yücetaş', '26019 Bennekom (Boon)')], posts })
    renderScherm()
    await waitFor(() => expect(screen.getByTestId('urenstaten-tabel')).toBeInTheDocument())
    const gebruiker = userEvent.setup()
    await gebruiker.click(within(screen.getByTestId('urenstaat-a')).getByRole('button', { name: 'Goedkeuren' }))
    await waitFor(() => expect(posts).toEqual([{ url: `/uren/kantoor/weekstaten/${ADM}/a/goedkeuren`, body: {} }]))
    await waitFor(() => expect(screen.queryByTestId('urenstaat-a')).not.toBeInTheDocument())
    expect(screen.getByTestId('tab-urenstaten')).toHaveTextContent('Urenstaten (1)')

    await gebruiker.click(screen.getByRole('button', { name: /Meer acties voor R\. Yücetaş week 37/ }))
    await gebruiker.click(screen.getByRole('menuitem', { name: 'Afkeuren…' }))
    const afkeurKnop = screen.getByRole('button', { name: 'Afkeuren' })
    expect(afkeurKnop).toBeDisabled() // reden verplicht
    await gebruiker.type(screen.getByLabelText('Reden van afkeuring'), 'Dinsdag was een vrije dag')
    await gebruiker.click(afkeurKnop)
    await waitFor(() => expect(posts[1]).toEqual({ url: `/uren/kantoor/weekstaten/${ADM}/b/afkeuren`, body: { reden: 'Dinsdag was een vrije dag', correcties: [] } }))
    await waitFor(() => expect(screen.getByTestId('urenstaten-leeg')).toBeInTheDocument())
  })

  it('lege stand = context + actie: laatste keuring mét datum en een ingang naar de planning (KP7)', async () => {
    installMock({ staten: [], laatsteKeuring: '2026-09-12T10:00:00Z' })
    renderScherm()
    await waitFor(() => expect(screen.getByTestId('urenstaten-leeg')).toBeInTheDocument())
    expect(screen.getByTestId('urenstaten-leeg')).toHaveTextContent('Geen urenstaten te beoordelen — laatste keuring 12 september 2026.')
    expect(screen.getByRole('link', { name: 'Planning openen →' })).toHaveAttribute('href', `/planning?administratie=${ADM}`)
    expect(screen.getByTestId('tab-urenstaten')).toHaveTextContent('Urenstaten (0)')
  })
})
