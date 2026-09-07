// Verzamelbak: "factuur of offerte?" (blok B 04-09, ①; C9 07-09: chip-toggle in de tenaamstelling-kolom). De intake-AI mag twijfelen — dan komt het
// document in de bak mét reden `documentsoort_onduidelijk` en beslist de MENS bij het toewijzen.
// Nooit stil als factuur behandeld; zonder die reden verandert er niets aan de bestaande rij.

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { VERZAMELBAK_KOLOMMEN, VerzamelbakPaneel } from './VerzamelbakPaneel'

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

describe('Verzamelbak — documentsoort-keuze bij twijfel (chip-toggle, C9 07-09)', () => {
  it('toont de leesbare reden én de toggle; klik "Offerte" → toewijzen stuurt soort verplichting mee', async () => {
    const aanroepen: { url: string; body: unknown }[] = []
    installFetch({ aanroepen })
    render(<VerzamelbakPaneel administraties={ADMINISTRATIES} />)

    expect(await screen.findByText('factuur of offerte? — kies bij toewijzen')).toBeInTheDocument()
    const toggle = screen.getByRole('group', { name: 'Documentsoort voor confide-koningstraat.pdf' })
    // Default = Factuur (bestaand servergedrag); de mens zet 'm om.
    expect(within(toggle).getByRole('button', { name: 'Factuur' })).toHaveAttribute('aria-pressed', 'true')
    expect(within(toggle).getByRole('button', { name: 'Offerte' })).toHaveAttribute('aria-pressed', 'false')
    await userEvent.click(within(toggle).getByRole('button', { name: 'Offerte' }))
    expect(within(toggle).getByRole('button', { name: 'Offerte' })).toHaveAttribute('aria-pressed', 'true')
    expect(within(toggle).getByRole('button', { name: 'Factuur' })).toHaveAttribute('aria-pressed', 'false')
    await userEvent.click(screen.getByRole('button', { name: 'Toewijzen ✓' }))

    await waitFor(() => expect(aanroepen).toHaveLength(1))
    expect(aanroepen[0].body).toEqual({ administratie_id: ADMIN, soort: 'verplichting' })
  })

  it('zonder die reden is er geen soort-toggle en blijft de POST-body ongewijzigd', async () => {
    const aanroepen: { url: string; body: unknown }[] = []
    installFetch({ aanroepen, items: [item({ reden: 'geen_tenaamstelling', reden_label: 'geen tenaamstelling gelezen' })] })
    render(<VerzamelbakPaneel administraties={ADMINISTRATIES} />)

    await waitFor(() => expect(screen.getByText('confide-koningstraat.pdf')).toBeInTheDocument())
    expect(screen.queryByRole('group', { name: 'Documentsoort voor confide-koningstraat.pdf' })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Toewijzen ✓' }))
    await waitFor(() => expect(aanroepen).toHaveLength(1))
    expect(aanroepen[0].body).toEqual({ administratie_id: ADMIN })
  })

  it('de toggle biedt precies twee chips: Factuur en Offerte', async () => {
    installFetch()
    render(<VerzamelbakPaneel administraties={ADMINISTRATIES} />)

    const toggle = await screen.findByRole('group', { name: 'Documentsoort voor confide-koningstraat.pdf' })
    expect(within(toggle).getAllByRole('button').map((b) => b.textContent)).toEqual(['Factuur', 'Offerte'])
  })

  it('layout (C9): toggle in de tenaamstelling-kolom onder de twijfelchip, toewijzen-kolom alleen de picker, actiekolom alleen knoppen, kolommen uit één bron', async () => {
    installFetch()
    render(<VerzamelbakPaneel administraties={ADMINISTRATIES} />)

    const toggle = await screen.findByRole('group', { name: 'Documentsoort voor confide-koningstraat.pdf' })
    const cel = toggle.closest('td')!
    expect(cel.classList.contains('kol-tenaamstelling')).toBe(true)
    // Direct onder de twijfelchip: de chip komt vóór de toggle in dezelfde cel.
    const chip = within(cel).getByText('factuur of offerte? — kies bij toewijzen')
    expect(chip.compareDocumentPosition(toggle) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()

    const picker = screen.getByLabelText('Toewijzen aan voor confide-koningstraat.pdf')
    const pickerCel = picker.closest('td')!
    expect(pickerCel.classList.contains('kol-toewijzen')).toBe(true)
    expect(within(pickerCel).queryByRole('group')).not.toBeInTheDocument()
    expect(within(pickerCel).queryByText('Wat is dit?')).not.toBeInTheDocument()

    const actieCel = screen.getByRole('button', { name: 'Toewijzen ✓' }).closest('td')!
    expect(actieCel.classList.contains('kol-acties')).toBe(true)
    expect(within(actieCel).getAllByRole('button').map((b) => b.textContent)).toEqual(['Toewijzen ✓', 'Hoort niet bij ons'])

    // Eén bron voor de kolommen: colgroup + kopcellen volgen VERZAMELBAK_KOLOMMEN; tabel is fixed-layout.
    const tabel = actieCel.closest('table')!
    expect(tabel.classList.contains('verzamelbak-tabel')).toBe(true)
    expect(Array.from(tabel.querySelectorAll('colgroup col')).map((c) => c.className)).toEqual(
      VERZAMELBAK_KOLOMMEN.map((k) => `kol-${k.sleutel}`),
    )
    expect(tabel.querySelectorAll('tr:first-child th')).toHaveLength(VERZAMELBAK_KOLOMMEN.length)
    const somBreedtes = VERZAMELBAK_KOLOMMEN.reduce((som, k) => som + Number(k.breedte.replace('%', '')), 0)
    expect(somBreedtes).toBe(100)
  })
})
