import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { BevindingDto } from './reconciliatieApi'
import { isRlzDubbel, RlzDubbelBoekstukken } from './RlzDubbelBoekstukken'

// Blok 6 (08-09): "mogelijk dubbel in RLZ" — de rij toont beide boekstuknummers als "Open in Reeleezee"-hulp
// (geen document in de app, geen bekende RLZ-URL-vorm); klik kopieert het nummer. Alleen op blok `rlz_dubbel`
// met afwijking_soort `dubbel_in_rlz`.

const ADMIN = 'aaaaaaaa-0000-0000-0000-000000000001'

function bevinding(extra: Partial<BevindingDto> = {}): BevindingDto {
  return {
    id: 'bev-6',
    run_id: 'run-1',
    blok: 'rlz_dubbel',
    soort: 'afwijking',
    administratie_id: ADMIN,
    administratie_naam: 'Kempen Facilities B.V.',
    vingerafdruk: 'vaf6',
    tekst: 'AFWIJKING  … rlz_a=… rlz_b=… soort=dubbel_in_rlz [vaf:vaf6]: RLZ-04-00004037 + RLZ-04-00004038 (bedrag_datum)',
    titel: 'Mogelijk dubbel in RLZ — BOOT · 202632703 / 202632704',
    wat: 'In Reeleezee staan twee inkoopfacturen van BOOT …',
    doe: 'Open beide boekstuknummers in Reeleezee en beoordeel …',
    details: [],
    sinds: '2026-09-08T05:00:00Z',
    nieuw: true,
    acceptatie: null,
    gezien: null,
    detail: {
      bron: 'documenten',
      afwijking_soort: 'dubbel_in_rlz',
      boekstuk_a: 'RLZ-04-00004037',
      boekstuk_b: 'RLZ-04-00004038',
      leverancier_naam: 'BOOT organiserend ingenieursburo B.V.',
    },
    doel_pad: null,
    ...extra,
  }
}

describe('RlzDubbelBoekstukken', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('isRlzDubbel: alleen blok rlz_dubbel met soort dubbel_in_rlz', () => {
    expect(isRlzDubbel(bevinding())).toBe(true)
    expect(isRlzDubbel(bevinding({ blok: 'documenten' }))).toBe(false)
    expect(isRlzDubbel(bevinding({ detail: { afwijking_soort: 'ontbreekt_in_rlz' } }))).toBe(false)
  })

  it('toont beide boekstuknummers als linkbtn en kopieert op klik', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
    render(<RlzDubbelBoekstukken bevinding={bevinding()} />)
    const blok = screen.getByTestId('rlz-dubbel-boekstukken')
    expect(blok).toHaveTextContent('Open in Reeleezee: RLZ-04-00004037 · RLZ-04-00004038')
    const knop = screen.getByRole('button', { name: 'Boekstuknummer RLZ-04-00004038 kopiëren' })
    expect(knop.className).toBe('linkbtn')
    await userEvent.click(knop)
    expect(writeText).toHaveBeenCalledWith('RLZ-04-00004038')
  })

  it('zonder boekstuknummers (concept zonder nummer) blijft de rij eerlijk: verwijst naar de details', () => {
    render(<RlzDubbelBoekstukken bevinding={bevinding({ detail: { afwijking_soort: 'dubbel_in_rlz' } })} />)
    expect(screen.getByTestId('rlz-dubbel-boekstukken')).toHaveTextContent('boekstuknummers onbekend (zie details)')
    expect(screen.queryByRole('button')).toBeNull()
  })
})
