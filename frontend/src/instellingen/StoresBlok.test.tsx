// Blok "Stores" op Instellingen › Boeken (0151, Peter 16-09 avond: Sunshine Island = eigen BV): lege stand = actie,
// koppelen → POST {store, administratie_id}, ⋯ → Ontkoppelen stuurt PUT {actief:false}, ⋯ → Andere administratie… →
// PUT {administratie_id}; de lijst is één platformbrede tabel (store · administratie · status).
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { StoresBlok } from './StoresBlok'

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const ADMINISTRATIES = [
  { id: 'a-elderveld', naam: 'Zonnestudio Elderveld B.V.' },
  { id: 'a-sunshine', naam: 'Sunshine Island B.V.' },
]

function rij(over: Partial<Record<string, unknown>> = {}) {
  return {
    id: 's1',
    store_naam: 'Elderveld',
    store_norm: 'elderveld',
    administratie_id: 'a-elderveld',
    administratie_naam: 'Zonnestudio Elderveld B.V.',
    actief: true,
    bron: 'mens',
    gewijzigd_op: null,
    ...over,
  }
}

function installFetch(stores: unknown[], aanroepen: { url: string; method: string; body: unknown }[]) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      if (url === '/auth/administraties') return Promise.resolve(json({ administraties: ADMINISTRATIES }))
      if (url === '/instellingen/omzet/stores' && method === 'GET') return Promise.resolve(json({ stores, doel_pad: '/instellingen/boeken#stores' }))
      const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null
      aanroepen.push({ url, method, body })
      if (url === '/instellingen/omzet/stores' && method === 'POST') {
        return Promise.resolve(json(rij({ id: 's2', store_naam: String(body?.store), store_norm: String(body?.store).toLowerCase(), administratie_id: String(body?.administratie_id), administratie_naam: 'Sunshine Island B.V.' })))
      }
      if (url.startsWith('/instellingen/omzet/stores/') && method === 'PUT') {
        return Promise.resolve(json(rij({ ...(body ?? {}), administratie_naam: body?.administratie_id === 'a-sunshine' ? 'Sunshine Island B.V.' : 'Zonnestudio Elderveld B.V.' })))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

describe('StoresBlok (0151)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lege stand = actie: uitleg + formulier; koppelen stuurt POST {store, administratie_id}', async () => {
    const aanroepen: { url: string; method: string; body: unknown }[] = []
    installFetch([], aanroepen)
    render(
      <MemoryRouter>
        <StoresBlok />
      </MemoryRouter>,
    )
    expect(await screen.findByTestId('stores-blok-leeg')).toHaveTextContent('Nog geen store gekoppeld')
    await userEvent.type(screen.getByLabelText('Naam nieuwe store'), 'Sunshine Island')
    const combobox = screen.getByLabelText('Administratie voor deze store')
    await userEvent.type(combobox, 'Sunshine')
    await userEvent.click(await screen.findByRole('option', { name: /Sunshine Island B.V./ }))
    await userEvent.click(screen.getByRole('button', { name: '+ Store koppelen' }))
    await waitFor(() => expect(aanroepen).toHaveLength(1))
    expect(aanroepen[0]).toEqual({ url: '/instellingen/omzet/stores', method: 'POST', body: { store: 'Sunshine Island', administratie_id: 'a-sunshine' } })
    const rijen = await screen.findAllByTestId('store-rij')
    expect(rijen).toHaveLength(1)
    expect(within(rijen[0]).getByText('Sunshine Island')).toBeInTheDocument()
    expect(within(rijen[0]).getByText('Sunshine Island B.V.')).toBeInTheDocument()
  })

  it('⋯ → Ontkoppelen stuurt PUT {actief:false} en de chip wordt "ontkoppeld"; Andere administratie… stuurt PUT {administratie_id}', async () => {
    const aanroepen: { url: string; method: string; body: unknown }[] = []
    installFetch([rij()], aanroepen)
    render(
      <MemoryRouter>
        <StoresBlok />
      </MemoryRouter>,
    )
    const [r] = await screen.findAllByTestId('store-rij')
    expect(within(r).getByText('actief')).toBeInTheDocument()
    await userEvent.click(within(r).getByRole('button', { name: /Meer acties voor store Elderveld/ }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Ontkoppelen' }))
    await waitFor(() => expect(aanroepen).toHaveLength(1))
    expect(aanroepen[0]).toEqual({ url: '/instellingen/omzet/stores/s1', method: 'PUT', body: { actief: false } })
    expect(await within(r).findByText('ontkoppeld')).toBeInTheDocument()

    await userEvent.click(within(r).getByRole('button', { name: /Meer acties voor store Elderveld/ }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Andere administratie…' }))
    const dialoog = await screen.findByTestId('store-verhuis-dialoog')
    await userEvent.type(within(dialoog).getByLabelText('Nieuwe administratie'), 'Sunshine')
    await userEvent.click(await screen.findByRole('option', { name: /Sunshine Island B.V./ }))
    await userEvent.click(within(dialoog).getByRole('button', { name: 'Verhuizen' }))
    await waitFor(() => expect(aanroepen).toHaveLength(2))
    expect(aanroepen[1]).toEqual({ url: '/instellingen/omzet/stores/s1', method: 'PUT', body: { administratie_id: 'a-sunshine' } })
    expect(await within(r).findByText('Sunshine Island B.V.')).toBeInTheDocument()
  })
})
