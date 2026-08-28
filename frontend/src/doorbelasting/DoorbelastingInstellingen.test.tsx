import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { DoorbelastingMappingDto } from '../api/types'
import { DoorbelastingInstellingen } from './DoorbelastingInstellingen'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOEL_ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000002'
const MAPPING_ONBOARDED = 'dddddddd-0000-0000-0000-000000000003'
const MAPPING_NIET_ONBOARDED = 'dddddddd-0000-0000-0000-000000000004'
const LEDGER_ID = '99999999-0000-0000-0000-000000000005'
const TAXRATE_ID = '88888888-0000-0000-0000-000000000006'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function mappingLijst(): DoorbelastingMappingDto[] {
  return [
    {
      id: MAPPING_ONBOARDED,
      doelentiteit_naam: 'Rubicon Investments B.V.',
      doel_customer_guid: '2f432363-127b-40e4-b331-ea8c03d4653d',
      doel_administratie_id: DOEL_ADMINISTRATIE_ID,
      intercompany: false,
      provisie_kosten_ledger_id: LEDGER_ID,
      laatste_kosten_ledger_id: null,
      actief: true,
    },
    {
      id: MAPPING_NIET_ONBOARDED,
      doelentiteit_naam: 'Kempen Chalets B.V.',
      doel_customer_guid: 'f5d427fa-2d63-4b19-bdb0-e3120fcbd92b',
      doel_administratie_id: null,
      intercompany: true,
      provisie_kosten_ledger_id: null,
      laatste_kosten_ledger_id: null,
      actief: true,
    },
  ]
}

interface MockOpties {
  ingeschakeld?: boolean
  toggleAanroepen?: { url: string; body: unknown }[]
  mappingAanroepen?: { url: string; body: unknown }[]
  instellingAanroepen?: { url: string; body: unknown }[]
}

function installFetchMock(opties: MockOpties = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/doorbelasting-instelling') && init?.method === 'PUT') {
        opties.toggleAanroepen?.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
        return Promise.resolve(jsonResponse({ ingeschakeld: true }))
      }
      if (url.endsWith('/doorbelasting-instelling')) {
        return Promise.resolve(jsonResponse({ ingeschakeld: opties.ingeschakeld ?? false }))
      }
      if (url.endsWith(`/doorbelasting/${ADMINISTRATIE_ID}/instelling`) && init?.method === 'PUT') {
        opties.instellingAanroepen?.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
        return Promise.resolve(
          jsonResponse({
            administratie_id: ADMINISTRATIE_ID,
            provisie_percentage: '7.50',
            btw_taxrate_id: TAXRATE_ID,
            omzet_ledger_id: LEDGER_ID,
            provisie_omzet_ledger_id: null,
          }),
        )
      }
      if (url.endsWith(`/doorbelasting/${ADMINISTRATIE_ID}/instelling`)) {
        return Promise.resolve(
          jsonResponse({
            administratie_id: ADMINISTRATIE_ID,
            provisie_percentage: '5.00',
            btw_taxrate_id: null,
            omzet_ledger_id: null,
            provisie_omzet_ledger_id: null,
          }),
        )
      }
      if (url.includes('/mappings/') && init?.method === 'PUT') {
        opties.mappingAanroepen?.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
        const gewijzigd = mappingLijst().find((m) => url.endsWith(m.id))
        const body = init.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {}
        return Promise.resolve(jsonResponse({ ...gewijzigd, ...body }))
      }
      if (url.endsWith('/mappings')) return Promise.resolve(jsonResponse(mappingLijst()))
      if (url.endsWith('/grootboek')) {
        return Promise.resolve(
          jsonResponse({ rekeningen: [{ ledger_id: LEDGER_ID, code: '4808', naam: 'Provisie', soort: 2 }] }),
        )
      }
      if (url.endsWith('/btw-codes')) {
        return Promise.resolve(jsonResponse({ btw_codes: [{ id: TAXRATE_ID, naam: 'NL, Hoog tarief', percentage: '0.2100' }] }))
      }
      return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
    }),
  )
}

/** Punt 13 (opruimrun 28-08): de administratie-kiezer is een doorzoekbare combobox — kiezen =
 * veld openen en de optie aanklikken (i.p.v. userEvent.selectOptions op een <select>). */
async function kiesAdministratie(gebruiker: ReturnType<typeof userEvent.setup>, label: string, naam: string) {
  await gebruiker.click(await screen.findByLabelText(label))
  await gebruiker.click(await screen.findByRole('option', { name: naam }))
}

