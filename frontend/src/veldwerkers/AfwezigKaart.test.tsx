import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AfwezigKaart } from './AfwezigKaart'

/** Kaartje "Afwezig" (planning v3 slice 5, 18-09): lijst, toevoegen (van/tot/reden → POST mét scope-query), beëindigen =
 * tot vervroegen (nooit verwijderen), 403 = kaartje bestaat niet. */
const ADM = 'dddddddd-0000-0000-0000-00000000000d'
const GEB = 'bbbbbbbb-0000-0000-0000-00000000000b'

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

afterEach(() => vi.unstubAllGlobals())

describe('AfwezigKaart', () => {
  it('toont de aankomende perioden, voegt toe via POST /uren/kantoor/afwezigheid en beëindigt via /beeindigen', async () => {
    const lijst = [{ id: 'a1', gebruiker_id: GEB, van: '2099-01-05', tot: '2099-01-09', reden: 'verlof' }]
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (init?.method === 'POST' && url.includes('/afwezigheid/beeindigen')) return Promise.resolve(json({ ...lijst[0], tot: '2099-01-05' }))
      if (init?.method === 'POST' && url.includes('/afwezigheid')) return Promise.resolve(json({ id: 'a2', gebruiker_id: GEB, van: '2099-02-01', tot: '2099-02-02', reden: null }, 201))
      if (url.includes('/uren/kantoor/afwezigheid')) return Promise.resolve(json(lijst))
      return Promise.resolve(json({ detail: url }, 500))
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<AfwezigKaart administratieId={ADM} gebruikerId={GEB} naam="Milan K." />)
    expect(await screen.findByTestId('afwezig-a1')).toHaveTextContent('verlof')
    fireEvent.click(screen.getByText('+ Toevoegen'))
    fireEvent.change(screen.getByLabelText('Afwezig van'), { target: { value: '2099-02-01' } })
    fireEvent.change(screen.getByLabelText('Afwezig tot en met'), { target: { value: '2099-02-02' } })
    fireEvent.change(screen.getByLabelText('Reden afwezigheid'), { target: { value: 'cursus' } })
    fireEvent.click(screen.getByRole('button', { name: 'Opslaan' }))
    await waitFor(() => {
      const post = fetchMock.mock.calls.find((c) => (c[1] as RequestInit | undefined)?.method === 'POST')
      expect(post).toBeDefined()
      expect(String(post![0])).toBe(`/uren/kantoor/afwezigheid?administratie_id=${ADM}`)
      expect(JSON.parse(String((post![1] as RequestInit).body))).toEqual({ administratie_id: ADM, gebruiker_id: GEB, van: '2099-02-01', tot: '2099-02-02', reden: 'cursus' })
    })
    fireEvent.click(screen.getAllByRole('button', { name: 'Beëindigen' })[0])
    await waitFor(() => {
      const post = fetchMock.mock.calls.find((c) => String(c[0]).includes('/afwezigheid/beeindigen'))
      expect(post).toBeDefined()
      expect(JSON.parse(String((post![1] as RequestInit).body))).toMatchObject({ administratie_id: ADM, id: 'a1' })
    })
    // Geen DELETE ergens.
    expect(fetchMock.mock.calls.some((c) => (c[1] as RequestInit | undefined)?.method === 'DELETE')).toBe(false)
  })

  it('403 (geen recht/opt-in) = kaartje bestaat niet', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(json({ detail: 'geen recht' }, 403))))
    const { container } = render(<AfwezigKaart administratieId={ADM} gebruikerId={GEB} naam="Milan K." />)
    await waitFor(() => expect(container.querySelector('[data-testid="afwezig-kaart"]')).toBeNull())
  })
})
