import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import {
  berekenVerschil,
  namenOpsomming,
  ScopeLijst,
  SCOPELIJST_MIN_RIJEN,
  SCOPELIJST_RIJHOOGTE_PX,
  sorteerScopeItems,
  verschilTekst,
  type ScopeLijstItem,
} from './ScopeLijst'

/* ScopeLijst (blok 2 nachtrun 10/11-09): één doorzoekbare lijst met vinkjes i.p.v. MultiSelect + chips-wolk.
 * Componenttests: zoeken, teller, filter "alleen geselecteerde", Alles/Geen (Geen mét bevestiging als er al scope
 * stond), alfabetische volgorde blijft bij aanvinken, gearchiveerd onderaan mét chip, verschil-helpers. */

const ITEMS: ScopeLijstItem[] = [
  { id: 'z', naam: 'Zilver Beheer B.V.', actief: true },
  { id: 'a', naam: 'Akkerman Holding B.V.', actief: true },
  { id: 'oud', naam: 'Oud Derva B.V.', actief: false },
  { id: 'm', naam: 'Molenhof Verhuur B.V.', actief: true },
  { id: 'b', naam: 'Baard Vastgoed B.V.', actief: true },
  { id: 'e', naam: 'Élan Exploitatie B.V.', actief: true },
]

function Harnas({ start = [], oorspronkelijk = start, vergrendeld }: { start?: string[]; oorspronkelijk?: string[]; vergrendeld?: Set<string> }) {
  const [sel, setSel] = useState<string[]>(start)
  return (
    <>
      <ScopeLijst items={ITEMS} geselecteerd={sel} onChange={setSel} oorspronkelijk={oorspronkelijk} vergrendeld={vergrendeld} />
      <output data-testid="stand">{[...sel].sort().join(',')}</output>
    </>
  )
}

function rijNamen(): string[] {
  return screen.getAllByTestId('scope-rij').map((r) => r.querySelector('span.truncate')?.textContent ?? '')
}

describe('ScopeLijst — helpers', () => {
  it('sorteert alfabetisch (nl, accent-ongevoelig) met gearchiveerd als blok onderaan', () => {
    expect(sorteerScopeItems(ITEMS).map((i) => i.id)).toEqual(['a', 'b', 'e', 'm', 'z', 'oud'])
  })
  it('berekenVerschil + verschilTekst: "+3 −1", alleen de niet-nul-delen, leeg zonder verschil', () => {
    const v = berekenVerschil(['a', 'b'], ['b', 'c', 'd', 'e'])
    expect(v).toEqual({ erbij: ['c', 'd', 'e'], eraf: ['a'] })
    expect(verschilTekst(v)).toBe('+3 −1')
    expect(verschilTekst(berekenVerschil([], ['a']))).toBe('+1')
    expect(verschilTekst(berekenVerschil(['a', 'b'], []))).toBe('−2')
    expect(verschilTekst(berekenVerschil(['a'], ['a']))).toBe('')
  })
  it('namenOpsomming: max 10 namen, daarna "en N andere"', () => {
    const namen = Array.from({ length: 13 }, (_, i) => `BV ${i + 1}`)
    expect(namenOpsomming(namen.slice(0, 3))).toBe('BV 1, BV 2, BV 3')
    expect(namenOpsomming(namen)).toBe('BV 1, BV 2, BV 3, BV 4, BV 5, BV 6, BV 7, BV 8, BV 9, BV 10 en 3 andere')
    expect(namenOpsomming(namen.slice(0, 11))).toMatch(/en 1 andere$/)
  })
})

