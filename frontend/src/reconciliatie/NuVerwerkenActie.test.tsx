import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { isIntakePostvakVerschil, NuVerwerkenActie, nuVerwerkenMelding } from './NuVerwerkenActie'
import type { BevindingDto } from './reconciliatieApi'

function bevinding(overrides: Partial<BevindingDto> = {}): BevindingDto {
  return {
    id: 'bev-1',
    run_id: 'run-1',
    blok: 'intake',
    soort: 'afwijking',
    administratie_id: null,
    administratie_naam: null,
    vingerafdruk: 'vaf',
    tekst: 'AFWIJKING  soort=intake_postvak_verschil postvak facturen@kempengroep.nl …',
    titel: '2 bericht(en) in het postvak niet verwerkt · facturen@kempengroep.nl',
    wat: 'In facturen@kempengroep.nl staan sinds gisteren 2 bericht(en) die de module niet verwerkt heeft.',
    doe: "Klik 'Nu verwerken' …",
    details: [],
    sinds: '2026-09-23T04:30:00Z',
    nieuw: true,
    acceptatie: null,
    gezien: null,
    detail: {
      afwijking_soort: 'intake_postvak_verschil',
      kanaal: 'facturen_kempengroep',
      postvak_adres: 'facturen@kempengroep.nl',
      aantal: 2,
      berichten: [{ message_id: '<a@x>', afzender: 'lev@x.example', map: 'INBOX', gelezen: true }],
    },
    doel_pad: null,
    ...overrides,
  } as BevindingDto
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('NuVerwerkenActie (Peter 22-09 — postvak-bewaking)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('herkent alleen de postvak-afwijking mét kanaal', () => {
    expect(isIntakePostvakVerschil(bevinding())).toBe(true)
    expect(isIntakePostvakVerschil(bevinding({ blok: 'documenten' }))).toBe(false)
    expect(isIntakePostvakVerschil(bevinding({ detail: { afwijking_soort: 'intake_postvak_verschil' } }))).toBe(false)
  })

  it('één klik → POST op de kanaalroute; melding noemt het postvak', async () => {
    const aanroepen: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        aanroepen.push(`${init?.method ?? 'GET'} ${url}`)
        return Promise.resolve(
          jsonResponse({ kanaal: 'facturen_kempengroep', postvak_adres: 'facturen@kempengroep.nl', voertuig: 'cloud_run_job', job_resource: 'projects/p/locations/l/jobs/rlz-intake-imap-kempengroep' }, 202),
        )
      }),
    )
    const gelukt = vi.fn()
    render(<NuVerwerkenActie bevinding={bevinding()} onGelukt={gelukt} />)
    await userEvent.click(screen.getByRole('button', { name: /Postvak facturen@kempengroep.nl nu verwerken \(2 bericht\(en\)\)/ }))
    await waitFor(() => expect(gelukt).toHaveBeenCalledTimes(1))
    expect(aanroepen).toContain('POST /reconciliatie/intake/facturen_kempengroep/nu-verwerken')
    expect(gelukt.mock.calls[0][0]).toContain('facturen@kempengroep.nl')
    expect(screen.getByText(/intake gestart/)).toBeTruthy()
  })

  it('502 (job niet te starten) staat leesbaar op de rij, nooit stil', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(jsonResponse({ detail: 'Intake-job voor facturen_kempengroep starten mislukt: 403 run.jobs.run' }, 502))),
    )
    render(<NuVerwerkenActie bevinding={bevinding()} onGelukt={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: /nu verwerken/ }))
    await waitFor(() => expect(screen.getByText(/403 run.jobs.run/)).toBeTruthy())
  })

  it('melding onderscheidt cloud-job en dev-thread', () => {
    expect(nuVerwerkenMelding({ kanaal: 'facturen', postvak_adres: 'facturen@ak-nijenhuis.nl', voertuig: 'cloud_run_job', job_resource: 'x' })).toMatch(/Intake-job voor facturen@ak-nijenhuis.nl gestart/)
    expect(nuVerwerkenMelding({ kanaal: 'facturen', postvak_adres: null, voertuig: 'thread', job_resource: null })).toMatch(/Intake voor facturen gestart/)
  })
})
