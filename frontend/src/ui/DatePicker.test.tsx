import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { DatePicker } from './DatePicker'

function Harnas({ onChange, min, max }: { onChange: (v: string | null) => void; min?: string; max?: string }) {
  const [waarde, setWaarde] = useState<string | null>(null)
  return (
    <DatePicker
      aria-label="Testdatum"
      value={waarde}
      onChange={(v) => {
        setWaarde(v)
        onChange(v)
      }}
      min={min}
      max={max}
    />
  )
}

describe('DatePicker', () => {
  it('volledig getypte datum levert ISO in de onChange (payload blijft ISO)', async () => {
    const gebruiker = userEvent.setup()
    const onChange = vi.fn()
    render(<Harnas onChange={onChange} />)

    await gebruiker.type(screen.getByLabelText('Testdatum'), '07082026')

    expect(onChange).toHaveBeenLastCalledWith('2026-08-07')
    expect(screen.getByLabelText('Testdatum')).toHaveValue('07-08-2026')
  })

  it('halfgetypte invoer verdwijnt op blur (canonieke weergave hersteld)', async () => {
    const gebruiker = userEvent.setup()
    const onChange = vi.fn()
    render(<Harnas onChange={onChange} />)

    const veld = screen.getByLabelText('Testdatum')
    await gebruiker.type(veld, '0708')
    await gebruiker.tab()

    expect(veld).toHaveValue('')
  })

  it('datum buiten min/max wordt niet doorgegeven', async () => {
    const gebruiker = userEvent.setup()
    const onChange = vi.fn()
    render(<Harnas onChange={onChange} min="2026-01-01" max="2026-12-31" />)

    await gebruiker.type(screen.getByLabelText('Testdatum'), '07082025')

    expect(onChange).not.toHaveBeenCalledWith('2025-08-07')
  })

  it('kalenderselectie geeft ISO terug en sluit de popover', async () => {
    const gebruiker = userEvent.setup()
    const onChange = vi.fn()
    render(<Harnas onChange={onChange} />)

    await gebruiker.click(screen.getByRole('button', { name: 'Kalender openen' }))
    // react-day-picker rendert dagknoppen met een toegankelijke naam die de datum bevat.
    const dagknoppen = await screen.findAllByRole('button', { name: /15/ })
    await gebruiker.click(dagknoppen[0])

    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange.mock.calls[0][0]).toMatch(/^\d{4}-\d{2}-15$/)
  })
})
