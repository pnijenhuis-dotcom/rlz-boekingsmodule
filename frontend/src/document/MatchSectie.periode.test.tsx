import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { FactuurmatchDto } from '../api/types'
import { MatchSectie } from './MatchSectie'

/** Blok 11 (07-09): het niet-blokkerende periode-signaal uit de factuurmatch-motor (`details.periode_signaal`) staat
 * als oranje hint in de match-sectie; zonder signaal niets extra. De uitkomst-chip blijft ongewijzigd. */

function match(details: Record<string, unknown>): FactuurmatchDto {
  return {
    document_id: 'bbbbbbbb-0000-0000-0000-000000000002',
    veldwerker_naam: 'Milan K.',
    uitkomst: 'match',
    staten_som_uren: '16',
    staten_som_bedrag: '680.00',
    factuur_bedrag: '680.00',
    factuur_uren: null,
    verschil_bedrag: null,
    verschil_uren: null,
    tarief_ontbreekt: false,
    details,
    berekend_op: '2026-09-07T10:00:00Z',
    afwijking_bevestigd: false,
    afwijking_bevestigd_op: null,
  } as unknown as FactuurmatchDto
}

const SIGNAAL =
  'Factuurperiode wk 31 · 2026 komt niet overeen met de weekstaten in deze match (wk 30 · 2026) — controleer de periode op de factuur of kies andere weekstaten.'

describe('MatchSectie — periode-signaal (blok 11)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('toont het signaal oranje als de motor het meegeeft, mét ongewijzigde uitkomst-chip', () => {
    render(
      <MatchSectie
        administratieId="a"
        documentId="b"
        match={match({ staten: [], leden: [], tariefbronnen: ['koppeling'], periode_signaal: { tekst: SIGNAAL } })}
        onGewijzigd={() => {}}
      />,
    )
    const hint = screen.getByTestId('match-periode-signaal')
    expect(hint).toHaveTextContent(SIGNAAL)
    expect(hint.style.color).toBe('var(--orange)')
    expect(screen.getByText('match — uren en bedrag sluiten')).toBeInTheDocument()
  })

  it('toont niets extra zonder signaal (null of afwezig)', () => {
    const { unmount } = render(
      <MatchSectie administratieId="a" documentId="b" match={match({ staten: [], leden: [], periode_signaal: null })} onGewijzigd={() => {}} />,
    )
    expect(screen.queryByTestId('match-periode-signaal')).toBeNull()
    unmount()
    render(<MatchSectie administratieId="a" documentId="b" match={match({ staten: [], leden: [] })} onGewijzigd={() => {}} />)
    expect(screen.queryByTestId('match-periode-signaal')).toBeNull()
  })
})
