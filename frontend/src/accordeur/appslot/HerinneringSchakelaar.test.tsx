/** Run B punt 4 — ⚙ Toegang › "Herinnering einde werkdag": stand uit GET, tijd van de administratie zichtbaar, schakelen = PUT. */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { HerinneringSchakelaar } from './HerinneringSchakelaar'

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

afterEach(() => vi.unstubAllGlobals())

describe('HerinneringSchakelaar', () => {
  it('toont de administratie-tijd en schakelt uit via PUT { uit: true }', async () => {
    const puts: unknown[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (String(url) === '/uren/zzp/herinnering' && init?.method === 'PUT') {
          puts.push(JSON.parse(String(init.body)))
          return Promise.resolve(json({ uit: true, tijd: '17:00' }))
        }
        if (String(url) === '/uren/zzp/herinnering') return Promise.resolve(json({ uit: false, tijd: '17:00' }))
        return Promise.resolve(json({ detail: 'onverwacht' }, 500))
      }),
    )
    render(<HerinneringSchakelaar />)
    const sw = await screen.findByRole('switch', { name: 'Herinnering einde werkdag' })
    await waitFor(() => expect(sw).toHaveAttribute('aria-checked', 'true'))
    expect(screen.getByTestId('acc-herinnering-rij')).toHaveTextContent('Om 17:00 een melding')
    await userEvent.click(sw)
    await waitFor(() => expect(sw).toHaveAttribute('aria-checked', 'false'))
    expect(puts).toEqual([{ uit: true }])
  })
  it('mislukte PUT = leesbare fout, stand blijft', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((_url: string, init?: RequestInit) => {
        if (init?.method === 'PUT') return Promise.resolve(json({ detail: 'Geen scope op een administratie mét uren.' }, 403))
        return Promise.resolve(json({ uit: false, tijd: '16:30' }))
      }),
    )
    render(<HerinneringSchakelaar />)
    const sw = await screen.findByRole('switch', { name: 'Herinnering einde werkdag' })
    await waitFor(() => expect(sw).toHaveAttribute('aria-checked', 'true'))
    await userEvent.click(sw)
    expect(await screen.findByRole('alert')).toHaveTextContent('Geen scope op een administratie mét uren.')
    expect(sw).toHaveAttribute('aria-checked', 'true')
  })
})
