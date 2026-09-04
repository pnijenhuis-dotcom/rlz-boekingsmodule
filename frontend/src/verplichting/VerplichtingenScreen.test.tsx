import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { VerplichtingenScreen } from './VerplichtingenScreen'
import type { VerplichtingKantoorLijstDto, VerplichtingKantoorRijDto } from './verplichtingApi'

// Inzicht › Verplichtingen (blok B 04-09, mockup offerte-matching blok 3 + ⑦): kantoorbreed
// lijstpatroon — server sorteert/pagineert, client filtert via facetten en formatteert alleen.
// Eén primaire handeling per rij ("Open verplichting") + ⋯-menu ("Laten vervallen…", reden verplicht).

const ADMIN_A = 'aaaaaaaa-0000-0000-0000-000000000001'
const ADMIN_B = 'bbbbbbbb-0000-0000-0000-000000000002'

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const CONFIDE: VerplichtingKantoorRijDto = {
  document_id: 'dddd0000-0000-0000-0000-000000000011',
  administratie_id: ADMIN_A,
  administratie_naam: 'Kempen Facilities B.V.',
  offertenummer: '26140-OFF-01',
  soort_label: 'offerte',
  leverancier_naam: 'Confide Bouw B.V.',
  project_naam: 'Koningstraat',
  totaal_excl: '48500.00',
  verbruikt_excl: '27150.00',
  percentage: 56,
  over_excl: null,
  open_facturen_aantal: 1,
  open_facturen_excl: '12400.00',
  goedgekeurd_op: '2026-09-04T10:00:00Z',
  goedgekeurd_door_naam: 'J. de Groot',
  geldig_tot: '2026-12-31',
  status: 'lopend',
  facturen: [
    {
      document_id: 'ffff0000-0000-0000-0000-000000000021',
      referentie: 'F-2026-118',
      factuurdatum: '2026-09-02',
      bedrag_excl: '12400.00',
      status: 'geboekt',
      verrekend: true,
    },
  ],
}

const GNM: VerplichtingKantoorRijDto = {
  document_id: 'eeee0000-0000-0000-0000-000000000012',
  administratie_id: ADMIN_B,
  administratie_naam: 'Universal Steigerbouw B.V.',
  offertenummer: '26133-OFF-02',
  soort_label: 'opdrachtbevestiging',
  leverancier_naam: 'GNM B.V.',
  project_naam: 'Dak Oirschot',
  totaal_excl: '18500.00',
  verbruikt_excl: '19870.00',
  percentage: 107,
  over_excl: '1370.00',
  goedgekeurd_op: '2026-08-28T10:00:00Z',
  goedgekeurd_door_naam: 'P. Nijenhuis',
  geldig_tot: null,
  status: 'overschreden',
  facturen: [],
}

function lijst(overrides: Partial<VerplichtingKantoorLijstDto> = {}): VerplichtingKantoorLijstDto {
  return {
    rijen: [GNM, CONFIDE],
    totaal: 2,
    pagina: 1,
    per_pagina: 25,
    administraties_in_selectie: 2,
    tellers: { lopend: 6, overschreden: 1, vervallen: 3 },
    facetten: {
      status: { lopend: 6, overschreden: 1, vervallen: 3, alle: 10 },
      administraties: [
        { administratie_id: ADMIN_A, naam: 'Kempen Facilities B.V.', aantal: 1 },
        { administratie_id: ADMIN_B, naam: 'Universal Steigerbouw B.V.', aantal: 1 },
      ],
    },
    ...overrides,
  }
}

interface Opties {
  lijstBody?: (url: string) => VerplichtingKantoorLijstDto
  urls?: string[]
  vervalAanroepen?: { url: string; body: unknown }[]
}

function installFetch(opties: Opties = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.startsWith('/verplichtingen?')) {
        opties.urls?.push(url)
        return Promise.resolve(json(opties.lijstBody ? opties.lijstBody(url) : lijst()))
      }
      if (url.endsWith('/vervallen') && init?.method === 'POST') {
        opties.vervalAanroepen?.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
        return Promise.resolve(json({ document_id: 'x' }))
      }
      if (url === '/auth/administraties') {
        return Promise.resolve(
          json({
            administraties: [
              { id: ADMIN_A, naam: 'Kempen Facilities B.V.' },
              { id: ADMIN_B, naam: 'Universal Steigerbouw B.V.' },
            ],
          }),
        )
      }
      return Promise.resolve(json({ detail: `onverwacht pad ${url}` }, 500))
    }),
  )
}

