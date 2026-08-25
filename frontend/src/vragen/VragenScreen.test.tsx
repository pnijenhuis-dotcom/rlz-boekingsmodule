import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { VragenScreen } from './VragenScreen'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const VRAAG_ID = 'cccccccc-0000-0000-0000-000000000003'
const EIGENAAR_ID = 'dddddddd-0000-0000-0000-000000000004'
const STELLER_ID = 'eeeeeeee-0000-0000-0000-000000000005'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function vraag(overrides: Record<string, unknown> = {}) {
  return {
    id: VRAAG_ID,
    document_id: DOCUMENT_ID,
    document_bestandsnaam: 'scan_0034.pdf',
    document_status: 'vraag_open',
    totaalbedrag: '450.00',
    vraag_tekst: 'Weet jij van wie dit is?',
    status: 'open',
    status_voor_vraag: 'te_controleren',
    gesteld_door: STELLER_ID,
    gesteld_op: '2026-07-01T14:32:00Z',
    toegewezen_aan: EIGENAAR_ID,
    antwoord_tekst: null,
    beantwoord_door: null,
    beantwoord_op: null,
    ingetrokken_door: null,
    ingetrokken_op: null,
    ingetrokken_reden: null,
    aan_de_beurt: EIGENAAR_ID,
    afgehandeld_door: null,
    afgehandeld_op: null,
    berichten: [],
    mag_afhandelen: false,
    ...overrides,
  }
}

interface MockOpties {
  vragen?: unknown[]
  vragenNaMutatie?: unknown[]
  berichtAanroepen?: { url: string; body: unknown }[]
  afhandelAanroepen?: { url: string; body: unknown }[]
  intrekAanroepen?: { url: string; body: unknown }[]
}

