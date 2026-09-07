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

  it('datum buiten min/max wordt niet doorgegeven tijdens het typen', async () => {
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

  // ————— Bugfix 07-09 ("Tab/blur wist ingevulde datum") — soepel parsen bij blur/Enter,
  // ongeldig/buiten de grenzen blijft de invoer STAAN met een zichtbare melding, nooit wissen. —————

  it('ongeldige invoer (halve datum) blijft staan bij blur, mét foutmelding en aria-invalid', async () => {
    const gebruiker = userEvent.setup()
    const onChange = vi.fn()
    render(<Harnas onChange={onChange} />)

    const veld = screen.getByLabelText('Testdatum')
    await gebruiker.type(veld, '0708')
    await gebruiker.tab()

    expect(veld).toHaveValue('07-08')
    expect(veld).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByRole('alert')).toHaveTextContent('Ongeldige datum')
    expect(onChange).not.toHaveBeenCalled()
  })

  it('niet-bestaande kalenderdatum blijft staan bij blur, mét melding', async () => {
    const gebruiker = userEvent.setup()
    const onChange = vi.fn()
    render(<Harnas onChange={onChange} />)

    const veld = screen.getByLabelText('Testdatum')
    await gebruiker.type(veld, '31022026')
    await gebruiker.tab()

    expect(veld).toHaveValue('31-02-2026')
    expect(screen.getByRole('alert')).toHaveTextContent('Ongeldige datum')
    expect(onChange).not.toHaveBeenCalled()
  })

  it('datum buiten min/max blijft staan bij blur, mét melding die de grenzen noemt', async () => {
    const gebruiker = userEvent.setup()
    const onChange = vi.fn()
    render(<Harnas onChange={onChange} min="2026-01-01" max="2026-12-31" />)

    const veld = screen.getByLabelText('Testdatum')
    await gebruiker.type(veld, '07082025')
    await gebruiker.tab()

    expect(veld).toHaveValue('07-08-2025')
    expect(screen.getByRole('alert')).toHaveTextContent('Datum moet tussen 01-01-2026 en 31-12-2026 liggen')
    expect(onChange).not.toHaveBeenCalledWith('2025-08-07')
  })

  it('geldige invoer bij blur: onChange en geen melding', async () => {
    const gebruiker = userEvent.setup()
    const onChange = vi.fn()
    render(<Harnas onChange={onChange} />)

    const veld = screen.getByLabelText('Testdatum')
    await gebruiker.type(veld, '07082026')
    await gebruiker.tab()

    expect(onChange).toHaveBeenLastCalledWith('2026-08-07')
    expect(veld).toHaveValue('07-08-2026')
    expect(veld).not.toHaveAttribute('aria-invalid')
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it.each([
    ['d-m-jjjj (eigen streepje)', '7-9-2026', '2026-09-07'],
    ['dd-mm-jj (tweecijferig jaar → 20jj)', '07-09-26', '2026-09-07'],
    ['d/m/jjjj (schuine streep)', '7/9/2026', '2026-09-07'],
    ['dd.mm.jjjj (punt)', '07.09.2026', '2026-09-07'],
  ])('soepel formaat %s wordt bij blur gecommit', async (_naam, invoer, verwachtIso) => {
    const gebruiker = userEvent.setup()
    const onChange = vi.fn()
    render(<Harnas onChange={onChange} />)

    const veld = screen.getByLabelText('Testdatum')
    await gebruiker.type(veld, invoer)
    await gebruiker.tab()

    expect(onChange).toHaveBeenLastCalledWith(verwachtIso)
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('Enter committeert hetzelfde als blur', async () => {
    const gebruiker = userEvent.setup()
    const onChange = vi.fn()
    render(<Harnas onChange={onChange} />)

    const veld = screen.getByLabelText('Testdatum')
    await gebruiker.type(veld, '7-9-2026{Enter}')

    expect(onChange).toHaveBeenLastCalledWith('2026-09-07')
  })

  it('bij een volgende invoer verdwijnt de foutmelding meteen (nog vóór de volgende blur)', async () => {
    const gebruiker = userEvent.setup()
    const onChange = vi.fn()
    render(<Harnas onChange={onChange} />)

    const veld = screen.getByLabelText('Testdatum')
    await gebruiker.type(veld, '0708')
    await gebruiker.tab()
    expect(screen.getByRole('alert')).toBeInTheDocument()

    await gebruiker.click(veld)
    await gebruiker.keyboard('2')
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('leeg veld bij blur geeft onChange(null) zonder melding', async () => {
    const gebruiker = userEvent.setup()
    const onChange = vi.fn()
    render(<Harnas onChange={onChange} />)

    const veld = screen.getByLabelText('Testdatum')
    await gebruiker.type(veld, '0708')
    await gebruiker.clear(veld)
    await gebruiker.tab()

    expect(veld).toHaveValue('')
    expect(screen.queryByRole('alert')).toBeNull()
  })
})
