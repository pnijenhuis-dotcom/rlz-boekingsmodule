// "+ Doelentiteit toevoegen" (mockup doorbelasting-doel-toevoegen.html, 01-09): kandidaat-doelen
// als doorzoekbare combobox, debiteur-lookup mét expliciete bevestiging op een (bijna-)match —
// de Mantelzorg-les: nooit stil koppelen — of het aanmaak-pad (idempotent, bij opslaan), en de
// vooringevulde provisie-GB op rekeningcode.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DoelToevoegenDialog } from './DoelToevoegenDialog'

const BRON_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOEL_ID = 'aaaaaaaa-0000-0000-0000-000000000002'
const LEDGER_4808 = '99999999-0000-0000-0000-000000000005'
const MANTELZORG_GUID = '90dbadcb-5066-4822-a374-0b454a4a9180'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function installFetchMock(opties: {
  matches?: unknown[]
  aanmaakAanroepen?: { url: string; body: unknown }[]
} = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url === `/doorbelasting/${BRON_ID}/mappings/kandidaat-doelen`) {
        return Promise.resolve(
          jsonResponse({
            kandidaten: [{ id: DOEL_ID, naam: 'Mantelzorgwoningen Midden Nederland' }],
            provisie_voorstel: { code: '4808', naam: 'Provisie Kempen Facilities' },
          }),
        )
      }
      if (url === `/doorbelasting/${BRON_ID}/mappings/debiteur-lookup`) {
        return Promise.resolve(jsonResponse({ matches: opties.matches ?? [] }))
      }
      if (url === `/doorbelasting/${BRON_ID}/mappings` && init?.method === 'POST') {
        opties.aanmaakAanroepen?.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
        return Promise.resolve(
          jsonResponse({
            id: 'dddddddd-0000-0000-0000-000000000009',
            doelentiteit_naam: 'x',
            doel_customer_guid: MANTELZORG_GUID,
            doel_administratie_id: DOEL_ID,
            intercompany: true,
            provisie_kosten_ledger_id: LEDGER_4808,
            laatste_kosten_ledger_id: null,
            actief: true,
          }),
        )
      }
      if (url === `/administraties/${DOEL_ID}/grootboek`) {
        return Promise.resolve(
          jsonResponse({
            rekeningen: [
              { ledger_id: LEDGER_4808, code: '4808', naam: 'Provisie Kempen Facilities' },
              { ledger_id: '99999999-0000-0000-0000-000000000006', code: '4173', naam: 'Provisie algemeen' },
            ],
          }),
        )
      }
      return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
    }),
  )
}

async function kiesDoel(gebruiker: ReturnType<typeof userEvent.setup>) {
  await gebruiker.click(await screen.findByRole('combobox', { name: /Doel-administratie/ }))
  await gebruiker.click(await screen.findByRole('option', { name: 'Mantelzorgwoningen Midden Nederland' }))
}

describe('DoelToevoegenDialog', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('geen match: aanmaak-pad aangekondigd, provisie-GB vooringevuld op code, opslaan zonder guid', async () => {
    const aanmaakAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ matches: [], aanmaakAanroepen })
    render(
      <DoelToevoegenDialog administratieId={BRON_ID} bronNaam="Kempen Facilities B.V." onSluiten={vi.fn()} onToegevoegd={vi.fn()} />,
    )
    const gebruiker = userEvent.setup()
    await kiesDoel(gebruiker)

    expect(await screen.findByText(/wordt bij opslaan idempotent\s+aangemaakt in RLZ/)).toBeInTheDocument()
    // Provisie-GB vooringevuld met de code van de bestaande rijen (mockup ③).
    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: 'Provisie-GB in Mantelzorgwoningen Midden Nederland' })).toHaveValue(
        '4808 · Provisie Kempen Facilities',
      ),
    )

    await gebruiker.click(screen.getByRole('button', { name: 'Toevoegen aan whitelist' }))
    await waitFor(() => expect(aanmaakAanroepen).toHaveLength(1))
    expect(aanmaakAanroepen[0].body).toEqual({
      doel_administratie_id: DOEL_ID,
      doelentiteit_naam: 'Mantelzorgwoningen Midden Nederland',
      doel_customer_guid: null,
      provisie_kosten_ledger_id: LEDGER_4808,
      intercompany: true,
    })
  })

  it('bijna-match (Mantelzorg-les): opslaan kan pas ná expliciete bevestiging, RLZ-naam wint', async () => {
    const aanmaakAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({
      matches: [
        {
          customer_guid: MANTELZORG_GUID,
          naam: 'Mantelzorgwoning Midden Nederland B.V.',
          exact: false,
          kaart: { plaats: 'Amersfoort' },
        },
      ],
      aanmaakAanroepen,
    })
    render(
      <DoelToevoegenDialog administratieId={BRON_ID} bronNaam="Kempen Facilities B.V." onSluiten={vi.fn()} onToegevoegd={vi.fn()} />,
    )
    const gebruiker = userEvent.setup()
    await kiesDoel(gebruiker)

    // De naam staat in de match-rij én in de bevestigingsvink (één match = voorgeselecteerd).
    expect(await screen.findAllByText('Mantelzorgwoning Midden Nederland B.V.')).not.toHaveLength(0)
    expect(screen.getByText(/bijna-match — controleer/)).toBeInTheDocument()
    // Zonder de bevestigingsvink blijft de knop dicht — nooit stil koppelen.
    const knop = screen.getByRole('button', { name: 'Toevoegen aan whitelist' })
    expect(knop).toBeDisabled()
    await gebruiker.click(screen.getByLabelText('Bevestig dat dit dezelfde entiteit is'))
    await waitFor(() => expect(knop).toBeEnabled())
    await gebruiker.click(knop)

    await waitFor(() => expect(aanmaakAanroepen).toHaveLength(1))
    const body = aanmaakAanroepen[0].body as { doelentiteit_naam: string; doel_customer_guid: string }
    expect(body.doel_customer_guid).toBe(MANTELZORG_GUID)
    expect(body.doelentiteit_naam).toBe('Mantelzorgwoning Midden Nederland B.V.')
  })
})
