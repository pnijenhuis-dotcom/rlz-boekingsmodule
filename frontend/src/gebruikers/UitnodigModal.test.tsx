import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { UitnodigModal } from './UitnodigModal'

const ADMINISTRATIES = [
  { id: 'a1', naam: 'Kempen Facilities B.V.' },
  { id: 'a2', naam: 'Rubicon Vastgoed B.V.' },
  { id: 'a3', naam: 'Universal Steigerbouw B.V.' },
]

describe('UitnodigModal — administratie-scope alles/geen (besluit Peter 25-08, punt D3)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('"Alle administraties selecteren" vinkt alles aan en "Geen" maakt de selectie leeg', async () => {
    const gebruiker = userEvent.setup()
    render(
      <UitnodigModal soort="medewerker" administraties={ADMINISTRATIES} open onSluiten={() => {}} onUitgenodigd={() => {}} />,
    )
    expect(screen.getByText('0 van 3 geselecteerd')).toBeInTheDocument()
    const geen = screen.getByRole('button', { name: 'Geen' })
    expect(geen).toBeDisabled()

    await gebruiker.click(screen.getByRole('button', { name: 'Alle administraties selecteren' }))
    expect(screen.getByText('3 van 3 geselecteerd')).toBeInTheDocument()
    // De losse vinkjes staan mee aan (MultiSelect toont de gekozen chips).
    expect(screen.getByRole('button', { name: 'Kempen Facilities B.V. verwijderen' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Alle administraties selecteren' })).toBeDisabled()

    await gebruiker.click(geen)
    expect(screen.getByText('0 van 3 geselecteerd')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Kempen Facilities B.V. verwijderen' })).not.toBeInTheDocument()
  })
})
