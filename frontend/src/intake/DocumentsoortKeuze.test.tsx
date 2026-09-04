// Verzamelbak: "factuur of offerte?" (blok B 04-09, ①). De intake-AI mag twijfelen — dan komt het
// document in de bak mét reden `documentsoort_onduidelijk` en beslist de MENS bij het toewijzen.
// Nooit stil als factuur behandeld; zonder die reden verandert er niets aan de bestaande rij.

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { VerzamelbakPaneel } from './VerzamelbakPaneel'

const ADMIN = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOC = 'cccccccc-0000-0000-0000-000000000003'
const ADMINISTRATIES = [{ id: ADMIN, naam: 'Kempen Facilities B.V.' }]

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function item(overrides: Record<string, unknown> = {}) {
  return {
    document_id: DOC,
    bestandsnaam: 'confide-koningstraat.pdf',
    soort: 'inkoopfactuur',
    bron: 'email',
    afzender_hint: 'administratie@confide.nl',
    tenaamstelling: 'Kempen Facilities B.V.',
    suggestie_administratie_id: ADMIN,
    suggestie_bron: 'tenaamstelling',
    reden: 'documentsoort_onduidelijk',
    reden_label: 'factuur of offerte? — kies bij toewijzen',
    aangemaakt_op: '2026-09-04T09:00:00Z',
    splitsing_id: null,
    splitsing_voorstel: null,
    ...overrides,
  }
}

function installFetch(opties: { items?: unknown[]; aanroepen?: { url: string; body: unknown }[] } = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/bestand') && (!init || !init.method)) {
        return Promise.resolve(new Response(new Blob(['%PDF-1.4'], { type: 'application/pdf' }), { status: 200 }))
      }
      if (url.endsWith('/verzamelbak') && (!init || !init.method)) {
        return Promise.resolve(jsonResponse({ items: opties.items ?? [item()] }))
      }
      if (url.includes('/toewijzen') && init?.method === 'POST') {
        opties.aanroepen?.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
        return Promise.resolve(jsonResponse({ document_id: DOC, status: 'te_controleren' }))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Verzamelbak — documentsoort-keuze bij twijfel', () => {
  it('toont de leesbare reden én een soort-keuze; toewijzen stuurt de gekozen soort mee', async () => {
    const aanroepen: { url: string; body: unknown }[] = []
    installFetch({ aanroepen })
    render(<VerzamelbakPaneel administraties={ADMINISTRATIES} />)

    expect(await screen.findByText('factuur of offerte? — kies bij toewijzen')).toBeInTheDocument()
    const keuze = screen.getByLabelText('Documentsoort voor confide-koningstraat.pdf')
    // Default = inkoopfactuur (bestaand servergedrag), de mens kan het omzetten.
    expect(keuze).toHaveValue('inkoopfactuur')
    await userEvent.selectOptions(keuze, 'verplichting')
    await userEvent.click(screen.getByRole('button', { name: 'Toewijzen ✓' }))

    await waitFor(() => expect(aanroepen).toHaveLength(1))
    expect(aanroepen[0].body).toEqual({ administratie_id: ADMIN, soort: 'verplichting' })
  })

  it('zonder die reden is er geen soort-keuze en blijft de POST-body ongewijzigd', async () => {
    const aanroepen: { url: string; body: unknown }[] = []
    installFetch({ aanroepen, items: [item({ reden: 'geen_tenaamstelling', reden_label: 'geen tenaamstelling gelezen' })] })
    render(<VerzamelbakPaneel administraties={ADMINISTRATIES} />)

    await waitFor(() => expect(screen.getByText('confide-koningstraat.pdf')).toBeInTheDocument())
    expect(screen.queryByLabelText('Documentsoort voor confide-koningstraat.pdf')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Toewijzen ✓' }))
    await waitFor(() => expect(aanroepen).toHaveLength(1))
    expect(aanroepen[0].body).toEqual({ administratie_id: ADMIN })
  })

  it('de keuze biedt precies twee soorten: inkoopfactuur en verplichting', async () => {
    installFetch()
    render(<VerzamelbakPaneel administraties={ADMINISTRATIES} />)

    const keuze = await screen.findByLabelText('Documentsoort voor confide-koningstraat.pdf')
    const opties = within(keuze).getAllByRole('option').map((o) => (o as HTMLOptionElement).value)
    expect(opties).toEqual(['inkoopfactuur', 'verplichting'])
  })
})
