import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AdministratieWizard } from './AdministratieWizard'
import { ODOO_KNIP_DEFAULT, OdooKoppelDialog } from './OdooKoppelWizard'

/** Odoo-koppelwizard (adapter blok E 03-09, mockup odoo-koppeling-ui.html §2): één component, twee ingangen.
 * Ingang A = de Odoo-tak van "+ Administratie toevoegen" (backend-keuze stap 1); ingang B = "Odoo koppelen…" op
 * de detailpagina mét expliciete koppelvorm (volledig + overgangsdatum → overstap; leesbron + knip → leesbron).
 * De 422 mét rapport blokkeert (zelfde poort als de RLZ-wizard); de sleutel reist alleen in de body. */

const ADMIN_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const NIEUW_ID = 'cccccccc-0000-0000-0000-000000000003'
const PROBE_OK = { ledgers: 'ok', taxrates: 'ok', vendors: 'ok', journals: 'ok', facturen: 'ok', boeken: 'ok' }

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function installMock(posts: { url: string; body: unknown }[]) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null
      if (init?.method === 'POST' || init?.method === 'PUT') posts.push({ url, body })
      if (url === '/instellingen/odoo/verbinding-testen') {
        if (body?.api_key === 'fout') return Promise.resolve(jsonResponse({ detail: { bericht: 'Odoo weigert deze sleutel (HTTP 401) — controleer de API-sleutel', rapport: { verbinding: 'HTTP 401' } } }, 422))
        return Promise.resolve(
          jsonResponse({
            companies: [
              { company_id: 1, naam: 'Universal Steigerbouw', al_gekoppeld: false },
              { company_id: 3, naam: 'Universal Verkoop', al_gekoppeld: true },
            ],
          }),
        )
      }
      if (url === '/instellingen/odoo/koppelen') {
        if (body?.api_key === 'rood') {
          return Promise.resolve(
            jsonResponse(
              {
                detail: {
                  bericht: 'Rechten-probe niet groen — niets opgeslagen',
                  rapport: { ...PROBE_OK, boeken: 'geen schrijfrecht op account.move — geef de API-gebruiker boekhoudrechten in Odoo' },
                },
              },
              422,
            ),
          )
        }
        return Promise.resolve(jsonResponse({ administraties: [{ id: NIEUW_ID, naam: 'Universal Steigerbouw', company_id: 1, probe: PROBE_OK, sync_run_id: 'run-1', sync: {} }] }, 201))
      }
      if (url === `/administraties/${ADMIN_ID}/odoo/overstap`) {
        return Promise.resolve(jsonResponse({ id: ADMIN_ID, naam: 'Universal Steigerbouw B.V.', company_id: 1, probe: PROBE_OK, sync_run_id: 'run-2', sync: {} }, 201))
      }
      if (url === `/administraties/${ADMIN_ID}/odoo/leesbron` && init?.method === 'POST') {
        return Promise.resolve(jsonResponse({ groen: true, rapport: { ledgers: 'ok', facturen: 'ok' }, company_naam: 'Universal Steigerbouw', versie: '19.0', lock_dates: {} }, 201))
      }
      if (url.endsWith('/eerste-sync/status')) {
        return Promise.resolve(
          jsonResponse({
            run_id: 'run-1',
            status: 'klaar',
            onderdelen: {
              ledgers: { status: 'klaar', aangemaakt: 212, bijgewerkt: 0 },
              taxrates: { status: 'klaar', aangemaakt: 14, bijgewerkt: 0 },
              vendors: { status: 'klaar', aangemaakt: 380, bijgewerkt: 0 },
              projects: { status: 'klaar', aangemaakt: 0, bijgewerkt: 0 },
            },
            aangevraagd_op: '2026-09-03T20:00:00Z',
            beeindigd_op: '2026-09-03T20:01:00Z',
            fout_reden: null,
          }),
        )
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

afterEach(() => vi.unstubAllGlobals())

async function vulVerbinding(sleutel = 'geheim') {
  fireEvent.change(screen.getByLabelText('Odoo-URL'), { target: { value: 'https://universal-steigers.odoo.com' } })
  fireEvent.change(screen.getByLabelText('API-sleutel'), { target: { value: sleutel } })
  fireEvent.click(screen.getByRole('button', { name: /Verbinding testen/ }))
  await waitFor(() => expect(screen.getByLabelText('Koppelen Universal Steigerbouw')).toBeInTheDocument())
}

describe('OdooKoppelWizard — ingang A (Odoo-tak van "+ Administratie toevoegen")', () => {
  it('backend-keuze Odoo → verbinding → companies (al gekoppeld uitgeschakeld) → koppelen → resultaat mét eerste sync per Odoo-onderdeel', async () => {
    const posts: { url: string; body: unknown }[] = []
    installMock(posts)
    const onAangemaakt = vi.fn()
    render(<AdministratieWizard open onSluiten={() => {}} onAangemaakt={onAangemaakt} />)

    expect(screen.getByText('Administratie toevoegen — stap 1 van 4')).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('Odoo'))
    fireEvent.click(screen.getByRole('button', { name: 'Verder →' }))
    expect(screen.getByText('Administratie toevoegen — stap 2 van 4')).toBeInTheDocument()
    // Bewust géén database-veld: de JSON-2-URL bindt de database.
    expect(screen.queryByLabelText(/database/i)).not.toBeInTheDocument()

    await vulVerbinding()
    expect(screen.getByText('Administratie toevoegen — stap 3 van 4')).toBeInTheDocument()
    expect(posts[0]).toEqual({ url: '/instellingen/odoo/verbinding-testen', body: { odoo_url: 'https://universal-steigers.odoo.com', api_key: 'geheim' } })
    expect(screen.getByLabelText('Koppelen Universal Verkoop')).toBeDisabled()
    expect(screen.getByText('al gekoppeld')).toBeInTheDocument()
    // Eén vrije company → alvast aangevinkt; company-id komt uit de lijst, nooit getypt.
    expect(screen.getByLabelText('Koppelen Universal Steigerbouw')).toBeChecked()
    expect(screen.getByText('company 1')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Koppeling opslaan \(1\)/ }))
    await waitFor(() => expect(screen.getByText('Administratie toevoegen — stap 4 van 4')).toBeInTheDocument())
    expect(posts.find((p) => p.url === '/instellingen/odoo/koppelen')?.body).toEqual({ odoo_url: 'https://universal-steigers.odoo.com', api_key: 'geheim', company_ids: [1] })
    // Resultaat: company i.p.v. RLZ-id, probe-samenvatting in Odoo-vorm, vier onderdelen (geen bankrekeningen).
    expect(screen.getByText(/company Universal Steigerbouw \(1\)/)).toBeInTheDocument()
    expect(screen.getByText(/Rechten-probe groen: grootboek · btw · relaties · journals · facturen · boeken \(schrijven\)/)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText(/212 nieuw/)).toBeInTheDocument())
    expect(screen.queryByText('Bankrekeningen:')).not.toBeInTheDocument()
    expect(screen.queryByText(/Bankrekeningen/)).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Sluiten' }))
    expect(onAangemaakt).toHaveBeenCalledTimes(1)
  })

  it('rode rechten-probe (422 mét rapport) blokkeert: foutregel mét handelingsperspectief zichtbaar, wizard blijft op de company-stap, niets aangemaakt', async () => {
    const posts: { url: string; body: unknown }[] = []
    installMock(posts)
    const onAangemaakt = vi.fn()
    render(<AdministratieWizard open onSluiten={() => {}} onAangemaakt={onAangemaakt} />)
    fireEvent.click(screen.getByLabelText('Odoo'))
    fireEvent.click(screen.getByRole('button', { name: 'Verder →' }))
    await vulVerbinding('rood')
    fireEvent.click(screen.getByRole('button', { name: /Koppeling opslaan \(1\)/ }))
    await waitFor(() => expect(screen.getByText(/Rechten-probe niet groen — niets opgeslagen/)).toBeInTheDocument())
    expect(screen.getByText(/geen schrijfrecht op account.move — geef de API-gebruiker boekhoudrechten in Odoo/)).toBeInTheDocument()
    expect(screen.getByText(/Opslaan is geblokkeerd tot de probe groen is/)).toBeInTheDocument()
    expect(screen.getByText('Administratie toevoegen — stap 3 van 4')).toBeInTheDocument()
    expect(screen.queryByTestId('odoo-wizard-resultaat')).not.toBeInTheDocument()
    // Sluiten zónder resultaat = niets aangemaakt → geen herlaad.
    fireEvent.click(screen.getByRole('button', { name: '← Terug' }))
    expect(onAangemaakt).not.toHaveBeenCalled()
  })

  it('sleutel geweigerd bij verbinding testen = leesbare fout op de verbindingsstap', async () => {
    installMock([])
    render(<AdministratieWizard open onSluiten={() => {}} onAangemaakt={() => {}} />)
    fireEvent.click(screen.getByLabelText('Odoo'))
    fireEvent.click(screen.getByRole('button', { name: 'Verder →' }))
    fireEvent.change(screen.getByLabelText('Odoo-URL'), { target: { value: 'https://x.odoo.com' } })
    fireEvent.change(screen.getByLabelText('API-sleutel'), { target: { value: 'fout' } })
    fireEvent.click(screen.getByRole('button', { name: /Verbinding testen/ }))
    await waitFor(() => expect(screen.getByText(/weigert deze sleutel \(HTTP 401\)/)).toBeInTheDocument())
    expect(screen.getByText('Administratie toevoegen — stap 2 van 4')).toBeInTheDocument()
  })
})

