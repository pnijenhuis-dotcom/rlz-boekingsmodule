import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { FormFouten, useFormFouten } from './FormFouten'

const LABELS = { 'test-email': 'E-mailadres', 'test-code': 'Code' }

function Formulier({ onGeldig }: { onGeldig: () => void }) {
  const { fouten, controleer } = useFormFouten(LABELS)
  return (
    <div>
      <FormFouten fouten={fouten} />
      <form
        noValidate
        onSubmit={(e) => {
          e.preventDefault()
          if (controleer(e.currentTarget)) onGeldig()
        }}
      >
        <label htmlFor="test-email">E-mailadres</label>
        <input id="test-email" type="email" required />
        <label htmlFor="test-code">Code</label>
        <input id="test-code" pattern="[0-9]{6}" required />
        <button type="submit">Versturen</button>
      </form>
    </div>
  )
}

describe('useFormFouten + FormFouten', () => {
  it('toont bij submit ALLE validatiefouten met NL-labels, niet alleen de eerste', async () => {
    const gebruiker = userEvent.setup()
    const onGeldig = vi.fn()
    render(<Formulier onGeldig={onGeldig} />)

    await gebruiker.click(screen.getByRole('button', { name: 'Versturen' }))

    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('Versturen kan nog niet — controleer:')
    expect(alert).toHaveTextContent('E-mailadres is verplicht')
    expect(alert).toHaveTextContent('Code is verplicht')
    expect(onGeldig).not.toHaveBeenCalled()
    // focus-naar-eerste-fout
    expect(screen.getByLabelText('E-mailadres')).toHaveFocus()
  })

  it('benoemt formaatfouten in het Nederlands', async () => {
    const gebruiker = userEvent.setup()
    render(<Formulier onGeldig={vi.fn()} />)

    await gebruiker.type(screen.getByLabelText('E-mailadres'), 'geen-emailadres')
    await gebruiker.type(screen.getByLabelText('Code'), 'abc')
    await gebruiker.click(screen.getByRole('button', { name: 'Versturen' }))

    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('E-mailadres is geen geldig e-mailadres')
    expect(alert).toHaveTextContent('Code heeft niet het verwachte formaat')
  })

  it('verdwijnt zodra het formulier geldig verstuurd wordt', async () => {
    const gebruiker = userEvent.setup()
    const onGeldig = vi.fn()
    render(<Formulier onGeldig={onGeldig} />)

    await gebruiker.click(screen.getByRole('button', { name: 'Versturen' }))
    expect(screen.getByRole('alert')).toBeInTheDocument()

    await gebruiker.type(screen.getByLabelText('E-mailadres'), 'p@test.local')
    await gebruiker.type(screen.getByLabelText('Code'), '123456')
    await gebruiker.click(screen.getByRole('button', { name: 'Versturen' }))

    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(onGeldig).toHaveBeenCalledTimes(1)
  })
})