function toonScherm(pad = '/verplichtingen') {
  return render(
    <MemoryRouter initialEntries={[pad]}>
      <VerplichtingenScreen />
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('VerplichtingenScreen — Inzicht kantoorbreed', () => {
  it('toont teller-chips, de verbruiksstand per rij en de voet met tellingen over administraties', async () => {
    installFetch()
    toonScherm()

    expect(await screen.findByTestId('chip-lopend')).toHaveTextContent('6 lopend')
    expect(screen.getByTestId('chip-overschreden')).toHaveTextContent('1 overschreden')

    const rijen = screen.getAllByTestId('verplichting-rij')
    expect(rijen).toHaveLength(2)
    // Server-sortering wordt niet overruled: overschreden staat bovenaan zoals geleverd.
    expect(rijen[0]).toHaveTextContent('26133-OFF-02')
    expect(rijen[0]).toHaveTextContent('€ 1.370,00 over')
    expect(rijen[1]).toHaveTextContent('binnen')
    expect(within(rijen[1]).getByTestId(`balk-${CONFIDE.document_id}`)).toHaveTextContent('56%')
    // 0.1 (04-09): voorwaarschuwing open facturen op de Inzicht-rij — informatief, buiten de balk.
    expect(within(rijen[1]).getByTestId(`balk-${CONFIDE.document_id}-open`)).toHaveTextContent('1 open factuur op deze offerte (€ 12.400,00)')
    expect(within(rijen[0]).queryByTestId(/-open$/)).toBeNull()
    expect(screen.getByTestId('verplichtingen-voet')).toHaveTextContent('2 verplichtingen over 2 administraties')
  })

  it('stuurt het status-facet en de zoekterm naar de server (filter, nooit poort)', async () => {
    const urls: string[] = []
    installFetch({ urls })
    toonScherm()

    await screen.findByTestId('chip-lopend')
    // Facet-select draagt de tellingen per stand.
    expect(screen.getByRole('option', { name: 'Status: vervallen (3)' })).toBeInTheDocument()

    await userEvent.selectOptions(screen.getByLabelText('Status'), 'overschreden')
    await waitFor(() => expect(urls.some((u) => u.includes('status=overschreden'))).toBe(true))

    await userEvent.type(screen.getByLabelText('Zoek offerte of leverancier'), 'GNM')
    await waitFor(() => expect(urls.some((u) => u.includes('q=GNM'))).toBe(true))
    // Default zonder param = lopend.
    expect(urls[0]).toContain('status=lopend')
  })

  it('leest een administratie-deeplink en pagineert server-side', async () => {
    const urls: string[] = []
    installFetch({ urls, lijstBody: () => lijst({ totaal: 40 }) })
    toonScherm(`/verplichtingen?administratie_id=${ADMIN_B}`)

    await screen.findByTestId('chip-lopend')
    expect(urls[0]).toContain(`administratie_id=${ADMIN_B}`)

    await userEvent.click(screen.getByLabelText('Volgende pagina'))
    await waitFor(() => expect(urls.some((u) => u.includes('pagina=2'))).toBe(true))
    expect(screen.getByTestId('verplichtingen-voet')).toHaveTextContent('van 2')
  })

  it('klapt de gekoppelde facturen per rij uit', async () => {
    installFetch()
    toonScherm()

    await screen.findByTestId('chip-lopend')
    expect(screen.queryByTestId('verplichting-facturen')).not.toBeInTheDocument()

    await userEvent.click(screen.getByLabelText('Gekoppelde facturen van 26140-OFF-01 Confide Bouw B.V.'))
    const uitklap = await screen.findByTestId('verplichting-facturen')
    expect(uitklap).toHaveTextContent('F-2026-118')
    expect(uitklap).toHaveTextContent('verrekend in de stand')
  })

  it('laat een rij vervallen via het ⋯-menu met een verplichte reden', async () => {
    const vervalAanroepen: { url: string; body: unknown }[] = []
    installFetch({ vervalAanroepen })
    toonScherm()

    await screen.findByTestId('chip-lopend')
    await userEvent.click(screen.getByLabelText('Meer acties 26133-OFF-02 GNM B.V.'))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Laten vervallen…' }))

    const dialoog = await screen.findByTestId('verval-dialoog')
    expect(within(dialoog).getByRole('button', { name: 'Laten vervallen' })).toBeDisabled()
    await userEvent.type(within(dialoog).getByLabelText('Reden'), 'werk is geannuleerd')
    await userEvent.click(within(dialoog).getByRole('button', { name: 'Laten vervallen' }))

    await waitFor(() => expect(vervalAanroepen).toHaveLength(1))
    expect(vervalAanroepen[0].url).toContain(`/administraties/${ADMIN_B}/verplichtingen/documenten/${GNM.document_id}/vervallen`)
    expect(vervalAanroepen[0].body).toEqual({ reden: 'werk is geannuleerd' })
  })

  it('lege stand is een actie, geen doodlopende melding', async () => {
    installFetch({
      lijstBody: () =>
        lijst({ rijen: [], totaal: 0, administraties_in_selectie: 0, tellers: { lopend: 0, overschreden: 0, vervallen: 0 } }),
    })
    toonScherm()

    expect(await screen.findByTestId('verplichtingen-leeg')).toHaveTextContent(
      /Zet een offerte, prijsopgave of opdrachtbevestiging in de werkvoorraad/i,
    )
  })
})
