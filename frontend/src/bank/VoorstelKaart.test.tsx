// Voorstel-kaart (blok E5–E9, mockup bank-voorstel-kaart.html): rendering per match-soort (exact /
// bedrag-zonder-referentie / deelmatch / geen), restant cent-exact, ontbrekend-cacheveld-pad (kaart zonder
// die regel, nooit leeg/wachtend), compact-variant voor de splitsen-dialoog.
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { GEEN_MATCH_TEKST, isDeelbetaling, matchChip, restantCenten, VoorstelKaart } from './VoorstelKaart'

const POST = {
  id: 'p1',
  bedrag: '4428.73',
  referentie: '202600081',
  referentie2: 'RLZ-01-00000942 01-09-2026',
  rlz_document_id: null,
  tegenpartij_naam: 'Hans Anders Nederland B.V.',
  documentsoort: 'Verkoopfactuur',
  boekstuknummer: 'RLZ-01-00000942',
  factuurdatum: '2026-09-01',
}

describe('restantCenten / isDeelbetaling (cent-exact, gehele centen)', () => {
  it('rekent het restant in centen zonder float-drift', () => {
    expect(restantCenten('-1000.00', '1200.00')).toBe(20000)
    expect(restantCenten('-0.10', '0.30')).toBe(20) // 0.3 − 0.1 zou als float 0.19999… zijn
    expect(restantCenten('-1200.00', '1200.00')).toBe(0)
    expect(restantCenten('-1300.00', '1200.00')).toBe(0) // méér betaald dan open = geen restant
    expect(restantCenten(null, '1200.00')).toBeNull()
    expect(restantCenten('-1000.00', null)).toBeNull()
    expect(isDeelbetaling('-1000.00', '1200.00')).toBe(true)
    expect(isDeelbetaling('-1200.00', '1200.00')).toBe(false)
  })
})

describe('matchChip (E6)', () => {
  it('groen = exacte match; oranje mét reden voor bedrag-zonder-referentie en deelmatch; geen chip voor vaste regel/handmatig', () => {
    expect(matchChip({ soort: 'exacte_match' }, false)).toEqual({ tekst: 'exacte match — naam + factuurnummer + bedrag', kleur: 'groen' })
    expect(matchChip({ soort: 'rlz_voorstel' }, false)).toEqual({ tekst: 'match op bedrag, geen referentie — bevestigen', kleur: 'oranje' })
    expect(matchChip({ soort: 'deel_match' }, true)?.tekst).toBe('match op naam + referentie, bedrag wijkt af — bevestigen')
    expect(matchChip({ soort: 'vaste_regel' }, false)).toBeNull()
    expect(matchChip({ soort: 'handmatig' }, false)).toBeNull()
  })
})

describe('VoorstelKaart', () => {
  it('exacte match: alle specs + groene chip, geen deelbetaling', () => {
    render(<VoorstelKaart voorstel={{ soort: 'exacte_match', open_post: POST }} mutatieBedrag="4428.73" />)
    const kaart = screen.getByTestId('voorstel-kaart')
    expect(kaart).toHaveTextContent('Hans Anders Nederland B.V.')
    expect(kaart).toHaveTextContent('Verkoopfactuur 202600081 · RLZ-01-00000942')
    expect(kaart).toHaveTextContent('factuurdatum 1-9-2026 · open € 4.428,73')
    expect(kaart).toHaveTextContent('exacte match — naam + factuurnummer + bedrag')
    expect(screen.queryByTestId('voorstel-deelbetaling')).not.toBeInTheDocument()
  })

  it('bedrag-match zonder referentie (RLZ-voorstel): oranje chip', () => {
    render(<VoorstelKaart voorstel={{ soort: 'rlz_voorstel', open_post: POST }} mutatieBedrag="4428.73" />)
    expect(screen.getByTestId('voorstel-kaart')).toHaveTextContent('match op bedrag, geen referentie — bevestigen')
  })

  it('deelmatch: restant expliciet (E7)', () => {
    render(<VoorstelKaart voorstel={{ soort: 'deel_match', open_post: { ...POST, bedrag: '1200.00' } }} mutatieBedrag="-1000.00" />)
    expect(screen.getByTestId('voorstel-deelbetaling')).toHaveTextContent('deelbetaling — restant € 200,00 blijft open')
    expect(screen.getByTestId('voorstel-kaart')).toHaveTextContent('match op naam + referentie, bedrag wijkt af — bevestigen')
  })

  it('ontbrekende cachevelden: kaart zónder die regels — nooit leeg of wachtend', () => {
    render(
      <VoorstelKaart
        voorstel={{ soort: 'exacte_match', open_post: { id: 'p2', bedrag: '10.00', referentie: 'F-1', referentie2: null, rlz_document_id: null } }}
        mutatieBedrag="10.00"
      />,
    )
    const kaart = screen.getByTestId('voorstel-kaart')
    expect(kaart).toHaveTextContent('F-1') // kop valt terug op de referentie
    expect(kaart).toHaveTextContent('open € 10,00')
    expect(kaart).not.toHaveTextContent('factuurdatum')
    expect(kaart).not.toHaveTextContent('·')
  })

  it('geen open post = klein chipje "handmatig" mét de uitleg als tooltip (iteratie 2); compact = zonder chip (E9, splitsen)', () => {
    const { rerender } = render(<VoorstelKaart voorstel={{ soort: 'handmatig', open_post: null }} mutatieBedrag="1" />)
    expect(screen.getByTestId('voorstel-handmatig')).toHaveTextContent('handmatig')
    expect(screen.getByTestId('voorstel-handmatig')).toHaveAttribute('title', GEEN_MATCH_TEKST)
    rerender(<VoorstelKaart voorstel={{ soort: 'exacte_match', open_post: POST }} mutatieBedrag="4428.73" compact />)
    expect(screen.getByTestId('voorstel-kaart')).toHaveClass('vk-compact')
    expect(screen.getByTestId('voorstel-kaart')).not.toHaveTextContent('exacte match')
  })
})
