/** "Corrigeren…" (opdracht Peter 21-09): de dialoog haalt de poort-toets op, toont per blokkade de route (tegenboeken /
 * bank / opnieuw boeken) i.p.v. een knop die pas server-side faalt, eist een reden ≥ 5 tekens, meldt de uitkomst en
 * behandelt een 409 "al gecorrigeerd" als klaar; de gele balk leest de laatste `gecorrigeerd`-tijdlijnregel en verdwijnt
 * zodra het document opnieuw geboekt is. */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { CorrigeerToetsDto, DocumentGebeurtenisDto } from '../api/types'
import { CorrectieBalk, CorrigerenDialog, corrigerenMogelijk, laatsteCorrectie } from './CorrigerenActie'

const ADMINISTRATIE_ID = 'dddddddd-0000-0000-0000-00000000000d'
const DOCUMENT_ID = 'aaaaaaaa-0000-0000-0000-00000000000a'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function toets(overrides: Partial<CorrigeerToetsDto> = {}): CorrigeerToetsDto {
  return {
    document_id: DOCUMENT_ID,
    soort: 'inkoopfactuur',
    backend: 'rlz',
    beschikbaar: true,
    blokkades: [],
    oud_boekstuknummer: 'RLZ-04-00000357',
    stukken: [{ label: 'inkoopfactuur', extern_id: DOCUMENT_ID, bestaat: true, nog_geboekt: true, boekstuknummer: 'RLZ-04-00000357', betaald_bedrag: '0' }],
    doorbelasting: [],
    tegenboeken_beschikbaar: false,
    ...overrides,
  }
}

