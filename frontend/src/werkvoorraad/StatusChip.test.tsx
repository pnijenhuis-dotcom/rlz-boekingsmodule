import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { StatusChip } from './StatusChip'

describe('StatusChip', () => {
  it('toont het Nederlandse label en de juiste chipklasse voor te_controleren', () => {
    render(<StatusChip status="te_controleren" />)
    const chip = screen.getByText('Te controleren')
    expect(chip).toHaveClass('chip', 'ai')
  })

  it('toont geboekt-status met de gedimde chipklasse', () => {
    render(<StatusChip status="geboekt" />)
    const chip = screen.getByText('Geboekt')
    expect(chip).toHaveClass('chip', 'geboekt')
  })

  it('valt terug op de ruwe statuswaarde voor een onbekende status', () => {
    render(<StatusChip status="iets_nieuws" />)
    expect(screen.getByText('iets_nieuws')).toHaveClass('chip', 'geheugen')
  })
})
