import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { VerzamelbakPaneel } from './VerzamelbakPaneel'

const ADMIN_A = 'aaaaaaaa-0000-0000-0000-000000000001'
const ADMIN_B = 'bbbbbbbb-0000-0000-0000-000000000002'
const DOC_ID = 'cccccccc-0000-0000-0000-000000000003'
const SPLITSING_ID = 'dddddddd-0000-0000-0000-000000000004'

const ADMINISTRATIES = [
  { id: ADMIN_A, naam: 'BLOW B.V.' },
  { id: ADMIN_B, naam: 'Kempen Groep B.V.' },
]

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function item(overrides: Record<string, unknown> = {}) {
  return {
    document_id: DOC_ID,
    bestandsnaam: 'factuur_energie.pdf',
    soort: 'inkoopfactuur',
    bron: 'email',
    afzender_hint: 'info@blow.nl',
    tenaamstelling: 'BLOW Holding',
    suggestie_administratie_id: ADMIN_A,
    suggestie_bron: 'afzender_regel_maar_onbekende_tenaamstelling',
    aangemaakt_op: '2026-08-07T09:00:00Z',
    splitsing_id: null,
    splitsing_voorstel: null,
    ...overrides,
  }
}

function installFetchMock(opties: {
  items?: unknown[]
  aanroepen?: { url: string; body: unknown }[]
}) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/verzamelbak') && (!init || !init.method)) {
        return Promise.resolve(jsonResponse({ items: opties.items ?? [item()] }))
      }
      if (init?.method === 'POST') {
        opties.aanroepen?.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
        return Promise.resolve(jsonResponse({ document_id: DOC_ID, status: 'te_controleren' }))
      }
      return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
    }),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('VerzamelbakPaneel', () => {
  it('toont herkomst, tenaamstelling en de AI-suggestie', async () => {
    installFetchMock({})
    render(<VerzamelbakPaneel administraties={ADMINISTRATIES} />)

    expect(await screen.findByText(/Niet toegewezen — handmatig koppelen \(1\)/)).toBeInTheDocument()
    expect(screen.getByText(/e-mail · info@blow.nl/)).toBeInTheDocument()
    expect(screen.getByText(/“BLOW Holding”/)).toBeInTheDocument()
    expect(screen.getByText('suggestie: BLOW B.V.')).toBeInTheDocument()
  })

  it('is onzichtbaar zolang de bak leeg is', async () => {
    installFetchMock({ items: [] })
    const { container } = render(<VerzamelbakPaneel administraties={ADMINISTRATIES} />)
    await waitFor(() => expect(container.firstChild).toBeNull())
  })

  it('toewijzen stuurt de gekozen administratie (suggestie voorgeselecteerd)', async () => {
    const aanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ aanroepen })
    render(<VerzamelbakPaneel administraties={ADMINISTRATIES} />)
    await screen.findByText(/handmatig koppelen/)

    await userEvent.click(screen.getByRole('button', { name: 'Toewijzen ✓' }))
    await waitFor(() => expect(aanroepen).toHaveLength(1))
    expect(aanroepen[0].url).toContain(`/verzamelbak/${DOC_ID}/toewijzen`)
    expect(aanroepen[0].body).toEqual({ administratie_id: ADMIN_A })
  })

  it('hoort niet bij ons vereist een reden', async () => {
    const aanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ aanroepen })
    render(<VerzamelbakPaneel administraties={ADMINISTRATIES} />)
    await screen.findByText(/handmatig koppelen/)

    await userEvent.click(screen.getByRole('button', { name: 'Hoort niet bij ons' }))
    const vastleggen = screen.getByRole('button', { name: 'Vastleggen ✓' })
    expect(vastleggen).toBeDisabled()

    await userEvent.type(screen.getByLabelText('Reden (verplicht)'), 'Ander kantoor')
    await userEvent.click(screen.getByRole('button', { name: 'Vastleggen ✓' }))
    await waitFor(() => expect(aanroepen).toHaveLength(1))
    expect(aanroepen[0].url).toContain('/hoort-niet-bij-ons')
    expect(aanroepen[0].body).toEqual({ reden: 'Ander kantoor' })
  })

  it('een splitsingsvoorstel toont de delen en bevestigt met de paginabereiken', async () => {
    const aanroepen: { url: string; body: unknown }[] = []
    installFetchMock({
      aanroepen,
      items: [
        item({
          bestandsnaam: 'batchscan.pdf',
          splitsing_id: SPLITSING_ID,
          splitsing_voorstel: [
            { start_pagina: 1, eind_pagina: 2, tenaamstelling: 'BLOW B.V.', leverancier: null, factuurnummer: null, zekerheid: 0.95 },
            { start_pagina: 3, eind_pagina: 3, tenaamstelling: 'Kempen Groep B.V.', leverancier: null, factuurnummer: null, zekerheid: 0.9 },
          ],
        }),
      ],
    })
    render(<VerzamelbakPaneel administraties={ADMINISTRATIES} />)
    await screen.findByText(/Splitsingsvoorstel: 2 facturen/)

    await userEvent.click(screen.getByRole('button', { name: 'Splitsing bevestigen ✓' }))
    await waitFor(() => expect(aanroepen).toHaveLength(1))
    expect(aanroepen[0].url).toContain(`/intake/splitsingen/${SPLITSING_ID}/bevestigen`)
    expect(aanroepen[0].body).toEqual({
      delen: [
        { start_pagina: 1, eind_pagina: 2, tenaamstelling: 'BLOW B.V.' },
        { start_pagina: 3, eind_pagina: 3, tenaamstelling: 'Kempen Groep B.V.' },
      ],
    })
  })
})
