/** Run B punt 4 — Instellingen › administratie › Uren & materiaal: herinneringstijd laden (chip "standaard"), wijzigen = PUT
 * { tijd }, "terug naar standaard" = PUT { tijd: null }; validatie 06:00–18:59; 409 zonder uren-opt-in leesbaar. */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { HerinneringTijdRij, valideerHerinneringTijd } from './HerinneringTijdRij'

const ADM = 'dddddddd-0000-0000-0000-00000000000d'
function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}
afterEach(() => vi.unstubAllGlobals())

describe('valideerHerinneringTijd', () => {
  it('UU:MM tussen 06:00 en 18:59 (contract 5B)', () => {
    expect(valideerHerinneringTijd('16:30')).toBeNull()
    expect(valideerHerinneringTijd('18:59')).toBeNull()
    expect(valideerHerinneringTijd('4:30')).toMatch(/UU:MM/)
    expect(valideerHerinneringTijd('03:00')).toMatch(/06:00/)
    expect(valideerHerinneringTijd('19:00')).toMatch(/18:59/)
  })
})

describe('HerinneringTijdRij', () => {
  it('laadt de tijd (standaard-chip), wijzigt via PUT en gaat terug naar standaard met null', async () => {
    const puts: unknown[] = []
    let stand = { tijd: '16:30', standaard: true }
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (String(url) === `/uren/beheer/herinnering-tijd/${ADM}` && init?.method === 'PUT') {
          const body = JSON.parse(String(init.body)) as { tijd: string | null }
          puts.push(body)
          stand = body.tijd ? { tijd: body.tijd, standaard: false } : { tijd: '16:30', standaard: true }
          return Promise.resolve(json(stand))
        }
        if (String(url) === `/uren/beheer/herinnering-tijd/${ADM}`) return Promise.resolve(json(stand))
        return Promise.resolve(json({ detail: 'onverwacht' }, 500))
      }),
    )
    render(<HerinneringTijdRij administratieId={ADM} administratieNaam="Universal Steigerbouw B.V." />)
    const veld = (await screen.findByLabelText('Herinneringstijd voor Universal Steigerbouw B.V.')) as HTMLInputElement
    await waitFor(() => expect(veld.value).toBe('16:30'))
    expect(screen.getByText('standaard')).toBeInTheDocument()
    await userEvent.clear(veld)
    await userEvent.type(veld, '17:00')
    await userEvent.click(screen.getByRole('button', { name: 'Opslaan' }))
    await waitFor(() => expect(puts).toEqual([{ tijd: '17:00' }]))
    await waitFor(() => expect(screen.getByRole('button', { name: 'terug naar standaard' })).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: 'terug naar standaard' }))
    await waitFor(() => expect(puts).toEqual([{ tijd: '17:00' }, { tijd: null }]))
    await waitFor(() => expect(screen.getByText('standaard')).toBeInTheDocument())
  })
  it('409 zonder uren-opt-in = leesbare fout, stand blijft', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((_url: string, init?: RequestInit) => {
        if (init?.method === 'PUT') return Promise.resolve(json({ detail: 'Uren & meerwerk staat uit voor deze administratie.' }, 409))
        return Promise.resolve(json({ tijd: '16:30', standaard: true }))
      }),
    )
    render(<HerinneringTijdRij administratieId={ADM} administratieNaam="Test B.V." />)
    const veld = (await screen.findByLabelText('Herinneringstijd voor Test B.V.')) as HTMLInputElement
    await waitFor(() => expect(veld.value).toBe('16:30'))
    await userEvent.clear(veld)
    await userEvent.type(veld, '17:00')
    await userEvent.click(screen.getByRole('button', { name: 'Opslaan' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Niet mogelijk: Uren & meerwerk staat uit voor deze administratie.')
  })
})
