import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { BedragModusInput } from './BedragModusInput'

describe('BedragModusInput — bruto/netto-schakelaar (blok E, Peter 16-09)', () => {
  it('toont in bruto-modus de omgerekende waarde van een netto-bron en schrijft getypte bruto terug als netto', async () => {
    const onWijzig = vi.fn()
    render(<BedragModusInput ariaLabel="bedrag" bron="netto" modus="bruto" percentage={0.21} waarde="100,00" onWijzig={onWijzig} />)
    const veld = screen.getByLabelText('Bruto bedrag') as HTMLInputElement
    expect(veld.value).toBe('121,00')
    await userEvent.clear(veld)
    await userEvent.type(veld, '242')
    // Elke toets rekent om; de laatste aanroep is de volledige invoer: bruto 242 → netto 200,00.
    expect(onWijzig).toHaveBeenLastCalledWith('200,00')
    expect(veld.value).toBe('242') // de getypte tekst blijft staan zolang het veld focus heeft (geen heen-en-weer-afronding)
  })

  it('toont in netto-modus de omgerekende waarde van een bruto-bron (kassabedragen incl. btw)', () => {
    render(<BedragModusInput ariaLabel="omzetbedrag Dranken" bron="bruto" modus="netto" percentage={0.09} waarde="88.50" onWijzig={vi.fn()} />)
    expect((screen.getByLabelText('Netto omzetbedrag Dranken') as HTMLInputElement).value).toBe('81,19')
  })

  it('blijft zonder btw-code in de bron-modus mét tooltip en geeft de invoer ongewijzigd door', async () => {
    const onWijzig = vi.fn()
    render(<BedragModusInput ariaLabel="bedrag" bron="netto" modus="bruto" percentage={undefined} waarde="10,00" onWijzig={onWijzig} />)
    const veld = screen.getByLabelText('Netto bedrag') as HTMLInputElement
    expect(veld.value).toBe('10,00')
    expect(veld.title).toMatch(/Geen btw-code/)
    await userEvent.type(veld, '5')
    expect(onWijzig).toHaveBeenLastCalledWith('10,005')
  })
})
