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

describe('UitnodigModal — veldwerker zonder mail (steigerbouw-run A4, 25-08)', () => {
  it('stuurt uitnodiging_later mee en hernoemt de knop', async () => {
    const gebruiker = userEvent.setup()
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/auth/uitnodigingen')) {
        const body = JSON.parse(String(init?.body))
        expect(body.uitnodiging_later).toBe(true)
        expect(body.rol).toBe('zzper')
        return new Response(
          JSON.stringify({
            uitnodiging_id: 'u1', gebruiker_id: 'g1', token: 't', verloopt_op: '2026-09-01T00:00:00Z',
            mail_verzonden: false, mail_fout: null, mail_uitgesteld: true,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        )
      }
      return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)
    const onUitgenodigd = vi.fn()
    render(
      <UitnodigModal soort="veldwerker" administraties={ADMINISTRATIES} open onSluiten={() => {}} onUitgenodigd={onUitgenodigd} />,
    )
    await gebruiker.type(screen.getByLabelText('Naam'), 'Stefan B.')
    await gebruiker.type(screen.getByLabelText('E-mailadres'), 'stefan@test.local')
    await gebruiker.click(screen.getByRole('button', { name: 'Alle administraties selecteren' }))
    await gebruiker.click(screen.getByRole('checkbox', { name: /Uitnodiging later versturen/ }))
    await gebruiker.click(screen.getByRole('button', { name: 'Account aanmaken (zonder mail)' }))
    expect(onUitgenodigd).toHaveBeenCalledWith(expect.objectContaining({ mail_uitgesteld: true, mail_verzonden: false }))
  })
})

describe('UitnodigModal — rolgroep volgt de ingang (bugfix 04-09, casus "+ Veldwerker" maakte een kantoormedewerker)', () => {
  afterEach(() => vi.unstubAllGlobals())

  function fetchMetVangnet(bodies: Record<string, unknown>[]) {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/auth/uitnodigingen')) {
        bodies.push(JSON.parse(String(init?.body)))
        return new Response(
          JSON.stringify({
            uitnodiging_id: 'u1', gebruiker_id: 'g1', token: 't', verloopt_op: '2026-09-01T00:00:00Z',
            mail_verzonden: true, mail_fout: null, mail_uitgesteld: false,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        )
      }
      return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)
  }

  it('productiepad: gemount als medewerker, daarna soort → veldwerker: rol wordt een veldrol, bron = veldwerkers, rolgroep zichtbaar', async () => {
    const gebruiker = userEvent.setup()
    const bodies: Record<string, unknown>[] = []
    fetchMetVangnet(bodies)
    const props = { administraties: ADMINISTRATIES, open: true, onSluiten: () => {}, onUitgenodigd: () => {} }
    const { rerender } = render(<UitnodigModal soort="medewerker" {...props} />)
    expect(screen.getByTestId('uitnodig-rolgroep')).toHaveTextContent('Rolgroep: Kantoormedewerker')
    // Kruis-case: op de kantoor-ingang eerst "Beheerder" kiezen …
    await gebruiker.selectOptions(screen.getByLabelText('Rol'), 'beheerder')
    // … dan wisselt de ingang naar veldwerker terwijl de component gemount blijft (de bug van 21-08).
    rerender(<UitnodigModal soort="veldwerker" {...props} />)
    expect(screen.getByTestId('uitnodig-rolgroep')).toHaveTextContent("Rolgroep: Veldwerker (ZZP'er · Uitvoerder · Detacheerder)")
    expect((screen.getByLabelText('Rol') as HTMLSelectElement).value).toBe('zzper')
    await gebruiker.type(screen.getByLabelText('Naam'), 'Stefan B.')
    await gebruiker.type(screen.getByLabelText('E-mailadres'), 'stefan@test.local')
    await gebruiker.click(screen.getByRole('button', { name: 'Alle administraties selecteren' }))
    await gebruiker.click(screen.getByRole('button', { name: 'Verstuur uitnodiging' }))
    expect(bodies).toHaveLength(1)
    expect(bodies[0]).toMatchObject({ rol: 'zzper', bron: 'veldwerkers' })
  })

  it('kantoor-ingang stuurt bron=kantoor, accordeur-ingang bron=klant_accordeurs mét rol klant_accordeur', async () => {
    const gebruiker = userEvent.setup()
    const bodies: Record<string, unknown>[] = []
    fetchMetVangnet(bodies)
    const props = { administraties: ADMINISTRATIES, open: true, onSluiten: () => {}, onUitgenodigd: () => {} }
    const { unmount } = render(<UitnodigModal soort="medewerker" {...props} />)
    await gebruiker.selectOptions(screen.getByLabelText('Rol'), 'boekhouding_projecten')
    await gebruiker.type(screen.getByLabelText('Naam'), 'Demi')
    await gebruiker.type(screen.getByLabelText('E-mailadres'), 'demi@ak-nijenhuis.nl')
    await gebruiker.click(screen.getByRole('button', { name: 'Alle administraties selecteren' }))
    await gebruiker.click(screen.getByRole('button', { name: 'Verstuur uitnodiging' }))
    expect(bodies.at(-1)).toMatchObject({ rol: 'boekhouding_projecten', bron: 'kantoor' })
    unmount()

    render(<UitnodigModal soort="accordeur" {...props} />)
    expect(screen.getByTestId('uitnodig-rolgroep')).toHaveTextContent('Rolgroep: Klant-accordeur')
    await gebruiker.type(screen.getByLabelText('Naam'), 'R. de Groot')
    await gebruiker.type(screen.getByLabelText('E-mailadres'), 'r@klant.nl')
    await gebruiker.click(screen.getByRole('button', { name: 'Alle administraties selecteren' }))
    await gebruiker.click(screen.getByRole('button', { name: 'Verstuur uitnodiging' }))
    expect(bodies.at(-1)).toMatchObject({ rol: 'klant_accordeur', bron: 'klant_accordeurs' })
  })
})