function installMock(toetsBody: CorrigeerToetsDto, post?: () => Response) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/corrigeer-toets')) return Promise.resolve(jsonResponse(toetsBody))
    if (url.includes('/corrigeren') && init?.method === 'POST')
      return Promise.resolve(
        (post ??
          (() =>
            jsonResponse({
              document_id: DOCUMENT_ID,
              status: 'klaar_om_te_boeken',
              soort: 'inkoopfactuur',
              boek_cyclus: 1,
              oud_boekstuknummer: 'RLZ-04-00000357',
              oud_extern_id: DOCUMENT_ID,
              gestorneerd: [DOCUMENT_ID],
              al_concept: [],
              doorbelasting_gestorneerd: 0,
              doel_pad: `/documenten/${ADMINISTRATIE_ID}/${DOCUMENT_ID}`,
            })))(),
      )
    return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderDialoog(props: Partial<Parameters<typeof CorrigerenDialog>[0]> = {}) {
  const onGecorrigeerd = vi.fn()
  const onClose = vi.fn()
  const onTegenboeken = vi.fn()
  render(
    <MemoryRouter>
      <CorrigerenDialog
        administratieId={ADMINISTRATIE_ID}
        documentId={DOCUMENT_ID}
        soort="inkoopfactuur"
        open
        onClose={onClose}
        onGecorrigeerd={onGecorrigeerd}
        onTegenboeken={onTegenboeken}
        {...props}
      />
    </MemoryRouter>,
  )
  return { onGecorrigeerd, onClose, onTegenboeken }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('corrigerenMogelijk', () => {
  it('alleen op een geboekt document van een soort mét boekmotor', () => {
    expect(corrigerenMogelijk('geboekt', 'inkoopfactuur')).toBe(true)
    expect(corrigerenMogelijk('geboekt', 'kassarapport')).toBe(true)
    expect(corrigerenMogelijk('geboekt', 'verkoopfactuur')).toBe(true)
    expect(corrigerenMogelijk('geboekt', 'waarborg')).toBe(false)
    expect(corrigerenMogelijk('klaar_om_te_boeken', 'inkoopfactuur')).toBe(false)
  })
})

describe('CorrigerenDialog', () => {
  it('toont de vorige boeking, eist een reden en meldt de uitkomst', async () => {
    const fetchMock = installMock(toets())
    const { onGecorrigeerd, onClose } = renderDialoog()
    await waitFor(() => expect(screen.getByText('RLZ-04-00000357')).toBeInTheDocument())
    const knop = screen.getByRole('button', { name: 'Storneren en opnieuw klaarzetten' })
    expect(knop).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Reden (verplicht)'), { target: { value: 'kort' } })
    expect(knop).toBeDisabled()
    expect(screen.getByText(/minimaal 5 tekens/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Reden (verplicht)'), { target: { value: 'btw-bedrag stond op 48,18 in plaats van 56,93' } })
    expect(knop).toBeEnabled()
    fireEvent.click(knop)
    await waitFor(() => expect(onGecorrigeerd).toHaveBeenCalledTimes(1))
    expect(onGecorrigeerd.mock.calls[0][0]).toMatchObject({ status: 'klaar_om_te_boeken', boek_cyclus: 1 })
    expect(onClose).toHaveBeenCalled()
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')
    expect(post).toBeTruthy()
    expect(JSON.parse(String(post![1]!.body))).toEqual({ reden: 'btw-bedrag stond op 48,18 in plaats van 56,93' })
  })

  it('toont bij een aangifte-blokkade de route Tegenboeken… en geen reden-veld', async () => {
    installMock(
      toets({
        beschikbaar: false,
        tegenboeken_beschikbaar: true,
        blokkades: [
          {
            code: 'aangifte',
            melding: 'Storno van de inkoopfactuur is geblokkeerd door de btw-aangifte (boekdatum 2026-06-22 valt in de ingediende btw-aangifte 2026-04-01 t/m 2026-06-30) — gebruik Tegenboeken…',
            actie: 'tegenboeken',
            actie_pad: null,
          },
        ],
      }),
    )
    const { onTegenboeken, onClose } = renderDialoog()
    await waitFor(() => expect(screen.getByTestId('corrigeren-blokkades')).toBeInTheDocument())
    expect(screen.getByText(/geblokkeerd door de btw-aangifte/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Reden (verplicht)')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Tegenboeken…' }))
    expect(onTegenboeken).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalled()
  })

  it('toont bij een afgeletterd-blokkade de link naar de bankmodule', async () => {
    installMock(
      toets({
        beschikbaar: false,
        blokkades: [
          {
            code: 'afgeletterd',
            melding: 'De inkoopfactuur is (deels) betaald/afgeletterd (€ 121.00) — draai eerst het afletteren terug in de bankmodule',
            actie: 'bank',
            actie_pad: `/bank/${ADMINISTRATIE_ID}?zoek=Fac-25-023465`,
          },
        ],
      }),
    )
    renderDialoog()
    await waitFor(() => expect(screen.getByText(/afletteren terug/)).toBeInTheDocument())
    const link = screen.getByRole('link', { name: 'Naar de bankmodule →' })
    expect(link).toHaveAttribute('href', `/bank/${ADMINISTRATIE_ID}?zoek=Fac-25-023465`)
  })

  it('benoemt de doorbelasting die mee teruggaat', async () => {
    installMock(toets({ doorbelasting: [{ boeking_id: 'b1', doelentiteit: 'Molenhof Beheer', toegestaan: true, reden: null }] }))
    renderDialoog()
    await waitFor(() => expect(screen.getByTestId('corrigeren-doorbelasting')).toHaveTextContent('Molenhof Beheer'))
  })

  it('behandelt 409 al_gecorrigeerd als klaar (herladen, geen fout)', async () => {
    installMock(toets(), () => jsonResponse({ detail: { code: 'al_gecorrigeerd', bericht: 'al verwerkt', status: 'klaar_om_te_boeken' } }, 409))
    const { onGecorrigeerd } = renderDialoog()
    await waitFor(() => expect(screen.getByText('RLZ-04-00000357')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('Reden (verplicht)'), { target: { value: 'btw-bedrag fout' } })
    fireEvent.click(screen.getByRole('button', { name: 'Storneren en opnieuw klaarzetten' }))
    await waitFor(() => expect(onGecorrigeerd).toHaveBeenCalledWith(null))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('toont blokkades uit een 409 ná het indienen (poort veranderde intussen)', async () => {
    installMock(toets(), () =>
      jsonResponse(
        { detail: { code: 'verdwenen', bericht: 'x', blokkades: [{ code: 'verdwenen', melding: 'Het externe document bestaat niet meer — gebruik Opnieuw boeken', actie: 'opnieuw_boeken', actie_pad: '/reconciliatie' }] } },
        409,
      ),
    )
    const { onGecorrigeerd } = renderDialoog()
    await waitFor(() => expect(screen.getByText('RLZ-04-00000357')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('Reden (verplicht)'), { target: { value: 'btw-bedrag fout' } })
    fireEvent.click(screen.getByRole('button', { name: 'Storneren en opnieuw klaarzetten' }))
    await waitFor(() => expect(screen.getByTestId('corrigeren-blokkades')).toBeInTheDocument())
    expect(screen.getByRole('link', { name: 'Naar Inzicht › Reconciliatie →' })).toHaveAttribute('href', '/reconciliatie')
    expect(onGecorrigeerd).not.toHaveBeenCalled()
  })
})

function gebeurtenis(naar: string, detail: Record<string, unknown> | null, tijdstip: string): DocumentGebeurtenisDto {
  return { van_status: null, naar_status: naar, actor_id: 'u1', actor_is_systeem: false, detail, tijdstip }
}

const CORRECTIE = gebeurtenis(
  'klaar_om_te_boeken',
  { gecorrigeerd: { reden: 'btw-bedrag fout', oud_boekstuknummer: 'RLZ-04-00000357', gestorneerd: ['x'], al_concept: [], doorbelasting_teruggedraaid: ['Molenhof Beheer'] } },
  '2026-09-21T10:00:00Z',
)

describe('CorrectieBalk', () => {
  it('toont reden, vorige boeking en doorbelasting zolang het document niet opnieuw geboekt is', () => {
    render(<CorrectieBalk tijdlijn={[gebeurtenis('geboekt', null, '2026-09-20T10:00:00Z'), CORRECTIE]} status="klaar_om_te_boeken" />)
    const balk = screen.getByTestId('correctie-balk')
    expect(balk).toHaveTextContent('Gecorrigeerd')
    expect(balk).toHaveTextContent('btw-bedrag fout')
    expect(balk).toHaveTextContent('RLZ-04-00000357')
    expect(balk).toHaveTextContent('Molenhof Beheer')
  })

  it('verdwijnt ná de herboeking', () => {
    render(<CorrectieBalk tijdlijn={[CORRECTIE, gebeurtenis('geboekt', null, '2026-09-21T11:00:00Z')]} status="geboekt" />)
    expect(screen.queryByTestId('correctie-balk')).not.toBeInTheDocument()
    expect(laatsteCorrectie([CORRECTIE, gebeurtenis('geboekt', null, '2026-09-21T11:00:00Z')], 'te_controleren')).toBeNull()
  })
})
