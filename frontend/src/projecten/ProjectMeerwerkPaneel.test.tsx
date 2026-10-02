/** Punt 12 run A (Peter 02-10): blok "Meerwerk" op de projectpagina — álle meldingen van het project mét status uit
 * dezelfde route/definitie als Beoordelen › Meerwerk (`?project_id=`), server-volgorde (nieuwste bovenaan), klik = bon
 * (punt 10); 403 = eerlijke zin, leeg = context + ingang. */
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ProjectMeerwerkPaneel } from './ProjectMeerwerkPaneel'

const ADM = 'aaaaaaaa-0000-0000-0000-000000000001'
const PROJECT = 'cccccccc-0000-0000-0000-000000000001'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const MW = (id: string, status: string, gemeldOp: string, extra: Record<string, unknown> = {}) => ({
  id,
  administratie_id: ADM,
  project_id: PROJECT,
  project_naam: '26149 Nijmegen (Dura Vermeer)',
  omschrijving: `Omschrijving ${id}`,
  aantal: '12',
  eenheid: 'm2',
  datum_uitgevoerd: '2026-09-28',
  in_opdracht_van: null,
  heeft_foto: false,
  foto_bestandsnaam: null,
  gemeld_door_naam: 'Irfan',
  gemeld_op: gemeldOp,
  status,
  prijs_per_eenheid: null,
  bedrag: null,
  facturatie_notitie: null,
  beoordeeld_op: null,
  beoordeeld_door_naam: null,
  afwijs_reden: null,
  doorbelast_op: null,
  verkoopfactuur_referentie: null,
  vraag_tekst: null,
  vraag_gesteld_op: null,
  vraag_antwoord: null,
  vraag_beantwoord_op: null,
  ...extra,
})

function installMock(antwoord: { body: unknown; status?: number }, urls: string[] = []) {
  vi.stubGlobal(
    'fetch',
    vi.fn((invoer: RequestInfo | URL) => {
      urls.push(String(invoer))
      return Promise.resolve(jsonResponse(antwoord.body, antwoord.status ?? 200))
    }),
  )
}

function renderPaneel() {
  return render(
    <MemoryRouter>
      <ProjectMeerwerkPaneel administratieId={ADM} projectId={PROJECT} />
    </MemoryRouter>,
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('ProjectMeerwerkPaneel (punt 12 run A)', () => {
  it('leest dezelfde route mét project_id, toont álle statussen in server-volgorde en linkt elke rij naar de bon', async () => {
    const urls: string[] = []
    installMock(
      {
        body: [
          MW('d', 'afgewezen', '2026-10-01T10:00:00Z', { afwijs_reden: 'eigen rekening' }),
          MW('c', 'doorbelast', '2026-09-30T10:00:00Z', { verkoopfactuur_referentie: 'VF-26149-3' }),
          MW('b', 'goedgekeurd', '2026-09-29T10:00:00Z'),
          MW('a', 'gemeld', '2026-09-28T10:00:00Z'),
        ],
      },
      urls,
    )
    renderPaneel()
    const tabel = await screen.findByTestId('meerwerk-tabel')
    expect(urls).toEqual([`/uren/kantoor/meerwerk?administratie_id=${ADM}&project_id=${PROJECT}`])
    expect(screen.getByRole('heading', { name: /^Meerwerk \(4\)/ })).toBeInTheDocument()
    // Server-volgorde (nieuwste bovenaan) blijft staan — de UI sorteert niet opnieuw.
    const rijen = within(tabel).getAllByTestId(/^meerwerk-rij-/)
    expect(rijen.map((r) => r.getAttribute('data-testid'))).toEqual(['meerwerk-rij-d', 'meerwerk-rij-c', 'meerwerk-rij-b', 'meerwerk-rij-a'])
    // Alle vier statussen zichtbaar, zelfde badge-teksten als Beoordelen › Meerwerk.
    expect(within(tabel).getByText('afgewezen · eigen rekening')).toBeInTheDocument()
    expect(within(tabel).getByText('doorbelast · VF-26149-3')).toBeInTheDocument()
    expect(within(tabel).getByText('nog doorbelasten')).toBeInTheDocument()
    expect(within(tabel).getByText('gemeld')).toBeInTheDocument()
    expect(within(tabel).getByText('reden: eigen rekening')).toBeInTheDocument()
    // Tellers per status in de kop.
    expect(screen.getByTestId('meerwerk-teller-gemeld')).toHaveTextContent('1 gemeld — te beoordelen')
    expect(screen.getByTestId('meerwerk-teller-doorbelast')).toHaveTextContent('1 doorbelast (gefactureerd)')
    // Klik = bon (punt 10): Beoordelen › Meerwerk met die bon open.
    expect(screen.getByTestId('meerwerk-bon-c')).toHaveAttribute('href', `/meerwerk?administratie=${ADM}&tab=meerwerk&meerwerk=c`)
    expect(screen.getByTestId('meerwerk-bon-c')).toHaveClass('linkbtn')
  })

  it('leeg = context + ingang naar Beoordelen; 403 = eerlijke zin over het module-recht', async () => {
    installMock({ body: [] })
    renderPaneel()
    await waitFor(() => expect(screen.getByTestId('meerwerk-leeg')).toBeInTheDocument())
    expect(screen.getByRole('link', { name: 'Beoordelen › Meerwerk →' })).toHaveAttribute('href', `/meerwerk?administratie=${ADM}&tab=meerwerk`)
    cleanup()
    installMock({ body: { detail: 'Vereist het module-recht' }, status: 403 })
    renderPaneel()
    await waitFor(() => expect(screen.getByTestId('meerwerk-geen-recht')).toBeInTheDocument())
    expect(screen.queryByTestId('meerwerk-leeg')).toBeNull()
  })
})
