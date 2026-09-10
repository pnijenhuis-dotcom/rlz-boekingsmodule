import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ScopeModal, scopeLijstItems } from './ScopeModal'
import type { GebruikerOverzichtDto } from './gebruikersApi'

/* Scope-dialoog (blok 2 nachtrun 10/11-09): ScopeLijst i.p.v. MultiSelect + chips; Opslaan toont het verschil
 * "+N −M" en bevestigt eerst mét namen; het verschil gaat via de BESTAANDE per-koppeling-routes (audit ongewijzigd). */

const GEBRUIKER_ID = 'bbbbbbbb-0000-0000-0000-00000000000b'
const A = 'dddddddd-0000-0000-0000-00000000000a'
const B = 'dddddddd-0000-0000-0000-00000000000b'
const C = 'dddddddd-0000-0000-0000-00000000000c'
const OUD = 'faae29c5-d197-4c24-a704-be2eae91fe49'

const ADMINISTRATIES = [
  { id: A, naam: 'Akkerman Holding B.V.' },
  { id: B, naam: 'Baard Vastgoed B.V.' },
  { id: C, naam: 'Coppens Beheer B.V.' },
]

function gebruiker(scope: string[]): GebruikerOverzichtDto {
  return {
    id: GEBRUIKER_ID,
    naam: 'Demi de Vries',
    e_mail: 'demi@ak-nijenhuis.nl',
    rol: 'boekhouding',
    status: 'actief',
    administratie_ids: scope,
    administraties: [
      ...ADMINISTRATIES.filter((a) => scope.includes(a.id)).map((a) => ({ ...a, actief: true })),
      ...(scope.includes(OUD) ? [{ id: OUD, naam: 'Odoo-testadministratie', actief: false }] : []),
    ],
    heeft_totp: true,
    aantal_passkeys: 0,
    open_uitnodiging_verloopt_op: null,
    open_herstel_verloopt_op: null,
    staande_goedkeuringen: 0,
    geblokkeerd_op: null,
    geblokkeerd_door_naam: null,
  } as unknown as GebruikerOverzichtDto
}

function installMock(aanroepen: { method: string; url: string; body: unknown }[], faalOp?: string) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/scope') && init?.method === 'POST') {
        const body = JSON.parse(String(init.body)) as { administratie_id: string }
        aanroepen.push({ method: 'POST', url, body })
        if (body.administratie_id === faalOp) {
          return Promise.resolve(
            new Response(JSON.stringify({ detail: 'Eigen scope wijzigen mag niet' }), { status: 403, headers: { 'Content-Type': 'application/json' } }),
          )
        }
        return Promise.resolve(new Response(null, { status: 204 }))
      }
      if (url.includes('/scope/') && init?.method === 'DELETE') {
        aanroepen.push({ method: 'DELETE', url, body: null })
        return Promise.resolve(new Response(null, { status: 204 }))
      }
      return Promise.reject(new Error(`onverwachte fetch ${init?.method ?? 'GET'} ${url}`))
    }),
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('scopeLijstItems', () => {
  it('= actieve administraties + gearchiveerde uit de scope (naam uit de DTO, nooit een GUID)', () => {
    const items = scopeLijstItems(gebruiker([A, OUD]), ADMINISTRATIES)
    expect(items.map((i) => [i.naam, i.actief])).toEqual([
      ['Akkerman Holding B.V.', true],
      ['Baard Vastgoed B.V.', true],
      ['Coppens Beheer B.V.', true],
      ['Odoo-testadministratie', false],
    ])
    // Een scope-id zonder naam in de DTO blijft zichtbaar, maar leesbaar.
    const kaal = { ...gebruiker([A]), administratie_ids: [A, 'onbekend-id'], administraties: undefined }
    expect(scopeLijstItems(kaal, ADMINISTRATIES).find((i) => i.id === 'onbekend-id')?.naam).toBe('onbekende administratie')
  })
})

