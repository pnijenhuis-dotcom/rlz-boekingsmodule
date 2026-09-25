import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
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

/** Gecontroleerd harnas: `waarde` volgt `onWijzig` zoals in BoekvoorstelPanel (regelstate). */
function Harnas({ modus, percentage, onWijzig }: { modus: 'netto' | 'bruto'; percentage: number | undefined; onWijzig: (w: string) => void }) {
  const [waarde, setWaarde] = useState('')
  return (
    <BedragModusInput
      ariaLabel="bedrag"
      bron="netto"
      modus={modus}
      percentage={percentage}
      waarde={waarde}
      onWijzig={(w) => {
        setWaarde(w)
        onWijzig(w)
      }}
    />
  )
}

describe('BedragModusInput — rekenexpressie (FV-08, feedbackrun A 25-09)', () => {
  it('rekent "20+30" uit bij het verlaten van het veld, toont 50,00 en een chip "= 20+30"', async () => {
    const onWijzig = vi.fn()
    render(<Harnas modus="netto" percentage={0.21} onWijzig={onWijzig} />)
    const veld = screen.getByLabelText('Netto bedrag') as HTMLInputElement
    await userEvent.type(veld, '20+30')
    // Tussentijds wordt een expressie nooit weggeschreven (alleen de kale cijfers vóór de operator).
    expect(onWijzig.mock.calls.every(([w]) => !String(w).includes('+'))).toBe(true)
    await userEvent.tab()
    expect(veld.value).toBe('50,00')
    expect(onWijzig).toHaveBeenLastCalledWith('50,00')
    expect(screen.getByTestId('bedrag-expressie-chip').textContent).toBe('= 20+30')
  })

  it('Enter rekent uit; in bruto-modus gaat het resultaat als netto naar de bron', async () => {
    const onWijzig = vi.fn()
    render(<Harnas modus="bruto" percentage={0.21} onWijzig={onWijzig} />)
    const veld = screen.getByLabelText('Bruto bedrag') as HTMLInputElement
    await userEvent.type(veld, '100+21{Enter}')
    expect(veld.value).toBe('121,00')
    expect(onWijzig).toHaveBeenLastCalledWith('100,00')
  })

  it('een kaal getal blijft ongewijzigd en krijgt geen chip; een ongeldige expressie blijft staan', async () => {
    const onWijzig = vi.fn()
    render(<Harnas modus="netto" percentage={undefined} onWijzig={onWijzig} />)
    const veld = screen.getByLabelText('Netto bedrag') as HTMLInputElement
    await userEvent.type(veld, '12,50')
    await userEvent.tab()
    expect(veld.value).toBe('12,50')
    expect(screen.queryByTestId('bedrag-expressie-chip')).toBeNull()
    await userEvent.clear(veld)
    await userEvent.type(veld, '20+')
    await userEvent.tab()
    // Ongeldige expressie: niets uitgerekend, niets weggeschreven — het veld valt terug op de laatst opgeslagen waarde
    // (de "20" van vóór de operator), nooit een gok.
    expect(veld.value).toBe('20')
    expect(onWijzig).toHaveBeenLastCalledWith('20')
    expect(screen.queryByTestId('bedrag-expressie-chip')).toBeNull()
  })
})
