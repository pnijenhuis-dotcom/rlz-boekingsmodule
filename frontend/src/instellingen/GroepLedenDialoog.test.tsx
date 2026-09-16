import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AdministratieInstellingenDto, GroepDto } from '../api/types'
import { GroepLedenDialoog, groepLedenItems, verhuisTekst } from './GroepLedenDialoog'

/** Bulk-toewijzing groepen 16-09 (Peter: "nu moet ik 1 voor 1 doen"): dialoog "Administraties toevoegen…" per groep op de
 * vinkjeslijst van de scope-dialoog — al-toegewezen aangevinkt, leden van een andere groep mét chip, Opslaan "+N −M",
 * verhuizen mét bevestiging, één PUT /groepen/{id}/administraties. */

const KG: GroepDto = { id: 'g-kg', naam: 'Kempen groep', code: 'KEMPENGROEP', actief: true, aantal_administraties: 1 }

function administratie(id: string, naam: string, over: Partial<AdministratieInstellingenDto> = {}): AdministratieInstellingenDto {
  return {
    id,
    naam,
    boeken_ingeschakeld: true,
    project_verplicht: false,
    ai_extractie_ingeschakeld: true,
    eigenaar_gebruiker_id: null,
    is_vastgoed: false,
    verkoop_autoboeken_ingeschakeld: false,
    uren_meerwerk_ingeschakeld: false,
    uren_dagmax_uren: '12',
    afdelingen_ingeschakeld: false,
    voorraad_ingeschakeld: false,
    mini_voorraad_ingeschakeld: false,
    ...over,
  }
}

const ADMINS = [
  administratie('a-lid', 'Kempen Facilities B.V.', { groep_id: 'g-kg', groep_naam: 'Kempen groep' }),
  administratie('a-vrij', 'Kempen B.V.'),
  administratie('a-vgg', 'Vastgoedgroep Nederland B.V.', { groep_id: 'g-vgg', groep_naam: 'Vastgoedgroep' }),
  administratie('a-oud', 'Oud Derva B.V.', { gearchiveerd_op: '2026-01-01T00:00:00Z' }),
]

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

afterEach(() => vi.unstubAllGlobals())

describe('groepLedenItems / verhuisTekst', () => {
  it('leden aangevinkt, andere groep als notitie, gearchiveerd inactief', () => {
    const { items, leden, andereGroep } = groepLedenItems(KG, ADMINS)
    expect(leden).toEqual(['a-lid'])
    expect(items.find((i) => i.id === 'a-vgg')?.notitie).toBe('groep: Vastgoedgroep')
    expect(items.find((i) => i.id === 'a-vrij')?.notitie).toBeUndefined()
    expect(items.find((i) => i.id === 'a-oud')?.actief).toBe(false)
    expect(verhuisTekst(['a-vgg', 'a-vrij'], andereGroep)).toBe('1 administratie verhuist van groep Vastgoedgroep')
    expect(verhuisTekst(['a-vrij'], andereGroep)).toBe('')
  })
})

