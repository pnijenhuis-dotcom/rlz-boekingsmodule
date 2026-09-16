// Bulkbediening administraties — blok A bundel 10-09: actie "Autoboeken aan/uit" per administratie over de bestaande
// PUT (één bevestigingsdialoog); een 409 (Kempen-regel: doorbelasting) staat per rij zichtbaar als "overgeslagen: ‹detail›",
// de rest gaat gewoon door (niets stil).
import { render, screen, waitFor, within } from '@testing-library/react'
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

describe('BulkBediening — Toewijzen aan groep… (bulk-toewijzing 16-09)', () => {
  afterEach(() => vi.unstubAllGlobals())

  const KG = { id: 'g-kg', naam: 'Kempen groep', code: 'KEMPENGROEP', actief: true, aantal_administraties: 0 }

  it('groep kiezen → bevestiging → één PUT /groepen/{id}/administraties met de selectie; overgeslagen rijen zichtbaar', async () => {
    const puts: { url: string; body: unknown }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url === '/groepen' && (init?.method ?? 'GET') === 'GET') return Promise.resolve(json({ groepen: [KG] }))
        if (url === '/groepen/g-kg/administraties' && init?.method === 'PUT') {
          puts.push({ url, body: JSON.parse(String(init.body)) })
          return Promise.resolve(
            json({
              groep: { ...KG, aantal_administraties: 2 },
              toegevoegd: 1,
              verwijderd: 0,
              rijen: [
                { administratie_id: 'a1', naam: 'ARVUM B.V.', uitkomst: 'toegevoegd', detail: null },
                { administratie_id: 'a3', naam: 'Kempen Facilities B.V.', uitkomst: 'overgeslagen', detail: 'al lid van deze groep' },
              ],
            }),
          )
        }
        return Promise.resolve(new Response(null, { status: 404 }))
      }),
    )
    const onGereed = vi.fn()
    const gebruiker = userEvent.setup()
    render(<BulkBediening administraties={[A, KEMPEN]} geselecteerd={['a1', 'a3']} onWisSelectie={vi.fn()} onGereed={onGereed} />)
    await gebruiker.click(screen.getByRole('button', { name: 'Toewijzen aan groep…' }))
    const kiezer = screen.getByTestId('bulk-groep-dialoog')
    const select = await within(kiezer).findByLabelText('Groep voor geselecteerde administraties')
    await waitFor(() => expect(within(select).getByRole('option', { name: 'Kempen groep' })).toBeInTheDocument())
    await gebruiker.selectOptions(select, 'g-kg')
    await gebruiker.click(within(kiezer).getByRole('button', { name: 'Verder' }))
    const bevestiging = screen.getByRole('dialog')
    expect(bevestiging).toHaveTextContent('Bulkactie: Groep → Kempen groep')
    expect(puts).toHaveLength(0)
    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await waitFor(() => expect(puts).toHaveLength(1))
    expect(puts[0].body).toEqual({ toevoegen: ['a1', 'a3'], verwijderen: [] })
    const melding = await screen.findByText(/Niet alles gelukt/)
    expect(melding).toHaveTextContent('Kempen Facilities B.V.: overgeslagen: al lid van deze groep')
    expect(onGereed).toHaveBeenCalled()
  })

  it('"— geen groep —" haalt de selectie per administratie uit hun groep via de bestaande route', async () => {
    const puts: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url === '/groepen' && (init?.method ?? 'GET') === 'GET') return Promise.resolve(json({ groepen: [KG] }))
        if (url.endsWith('/groep') && init?.method === 'PUT') {
          puts.push(url)
          return Promise.resolve(json({ groep_id: null, groep_naam: null, groep_code: null }))
        }
        return Promise.resolve(new Response(null, { status: 404 }))
      }),
    )
    const gebruiker = userEvent.setup()
    render(<BulkBediening administraties={[A, KEMPEN]} geselecteerd={['a1', 'a3']} onWisSelectie={vi.fn()} onGereed={vi.fn()} />)
    await gebruiker.click(screen.getByRole('button', { name: 'Toewijzen aan groep…' }))
    await gebruiker.click(within(screen.getByTestId('bulk-groep-dialoog')).getByRole('button', { name: 'Verder' }))
    expect(screen.getByRole('dialog')).toHaveTextContent('Bulkactie: Uit hun groep halen')
    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await waitFor(() => expect(puts).toEqual(['/administraties/a1/groep', '/administraties/a3/groep']))
  })
})