describe('ScopeModal', () => {
  it('toont de lijst met de scope aangevinkt (gearchiveerd onderaan), Opslaan uit zonder verschil, daarna "Scope opslaan (+1 −1)"', async () => {
    const aanroepen: { method: string; url: string; body: unknown }[] = []
    installMock(aanroepen)
    const g = userEvent.setup()
    render(<ScopeModal gebruiker={gebruiker([A, OUD])} administraties={ADMINISTRATIES} onSluiten={() => undefined} onGewijzigd={() => undefined} />)
    const dialoog = screen.getByTestId('scope-dialoog')
    expect(dialoog).toHaveTextContent('Scope van Demi de Vries')
    // Geen chips-wolk meer.
    expect(dialoog.querySelector('.ms-gekozen')).toBeNull()
    expect(dialoog.querySelector('.ms')).toBeNull()
    expect(screen.getByTestId('scope-teller')).toHaveTextContent('2 van 4 geselecteerd')
    const rijen = screen.getAllByTestId('scope-rij')
    expect(rijen.at(-1)).toHaveTextContent('Odoo-testadministratie')
    expect(within(rijen.at(-1)!).getByText('gearchiveerd')).toBeInTheDocument()
    expect(screen.getByTestId('scope-opslaan')).toBeDisabled()
    expect(screen.getByTestId('scope-opslaan')).toHaveTextContent('Scope opslaan')

    await g.click(screen.getByRole('checkbox', { name: 'Baard Vastgoed B.V.' }))
    expect(screen.getByTestId('scope-opslaan')).toHaveTextContent('Scope opslaan (+1)')
    await g.click(screen.getByRole('checkbox', { name: 'Odoo-testadministratie — gearchiveerd' }))
    expect(screen.getByTestId('scope-opslaan')).toHaveTextContent('Scope opslaan (+1 −1)')
    expect(screen.getByTestId('scope-opslaan')).toBeEnabled()
    expect(aanroepen).toHaveLength(0)
  })

  it('Opslaan bevestigt eerst mét de namen (erbij/eraf) en voert dan het verschil door via POST …/scope en DELETE …/scope/{id}', async () => {
    const aanroepen: { method: string; url: string; body: unknown }[] = []
    installMock(aanroepen)
    const gewijzigd = vi.fn()
    const gesloten = vi.fn()
    const g = userEvent.setup()
    render(<ScopeModal gebruiker={gebruiker([A, OUD])} administraties={ADMINISTRATIES} onSluiten={gesloten} onGewijzigd={gewijzigd} />)
    await g.click(screen.getByRole('checkbox', { name: 'Baard Vastgoed B.V.' }))
    await g.click(screen.getByRole('checkbox', { name: 'Coppens Beheer B.V.' }))
    await g.click(screen.getByRole('checkbox', { name: 'Odoo-testadministratie — gearchiveerd' }))
    await g.click(screen.getByTestId('scope-opslaan'))

    const bevestig = await screen.findByTestId('bevestig-dialoog')
    expect(bevestig).toHaveTextContent('Scope van Demi de Vries wijzigen (+2 −1)')
    expect(bevestig).toHaveTextContent('Erbij (2): Baard Vastgoed B.V., Coppens Beheer B.V.')
    expect(bevestig).toHaveTextContent('Eraf (1): Odoo-testadministratie')
    expect(bevestig).toHaveTextContent(/geauditeerd/)
    expect(aanroepen).toHaveLength(0)

    await g.click(within(bevestig).getByRole('button', { name: 'Bevestigen' }))
    await waitFor(() => expect(gesloten).toHaveBeenCalled())
    expect(gewijzigd).toHaveBeenCalled()
    expect(aanroepen).toEqual([
      { method: 'POST', url: `/auth/gebruikers/${GEBRUIKER_ID}/scope`, body: { administratie_id: B } },
      { method: 'POST', url: `/auth/gebruikers/${GEBRUIKER_ID}/scope`, body: { administratie_id: C } },
      { method: 'DELETE', url: `/auth/gebruikers/${GEBRUIKER_ID}/scope/${OUD}`, body: null },
    ])
  })

  it('"Geen" vraagt bevestiging (er stond scope) en de opslaan-bevestiging waarschuwt dat de medewerker dan niets meer ziet', async () => {
    const aanroepen: { method: string; url: string; body: unknown }[] = []
    installMock(aanroepen)
    const g = userEvent.setup()
    render(<ScopeModal gebruiker={gebruiker([A, B])} administraties={ADMINISTRATIES} onSluiten={() => undefined} onGewijzigd={() => undefined} />)
    await g.click(screen.getByRole('button', { name: 'Geen selecteren' }))
    const geen = await screen.findByTestId('bevestig-dialoog')
    expect(geen).toHaveTextContent('Demi de Vries heeft nu toegang tot 2 administraties')
    await g.click(within(geen).getByRole('button', { name: 'Bevestigen' }))
    expect(screen.getByTestId('scope-teller')).toHaveTextContent('0 van 3 geselecteerd')
    expect(screen.getByTestId('scope-opslaan')).toHaveTextContent('Scope opslaan (−2)')
    await g.click(screen.getByTestId('scope-opslaan'))
    const bevestig = await screen.findByTestId('bevestig-dialoog')
    expect(bevestig).toHaveTextContent('LET OP: zonder scope ziet deze medewerker niets meer')
    expect(aanroepen).toHaveLength(0)
  })

  it('een geweigerde koppeling is zichtbaar (fout mét vervolgtekst), niets verdwijnt stil; de lijst wordt ververst', async () => {
    const aanroepen: { method: string; url: string; body: unknown }[] = []
    installMock(aanroepen, C)
    const gewijzigd = vi.fn()
    const gesloten = vi.fn()
    const g = userEvent.setup()
    render(<ScopeModal gebruiker={gebruiker([A])} administraties={ADMINISTRATIES} onSluiten={gesloten} onGewijzigd={gewijzigd} />)
    await g.click(screen.getByRole('checkbox', { name: 'Baard Vastgoed B.V.' }))
    await g.click(screen.getByRole('checkbox', { name: 'Coppens Beheer B.V.' }))
    await g.click(screen.getByTestId('scope-opslaan'))
    await g.click(within(await screen.findByTestId('bevestig-dialoog')).getByRole('button', { name: 'Bevestigen' }))
    await waitFor(() => expect(screen.getByTestId('scope-dialoog')).toHaveTextContent(/Eigen scope wijzigen mag niet — al doorgevoerde wijzigingen blijven staan/))
    expect(gesloten).not.toHaveBeenCalled()
    expect(gewijzigd).toHaveBeenCalled()
    expect(aanroepen.map((a) => a.method)).toEqual(['POST', 'POST'])
  })
})
