// Voorstel-kaart (blok E5–E9, mockup bank-voorstel-kaart.html): rendering per match-soort (exact /
// bedrag-zonder-referentie / deelmatch / geen), restant cent-exact, ontbrekend-cacheveld-pad (kaart zonder
// die regel, nooit leeg/wachtend), compact-variant voor de splitsen-dialoog.
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AiToetsChip, GEEN_MATCH_TEKST, historieChip, isDeelbetaling, matchChip, restantCenten, VoorstelKaart } from './VoorstelKaart'

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

describe('matchChip (E6, label uit de motor sinds blok 2 08-09)', () => {
  it('groen = exacte match mét wat matchte; oranje = bevestigen mét wat matchte en wat niet; geen chip voor vaste regel/handmatig', () => {
    expect(matchChip({ soort: 'exacte_match', bron: 'naam + nummer + bedrag' }, false)).toEqual({ tekst: 'exacte match — naam + nummer + bedrag', kleur: 'groen' })
    expect(matchChip({ soort: 'exacte_match', bron: 'IBAN + nummer + bedrag' }, false)?.tekst).toBe('exacte match — IBAN + nummer + bedrag')
    expect(matchChip({ soort: 'deel_match', bron: 'nummer + bedrag, naam onbekend' }, false)?.tekst).toBe('match op nummer + bedrag, naam onbekend — bevestigen')
    expect(matchChip({ soort: 'deel_match', bron: 'naam + nummer, bedrag wijkt af' }, true)?.tekst).toBe('match op naam + nummer, bedrag wijkt af — bevestigen')
    expect(matchChip({ soort: 'rlz_voorstel', bron: 'voorstel Reeleezee — bedrag-match' }, false)).toEqual({
      tekst: 'voorstel Reeleezee — alleen bedrag, geen naam of nummer — bevestigen',
      kleur: 'oranje',
    })
    expect(matchChip({ soort: 'vaste_regel' }, false)).toBeNull()
    expect(matchChip({ soort: 'handmatig' }, false)).toBeNull()
  })

  it('zonder bron (oudere DTO) nooit "naam + referentie" verzinnen', () => {
    expect(matchChip({ soort: 'exacte_match' }, false)?.tekst).toBe('exacte match — naam + nummer + bedrag')
    expect(matchChip({ soort: 'deel_match' }, true)?.tekst).toBe('match op nummer, bedrag wijkt af — bevestigen')
    expect(matchChip({ soort: 'deel_match' }, false)?.tekst).not.toContain('naam + referentie')
  })
})

