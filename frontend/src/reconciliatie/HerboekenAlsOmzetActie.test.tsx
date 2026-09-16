import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { HerboekenAlsOmzetActie, isOmzetInInkoopstroom } from './HerboekenAlsOmzetActie'
import type { BevindingDto } from './reconciliatieApi'

function bevinding(overrides: Partial<BevindingDto> = {}): BevindingDto {
  return {
    id: 'bev-1',
    run_id: 'run-1',
    blok: 'omzet',
    soort: 'afwijking',
    administratie_id: 'adm-1',
    administratie_naam: 'Van Boxtel Horeca Exploitatie B.V.',
    vingerafdruk: 'vaf',
    tekst: 'AFWIJKING …',
    titel: 'Omzet als inkoopfactuur geboekt · journaal.pdf · RLZ-04-00000686',
    wat: 'Kassarapport journaal.pdf is als inkoopfactuur RLZ-04-00000686 geboekt.',
    doe: 'Klik "Herboeken als omzet…".',
    details: [],
    sinds: '2026-09-16T05:30:00Z',
    nieuw: true,
    acceptatie: null,
    gezien: null,
    detail: { afwijking_soort: 'omzet_in_inkoopstroom', document_id: 'doc-1' },
    doel_pad: '/?administratie=adm-1&document=doc-1',
    ...overrides,
  } as BevindingDto
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('HerboekenAlsOmzetActie (Peter 16-09, Van Boxtel)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('herkent alleen de omzet-afwijking omzet_in_inkoopstroom', () => {
    expect(isOmzetInInkoopstroom(bevinding())).toBe(true)
    expect(isOmzetInInkoopstroom(bevinding({ detail: { afwijking_soort: 'half_geboekt' } }))).toBe(false)
    expect(isOmzetInInkoopstroom(bevinding({ blok: 'documenten' }))).toBe(false)
  })

  it('stuurt reden mee, toont de aangifte-blokkade en zet als Beheerder door mét bevestiging', async () => {
    const aanroepen: { pad: string; body: Record<string, unknown> }[] = []
    let eerste = true
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {}
        aanroepen.push({ pad: url, body })
        if (eerste) {
          eerste = false
          return Promise.resolve(
            jsonResponse(
              {
                detail: {
                  code: 'btw_mogelijk_aangegeven',
                  bericht: 'Btw mogelijk al aangegeven (boekdatum 2026-09-11 valt in de ingediende aangifte).',
                  soort: 'ingediende_periode',
                  boekdatum: '2026-09-11',
                  periode_start: '2026-07-01',
                  periode_eind: '2026-09-30',
                  backend: 'rlz',
                  bevestiging_mogelijk: true,
                  bevestiging_rol: 'beheerder',
                },
              },
              409,
            ),
          )
        }
        return Promise.resolve(jsonResponse({ document_id: 'doc-1', status: 'ontvangen', gestorneerd: true, doel_pad: '/?administratie=adm-1&document=doc-1' }))
      }),
    )
    const onGelukt = vi.fn()
    render(
      <MemoryRouter>
        <HerboekenAlsOmzetActie bevinding={bevinding()} onGelukt={onGelukt} isBeheerder />
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByRole('button', { name: /Herboeken als omzet/ }))
    await userEvent.type(screen.getByLabelText('Reden'), 'Kassarapport als inkoop geboekt')
    await userEvent.click(screen.getByRole('button', { name: 'Storneren en herclassificeren' }))
    await screen.findByTestId('btw-blokkade')
    expect(aanroepen[0].pad).toBe('/reconciliatie/bevindingen/bev-1/herboeken-als-omzet')
    expect(aanroepen[0].body).toEqual({ administratie_id: 'adm-1', reden: 'Kassarapport als inkoop geboekt' })
    await userEvent.click(screen.getByLabelText(/Ik bevestig/))
    await userEvent.type(screen.getByLabelText('Reden van de bevestiging'), 'Aangifte Q3 nog niet ingediend volgens Peter')
    await userEvent.click(screen.getByRole('button', { name: 'Toch herboeken (Beheerder)' }))
    await waitFor(() => expect(aanroepen).toHaveLength(2))
    expect(aanroepen[1].body).toMatchObject({ btw_niet_in_aangifte_bevestigd: true, bevestiging_reden: 'Aangifte Q3 nog niet ingediend volgens Peter' })
    await waitFor(() => expect(onGelukt).toHaveBeenCalled())
    expect(onGelukt.mock.calls[0][0]).toMatch(/gestorneerd/)
    expect(screen.getByRole('link', { name: /als omzet te boeken/ })).toHaveAttribute('href', '/?administratie=adm-1&document=doc-1')
  })
})
