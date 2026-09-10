import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { BevindingDto } from './reconciliatieApi'
import { isRlzDubbel, RlzDubbelBoekstukken, rlzDubbelBoekstukken } from './RlzDubbelBoekstukken'

// Blok 6 (08-09) / blok 1 vervolgrun 10-09: "dubbel in RLZ" — de rij toont ALLE boekstuknummers van het cluster als
// "Open in Reeleezee"-hulp (geen document in de app, geen bekende RLZ-URL-vorm); klik kopieert het nummer. Oude
// paar-bevindingen (alleen boekstuk_a/boekstuk_b) blijven werken. Alleen op blok `rlz_dubbel` met soort `dubbel_in_rlz`.

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
    tekst: 'AFWIJKING  … rlz_a=… rlz_b=… soort=dubbel_in_rlz [vaf:vaf6]: RLZ-04-00004037 + RLZ-04-00004038 (referentie)',
    titel: 'Zelfde referentie, controleer — BOOT · 202632703',
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

  it('oude paar-bevinding (boekstuk_a/b): toont beide boekstuknummers als linkbtn en kopieert op klik', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
    render(<RlzDubbelBoekstukken bevinding={bevinding()} />)
    const blok = screen.getByTestId('rlz-dubbel-boekstukken')
    expect(blok).toHaveTextContent('Open in Reeleezee: RLZ-04-00004037 · RLZ-04-00004038')
    const knop = screen.getByRole('button', { name: 'Boekstuknummer RLZ-04-00004038 kopiëren' })
    expect(knop.className).toBe('linkbtn')
    await userEvent.click(knop)
    expect(writeText).toHaveBeenCalledWith('RLZ-04-00004038')
    expect(screen.queryByTestId('rlz-dubbel-waarschijnlijk')).toBeNull()
  })

  it('cluster (blok 1 10-09): alle N boekstuknummers uit `boekstukken`, in volgorde, boven de A/B-terugval', () => {
    render(
      <RlzDubbelBoekstukken
        bevinding={bevinding({
          detail: {
            afwijking_soort: 'dubbel_in_rlz',
            boekstukken: ['RLZ-04-00000069', 'RLZ-04-00000072', 'RLZ-04-00000080'],
            boekstuk_a: 'RLZ-04-00000069',
            boekstuk_b: 'RLZ-04-00000072',
            aantal_exemplaren: 3,
          },
        })}
      />,
    )
    expect(screen.getByTestId('rlz-dubbel-boekstukken')).toHaveTextContent(
      'Open in Reeleezee: RLZ-04-00000069 · RLZ-04-00000072 · RLZ-04-00000080',
    )
    expect(screen.getAllByRole('button')).toHaveLength(3)
    expect(screen.getAllByRole('button').every((b) => b.className === 'linkbtn')).toBe(true)
  })

  it('6-Steps-casus: `waarschijnlijk_dubbel` toont een status-chip vóór de boekstuknummers', () => {
    render(
      <RlzDubbelBoekstukken
        bevinding={bevinding({
          detail: {
            afwijking_soort: 'dubbel_in_rlz',
            boekstukken: ['RLZ-04-00000069', 'RLZ-04-00000072'],
            waarschijnlijk_dubbel: true,
          },
        })}
      />,
    )
    expect(screen.getByTestId('rlz-dubbel-waarschijnlijk')).toHaveTextContent('waarschijnlijk dubbel')
    expect(screen.getByTestId('rlz-dubbel-boekstukken')).toHaveTextContent('RLZ-04-00000069 · RLZ-04-00000072')
  })

  it('rlzDubbelBoekstukken: lege of ongeldige lijst valt terug op A/B; niets = leeg', () => {
    expect(rlzDubbelBoekstukken({ boekstukken: [], boekstuk_a: 'A', boekstuk_b: 'B' })).toEqual(['A', 'B'])
    expect(rlzDubbelBoekstukken({ boekstukken: 'x', boekstuk_a: 'A' })).toEqual(['A'])
    expect(rlzDubbelBoekstukken({ boekstukken: [null, 'C', ''] })).toEqual(['C'])
    expect(rlzDubbelBoekstukken(null)).toEqual([])
  })

  it('zonder boekstuknummers (concept zonder nummer) blijft de rij eerlijk: verwijst naar de details', () => {
    render(<RlzDubbelBoekstukken bevinding={bevinding({ detail: { afwijking_soort: 'dubbel_in_rlz' } })} />)
    expect(screen.getByTestId('rlz-dubbel-boekstukken')).toHaveTextContent('boekstuknummers onbekend (zie details)')
    expect(screen.queryByRole('button')).toBeNull()
  })
})
