import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { StatusChip } from './StatusChip'

describe('StatusChip (dot + label, designpass v2)', () => {
  it('toont het Nederlandse label en de juiste kleurklasse voor te_controleren', () => {
    render(<StatusChip status="te_controleren" />)
    const chip = screen.getByText('Te controleren')
    expect(chip).toHaveClass('status', 'ai')
  })

  it('toont geboekt-status met de gedimde kleurklasse', () => {
    render(<StatusChip status="geboekt" />)
    const chip = screen.getByText('Geboekt')
    expect(chip).toHaveClass('status', 'geboekt')
  })

  it('valt terug op de ruwe statuswaarde voor een onbekende status', () => {
    render(<StatusChip status="iets_nieuws" />)
    expect(screen.getByText('iets_nieuws')).toHaveClass('status', 'geheugen')
  })

  it('blok C (02-09): draagt de "Geboekt in RLZ"-tooltip als die meegegeven wordt', () => {
    render(<StatusChip status="geboekt" title={'Geboekt in RLZ · boekstuk RLZ-1 · Crediteur\nhint'} />)
    expect(screen.getByText('Geboekt')).toHaveAttribute('title', 'Geboekt in RLZ · boekstuk RLZ-1 · Crediteur\nhint')
  })
})
