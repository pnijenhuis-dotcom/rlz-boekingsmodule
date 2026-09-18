import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { SearchableCombobox, type ComboboxOptie } from './SearchableCombobox'

/** Ingeklapte groep (18-09 DEEL B): buitenland-tarieven achter één regel onderaan; zoeken doorzoekt alles; de
 * geselecteerde optie blijft zichtbaar; pijltjes slaan de ingeklapte groep over tot uitgevouwen. */
const OPTIES: ComboboxOptie[] = [
  { id: 'hoog', code: '21%', label: 'NL, Hoog Tarief' },
  { id: 'laag', code: '9%', label: 'NL, Laag tarief' },
  { id: 'eu1', code: '0%', label: 'EU, Producten Hoog tarief', groep: 'buitenland' },
  { id: 'eu2', code: '0%', label: 'EU, Diensten Hoog tarief', groep: 'buitenland' },
  { id: 'exeu', code: '0%', label: 'Ex EU, Diensten Laag tarief', groep: 'buitenland' },
]
const GROEP = { groep: 'buitenland', label: (n: number) => `Buitenland-tarieven tonen (${n})` }

describe('SearchableCombobox — ingeklapte groep', () => {
  it('verbergt de groep zonder zoekterm achter "Buitenland-tarieven tonen (3)"; klik vouwt uit', async () => {
    const gebruiker = userEvent.setup()
    render(<SearchableCombobox label="Btw-code" opties={OPTIES} waarde={null} onWijzig={() => {}} ingeklapteGroep={GROEP} />)
    await gebruiker.click(screen.getByRole('combobox'))
    await waitFor(() => expect(screen.getAllByRole('option')).toHaveLength(2))
    expect(screen.queryByRole('option', { name: /EU, Producten/ })).toBeNull()
    const toggle = screen.getByTestId('combobox-inklap')
    expect(toggle).toHaveTextContent('Buitenland-tarieven tonen (3)')
    await gebruiker.click(toggle)
    await waitFor(() => expect(screen.getAllByRole('option')).toHaveLength(5))
    expect(screen.queryByTestId('combobox-inklap')).toBeNull()
  })

  it('zoeken doorzoekt altijd álles, ook de ingeklapte groep', async () => {
    const gebruiker = userEvent.setup()
    render(<SearchableCombobox label="Btw-code" opties={OPTIES} waarde={null} onWijzig={() => {}} ingeklapteGroep={GROEP} />)
    await gebruiker.type(screen.getByRole('combobox'), 'EU')
    await waitFor(() => expect(screen.getByRole('option', { name: /EU, Producten Hoog/ })).toBeInTheDocument())
    expect(screen.getAllByRole('option')).toHaveLength(3)
    expect(screen.queryByTestId('combobox-inklap')).toBeNull()
  })

  it('een al gekozen buitenland-tarief blijft zichtbaar en geselecteerd (nooit een stille wijziging)', async () => {
    const gebruiker = userEvent.setup()
    render(<SearchableCombobox label="Btw-code" opties={OPTIES} waarde="eu2" onWijzig={() => {}} ingeklapteGroep={GROEP} />)
    expect(screen.getByRole('combobox')).toHaveValue('0% · EU, Diensten Hoog tarief')
    await gebruiker.click(screen.getByRole('combobox'))
    await waitFor(() => expect(screen.getByRole('option', { name: /EU, Diensten Hoog/ })).toBeInTheDocument())
    expect(screen.getAllByRole('option')).toHaveLength(3)
    expect(screen.getByTestId('combobox-inklap')).toHaveTextContent('Buitenland-tarieven tonen (2)')
  })

  it('pijltjes slaan de ingeklapte groep over; Enter op de toggle vouwt uit en kiest niets', async () => {
    const gebruiker = userEvent.setup()
    const onWijzig = vi.fn()
    render(<SearchableCombobox label="Btw-code" opties={OPTIES} waarde={null} onWijzig={onWijzig} ingeklapteGroep={GROEP} />)
    const veld = screen.getByRole('combobox')
    await gebruiker.click(veld)
    await waitFor(() => expect(screen.getAllByRole('option')).toHaveLength(2))
    await gebruiker.keyboard('{ArrowDown}{ArrowDown}{ArrowDown}') // hoog → laag → toggle (stopt daar)
    expect(veld.getAttribute('aria-activedescendant')).toMatch(/-inklap$/)
    await gebruiker.keyboard('{Enter}')
    expect(onWijzig).not.toHaveBeenCalled()
    await waitFor(() => expect(screen.getAllByRole('option')).toHaveLength(5))
  })

  it('zonder ingeklapteGroep gedraagt de combobox zich als voorheen', async () => {
    const gebruiker = userEvent.setup()
    render(<SearchableCombobox label="Btw-code" opties={OPTIES} waarde={null} onWijzig={() => {}} />)
    await gebruiker.click(screen.getByRole('combobox'))
    await waitFor(() => expect(screen.getAllByRole('option')).toHaveLength(5))
    expect(screen.queryByTestId('combobox-inklap')).toBeNull()
  })
})
