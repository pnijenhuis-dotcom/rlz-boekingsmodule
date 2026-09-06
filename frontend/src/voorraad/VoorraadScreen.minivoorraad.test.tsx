// Voorraad-aansluiting × mini-voorraad (opdracht 06-09, F5): de virtuele groep "Speciale producten
// (mini-voorraad)" komt met `bron: 'mini_voorraad'` binnen — chip, géén telling-invoer, géén tolerantie
// (⑧: telverschillen worden nooit weggecorrigeerd; de stand is een afgeleide van het voorraadlog).
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../auth/AuthContext'
import { VoorraadScreen } from './VoorraadScreen'
import type { GroepAansluitingDto } from './voorraadApi'

const ADMIN = 'aaaaaaaa-0000-0000-0000-000000000001'

function groep(over: Partial<GroepAansluitingDto>): GroepAansluitingDto {
  return {
    artikelgroep_id: 'g1',
    naam: 'Koppelingen 48mm',
    eenheid: 'st',
    tolerantie_pct: '1.00',
    begin: '1240.000',
    inkoop: '3600.000',
    verkoop: '3410.000',
    theoretisch: '1430.000',
    systeemstand: '1428.000',
    telling_datum: '2026-08-28',
    verschil: '-2.000',
    verschil_pct: '-0.14',
    signaal: 'binnen_tolerantie',
    onzeker_pct: '0.00',
    regels_in: 4,
    regels_uit: 9,
    ...over,
  }
}

const AANSLUITING = {
  administratie_id: ADMIN,
  van: '2026-01-01',
  tot: '2026-09-06',
  groepen: [
    groep({}),
    groep({
      artikelgroep_id: 'mini',
      naam: 'Speciale producten (mini-voorraad)',
      bron: 'mini_voorraad',
      begin: '0',
      inkoop: '102.000',
      verkoop: '4.000',
      theoretisch: '98.000',
      systeemstand: null,
      telling_datum: null,
      verschil: null,
      verschil_pct: null,
      signaal: 'informatief',
      tolerantie_pct: '0',
    }),
  ],
  niet_genormaliseerd_in: 0,
  niet_genormaliseerd_uit: 0,
  regels_totaal: 13,
  bronnen: { inkoop: 'app', verkoop: 'RLZ', systeemstand: 'telling' },
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('VoorraadScreen — virtuele groep mini-voorraad', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('toont de chip "mini-voorraad" zonder telling- of tolerantie-knop; een gewone artikelgroep houdt "Telling…"', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        const pad = url.split('?')[0]
        if (url === '/auth/token/vernieuwen') return Promise.resolve(new Response(null, { status: 401 }))
        if (url === '/auth/administraties') return Promise.resolve(jsonResponse({ administraties: [{ id: ADMIN, naam: 'Universal Steigerbouw B.V.' }] }))
        if (pad === `/administraties/${ADMIN}/voorraad/aansluiting`) return Promise.resolve(jsonResponse(AANSLUITING))
        if (pad === `/administraties/${ADMIN}/voorraad/groepen`) return Promise.resolve(jsonResponse([{ id: 'g1', naam: 'Koppelingen 48mm', eenheid: 'st', tolerantie_pct: '1.00', actief: true }]))
        return Promise.resolve(jsonResponse({ rijen: [], totaal: 0, pagina: 1, per_pagina: 25 }))
      }),
    )
    render(
      <MemoryRouter initialEntries={[`/voorraad?administratie=${ADMIN}`]}>
        <AuthProvider>
          <VoorraadScreen />
        </AuthProvider>
      </MemoryRouter>,
    )
    const rij = await screen.findByTestId('aansluiting-rij-mini-voorraad')
    expect(rij).toHaveTextContent('Speciale producten (mini-voorraad)')
    expect(within(rij).getByText('mini-voorraad')).toBeInTheDocument()
    expect(rij).toHaveTextContent('standen uit het voorraadlog')
    expect(within(rij).queryByRole('button', { name: /Telling/ })).not.toBeInTheDocument()
    expect(within(rij).queryByRole('button', { name: /Tolerantie/ })).not.toBeInTheDocument()
    expect(within(rij).queryByRole('button', { name: /Speciale producten/ })).not.toBeInTheDocument()
    expect(rij).toHaveTextContent('informatief — niet muteerbaar')
    expect(within(rij).queryByText(/nog geen telling/)).not.toBeInTheDocument()
    const tabel = screen.getByTestId('aansluiting-tabel')
    const gewoon = within(tabel).getAllByRole('row').find((r) => within(r).queryByText('Koppelingen 48mm'))!
    expect(within(gewoon).getByRole('button', { name: 'Telling…' })).toBeInTheDocument()
  })
})
