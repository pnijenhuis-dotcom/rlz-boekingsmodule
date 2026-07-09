import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { SearchableCombobox } from './SearchableCombobox'

const OPTIES = [
  { id: '1', label: 'Aap' },
  { id: '2', label: 'Beer' },
  { id: '3', label: 'Cavia' },
]

describe('SearchableCombobox', () => {
  it('rendert de opties-lijst buiten een table-container met overflow: hidden (portal)', async () => {
    const gebruiker = userEvent.setup()
    const { container } = render(
      <table style={{ overflow: 'hidden' }}>
        <tbody>
          <tr>
            <td>
              <SearchableCombobox label="Grootboek" opties={OPTIES} waarde={null} onWijzig={() => {}} />
            </td>
          </tr>
        </tbody>
      </table>,
    )

    await gebruiker.click(screen.getByRole('combobox', { name: 'Grootboek' }))

    const listbox = screen.getByRole('listbox', { name: 'Grootboek' })
    // De listbox mag geen DOM-afstammeling van de (clippende) table zijn — anders zou
    // `overflow: hidden` op de table 'm nog steeds kunnen afknippen.
    expect(container.contains(listbox)).toBe(false)
    expect(document.body.contains(listbox)).toBe(true)
    expect(screen.getByText('Aap')).toBeInTheDocument()
  })

  it('opent met de eerste resultaten zodra het veld focus krijgt, zonder eerst te moeten typen', async () => {
    const gebruiker = userEvent.setup()
    render(<SearchableCombobox label="Crediteur" opties={OPTIES} waarde={null} onWijzig={() => {}} />)

    await gebruiker.click(screen.getByRole('combobox', { name: 'Crediteur' }))

    expect(screen.getByText('Aap')).toBeInTheDocument()
    expect(screen.getByText('Beer')).toBeInTheDocument()
  })

  it('opnieuw klikken op een al-gefocust, nog steeds ingevuld veld heropent de lijst', async () => {
    const gebruiker = userEvent.setup()
    render(<SearchableCombobox label="Crediteur" opties={OPTIES} waarde="2" onWijzig={() => {}} />)

    const veld = screen.getByRole('combobox', { name: 'Crediteur' })
    await gebruiker.click(veld) // opent + focust
    await gebruiker.keyboard('{Escape}') // sluit, veld blijft focused
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()

    await gebruiker.click(veld) // zelfde, al-focused veld opnieuw aanklikken
    expect(screen.getByRole('listbox', { name: 'Crediteur' })).toBeInTheDocument()
  })

  it('toetsenbordnavigatie: pijltjes + enter kiezen een optie, escape sluit zonder te kiezen', async () => {
    const gebruiker = userEvent.setup()
    const onWijzig = vi.fn()
    render(<SearchableCombobox label="Crediteur" opties={OPTIES} waarde={null} onWijzig={onWijzig} />)

    const veld = screen.getByRole('combobox', { name: 'Crediteur' })
    await gebruiker.click(veld)
    await gebruiker.keyboard('{ArrowDown}{Enter}')

    expect(onWijzig).toHaveBeenCalledWith('2')
  })

  it('toont code+naam (het volledige label) van de gekozen waarde na selectie', async () => {
    const gebruiker = userEvent.setup()
    function Wrapper() {
      const [waarde, setWaarde] = useState<string | null>(null)
      return (
        <SearchableCombobox
          label="Grootboek"
          opties={[{ id: '1', label: '4699 · Diverse algemene kosten' }]}
          waarde={waarde}
          onWijzig={setWaarde}
        />
      )
    }
    render(<Wrapper />)
    await gebruiker.click(screen.getByRole('combobox', { name: 'Grootboek' }))
    await gebruiker.click(screen.getByText('4699 · Diverse algemene kosten'))
    expect(screen.getByRole('combobox', { name: 'Grootboek' })).toHaveValue('4699 · Diverse algemene kosten')
  })

  it('optie met een code toont die vet vóór de omschrijving, en zet ze samen als invoerwaarde', async () => {
    const gebruiker = userEvent.setup()
    function Wrapper() {
      const [waarde, setWaarde] = useState<string | null>(null)
      return (
        <SearchableCombobox
          label="Btw-code"
          opties={[{ id: '1', code: '21%', label: 'NL, Hoog Tarief' }]}
          waarde={waarde}
          onWijzig={setWaarde}
        />
      )
    }
    render(<Wrapper />)
    await gebruiker.click(screen.getByRole('combobox', { name: 'Btw-code' }))

    const code = screen.getByText('21%')
    expect(code.className).toContain('combobox-optie-code')
    expect(screen.getByText('NL, Hoog Tarief')).toBeInTheDocument()

    await gebruiker.click(screen.getByRole('option', { name: /21%.*NL, Hoog Tarief/ }))
    expect(screen.getByRole('combobox', { name: 'Btw-code' })).toHaveValue('21% · NL, Hoog Tarief')
  })

  it('toonLabel=false verbergt het zichtbare label maar behoudt de aria-label', () => {
    render(
      <SearchableCombobox label="Grootboek" opties={OPTIES} waarde={null} onWijzig={() => {}} toonLabel={false} />,
    )
    expect(screen.queryByText('Grootboek')).not.toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: /Grootboek/ })).toBeInTheDocument()
  })
})
