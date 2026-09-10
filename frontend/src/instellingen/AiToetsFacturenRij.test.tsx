// Platformbrede schakelaar "AI-plausibiliteitstoets vóór automatische factuurboekingen" (blok B bundel 10-09):
// laadt GET /instellingen/boeken/ai-toets (default aan), uitzetten via bevestiging → PUT, fout blijft in de dialoog.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AiToetsFacturenRij } from './AiToetsFacturenRij'

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function installFetch(opties: { stand?: boolean; putStatus?: number; puts?: unknown[] } = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url === '/instellingen/boeken/ai-toets' && (!init?.method || init.method === 'GET')) return Promise.resolve(json({ ingeschakeld: opties.stand ?? true }))
      if (url === '/instellingen/boeken/ai-toets' && init?.method === 'PUT') {
        const body = JSON.parse(String(init.body)) as { ingeschakeld: boolean }
        opties.puts?.push(body)
        if (opties.putStatus) return Promise.resolve(json({ detail: 'Alleen een Beheerder mag dit wijzigen.' }, opties.putStatus))
        return Promise.resolve(json(body))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

describe('AiToetsFacturenRij (Instellingen › Boeken platformbreed, blok B 10-09)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('laadt de stand (default aan) en zet uit via bevestiging → PUT {ingeschakeld:false}', async () => {
    const puts: unknown[] = []
    installFetch({ puts })
    const gebruiker = userEvent.setup()
    render(<AiToetsFacturenRij />)
    const sw = await screen.findByRole('checkbox', { name: 'AI-plausibiliteitstoets vóór automatische factuurboekingen' })
    expect(sw).toBeChecked()
    expect(screen.getByText('aan — AI toetst vóór het boeken')).toBeInTheDocument()
    await gebruiker.click(sw)
    expect(screen.getByRole('dialog')).toHaveTextContent('alleen nog door de deterministische poorten')
    expect(puts).toHaveLength(0)
    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await waitFor(() => expect(puts).toEqual([{ ingeschakeld: false }]))
    await waitFor(() => expect(sw).not.toBeChecked())
    expect(screen.getByText('uit — alleen de deterministische controles')).toBeInTheDocument()
  })

  it('aanzetten vanuit uit; annuleren = geen PUT; 403 blijft in de dialoog', async () => {
    const puts: unknown[] = []
    installFetch({ stand: false, puts, putStatus: 403 })
    const gebruiker = userEvent.setup()
    render(<AiToetsFacturenRij />)
    const sw = await screen.findByRole('checkbox', { name: 'AI-plausibiliteitstoets vóór automatische factuurboekingen' })
    expect(sw).not.toBeChecked()
    await gebruiker.click(sw)
    await gebruiker.click(screen.getByRole('button', { name: 'Annuleren' }))
    expect(puts).toHaveLength(0)
    await gebruiker.click(sw)
    expect(screen.getByRole('dialog')).toHaveTextContent('Kost AI-tegoed per toets')
    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))
    expect(await screen.findByText('Alleen een Beheerder mag dit wijzigen.')).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(sw).not.toBeChecked()
  })

  it('laadfout = één hint-regel, geen switch (de noodstop-schakelaars ernaast blijven werken)', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(json({ detail: 'Instelling niet gevonden' }, 500))))
    render(<AiToetsFacturenRij />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Instelling niet gevonden')
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  })
})