describe('GroepLedenDialoog', () => {
  it('aanvinken toont "+N −M", verhuizen vraagt bevestiging mét de oude groep, Opslaan = één PUT met toevoegen/verwijderen', async () => {
    const puts: { url: string; body: unknown }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url === '/groepen/g-kg/administraties' && init?.method === 'PUT') {
          puts.push({ url, body: JSON.parse(String(init.body)) })
          return Promise.resolve(
            json({
              groep: { ...KG, aantal_administraties: 2 },
              toegevoegd: 2,
              verwijderd: 1,
              rijen: [
                { administratie_id: 'a-vrij', naam: 'Kempen B.V.', uitkomst: 'toegevoegd', detail: null },
                { administratie_id: 'a-vgg', naam: 'Vastgoedgroep Nederland B.V.', uitkomst: 'verhuisd', detail: 'Vastgoedgroep' },
                { administratie_id: 'a-lid', naam: 'Kempen Facilities B.V.', uitkomst: 'verwijderd', detail: null },
              ],
            }),
          )
        }
        return Promise.resolve(new Response(null, { status: 404 }))
      }),
    )
    const onGewijzigd = vi.fn()
    const onSluiten = vi.fn()
    const gebruiker = userEvent.setup()
    render(<GroepLedenDialoog groep={KG} administraties={ADMINS} onSluiten={onSluiten} onGewijzigd={onGewijzigd} />)

    const dialoog = screen.getByTestId('groep-leden-dialoog')
    expect(dialoog).toHaveTextContent('Administraties in groep Kempen groep')
    // Al-toegewezen aangevinkt, lid van een andere groep mét chip, gearchiveerd onderaan.
    expect(screen.getByRole('checkbox', { name: 'Kempen Facilities B.V.' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Kempen B.V.' })).not.toBeChecked()
    expect(screen.getByTestId('scope-rij-notitie')).toHaveTextContent('groep: Vastgoedgroep')
    const namen = screen.getAllByTestId('scope-rij').map((r) => r.querySelector('span.truncate')?.textContent)
    expect(namen[namen.length - 1]).toBe('Oud Derva B.V.')
    const opslaan = screen.getByTestId('groep-leden-opslaan')
    expect(opslaan).toBeDisabled()

    await gebruiker.click(screen.getByRole('checkbox', { name: 'Kempen B.V.' }))
    await gebruiker.click(screen.getByRole('checkbox', { name: 'Vastgoedgroep Nederland B.V.' }))
    await gebruiker.click(screen.getByRole('checkbox', { name: 'Kempen Facilities B.V.' }))
    expect(opslaan).toHaveTextContent('Opslaan (+2 −1)')

    await gebruiker.click(opslaan)
    const bevestiging = screen.getAllByRole('dialog').at(-1)!
    expect(bevestiging).toHaveTextContent('Groep Kempen groep wijzigen (+2 −1)')
    expect(bevestiging).toHaveTextContent('1 administratie verhuist van groep Vastgoedgroep')
    expect(bevestiging).toHaveTextContent('Eruit (1): Kempen Facilities B.V.')
    expect(puts).toHaveLength(0)
    await gebruiker.click(within(bevestiging).getByRole('button', { name: 'Bevestigen' }))

    await waitFor(() => expect(puts).toHaveLength(1))
    expect(puts[0].body).toEqual({ toevoegen: ['a-vrij', 'a-vgg'], verwijderen: ['a-lid'] })
    await waitFor(() => expect(onGewijzigd).toHaveBeenCalled())
    expect(onGewijzigd.mock.calls[0][0].toegevoegd).toBe(2)
    expect(onSluiten).toHaveBeenCalled()
  })

  it('een 409 (gearchiveerde groep) blijft zichtbaar in de dialoog, niets wordt gesloten', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url === '/groepen/g-kg/administraties' && init?.method === 'PUT')
          return Promise.resolve(json({ detail: 'Groep Kempen groep is gearchiveerd — heractiveer ’m eerst of kies een andere.' }, 409))
        return Promise.resolve(new Response(null, { status: 404 }))
      }),
    )
    const onSluiten = vi.fn()
    const gebruiker = userEvent.setup()
    render(<GroepLedenDialoog groep={KG} administraties={ADMINS} onSluiten={onSluiten} onGewijzigd={vi.fn()} />)
    await gebruiker.click(screen.getByRole('checkbox', { name: 'Kempen B.V.' }))
    await gebruiker.click(screen.getByTestId('groep-leden-opslaan'))
    await gebruiker.click(within(screen.getAllByRole('dialog').at(-1)!).getByRole('button', { name: 'Bevestigen' }))
    expect(await screen.findByText(/is gearchiveerd/)).toBeInTheDocument()
    expect(onSluiten).not.toHaveBeenCalled()
  })
})
