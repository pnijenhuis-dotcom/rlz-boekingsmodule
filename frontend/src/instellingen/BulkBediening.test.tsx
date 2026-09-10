// Bulkbediening administraties — blok A bundel 10-09: actie "Autoboeken aan/uit" per administratie over de bestaande
// PUT (één bevestigingsdialoog); een 409 (Kempen-regel: doorbelasting) staat per rij zichtbaar als "overgeslagen: ‹detail›",
// de rest gaat gewoon door (niets stil).
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AdministratieInstellingenDto } from '../api/types'
import { BulkBediening } from './BulkBediening'
import { AUTOBOEKEN_LEREN_NIET_TOEGESTAAN_TEKST } from './instellingenApi'

function administratie(id: string, naam: string, over: Partial<AdministratieInstellingenDto> = {}): AdministratieInstellingenDto {
  return {
    id,
    naam,
    boeken_ingeschakeld: true,
    project_verplicht: false,
    ai_extractie_ingeschakeld: true,
    eigenaar_gebruiker_id: null,
    is_vastgoed: false,
    verkoop_autoboeken_ingeschakeld: false,
    uren_meerwerk_ingeschakeld: false,
    uren_dagmax_uren: '12',
    afdelingen_ingeschakeld: false,
    voorraad_ingeschakeld: false,
    mini_voorraad_ingeschakeld: false,
    ...over,
  }
}

const A = administratie('a1', 'ARVUM B.V.')
const KEMPEN = administratie('a3', 'Kempen Facilities B.V.', { doorbelasting_ingeschakeld: true, autoboeken_leren_toegestaan: false })

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('BulkBediening — Autoboeken (leren en boeken) aan/uit (blok A 10-09)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('"Autoboeken aan" → bevestiging → PUT per administratie; 409 per rij als "overgeslagen: ‹detail›", de rest gelukt', async () => {
    const puts: { url: string; body: unknown }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith('/autoboeken-leren-instelling') && init?.method === 'PUT') {
          puts.push({ url, body: JSON.parse(String(init.body)) })
          if (url.includes('/a3/')) return Promise.resolve(json({ detail: AUTOBOEKEN_LEREN_NIET_TOEGESTAAN_TEKST }, 409))
          return Promise.resolve(json({ ingeschakeld: true, toegestaan: true, reden_niet_toegestaan: null }))
        }
        return Promise.resolve(new Response(null, { status: 404 }))
      }),
    )
    const onWisSelectie = vi.fn()
    const onGereed = vi.fn()
    const gebruiker = userEvent.setup()
    render(<BulkBediening administraties={[A, KEMPEN]} geselecteerd={['a1', 'a3']} onWisSelectie={onWisSelectie} onGereed={onGereed} />)
    await gebruiker.click(screen.getByRole('button', { name: 'Autoboeken aan' }))
    const dialoog = screen.getByRole('dialog')
    expect(dialoog).toHaveTextContent('Bulkactie: Autoboeken (leren en boeken) AAN')
    expect(dialoog).toHaveTextContent('ARVUM B.V., Kempen Facilities B.V.')
    expect(puts).toHaveLength(0)
    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await waitFor(() => expect(puts).toHaveLength(2))
    expect(puts.map((p) => p.url)).toEqual(['/administraties/a1/autoboeken-leren-instelling', '/administraties/a3/autoboeken-leren-instelling'])
    expect(puts.every((p) => JSON.stringify(p.body) === JSON.stringify({ ingeschakeld: true }))).toBe(true)
    // Per-rij-uitkomst: de 409 letterlijk als "overgeslagen: …", ARVUM niet in de lijst.
    const melding = await screen.findByText(/Niet alles gelukt/)
    expect(melding).toHaveTextContent(`Kempen Facilities B.V.: overgeslagen: ${AUTOBOEKEN_LEREN_NIET_TOEGESTAAN_TEKST}`)
    expect(melding).not.toHaveTextContent('ARVUM')
    expect(onWisSelectie).toHaveBeenCalled()
    expect(onGereed).toHaveBeenCalled()
  })

  it('"Autoboeken uit" stuurt {ingeschakeld:false}', async () => {
    const puts: { url: string; body: unknown }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith('/autoboeken-leren-instelling') && init?.method === 'PUT') {
          puts.push({ url, body: JSON.parse(String(init.body)) })
          return Promise.resolve(json({ ingeschakeld: false, toegestaan: true, reden_niet_toegestaan: null }))
        }
        return Promise.resolve(new Response(null, { status: 404 }))
      }),
    )
    const gebruiker = userEvent.setup()
    render(<BulkBediening administraties={[A]} geselecteerd={['a1']} onWisSelectie={vi.fn()} onGereed={vi.fn()} />)
    await gebruiker.click(screen.getByRole('button', { name: 'Autoboeken uit' }))
    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await waitFor(() => expect(puts).toEqual([{ url: '/administraties/a1/autoboeken-leren-instelling', body: { ingeschakeld: false } }]))
    expect(screen.queryByText(/Niet alles gelukt/)).not.toBeInTheDocument()
  })
})
