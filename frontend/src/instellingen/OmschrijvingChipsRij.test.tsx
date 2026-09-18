/** Run A punt 3 — omschrijving-chips per administratie (Beheerder): laden, toevoegen/verwijderen, validatie, PUT. */
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { OmschrijvingChipsRij, valideerChips } from './OmschrijvingChipsRij'

const ADM = 'dddddddd-0000-0000-0000-00000000000d'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('valideerChips', () => {
  it('1–10, ≤ 30 tekens, uniek (hoofdletterongevoelig)', () => {
    expect(valideerChips(['opbouwen'])).toBeNull()
    expect(valideerChips([])).toMatch(/Minstens één/)
    expect(valideerChips(Array.from({ length: 11 }, (_, i) => `c${i}`))).toMatch(/tien/)
    expect(valideerChips(['a'.repeat(31)])).toMatch(/30 tekens/)
    expect(valideerChips(['Opbouwen', 'opbouwen'])).toMatch(/uniek/)
  })
})

describe('OmschrijvingChipsRij', () => {
  it('laadt de chips, verwijdert en voegt toe, en PUT de nieuwe lijst', async () => {
    const puts: unknown[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((invoer: RequestInfo | URL, init?: RequestInit) => {
        const url = String(invoer)
        if (url === `/uren/beheer/omschrijving-chips/${ADM}` && init?.method === 'PUT') {
          const body = JSON.parse(String(init.body)) as { chips: string[] }
          puts.push(body)
          return Promise.resolve(jsonResponse({ chips: body.chips }))
        }
        if (url === `/uren/beheer/omschrijving-chips/${ADM}`) {
          return Promise.resolve(jsonResponse({ chips: ['opbouwen', 'afbreken', 'ombouwen', 'transport', 'overig'] }))
        }
        return Promise.resolve(jsonResponse({ detail: url }, 500))
      }),
    )
    render(<OmschrijvingChipsRij administratieId={ADM} administratieNaam="Universal Steigerbouw B.V." />)
    await waitFor(() => expect(screen.getByText('opbouwen')).toBeInTheDocument())
    const gebruiker = userEvent.setup()
    await gebruiker.click(screen.getByRole('button', { name: 'Verwijder chip ombouwen' }))
    await gebruiker.type(screen.getByLabelText('Nieuwe chip voor Universal Steigerbouw B.V.'), 'steigers keuren')
    await gebruiker.click(screen.getByRole('button', { name: '+ Toevoegen' }))
    await gebruiker.click(screen.getByRole('button', { name: 'Opslaan' }))
    await waitFor(() => expect(puts).toEqual([{ chips: ['opbouwen', 'afbreken', 'transport', 'overig', 'steigers keuren'] }]))
  })
})
