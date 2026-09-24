import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import type { VraagDto } from '../api/types'
import { VraagThread } from './VraagThread'

const ADM = 'aaaaaaaa-0000-0000-0000-000000000001'
const BARBARA = 'b0000000-0000-0000-0000-000000000001'
const SOPHIA = 's0000000-0000-0000-0000-000000000002'

function installeerLocalStorage() {
  const opslag = new Map<string, string>()
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: {
      getItem: (k: string) => opslag.get(k) ?? null,
      setItem: (k: string, v: string) => void opslag.set(k, String(v)),
      removeItem: (k: string) => void opslag.delete(k),
      clear: () => opslag.clear(),
    },
  })
}

function vraag(overrides: Partial<VraagDto> = {}): VraagDto {
  return {
    id: 'v1',
    document_id: 'd1',
    document_bestandsnaam: 'factuur.pdf',
    document_status: 'vraag_open',
    totaalbedrag: '100.00',
    vraag_tekst: 'Is dit meerwerk door u opgedragen?',
    status: 'open',
    status_voor_vraag: 'te_controleren',
    gesteld_door: BARBARA,
    gesteld_op: '2026-09-16T09:00:00Z',
    toegewezen_aan: SOPHIA,
    antwoord_tekst: null,
    beantwoord_door: null,
    beantwoord_op: null,
    ingetrokken_door: null,
    ingetrokken_op: null,
    ingetrokken_reden: null,
    aan_de_beurt: BARBARA,
    afgehandeld_door: null,
    afgehandeld_op: null,
    berichten: [
      { id: 'b1', auteur_id: SOPHIA, tekst: 'Ja, door mij.', geplaatst_op: '2026-09-16T10:00:00Z' },
      { id: 'b2', auteur_id: SOPHIA, tekst: 'Op 12-08, bon 4471.', geplaatst_op: '2026-09-16T10:01:00Z' },
    ],
    mag_afhandelen: false,
    laatste_bericht_door: SOPHIA,
    laatste_bericht_op: '2026-09-16T10:01:00Z',
    mag_afhandelen_namens: true,
    mag_heropenen: false,
    ...overrides,
  }
}

const naamVoor = (id: string | null) => (id === BARBARA ? 'Barbara' : id === SOPHIA ? 'Sophia' : '—')

function renderThread(v: VraagDto, onGewijzigd = vi.fn()) {
  render(
    <MemoryRouter>
      <VraagThread vraag={v} administratieId={ADM} naamVoor={naamVoor} onGewijzigd={onGewijzigd} />
    </MemoryRouter>,
  )
  return onGewijzigd
}

describe('VraagThread — documentlink volgt de soort (BUG 23-09, Van Boxtel Journaal 19-9.pdf)', () => {
  beforeAll(() => installeerLocalStorage())
  afterEach(() => {
    vi.unstubAllGlobals()
    window.localStorage.clear()
  })

  it('kassarapport: "Document bekijken" opent het omzetreview-scherm en "Naar omzetreview →" staat erbij', () => {
    renderThread(
      vraag({
        document_soort: 'kassarapport',
        vraag_tekst: 'Nieuwe rapportcategorie(ën) zonder GB/btw-mapping: Dranken, Edible … stel op het omzetreview-scherm de mapping in',
      }),
    )
    expect(screen.getByRole('link', { name: 'Document bekijken' })).toHaveAttribute('href', `/omzet/${ADM}/d1`)
    expect(screen.getByRole('link', { name: 'Naar omzetreview →' })).toHaveAttribute('href', `/omzet/${ADM}/d1`)
    expect(screen.queryByRole('link', { name: 'Factuur bekijken' })).not.toBeInTheDocument()
  })

  it('inkoopfactuur (ook zonder soort in de DTO): inkoop-controlescherm, geen omzetreview-knop', () => {
    renderThread(vraag({ document_soort: undefined }))
    expect(screen.getByRole('link', { name: 'Document bekijken' })).toHaveAttribute('href', `/documenten/${ADM}/d1`)
    expect(screen.queryByRole('link', { name: 'Naar omzetreview →' })).not.toBeInTheDocument()
  })

  it('vraag-tekst die naar het omzetreview-scherm verwijst krijgt de knop óók als de soort ontbreekt', () => {
    renderThread(vraag({ document_soort: null, vraag_tekst: 'Stel op het omzetreview-scherm de mapping in.' }))
    expect(screen.getByRole('link', { name: 'Naar omzetreview →' })).toHaveAttribute('href', `/omzet/${ADM}/d1`)
  })
})