describe('VoorstelKaart', () => {
  it('exacte match: alle specs + groene chip, geen deelbetaling', () => {
    render(<VoorstelKaart voorstel={{ soort: 'exacte_match', bron: 'naam + nummer + bedrag', open_post: POST }} mutatieBedrag="4428.73" />)
    const kaart = screen.getByTestId('voorstel-kaart')
    expect(kaart).toHaveTextContent('Hans Anders Nederland B.V.')
    expect(kaart).toHaveTextContent('Verkoopfactuur 202600081 · RLZ-01-00000942')
    expect(kaart).toHaveTextContent('factuurdatum 1-9-2026 · open € 4.428,73')
    expect(kaart).toHaveTextContent('exacte match — naam + nummer + bedrag')
    expect(screen.queryByTestId('voorstel-deelbetaling')).not.toBeInTheDocument()
  })

  it('bedrag-match zonder referentie (RLZ-voorstel): oranje chip', () => {
    render(<VoorstelKaart voorstel={{ soort: 'rlz_voorstel', open_post: POST }} mutatieBedrag="4428.73" />)
    expect(screen.getByTestId('voorstel-kaart')).toHaveTextContent('voorstel Reeleezee — alleen bedrag, geen naam of nummer — bevestigen')
  })

  it('deelmatch: restant expliciet (E7)', () => {
    render(
      <VoorstelKaart
        voorstel={{ soort: 'deel_match', bron: 'naam + nummer, bedrag wijkt af', open_post: { ...POST, bedrag: '1200.00' } }}
        mutatieBedrag="-1000.00"
      />,
    )
    expect(screen.getByTestId('voorstel-deelbetaling')).toHaveTextContent('deelbetaling — restant € 200,00 blijft open')
    expect(screen.getByTestId('voorstel-kaart')).toHaveTextContent('match op naam + nummer, bedrag wijkt af — bevestigen')
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

describe('historie-regel + AI-toets-chips (blok B bundel 10-09)', () => {
  it('groen = "historie-regel — k van n op ‹rekening›"; oranje = "historie: k van n op ‹rekening› — bevestigen"; k/n uit de velden, rekening uit bron', () => {
    expect(historieChip({ soort: 'historie_regel', kleur: 'groen', bron: 'historie: 12 van 12 op 4400 Huur', historie_k: 12, historie_n: 12 })).toEqual({
      tekst: 'historie-regel — 12 van 12 op 4400 Huur',
      kleur: 'groen',
    })
    expect(historieChip({ soort: 'historie_regel', kleur: 'oranje', bron: 'historie: 4 van 6 op 4300 Telefoon', historie_k: 4, historie_n: 6 })).toEqual({
      tekst: 'historie: 4 van 6 op 4300 Telefoon — bevestigen',
      kleur: 'oranje',
    })
    // Zonder k/n-velden (ouder antwoord): k van n uit de bron-tekst.
    expect(historieChip({ soort: 'historie_regel', kleur: 'oranje', bron: 'historie: 3 van 5 op 4500 Kantoor' })?.tekst).toBe('historie: 3 van 5 op 4500 Kantoor — bevestigen')
    expect(historieChip({ soort: 'vaste_regel', kleur: 'groen' })).toBeNull()
    // matchChip kent de soort ook (kaart-pad).
    expect(matchChip({ soort: 'historie_regel', kleur: 'groen', bron: 'historie: 3 van 3 op 4400 Huur', historie_k: 3, historie_n: 3 }, false)?.tekst).toBe('historie-regel — 3 van 3 op 4400 Huur')
  })

  it('AI-toets: twijfel = oranje chip mét reden, overgeslagen = grijze chip "zonder AI-toets" (blok 4: geboekt zonder toets), plausibel/null = geen chip', () => {
    const { rerender } = render(<AiToetsChip mutatie={{ ai_toets_uitkomst: 'twijfel', ai_toets_reden: 'bedrag 3× hoger dan de historie', ai_toets_op: '2026-09-10T03:00:00Z' }} />)
    const twijfel = screen.getByTestId('ai-toets-twijfel')
    expect(twijfel).toHaveTextContent('AI-twijfel: bedrag 3× hoger dan de historie')
    expect(twijfel).toHaveClass('chip', 'ai')
    rerender(<AiToetsChip mutatie={{ ai_toets_uitkomst: 'overgeslagen', ai_toets_reden: 'api_key — geen API-key geconfigureerd', ai_toets_op: null }} />)
    const over = screen.getByTestId('ai-toets-overgeslagen')
    expect(over).toHaveTextContent('zonder AI-toets: api_key — geen API-key geconfigureerd')
    expect(over).toHaveAttribute('title', expect.stringContaining('loopt door zónder AI-toets'))
    expect(over).toHaveClass('chip')
    expect(over).not.toHaveClass('ai')
    rerender(<AiToetsChip mutatie={{ ai_toets_uitkomst: 'plausibel', ai_toets_reden: 'ok', ai_toets_op: null }} />)
    expect(screen.queryByTestId(/ai-toets-/)).not.toBeInTheDocument()
    rerender(<AiToetsChip mutatie={{}} />)
    expect(screen.queryByTestId(/ai-toets-/)).not.toBeInTheDocument()
  })
})