describe('OdooKoppelWizard — ingang B (detailpagina "Odoo koppelen…")', () => {
  const administratie = { id: ADMIN_ID, naam: 'Universal Steigerbouw B.V.' }

  it('koppelvorm VOLLEDIG: overgangsdatum verplicht, radio één company, "Koppeling opslaan" = POST …/odoo/overstap mét company + overgangsdatum', async () => {
    const posts: { url: string; body: unknown }[] = []
    installMock(posts)
    const onAfgerond = vi.fn()
    render(<OdooKoppelDialog administratie={administratie} onSluiten={() => {}} onAfgerond={onAfgerond} />)

    expect(screen.getByText('Odoo koppelen — Universal Steigerbouw B.V. — stap 1 van 4')).toBeInTheDocument()
    expect(screen.getByLabelText('Volledige backend')).toBeChecked()
    fireEvent.click(screen.getByRole('button', { name: 'Verder →' }))
    await vulVerbinding()
    expect(screen.getByText('Odoo koppelen — Universal Steigerbouw B.V. — stap 3 van 4')).toBeInTheDocument()
    expect(screen.getByLabelText('Koppelen Universal Steigerbouw')).toHaveAttribute('type', 'radio')
    // Zonder overgangsdatum blijft opslaan uit (verplicht).
    const opslaan = screen.getByRole('button', { name: /Koppeling opslaan/ })
    expect(opslaan).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Overgangsdatum'), { target: { value: '2026-10-01' } })
    expect(opslaan).toBeEnabled()
    fireEvent.click(opslaan)

    await waitFor(() => expect(screen.getByTestId('odoo-wizard-resultaat')).toBeInTheDocument())
    const overstap = posts.find((p) => p.url === `/administraties/${ADMIN_ID}/odoo/overstap`)
    expect(overstap?.body).toEqual({ odoo_url: 'https://universal-steigers.odoo.com', api_key: 'geheim', company_id: 1, overgangsdatum: '2026-10-01' })
    expect(posts.some((p) => p.url.endsWith('/odoo/leesbron'))).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: 'Sluiten' }))
    expect(onAfgerond).toHaveBeenCalledTimes(1)
  })

  it('koppelvorm LEESBRON: knipdatum-stap mét default 2026-09-01, "Koppeling opslaan" = POST …/odoo/leesbron mét knip; resultaat toont de leesprobe', async () => {
    const posts: { url: string; body: unknown }[] = []
    installMock(posts)
    render(<OdooKoppelDialog administratie={administratie} onSluiten={() => {}} onAfgerond={() => {}} />)

    fireEvent.click(screen.getByLabelText('Alleen-lezen leesbron'))
    fireEvent.click(screen.getByRole('button', { name: 'Verder →' }))
    expect(screen.getByText('Odoo koppelen — Universal Steigerbouw B.V. — stap 2 van 5')).toBeInTheDocument()
    await vulVerbinding()
    // Leesbron: geen overgangsdatum, wél een knipdatum-stap.
    expect(screen.queryByLabelText('Overgangsdatum')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Knipdatum kiezen →' }))
    const knip = screen.getByLabelText('Knipdatum voorraad-uitstroom') as HTMLInputElement
    expect(knip.value).toBe(ODOO_KNIP_DEFAULT)
    expect(ODOO_KNIP_DEFAULT).toBe('2026-09-01')
    fireEvent.click(screen.getByRole('button', { name: /Koppeling opslaan/ }))

    await waitFor(() => expect(screen.getByTestId('odoo-wizard-resultaat')).toBeInTheDocument())
    const leesbron = posts.find((p) => p.url === `/administraties/${ADMIN_ID}/odoo/leesbron`)
    expect(leesbron?.body).toEqual({ odoo_url: 'https://universal-steigers.odoo.com', api_key: 'geheim', company_id: 1, voorraad_knip_datum: '2026-09-01' })
    expect(posts.some((p) => p.url.endsWith('/odoo/overstap'))).toBe(false)
    expect(screen.getByText('leesbron gekoppeld')).toBeInTheDocument()
    expect(screen.getByText(/verkoop-uitstroom vanaf 01-09-2026/)).toBeInTheDocument()
  })
})
