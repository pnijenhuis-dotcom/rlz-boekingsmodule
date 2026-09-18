import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it } from 'vitest'
import { Klantenlijst } from './Klantenlijst'
import { filterKlanten, klantMatcht, leesOnthoudenZoek, onthoudZoek } from './klantZoek'
import type { KlantRij } from './useWerkvoorraadData'

/** Zoekveld klantenlijst (Peter 18-09): client-side op naam/groep zonder diakrieten, teller "N van M", "/" focust,
 * leeg = alles, lege uitkomst = melding + wis-knop, werkt samen met het Groep-filter (dat server-side de rijen al
 * beperkt — hier: de zoekterm filtert de rijen die er zijn). */

function rij(id: string, naam: string, extra: Partial<KlantRij> = {}): KlantRij {
  return {
    administratie_id: id,
    naam,
    te_controleren: 1,
    klaar_om_te_boeken: 0,
    vragen: 0,
    afgewezen: 0,
    bij_klant: 0,
    iban_wachtend: 0,
    bank_open: 0,
    spiegel_taken: 0,
    ...extra,
  }
}

const KLANTEN = [
  rij('a1', 'Universal Steigerbouw B.V.'),
  rij('a2', 'Universal Nederland B.V.'),
  rij('a3', 'Universal Verkoop B.V.'),
  rij('a4', 'BLOW Apeldoorn B.V.'),
  rij('a5', 'Café Zürich Exploitatie'),
  rij('a6', 'Zonder werk', { te_controleren: 0 }),
]
const ADMINISTRATIES = [
  { id: 'a1', groep_naam: 'Universal groep' },
  { id: 'a4', groep_naam: 'Kempen groep' },
  { id: 'a5', groep_naam: null },
]

describe('klantZoek — filter', () => {
  it('filtert op naam zonder hoofdletters/diakrieten en met AND over termen', () => {
    expect(filterKlanten(KLANTEN, 'univ').map((k) => k.administratie_id)).toEqual(['a1', 'a2', 'a3'])
    expect(filterKlanten(KLANTEN, 'zurich').map((k) => k.administratie_id)).toEqual(['a5'])
    expect(filterKlanten(KLANTEN, 'universal verkoop').map((k) => k.administratie_id)).toEqual(['a3'])
    expect(filterKlanten(KLANTEN, '   ')).toBe(KLANTEN)
  })
  it('vindt óók op de groepsnaam (Groep-filter en zoekveld werken samen)', () => {
    expect(klantMatcht(KLANTEN[3], 'kempen', ADMINISTRATIES)).toBe(true)
    expect(klantMatcht(KLANTEN[3], 'kempen')).toBe(false)
    expect(filterKlanten(KLANTEN, 'groep', ADMINISTRATIES).map((k) => k.administratie_id)).toEqual(['a1', 'a4'])
  })
  it('onthoudt de laatste term per sessie en wist bij leeg', () => {
    onthoudZoek('univ')
    expect(leesOnthoudenZoek()).toBe('univ')
    onthoudZoek('')
    expect(leesOnthoudenZoek()).toBe('')
  })
})

function Harnas({ start = '' }: { start?: string }) {
  const [zoek, setZoek] = useState(start)
  return (
    <MemoryRouter>
      <Klantenlijst
        klanten={KLANTEN}
        fout={null}
        onHerlaad={() => {}}
        totaalAdministraties={KLANTEN.length}
        zoek={zoek}
        onZoek={setZoek}
        administraties={ADMINISTRATIES}
      />
    </MemoryRouter>
  )
}

describe('Klantenlijst — zoekveld', () => {
  afterEach(() => onthoudZoek(''))

  it('toont alle klanten mét werk en de teller "N van M"; typen filtert live', async () => {
    render(<Harnas />)
    expect(screen.getByTestId('klant-zoek-teller')).toHaveTextContent('5 van 5')
    await userEvent.type(screen.getByTestId('klant-zoekveld'), 'Univ')
    expect(screen.getByTestId('klant-zoek-teller')).toHaveTextContent('3 van 5')
    expect(screen.getAllByRole('row')).toHaveLength(1 + 3)
    expect(screen.queryByText('BLOW Apeldoorn B.V.')).not.toBeInTheDocument()
  })

  it('lege uitkomst = melding mét wis-knop (nooit een lege tabel zonder uitleg)', async () => {
    render(<Harnas start="xyzzy" />)
    expect(screen.getByTestId('klant-zoek-leeg')).toHaveTextContent('Geen administratie past bij "xyzzy"')
    await userEvent.click(screen.getByRole('button', { name: 'wis het zoekveld' }))
    expect(screen.getByTestId('klant-zoek-teller')).toHaveTextContent('5 van 5')
  })

  it('"/" zet de cursor in het zoekveld', async () => {
    render(<Harnas />)
    const veld = screen.getByTestId('klant-zoekveld')
    expect(veld).not.toHaveFocus()
    await userEvent.keyboard('/')
    expect(veld).toHaveFocus()
  })
})