async function renderEnKies() {
  render(<DoorbelastingInstellingen administraties={[{ id: ADMINISTRATIE_ID, naam: 'Kempen Facilities B.V.' }]} />)
  const gebruiker = userEvent.setup()
  await kiesAdministratie(gebruiker, 'Administratie voor doorbelasting', 'Kempen Facilities B.V.')
  return gebruiker
}

describe('DoorbelastingInstellingen', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('laadt toggle, instellingen en mappings na het kiezen van een administratie', async () => {
    installFetchMock()
    await renderEnKies()

    expect(await screen.findByLabelText('Doorbelasting ingeschakeld voor Kempen Facilities B.V.')).not.toBeChecked()
    expect(screen.getByLabelText('Provisie-opslag (%)')).toHaveValue('5')
    expect(screen.getByText('Rubicon Investments B.V.')).toBeInTheDocument()
    expect(screen.getByText('onboarded')).toBeInTheDocument()
    expect(screen.getByText('niet onboarded')).toBeInTheDocument()
    // Niet-onboarded doel: provisie-GB pas kiesbaar ná onboarding.
    expect(screen.getByText('kiesbaar ná onboarding')).toBeInTheDocument()
  })

  it('zet de toggle aan via de BevestigDialog (PUT op de administratie-instelling)', async () => {
    const toggleAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ toggleAanroepen })
    const gebruiker = await renderEnKies()

    await gebruiker.click(
      await screen.findByLabelText('Doorbelasting ingeschakeld voor Kempen Facilities B.V.'),
    )
    // Eerst bevestigen — niets wijzigt zonder expliciete bevestiging.
    expect(await screen.findByText('Doorbelasting-instelling wijzigen?')).toBeInTheDocument()
    expect(toggleAanroepen).toHaveLength(0)
    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))

    await waitFor(() => expect(toggleAanroepen).toHaveLength(1))
    expect(toggleAanroepen[0].url).toContain(`/administraties/${ADMINISTRATIE_ID}/doorbelasting-instelling`)
    expect(toggleAanroepen[0].body).toEqual({ ingeschakeld: true })
    expect(await screen.findByLabelText('Doorbelasting ingeschakeld voor Kempen Facilities B.V.')).toBeChecked()
  })

  it('annuleren van de dialoog wijzigt niets', async () => {
    const toggleAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ toggleAanroepen })
    const gebruiker = await renderEnKies()

    await gebruiker.click(
      await screen.findByLabelText('Doorbelasting ingeschakeld voor Kempen Facilities B.V.'),
    )
    await gebruiker.click(await screen.findByRole('button', { name: 'Annuleren' }))

    expect(toggleAanroepen).toHaveLength(0)
    expect(screen.getByLabelText('Doorbelasting ingeschakeld voor Kempen Facilities B.V.')).not.toBeChecked()
  })

  it('wijzigt de intercompany-vlag als gerichte partial-PUT op de mapping', async () => {
    const mappingAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ mappingAanroepen })
    const gebruiker = await renderEnKies()

    await gebruiker.click(await screen.findByLabelText('Intercompany voor Rubicon Investments B.V.'))
    expect(await screen.findByText(/wordt gemarkeerd als intercompany/)).toBeInTheDocument()
    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))

    await waitFor(() => expect(mappingAanroepen).toHaveLength(1))
    expect(mappingAanroepen[0].url).toContain(`/doorbelasting/${ADMINISTRATIE_ID}/mappings/${MAPPING_ONBOARDED}`)
    // Partial: uitsluitend het gewijzigde veld reist mee (backend: exclude_unset).
    expect(mappingAanroepen[0].body).toEqual({ intercompany: true })
    expect(await screen.findByLabelText('Intercompany voor Rubicon Investments B.V.')).toBeChecked()
  })

  it('slaat de provisie-instellingen op met genormaliseerd percentage', async () => {
    const instellingAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ instellingAanroepen })
    const gebruiker = await renderEnKies()

    const veld = await screen.findByLabelText('Provisie-opslag (%)')
    await gebruiker.clear(veld)
    await gebruiker.type(veld, '7,5')
    await gebruiker.click(screen.getByRole('button', { name: 'Instellingen opslaan' }))
    await gebruiker.click(await screen.findByRole('button', { name: 'Bevestigen' }))

    await waitFor(() => expect(instellingAanroepen).toHaveLength(1))
    expect(instellingAanroepen[0].body).toEqual({
      provisie_percentage: '7.5',
      btw_taxrate_id: null,
      omzet_ledger_id: null,
      provisie_omzet_ledger_id: null,
    })
    // Response is leidend voor de nieuwe stand.
    expect(await screen.findByLabelText('Provisie-opslag (%)')).toHaveValue('7,5')
  })
})
