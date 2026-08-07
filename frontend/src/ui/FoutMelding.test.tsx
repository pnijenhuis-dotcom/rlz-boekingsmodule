import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { FoutMelding } from './FoutMelding'

describe('FoutMelding — mensentaal + retry + technisch detail achter uitklap (punt 4)', () => {
  it('toont de melding en roept onOpnieuw aan via de retry-knop', async () => {
    const gebruiker = userEvent.setup()
    const opnieuw = vi.fn()
    render(<FoutMelding melding="De lijst kon niet geladen worden." onOpnieuw={opnieuw} />)

    expect(screen.getByRole('alert')).toHaveTextContent('De lijst kon niet geladen worden.')
    await gebruiker.click(screen.getByRole('button', { name: 'Opnieuw proberen' }))
    expect(opnieuw).toHaveBeenCalledTimes(1)
  })

  it('verstopt het technische detail achter een uitklap', () => {
    render(<FoutMelding melding="Er ging iets mis." detail="SyntaxError: Unexpected token '<'" />)

    const uitklap = screen.getByText('Technische details').closest('details')
    expect(uitklap).not.toBeNull()
    expect(uitklap).not.toHaveAttribute('open')
    expect(screen.getByText(/Unexpected token/)).toBeInTheDocument()
  })

  it('toont geen dubbele tekst als detail gelijk is aan de melding, en geen knop zonder handler', () => {
    render(<FoutMelding melding="Zelfde tekst." detail="Zelfde tekst." />)
    expect(screen.queryByText('Technische details')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Opnieuw proberen' })).not.toBeInTheDocument()
  })
})
