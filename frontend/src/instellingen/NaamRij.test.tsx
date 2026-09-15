import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AdministratieInstellingenDto } from '../api/types'
import { NaamRij, bronAfwijkend, bronLabel } from './NaamRij'

/** Veld "Naam" op tab Algemeen (Peter 15-09, migratie 0144): inline bewerken = PUT /administraties/{id}/naam (409 =
 * reden van de server), herkomst-chip "volgt Odoo/Reeleezee" of "handmatig", afwijkende bronnaam = chip + "Naam
 * overnemen" (POST …/naam-overnemen). */

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function administratie(overrides: Partial<AdministratieInstellingenDto> = {}): AdministratieInstellingenDto {
  return {
    id: ADMINISTRATIE_ID,
    naam: 'Camping Nieuwenhoven',
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
    boekhoud_backend: 'odoo',
    naam_bron: 'mens',
    ...overrides,
  }
}

function installFetchMock(aanroepen: { url: string; method: string; body: unknown }[], opties: { putStatus?: number } = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      aanroepen.push({ url, method, body })
      if (url.endsWith('/naam') && method === 'PUT') {
        if (opties.putStatus === 409) {
          return Promise.resolve(jsonResponse({ detail: 'De naam "Kempen Facilities" is al in gebruik bij administratie "Kempen Facilities".' }, 409))
        }
        return Promise.resolve(
          jsonResponse({ id: ADMINISTRATIE_ID, naam: body.naam, naam_bron: 'mens', bron_naam: null, bron_naam_gezien_op: null, naam_gevolgd_op: null, bron_afwijkend: false }),
        )
      }
      if (url.endsWith('/naam-overnemen') && method === 'POST') {
        return Promise.resolve(
          jsonResponse({ id: ADMINISTRATIE_ID, naam: 'Strandpark Zilverduynen', naam_bron: 'mens', bron_naam: 'Strandpark Zilverduynen', bron_naam_gezien_op: null, naam_gevolgd_op: null, bron_afwijkend: false }),
        )
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('bronLabel / bronAfwijkend', () => {
  it('leest het label uit naam_bron en valt terug op de backend', () => {
    expect(bronLabel({ naam_bron: 'odoo', boekhoud_backend: 'rlz' })).toBe('Odoo')
    expect(bronLabel({ naam_bron: 'mens', boekhoud_backend: 'odoo' })).toBe('Odoo')
    expect(bronLabel({ naam_bron: 'mens', boekhoud_backend: 'rlz' })).toBe('Reeleezee')
  })
  it('afwijkend = bronnaam gevuld en (hoofdletter-/witruimte-ongevoelig) anders dan de naam', () => {
    expect(bronAfwijkend({ naam: 'Camping Nieuwenhoven', bron_naam: 'Strandpark Zilverduynen' })).toBe(true)
    expect(bronAfwijkend({ naam: 'Camping Nieuwenhoven', bron_naam: ' camping  nieuwenhoven ' })).toBe(false)
    expect(bronAfwijkend({ naam: 'Camping Nieuwenhoven', bron_naam: null })).toBe(false)
  })
})

describe('NaamRij', () => {
  it('toont naam + chip "volgt Odoo" en bewerkt inline via PUT', async () => {
    const aanroepen: { url: string; method: string; body: unknown }[] = []
    installFetchMock(aanroepen)
    const onGewijzigd = vi.fn()
    render(<NaamRij administratie={administratie({ naam_bron: 'odoo', naam_gevolgd_op: '2026-09-15T05:00:00Z' })} onGewijzigd={onGewijzigd} />)
    expect(screen.getByTestId('administratie-naam')).toHaveTextContent('Camping Nieuwenhoven')
    expect(screen.getByText('volgt Odoo')).toBeInTheDocument()
    expect(screen.queryByTestId('bronnaam-afwijkend')).toBeNull()

    await userEvent.click(screen.getByRole('button', { name: /Naam bewerken/ }))
    const veld = screen.getByLabelText('Naam van Camping Nieuwenhoven')
    await userEvent.clear(veld)
    await userEvent.type(veld, 'Strandpark  Zilverduynen{Enter}')
    await waitFor(() => expect(onGewijzigd).toHaveBeenCalled())
    expect(aanroepen).toEqual([{ url: `/administraties/${ADMINISTRATIE_ID}/naam`, method: 'PUT', body: { naam: 'Strandpark Zilverduynen' } }])
    expect(screen.getByText('opgeslagen')).toBeInTheDocument()
  })

  it('toont de 409-reden van de server letterlijk en blijft in bewerkmodus', async () => {
    const aanroepen: { url: string; method: string; body: unknown }[] = []
    installFetchMock(aanroepen, { putStatus: 409 })
    render(<NaamRij administratie={administratie()} />)
    await userEvent.click(screen.getByRole('button', { name: /Naam bewerken/ }))
    const veld = screen.getByLabelText('Naam van Camping Nieuwenhoven')
    await userEvent.clear(veld)
    await userEvent.type(veld, 'Kempen Facilities')
    await userEvent.click(screen.getByRole('button', { name: 'Opslaan' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('al in gebruik bij administratie "Kempen Facilities"')
    expect(screen.getByLabelText('Naam van Camping Nieuwenhoven')).toBeInTheDocument()
  })

  it('handmatige naam mét afwijkende bronnaam: chip + "Naam overnemen" via POST', async () => {
    const aanroepen: { url: string; method: string; body: unknown }[] = []
    installFetchMock(aanroepen)
    const onGewijzigd = vi.fn()
    render(
      <NaamRij
        administratie={administratie({ naam_bron: 'mens', bron_naam: 'Strandpark Zilverduynen', bron_naam_gezien_op: '2026-09-15T05:00:00Z' })}
        onGewijzigd={onGewijzigd}
      />,
    )
    expect(screen.getByText('handmatig')).toBeInTheDocument()
    expect(screen.getByTestId('bronnaam-afwijkend')).toHaveTextContent('in Odoo heet deze administratie nu “Strandpark Zilverduynen”')
    await userEvent.click(screen.getByRole('button', { name: 'Naam overnemen' }))
    await waitFor(() => expect(onGewijzigd).toHaveBeenCalled())
    expect(aanroepen).toEqual([{ url: `/administraties/${ADMINISTRATIE_ID}/naam-overnemen`, method: 'POST', body: undefined }])
  })

  it('gearchiveerd: geen Bewerken, geen overnemen', () => {
    installFetchMock([])
    render(<NaamRij administratie={administratie({ gearchiveerd_op: '2026-09-01T00:00:00Z', bron_naam: 'Anders' })} />)
    expect(screen.queryByRole('button', { name: /Naam bewerken/ })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Naam overnemen' })).toBeNull()
    expect(screen.getByTestId('bronnaam-afwijkend')).toBeInTheDocument()
  })
})