describe('VraagThread — dialoog open tot Afgehandeld (Peter 16-09, casus Barbara → Sophia)', () => {
  beforeAll(() => installeerLocalStorage())
  afterEach(() => {
    vi.unstubAllGlobals()
    window.localStorage.clear()
  })

  it('toont twee berichten achter elkaar van dezelfde kant, de afgeleide stand en houdt het invoerveld open', async () => {
    const aanroepen: { url: string; body: unknown }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        aanroepen.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null })
        return Promise.resolve(new Response(JSON.stringify(vraag()), { status: 201, headers: { 'Content-Type': 'application/json' } }))
      }),
    )
    const onGewijzigd = renderThread(vraag())
    expect(screen.getByTestId('laatste-bericht')).toHaveTextContent('laatste bericht van Sophia')
    expect(screen.getAllByRole('listitem')).toHaveLength(3) // openingsvraag + 2 berichten van Sophia
    const veld = screen.getByLabelText('Reactie') as HTMLTextAreaElement
    expect(veld.tagName).toBe('TEXTAREA')
    // Enter = nieuwe regel (geen verzending); Cmd/Ctrl-Enter = versturen.
    await userEvent.type(veld, 'Dank!{Enter}Nog één vraag')
    expect(aanroepen).toHaveLength(0)
    expect(veld.value).toContain('\n')
    expect(window.localStorage.getItem('rlz.vraagconcept.v1')).toContain('Nog één vraag') // concept bewaard
    await userEvent.keyboard('{Control>}{Enter}{/Control}')
    await waitFor(() => expect(aanroepen).toHaveLength(1))
    expect(aanroepen[0].url).toContain('/vragen/v1/berichten')
    expect((aanroepen[0].body as { tekst: string }).tekst).toBe('Dank!\nNog één vraag')
    expect(onGewijzigd).toHaveBeenCalled()
    expect(window.localStorage.getItem('rlz.vraagconcept.v1')).toBeNull()
  })

  it('kantoor (niet-vraagsteller) ziet "Afgehandeld namens vraagsteller…" en stuurt de vlag mee', async () => {
    const aanroepen: { url: string; body: unknown }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        aanroepen.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null })
        return Promise.resolve(
          new Response(JSON.stringify(vraag({ status: 'afgehandeld' })), { status: 200, headers: { 'Content-Type': 'application/json' } }),
        )
      }),
    )
    renderThread(vraag())
    expect(screen.queryByRole('button', { name: 'Afgehandeld…' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Afgehandeld namens vraagsteller…' }))
    await userEvent.click(screen.getByRole('button', { name: 'Afgehandeld namens Barbara' }))
    await waitFor(() => expect(aanroepen).toHaveLength(1))
    expect(aanroepen[0].url).toContain('/vragen/v1/afhandelen')
    expect(aanroepen[0].body).toEqual({ slotbericht: null, namens_vraagsteller: true })
  })

  it('een afgehandelde vraag is alleen-lezen mét "Heropenen" als de server dat toestaat', async () => {
    const aanroepen: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        aanroepen.push(url)
        return Promise.resolve(new Response(JSON.stringify(vraag()), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      }),
    )
    renderThread(
      vraag({
        status: 'afgehandeld',
        document_status: 'te_controleren',
        afgehandeld_door: BARBARA,
        afgehandeld_op: '2026-09-16T11:00:00Z',
        mag_afhandelen_namens: false,
        mag_heropenen: true,
      }),
    )
    expect(screen.queryByLabelText('Reactie')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Heropenen' }))
    await waitFor(() => expect(aanroepen).toHaveLength(1))
    expect(aanroepen[0]).toContain('/vragen/v1/heropenen')
  })
})