function installFetchMock(opties: MockOpties) {
  let gemuteerd = false
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/auth/administraties')) {
        return Promise.resolve(jsonResponse({ administraties: [{ id: ADMINISTRATIE_ID, naam: 'Kempen Vastgoed B.V.' }] }))
      }
      if (url.endsWith('/medewerkers')) {
        return Promise.resolve(
          jsonResponse({
            medewerkers: [
              { id: EIGENAAR_ID, naam: 'M. de Boer' },
              { id: STELLER_ID, naam: 'P. Nijenhuis' },
            ],
          }),
        )
      }
      if (url.endsWith('/eigenaar')) {
        return Promise.resolve(jsonResponse({ eigenaar_gebruiker_id: EIGENAAR_ID }))
      }
      if (url.includes('/berichten') && init?.method === 'POST') {
        gemuteerd = true
        opties.berichtAanroepen?.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
        return Promise.resolve(jsonResponse(vraag({ aan_de_beurt: STELLER_ID })))
      }
      if (url.includes('/afhandelen') && init?.method === 'POST') {
        gemuteerd = true
        opties.afhandelAanroepen?.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
        return Promise.resolve(jsonResponse(vraag({ status: 'afgehandeld' })))
      }
      if (url.includes('/intrekken') && init?.method === 'POST') {
        gemuteerd = true
        opties.intrekAanroepen?.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
        return Promise.resolve(jsonResponse(vraag({ status: 'ingetrokken' })))
      }
      if (url.includes('/vragen')) {
        return Promise.resolve(
          jsonResponse({ vragen: gemuteerd ? (opties.vragenNaMutatie ?? []) : (opties.vragen ?? [vraag()]) }),
        )
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

function renderScherm() {
  return render(
    <MemoryRouter initialEntries={['/vragen']}>
      <VragenScreen />
    </MemoryRouter>,
  )
}

describe('VragenScreen (mockup #vragen)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('toont een open vraag met meta, bedrag, namen, vraagtekst en acties', async () => {
    installFetchMock({ vragen: [vraag()] })
    renderScherm()

    await waitFor(() => expect(screen.getByText(/scan_0034\.pdf/)).toBeInTheDocument())
    expect(screen.getByText('Open')).toBeInTheDocument()
    expect(screen.getByText(/€ 450,00/)).toBeInTheDocument()
    expect(screen.getByText(/gesteld door P\. Nijenhuis/)).toBeInTheDocument()
    expect(screen.getAllByText('M. de Boer').length).toBeGreaterThan(0)
    expect(screen.getByText(/\(eigenaar administratie\)/)).toBeInTheDocument()
    expect(screen.getByText(/Weet jij van wie dit is\?/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reageren' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Factuur bekijken' })).toHaveAttribute(
      'href',
      `/documenten/${ADMINISTRATIE_ID}/${DOCUMENT_ID}`,
    )
    expect(screen.getByRole('button', { name: 'Intrekken…' })).toBeInTheDocument()
    // Niet de vraagsteller (server-hint mag_afhandelen=false) → geen Afgehandeld-knop.
    expect(screen.queryByRole('button', { name: 'Afgehandeld…' })).not.toBeInTheDocument()
  })

  it('reageren plaatst een bericht; de vraag blijft open en de thread toont auteur + tijd (nieuwste onderaan)', async () => {
    const gebruiker = userEvent.setup()
    const berichtAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({
      vragen: [vraag()],
      vragenNaMutatie: [
        vraag({
          aan_de_beurt: STELLER_ID,
          berichten: [
            { id: 'b1', auteur_id: EIGENAAR_ID, tekst: 'Zakelijk, boeken op 4560.', geplaatst_op: '2026-07-02T09:00:00Z' },
            { id: 'b2', auteur_id: STELLER_ID, tekst: 'En de btw?', geplaatst_op: '2026-07-02T09:05:00Z' },
          ],
        }),
      ],
      berichtAanroepen,
    })
    renderScherm()

    await waitFor(() => expect(screen.getByLabelText('Reactie')).toBeInTheDocument())
    const knop = screen.getByRole('button', { name: 'Reageren' })
    expect(knop).toBeDisabled()
    await gebruiker.type(screen.getByLabelText('Reactie'), 'Zakelijk, boeken op 4560.')
    await gebruiker.click(knop)

    await waitFor(() => expect(screen.getByText(/En de btw\?/)).toBeInTheDocument())
    expect(berichtAanroepen).toHaveLength(1)
    expect(berichtAanroepen[0].url).toContain(`/vragen/${VRAAG_ID}/berichten`)
    expect(berichtAanroepen[0].body).toEqual({ tekst: 'Zakelijk, boeken op 4560.' })
    // Blijft open (blokkeert boeken) en de beurt ligt weer bij de vraagsteller.
    expect(screen.getByText('Open')).toBeInTheDocument()
    expect(screen.getByText(/aan de beurt:/)).toBeInTheDocument()
    const berichten = screen.getAllByRole('listitem')
    expect(berichten).toHaveLength(3)
    expect(berichten[1]).toHaveTextContent('M. de Boer')
    expect(berichten[1]).toHaveTextContent('Zakelijk, boeken op 4560.')
    expect(berichten[2]).toHaveTextContent('En de btw?')
  })

  it('alleen de vraagsteller ziet "Afgehandeld…"; afhandelen sluit de thread en stuurt het slotbericht mee', async () => {
    const gebruiker = userEvent.setup()
    const afhandelAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({
      vragen: [vraag({ mag_afhandelen: true })],
      vragenNaMutatie: [
        vraag({ status: 'afgehandeld', afgehandeld_door: STELLER_ID, afgehandeld_op: '2026-07-02T10:00:00Z' }),
      ],
      afhandelAanroepen,
    })
    renderScherm()

    await waitFor(() => expect(screen.getByRole('button', { name: 'Afgehandeld…' })).toBeInTheDocument())
    await gebruiker.type(screen.getByLabelText('Reactie'), 'Dank, ik boek hem.')
    await gebruiker.click(screen.getByRole('button', { name: 'Afgehandeld…' }))
    await gebruiker.click(screen.getByRole('button', { name: 'Vraag afgehandeld' }))

    await waitFor(() => expect(screen.getByText('Afgehandeld')).toBeInTheDocument())
    expect(afhandelAanroepen).toHaveLength(1)
    expect(afhandelAanroepen[0].url).toContain(`/vragen/${VRAAG_ID}/afhandelen`)
    expect(afhandelAanroepen[0].body).toEqual({ slotbericht: 'Dank, ik boek hem.' })
    expect(screen.getByText(/afgehandeld door P\. Nijenhuis/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reageren' })).not.toBeInTheDocument()
  })

  it('intrekken stuurt de optionele reden en toont daarna de ingetrokken-historie', async () => {
    const gebruiker = userEvent.setup()
    const intrekAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({
      vragen: [vraag()],
      vragenNaMutatie: [
        vraag({
          status: 'ingetrokken',
          ingetrokken_door: STELLER_ID,
          ingetrokken_op: '2026-07-02T09:00:00Z',
          ingetrokken_reden: 'Verkeerd document',
        }),
      ],
      intrekAanroepen,
    })
    renderScherm()

    await waitFor(() => expect(screen.getByRole('button', { name: 'Intrekken…' })).toBeInTheDocument())
    await gebruiker.click(screen.getByRole('button', { name: 'Intrekken…' }))
    await gebruiker.type(screen.getByLabelText('Reden van intrekken'), 'Verkeerd document')
    await gebruiker.click(screen.getByRole('button', { name: 'Vraag intrekken' }))

    await waitFor(() => expect(screen.getByText('Ingetrokken')).toBeInTheDocument())
    expect(intrekAanroepen).toHaveLength(1)
    expect(intrekAanroepen[0].url).toContain(`/vragen/${VRAAG_ID}/intrekken`)
    expect(intrekAanroepen[0].body).toEqual({ reden: 'Verkeerd document' })
    expect(screen.getByText(/ingetrokken door P\. Nijenhuis/)).toBeInTheDocument()
  })

  it('een weesvraag (document verwijderd) toont geen acties maar wel de uitleg', async () => {
    installFetchMock({ vragen: [vraag({ document_status: 'verwijderd' })] })
    renderScherm()

    await waitFor(() => expect(screen.getByText(/scan_0034\.pdf/)).toBeInTheDocument())
    expect(screen.getByText(/Het document is verwijderd/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reageren' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Intrekken…' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Factuur bekijken' })).not.toBeInTheDocument()
  })

  it('een legacy-beantwoorde vraag is historie: antwoord als laatste bericht, geen actieknoppen', async () => {
    installFetchMock({
      vragen: [
        vraag({
          status: 'beantwoord',
          document_status: 'te_controleren',
          antwoord_tekst: 'Zakelijk, boeken op 4560.',
          beantwoord_door: EIGENAAR_ID,
          beantwoord_op: '2026-07-02T09:00:00Z',
          // De backend spiegelt het legacy-antwoord als laatste bericht van de thread.
          berichten: [
            { id: VRAAG_ID, auteur_id: EIGENAAR_ID, tekst: 'Zakelijk, boeken op 4560.', geplaatst_op: '2026-07-02T09:00:00Z' },
          ],
        }),
      ],
    })
    renderScherm()

    await waitFor(() => expect(screen.getByText('Beantwoord')).toBeInTheDocument())
    expect(screen.getByText(/Zakelijk, boeken op 4560\./)).toBeInTheDocument()
    expect(screen.getByText(/beantwoord door M\. de Boer/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reageren' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Intrekken…' })).not.toBeInTheDocument()
  })
})