describe('ScopeLijst — component', () => {
  it('toont álle administraties alfabetisch, gearchiveerd onderaan mét chip, en een teller "N van M geselecteerd"', () => {
    render(<Harnas start={['z', 'oud']} />)
    expect(rijNamen()).toEqual([
      'Akkerman Holding B.V.',
      'Baard Vastgoed B.V.',
      'Élan Exploitatie B.V.',
      'Molenhof Verhuur B.V.',
      'Zilver Beheer B.V.',
      'Oud Derva B.V.',
    ])
    const laatste = screen.getAllByTestId('scope-rij').at(-1)!
    expect(within(laatste).getByText('gearchiveerd')).toBeInTheDocument()
    expect(screen.getByTestId('scope-teller')).toHaveTextContent('2 van 6 geselecteerd')
    expect(screen.getByRole('checkbox', { name: 'Zilver Beheer B.V.' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Oud Derva B.V. — gearchiveerd' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Akkerman Holding B.V.' })).not.toBeChecked()
    // Min. 12 rijen zichtbaar: de lijsthoogte is nooit kleiner dan 12 × rijhoogte.
    expect(screen.getByTestId('scope-lijst-rijen').style.minHeight).toBe(`${SCOPELIJST_MIN_RIJEN * SCOPELIJST_RIJHOOGTE_PX}px`)
    expect(screen.getByTestId('scope-lijst-rijen')).toHaveAttribute('data-min-rijen', '12')
  })

  it('aanvinken markeert de rij (chip-kleur) maar hersorteert NIET — de lijst springt niet', async () => {
    const g = userEvent.setup()
    render(<Harnas />)
    const voor = rijNamen()
    await g.click(screen.getByRole('checkbox', { name: 'Zilver Beheer B.V.' }))
    expect(rijNamen()).toEqual(voor)
    const zilver = screen.getAllByTestId('scope-rij').find((r) => r.textContent?.includes('Zilver'))!
    expect(zilver).toHaveAttribute('data-geselecteerd', 'ja')
    expect(zilver.className).toContain('bg-accent-bg')
    expect(screen.getByTestId('stand')).toHaveTextContent('z')
    expect(screen.getByTestId('scope-teller')).toHaveTextContent('1 van 6 geselecteerd')
  })

  it('zoekveld filtert accent-ongevoelig; niets gevonden = leesbare lege stand', async () => {
    const g = userEvent.setup()
    render(<Harnas />)
    await g.type(screen.getByRole('textbox', { name: 'Zoek administratie…' }), 'elan')
    expect(rijNamen()).toEqual(['Élan Exploitatie B.V.'])
    await g.clear(screen.getByRole('textbox', { name: 'Zoek administratie…' }))
    await g.type(screen.getByRole('textbox', { name: 'Zoek administratie…' }), 'xyz')
    expect(screen.queryAllByTestId('scope-rij')).toHaveLength(0)
    expect(screen.getByText('Geen administratie gevonden voor "xyz".')).toBeInTheDocument()
  })

  it('filter "alleen geselecteerde" toont enkel de aangevinkte rijen; een uitgevinkte rij verdwijnt dan uit het zicht', async () => {
    const g = userEvent.setup()
    render(<Harnas start={['a', 'm']} />)
    await g.click(screen.getByRole('checkbox', { name: 'alleen geselecteerde' }))
    expect(rijNamen()).toEqual(['Akkerman Holding B.V.', 'Molenhof Verhuur B.V.'])
    await g.click(screen.getByRole('checkbox', { name: 'Molenhof Verhuur B.V.' }))
    expect(rijNamen()).toEqual(['Akkerman Holding B.V.'])
    await g.click(screen.getByRole('checkbox', { name: 'Akkerman Holding B.V.' }))
    expect(screen.getByText('Nog niets geselecteerd.')).toBeInTheDocument()
  })

  it('"Alles" vinkt alle zichtbare ACTIEVE rijen aan (gearchiveerd nooit in bulk) en volgt het zoekfilter', async () => {
    const g = userEvent.setup()
    render(<Harnas />)
    await g.click(screen.getByRole('button', { name: 'Alles selecteren' }))
    expect(screen.getByTestId('stand')).toHaveTextContent('a,b,e,m,z')
    expect(screen.getByRole('checkbox', { name: 'Oud Derva B.V. — gearchiveerd' })).not.toBeChecked()
    expect(screen.getByRole('button', { name: 'Alles selecteren' })).toBeDisabled()
  })

  it('"Alles" binnen een zoekterm raakt alleen de gevonden rijen', async () => {
    const g = userEvent.setup()
    render(<Harnas />)
    await g.type(screen.getByRole('textbox', { name: 'Zoek administratie…' }), 'ba')
    await g.click(screen.getByRole('button', { name: 'Alles selecteren' }))
    expect(screen.getByTestId('stand')).toHaveTextContent(/^b$/)
  })

  it('"Geen" zonder eerdere scope haalt direct alles weg; mét eerdere scope eerst een bevestiging (RLS: geen scope = niets zien)', async () => {
    const g = userEvent.setup()
    const { unmount } = render(<Harnas start={['a', 'z']} oorspronkelijk={[]} />)
    await g.click(screen.getByRole('button', { name: 'Geen selecteren' }))
    expect(screen.queryByTestId('bevestig-dialoog')).not.toBeInTheDocument()
    expect(screen.getByTestId('stand')).toHaveTextContent('')
    unmount()

    render(<Harnas start={['a', 'z']} />)
    await g.click(screen.getByRole('button', { name: 'Geen selecteren' }))
    const dialoog = await screen.findByTestId('bevestig-dialoog')
    expect(dialoog).toHaveTextContent('Alle administraties uit de selectie halen?')
    expect(dialoog).toHaveTextContent(/RLS/)
    // Annuleren = niets gebeurd.
    await g.click(within(dialoog).getByRole('button', { name: 'Annuleren' }))
    expect(screen.getByTestId('stand')).toHaveTextContent('a,z')
    await g.click(screen.getByRole('button', { name: 'Geen selecteren' }))
    await g.click(within(await screen.findByTestId('bevestig-dialoog')).getByRole('button', { name: 'Bevestigen' }))
    expect(screen.getByTestId('stand')).toHaveTextContent('')
    expect(screen.getByRole('button', { name: 'Geen selecteren' })).toBeDisabled()
  })

  it('vergrendelde rijen (accordeur-variant "heeft al toegang") zijn aangevinkt + uitgeschakeld, tellen apart en blijven bij Alles/Geen buiten schot', async () => {
    const g = userEvent.setup()
    render(<Harnas vergrendeld={new Set(['a', 'oud'])} />)
    expect(screen.getByTestId('scope-teller')).toHaveTextContent('0 van 4 geselecteerd · 2 hebben al toegang')
    expect(screen.getByRole('checkbox', { name: 'Akkerman Holding B.V.' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Akkerman Holding B.V.' })).toBeDisabled()
    expect(screen.getAllByText('heeft al toegang')).toHaveLength(2)
    await g.click(screen.getByRole('button', { name: 'Alles selecteren' }))
    expect(screen.getByTestId('stand')).toHaveTextContent('b,e,m,z')
    await g.click(screen.getByRole('button', { name: 'Geen selecteren' }))
    expect(screen.getByTestId('stand')).toHaveTextContent('')
    expect(screen.getByRole('checkbox', { name: 'Akkerman Holding B.V.' })).toBeChecked()
  })

  it('pijl-omlaag vanuit het zoekveld zet de focus op de eerste rij (sneltoets-vriendelijk)', async () => {
    const g = userEvent.setup()
    render(<Harnas />)
    const zoek = screen.getByRole('textbox', { name: 'Zoek administratie…' })
    await g.click(zoek)
    await g.keyboard('{ArrowDown}')
    expect(screen.getByRole('checkbox', { name: 'Akkerman Holding B.V.' })).toHaveFocus()
    await g.keyboard(' ')
    expect(screen.getByTestId('stand')).toHaveTextContent('a')
  })
})
