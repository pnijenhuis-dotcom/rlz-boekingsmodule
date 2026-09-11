// Blok 7 run 11-09 middag: kantoor-web staande-goedkeuringen-lijst — chip "nooit voorstellen" + opheffen, en de
// Beheerder-knop "Nooit voorstellen" per leverancier (administratiebreed).

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AccorderingInstellingen } from './AccorderingInstellingen'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

import type { VoorstelUitzonderingDto } from '../accordering/accorderingApi'

const UITZONDERING: VoorstelUitzonderingDto = {
  id: 'u1',
  accordeur_gebruiker_id: null,
  accordeur_naam: null,
  vendor_id: 'v-lusso',
  leverancier_naam: 'Lusso Chalets B.V.',
  soort: 'nooit',
  stil_tot: null,
  reden: 'chalets: elke factuur apart controleren',
  actief: true,
  aangemaakt_op: '2026-09-11T10:00:00Z',
  opgeheven_op: null,
}

function stub(state: { uitzonderingen: VoorstelUitzonderingDto[]; gezet: unknown[]; opgeheven: string[] }) {
  vi.stubGlobal(
    'fetch',
    vi.fn((invoer: RequestInfo | URL, init?: RequestInit) => {
      const pad = String(invoer).split('?')[0]
      if (pad === '/administraties/a1/accordering/instellingen')
        return Promise.resolve(jsonResponse({ ingeschakeld: true, lagen: [] }))
      if (pad === '/administraties/a1/accordering/kandidaten') return Promise.resolve(jsonResponse({ kandidaten: [] }))
      if (pad === '/administraties/a1/accordering/staande-regels')
        return Promise.resolve(
          jsonResponse({
            regels: [
              {
                id: 'r1',
                accordeur_gebruiker_id: 'g1',
                accordeur_naam: 'S. Bakker',
                vendor_id: 'v-essent',
                leverancier_naam: 'Essent',
                bedrag: '847.00',
                actief: true,
                aangemaakt_op: '2026-09-01T10:00:00Z',
                ingetrokken_op: null,
              },
            ],
            uitzonderingen: state.uitzonderingen,
          }),
        )
      if (pad === '/administraties/a1/crediteuren')
        return Promise.resolve(
          jsonResponse({
            crediteuren: [
              { id: 'v-lusso', naam: 'Lusso Chalets B.V.' },
              { id: 'v-boot', naam: 'BOOT Steigers' },
            ],
          }),
        )
      if (pad === '/administraties/a1/accordering/staande-regels/voorstel-uitzonderingen' && init?.method === 'POST') {
        const body = JSON.parse(String(init.body)) as { vendor_id: string }
        state.gezet.push(body)
        const nieuw = { ...UITZONDERING, id: `u-${body.vendor_id}`, vendor_id: body.vendor_id, leverancier_naam: null }
        state.uitzonderingen = [...state.uitzonderingen, nieuw]
        return Promise.resolve(jsonResponse(nieuw))
      }
      if (pad === '/administraties/a1/accordering/staande-regels/voorstel-uitzonderingen/u1/opheffen') {
        state.opgeheven.push('u1')
        state.uitzonderingen = state.uitzonderingen.filter((u) => u.id !== 'u1')
        return Promise.resolve(new Response(null, { status: 204 }))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

describe('AccorderingInstellingen — voorstel "nooit voorstellen"', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('toont de uitzondering als chip "nooit voorstellen" met opheffen', async () => {
    const state = { uitzonderingen: [UITZONDERING], gezet: [] as unknown[], opgeheven: [] as string[] }
    stub(state)
    render(<AccorderingInstellingen administraties={[{ id: 'a1', naam: 'Lusso' }]} />)
    await userEvent.click(screen.getByText('Lusso'))

    expect(await screen.findByText('Lusso Chalets B.V.')).toBeInTheDocument()
    expect(screen.getByText('nooit voorstellen')).toBeInTheDocument()
    expect(screen.getByText('alle accordeurs')).toBeInTheDocument()
    expect(screen.getByText('chalets: elke factuur apart controleren')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Opheffen' }))
    await waitFor(() => expect(state.opgeheven).toEqual(['u1']))
    await waitFor(() => expect(screen.queryByText('nooit voorstellen')).not.toBeInTheDocument())
  })

  it('Beheerder zet "nooit voorstellen" voor een gekozen leverancier (administratiebreed) en per staande regel', async () => {
    const state = { uitzonderingen: [] as VoorstelUitzonderingDto[], gezet: [] as { vendor_id: string }[], opgeheven: [] as string[] }
    stub(state)
    render(<AccorderingInstellingen administraties={[{ id: 'a1', naam: 'Lusso' }]} />)
    await userEvent.click(screen.getByText('Lusso'))
    await screen.findByText('Essent')

    // Knop is dicht zonder leverancier; kies er één + reden → POST met accordeur null.
    const knoppen = screen.getAllByRole('button', { name: 'Nooit voorstellen' })
    const formKnop = knoppen.find((k) => (k as HTMLButtonElement).disabled)
    expect(formKnop).toBeDefined()
    await userEvent.selectOptions(screen.getByLabelText('Leverancier voor nooit voorstellen'), 'v-lusso')
    await userEvent.type(screen.getByLabelText('Reden nooit voorstellen'), 'chalets')
    await userEvent.click(formKnop as HTMLButtonElement)
    await waitFor(() => expect(state.gezet).toEqual([{ vendor_id: 'v-lusso', reden: 'chalets', accordeur_gebruiker_id: null }]))

    // Per staande regel: linkknop "Nooit voorstellen" op de rij van Essent.
    const rijKnop = (await screen.findAllByRole('button', { name: 'Nooit voorstellen' })).find(
      (k) => k.classList.contains('linkbtn'),
    )
    expect(rijKnop).toBeDefined()
    await userEvent.click(rijKnop as HTMLButtonElement)
    await waitFor(() => expect(state.gezet.map((g) => g.vendor_id)).toEqual(['v-lusso', 'v-essent']))
  })
})
