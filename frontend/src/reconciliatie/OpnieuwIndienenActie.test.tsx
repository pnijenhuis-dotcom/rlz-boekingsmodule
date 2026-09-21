import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { isBoekWachtrijGestrand, OpnieuwIndienenActie } from './OpnieuwIndienenActie'
import type { BevindingDto } from './reconciliatieApi'

function bevinding(overrides: Partial<BevindingDto> = {}): BevindingDto {
  return {
    id: 'bev-1',
    run_id: 'run-1',
    blok: 'automatisering',
    soort: 'let_op',
    administratie_id: 'adm-1',
    administratie_naam: 'Administratiekantoor Nijenhuis C.V.',
    vingerafdruk: 'vaf',
    tekst: 'LET-OP     automatisering boek_wachtrij: …',
    titel: "Boeking blijft hangen op 'Wordt geboekt…' · Administratiekantoor Nijenhuis C.V.",
    wat: 'Deze boeking is 46 minuten geleden ingediend …',
    doe: "Kies 'Opnieuw indienen' op deze rij …",
    details: [],
    sinds: '2026-09-21T12:46:00Z',
    nieuw: true,
    acceptatie: null,
    gezien: null,
    detail: { reden: 'boek_wachtrij_gestrand', afwijking_soort: 'wordt_geboekt_verouderd', document_id: 'doc-1', minuten: 46 },
    doel_pad: '/?administratie=adm-1&document=doc-1',
    ...overrides,
  } as BevindingDto
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('OpnieuwIndienenActie (BUG 21-09)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('herkent alleen de automatiserings-LET-OP boek_wachtrij_gestrand mét document en administratie', () => {
    expect(isBoekWachtrijGestrand(bevinding())).toBe(true)
    expect(isBoekWachtrijGestrand(bevinding({ detail: { reden: 'vangnet_scheduler' } }))).toBe(false)
    expect(isBoekWachtrijGestrand(bevinding({ blok: 'documenten' }))).toBe(false)
    expect(isBoekWachtrijGestrand(bevinding({ administratie_id: null }))).toBe(false)
  })

  it('één klik → POST op de documentroute; de uitkomst staat in de rij', async () => {
    const aanroepen: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        aanroepen.push(`${init?.method ?? 'GET'} ${url}`)
        return Promise.resolve(
          jsonResponse({ document_id: 'doc-1', status: 'wordt_geboekt', sleutel: 'boek-doc-1-0', trigger_uitkomst: 'mislukt', trigger_fout: 'PermissionError: 403 invoker' }),
        )
      }),
    )
    const gelukt = vi.fn()
    render(<OpnieuwIndienenActie bevinding={bevinding()} onGelukt={gelukt} />)
    await userEvent.click(screen.getByRole('button', { name: /Boeking opnieuw indienen/ }))
    await waitFor(() => expect(gelukt).toHaveBeenCalledTimes(1))
    expect(aanroepen).toContain('POST /administraties/adm-1/documenten/doc-1/boek-wachtrij/opnieuw-indienen')
    expect(gelukt.mock.calls[0][1]).toBe('warn')
    expect(screen.getByText(/start mislukt: PermissionError: 403 invoker/)).toBeInTheDocument()
  })

  it('409 (intussen geboekt/mislukt) blijft zichtbaar als fout, nooit stil', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(jsonResponse({ detail: "Opnieuw indienen kan alleen bij 'Wordt geboekt…' — dit document staat op geboekt" }, 409))))
    render(<OpnieuwIndienenActie bevinding={bevinding()} onGelukt={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: /Boeking opnieuw indienen/ }))
    await waitFor(() => expect(screen.getByText(/staat op geboekt/)).toBeInTheDocument())
  })
})
