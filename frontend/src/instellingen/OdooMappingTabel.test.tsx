import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { OdooMappingStandDto, OdooOverstapVoorbereidingDto, OdooRekeningDto, OdooTariefDto } from './instellingenApi'
import {
  bronChip,
  btwOpties,
  mappingCompleet,
  mappingInvoer,
  mappingTelling,
  OdooMappingTabel,
  rijenUitStand,
  rijenUitVoorbereiding,
  type MappingTabelRij,
} from './OdooMappingTabel'

/** Rekening-mapping RLZ → Odoo (blok A 04-09): chips per herkomst, kop-teller als restant-balk, filter "alleen nog
 * te kiezen", keuze via de doorzoekbare combobox, versie-badge in corrigeer-modus en de lege stand als één zin. */

const ODOO_GB: OdooRekeningDto[] = [
  { odoo_id: 11, lokaal_id: '11111111-0000-0000-0000-000000000011', code: '480800', naam: 'Huur materieel' },
  { odoo_id: 12, lokaal_id: '11111111-0000-0000-0000-000000000012', code: '424000', naam: 'Inhuur personeel' },
  { odoo_id: 13, lokaal_id: '11111111-0000-0000-0000-000000000013', code: '4699', naam: 'Diverse algemene kosten' },
]
const ODOO_BTW: OdooTariefDto[] = [
  { odoo_id: 21, lokaal_id: '22222222-0000-0000-0000-000000000021', naam: '21% inkoop', percentage: '0.21', verlegd: false, synthetisch: false },
  { odoo_id: 22, lokaal_id: '22222222-0000-0000-0000-000000000022', naam: '21% R', percentage: '0.21', verlegd: true, synthetisch: false },
  { odoo_id: 0, lokaal_id: '22222222-0000-0000-0000-000000000000', naam: 'Geen btw (0%)', percentage: '0', verlegd: false, synthetisch: true },
]

const VOORBEREIDING: OdooOverstapVoorbereidingDto = {
  company_naam: 'Universal Steigerbouw',
  probe: { ledgers: 'ok', boeken: 'ok' },
  grootboek: [
    { rlz_id: 'gb-4699', rlz_code: '4699', rlz_naam: 'Diverse algemene kosten', in_gebruik_observaties: 12, in_gebruik_open_regels: 2, voorstel_odoo_id: 13, voorstel_odoo_code: '4699', voorstel_odoo_naam: 'Diverse algemene kosten', reden: 'zelfde_code' },
    { rlz_id: 'gb-4808', rlz_code: '4808', rlz_naam: 'Huur materieel', in_gebruik_observaties: 40, in_gebruik_open_regels: 0, voorstel_odoo_id: 11, voorstel_odoo_code: '480800', voorstel_odoo_naam: 'Huur materieel', reden: 'code_verlengd' },
    { rlz_id: 'gb-7000', rlz_code: '7000', rlz_naam: 'Inkoop onderaanneming', in_gebruik_observaties: 0, in_gebruik_open_regels: 1, voorstel_odoo_id: null, voorstel_odoo_code: null, voorstel_odoo_naam: null, reden: null },
  ],
  btw: [
    { rlz_id: 'btw-hoog', rlz_naam: 'NL, Hoog Tarief', rlz_percentage: '0.21', verlegd: false, in_gebruik_observaties: 30, in_gebruik_open_regels: 3, voorstel_odoo_id: 21, voorstel_odoo_naam: '21% inkoop', reden: 'tarief' },
    { rlz_id: 'btw-verlegd', rlz_naam: 'NL, Verlegd', rlz_percentage: '0.21', verlegd: true, in_gebruik_observaties: 5, in_gebruik_open_regels: 0, voorstel_odoo_id: null, voorstel_odoo_naam: null, reden: null },
  ],
  odoo_grootboek: ODOO_GB,
  odoo_btw: ODOO_BTW,
  telling: { grootboek_totaal: 3, grootboek_met_voorstel: 2, btw_totaal: 2, btw_met_voorstel: 1 },
}

function Harnas({ start, modus, onKies }: { start: MappingTabelRij[]; modus?: 'kiezen' | 'corrigeren'; onKies?: (rij: MappingTabelRij, id: number | null) => void }) {
  const [rijen, setRijen] = useState(start)
  return (
    <OdooMappingTabel
      rijen={rijen}
      odooGrootboek={ODOO_GB}
      odooBtw={ODOO_BTW}
      modus={modus}
      onKies={(rij, id) => {
        onKies?.(rij, id)
        setRijen((h) => h.map((r) => (r.rlz_id === rij.rlz_id ? { ...r, odoo_id: id, bron: id == null ? null : 'handmatig' } : r)))
      }}
    />
  )
}

describe('OdooMappingTabel — helpers (puur)', () => {
  it('rijenUitVoorbereiding zet het voorstel vooringevuld mét reden; zonder voorstel = leeg + geen bron', () => {
    const rijen = rijenUitVoorbereiding(VOORBEREIDING)
    expect(rijen).toHaveLength(5)
    expect(rijen[0]).toMatchObject({ soort: 'grootboek', rlz_code: '4699', odoo_id: 13, bron: 'zelfde_code' })
    expect(rijen[1]).toMatchObject({ odoo_id: 11, bron: 'code_verlengd' })
    expect(rijen[2]).toMatchObject({ odoo_id: null, bron: null })
    expect(rijen[3]).toMatchObject({ soort: 'btw', rlz_percentage: '0.21', odoo_id: 21, bron: 'tarief' })
    expect(rijen[4]).toMatchObject({ soort: 'btw', verlegd: true, odoo_id: null })
  })

  it('mappingInvoer draagt alleen gekozen rijen, gesplitst per soort; telling en compleet volgen de keuzes', () => {
    const rijen = rijenUitVoorbereiding(VOORBEREIDING)
    expect(mappingInvoer(rijen)).toEqual({
      grootboek: [
        { rlz_id: 'gb-4699', odoo_id: 13 },
        { rlz_id: 'gb-4808', odoo_id: 11 },
      ],
      btw: [{ rlz_id: 'btw-hoog', odoo_id: 21 }],
    })
    expect(mappingTelling(rijen)).toEqual({ gekozen: 3, totaal: 5 })
    expect(mappingCompleet(rijen)).toBe(false)
    const compleet = rijen.map((r) => ({ ...r, odoo_id: r.odoo_id ?? 12 }))
    expect(mappingCompleet(compleet)).toBe(true)
    // Synthetisch "geen btw" = odoo_id 0 telt als gekozen (0 is géén "leeg").
    expect(mappingCompleet([{ ...rijen[4], odoo_id: 0 }])).toBe(true)
    expect(mappingInvoer([{ ...rijen[4], odoo_id: 0 }]).btw).toEqual([{ rlz_id: 'btw-verlegd', odoo_id: 0 }])
    // Lege lijst = compleet (mapping niet nodig).
    expect(mappingCompleet([])).toBe(true)
  })

  it('bronChip: groen zelfde code · oranje code + 00 / tarief · neutraal handmatig · rood kies (leeg)', () => {
    expect(bronChip('zelfde_code', 13)).toEqual({ klasse: 'chip ok', tekst: 'zelfde code' })
    expect(bronChip('code_verlengd', 11)).toEqual({ klasse: 'chip afwijking', tekst: 'code + 00 — bevestig' })
    expect(bronChip('tarief', 21)).toEqual({ klasse: 'chip afwijking', tekst: 'tarief' })
    expect(bronChip('handmatig', 12)).toEqual({ klasse: 'chip handmatig', tekst: 'handmatig' })
    expect(bronChip(null, null)).toEqual({ klasse: 'chip blokkerend', tekst: 'kies' })
    expect(bronChip('zelfde_code', null)).toEqual({ klasse: 'chip blokkerend', tekst: 'kies' })
  })

  it('btwOpties: percentage als code, verlegd benoemd, synthetische rij heet "geen btw-code in Odoo"', () => {
    expect(btwOpties(ODOO_BTW)).toEqual([
      { id: '21', code: '21%', label: '21% inkoop' },
      { id: '22', code: '21%', label: '21% R (verlegd)' },
      { id: '0', code: '0%', label: 'Geen btw (0%) — geen btw-code in Odoo' },
    ])
  })

  it('rijenUitStand: geldende mapping → rijen mét versie, bron uit de rij', () => {
    const stand: OdooMappingStandDto = {
      grootboek: [{ soort: 'grootboek', rlz_id: 'gb-4808', rlz_code: '4808', rlz_naam: 'Huur materieel', odoo_id: 12, odoo_code: '424000', odoo_naam: 'Inhuur personeel', bron: 'handmatig', versie: 2, bevestigd_op: '2026-09-04T10:00:00Z', bevestigd_door_naam: 'Peter' }],
      btw: [],
      odoo_grootboek: ODOO_GB,
      odoo_btw: ODOO_BTW,
      laatst_bevestigd_op: '2026-09-04T10:00:00Z',
      laatst_bevestigd_door_naam: 'Peter',
    }
    expect(rijenUitStand(stand)).toEqual([expect.objectContaining({ soort: 'grootboek', rlz_id: 'gb-4808', odoo_id: 12, bron: 'handmatig', versie: 2 })])
  })
})

describe('OdooMappingTabel — weergave en keuze', () => {
  it('twee blokken mét tellers, per rij code · naam + in-gebruik-regel, voorstel vooringevuld in de combobox, chips per herkomst, teller "3 van 5 gekoppeld"', () => {
    render(<Harnas start={rijenUitVoorbereiding(VOORBEREIDING)} />)
    expect(screen.getByRole('heading', { name: 'Grootboek (3)' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Btw-tarieven (2)' })).toBeInTheDocument()
    const teller = screen.getByTestId('odoo-mapping-teller')
    expect(teller).toHaveTextContent('3 van 5 gekoppeld')
    expect(teller).toHaveTextContent('nog 2 te kiezen')
    expect(teller).not.toHaveClass('compleet')

    const rij4808 = screen.getByTestId('odoo-mapping-rij-grootboek:gb-4808')
    expect(rij4808).toHaveTextContent('4808 · Huur materieel')
    expect(rij4808).toHaveTextContent('in gebruik: 40× geheugen')
    expect(within(rij4808).getByRole('combobox')).toHaveValue('480800 · Huur materieel')
    expect(within(rij4808).getByText('code + 00 — bevestig')).toHaveClass('chip', 'afwijking')

    const rij4699 = screen.getByTestId('odoo-mapping-rij-grootboek:gb-4699')
    expect(rij4699).toHaveTextContent('in gebruik: 12× geheugen · 2 open regels')
    expect(within(rij4699).getByText('zelfde code')).toHaveClass('chip', 'ok')

    const rij7000 = screen.getByTestId('odoo-mapping-rij-grootboek:gb-7000')
    expect(rij7000).toHaveTextContent('in gebruik: 1 open regel')
    expect(within(rij7000).getByRole('combobox')).toHaveValue('')
    expect(within(rij7000).getByText('kies')).toHaveClass('chip', 'blokkerend')

    const rijBtw = screen.getByTestId('odoo-mapping-rij-btw:btw-hoog')
    expect(rijBtw).toHaveTextContent('NL, Hoog Tarief · 21%')
    expect(within(rijBtw).getByRole('combobox')).toHaveValue('21% · 21% inkoop')
    expect(within(rijBtw).getByText('tarief')).toHaveClass('chip', 'afwijking')
    expect(screen.getByTestId('odoo-mapping-rij-btw:btw-verlegd')).toHaveTextContent('NL, Verlegd · verlegd')
  })

  it('kiezen via de combobox meldt (rij, odoo_id als getal); alles gekozen = teller groen ✓; synthetisch "geen btw" = id 0', async () => {
    const gebruiker = userEvent.setup()
    const onKies = vi.fn()
    render(<Harnas start={rijenUitVoorbereiding(VOORBEREIDING)} onKies={onKies} />)

    const rij7000 = screen.getByTestId('odoo-mapping-rij-grootboek:gb-7000')
    await gebruiker.click(within(rij7000).getByRole('combobox'))
    await gebruiker.click(screen.getByRole('option', { name: /424000.*Inhuur personeel/ }))
    expect(onKies).toHaveBeenLastCalledWith(expect.objectContaining({ soort: 'grootboek', rlz_id: 'gb-7000' }), 12)
    expect(screen.getByTestId('odoo-mapping-teller')).toHaveTextContent('4 van 5 gekoppeld')

    const rijVerlegd = screen.getByTestId('odoo-mapping-rij-btw:btw-verlegd')
    await gebruiker.click(within(rijVerlegd).getByRole('combobox'))
    await gebruiker.click(screen.getByRole('option', { name: /0%.*Geen btw \(0%\) — geen btw-code in Odoo/ }))
    expect(onKies).toHaveBeenLastCalledWith(expect.objectContaining({ soort: 'btw', rlz_id: 'btw-verlegd' }), 0)

    const teller = screen.getByTestId('odoo-mapping-teller')
    expect(teller).toHaveTextContent('5 van 5 gekoppeld')
    expect(teller).toHaveTextContent('✓ alles gekoppeld')
    expect(teller).toHaveClass('compleet')
    expect(within(screen.getByTestId('odoo-mapping-rij-btw:btw-verlegd')).getByText('handmatig')).toHaveClass('chip', 'handmatig')
  })

  it('filter "alleen nog te kiezen" verbergt gekozen rijen; een blok zonder open rijen zegt dat expliciet', () => {
    render(<Harnas start={rijenUitVoorbereiding(VOORBEREIDING)} />)
    fireEvent.click(screen.getByLabelText('Alleen nog te kiezen'))
    expect(screen.queryByTestId('odoo-mapping-rij-grootboek:gb-4699')).not.toBeInTheDocument()
    expect(screen.queryByTestId('odoo-mapping-rij-grootboek:gb-4808')).not.toBeInTheDocument()
    expect(screen.getByTestId('odoo-mapping-rij-grootboek:gb-7000')).toBeInTheDocument()
    expect(screen.queryByTestId('odoo-mapping-rij-btw:btw-hoog')).not.toBeInTheDocument()
    expect(screen.getByTestId('odoo-mapping-rij-btw:btw-verlegd')).toBeInTheDocument()
    // De blok-tellers blijven het totaal tonen, niet het gefilterde aantal.
    expect(screen.getByRole('heading', { name: 'Grootboek (3)' })).toBeInTheDocument()

    // Alles in het btw-blok gekozen → geen lege tabel maar één zin.
    const alleenGb = rijenUitVoorbereiding(VOORBEREIDING).map((r) => (r.soort === 'btw' ? { ...r, odoo_id: r.odoo_id ?? 22, bron: r.bron ?? ('handmatig' as const) } : r))
    render(<Harnas start={alleenGb} />)
    fireEvent.click(screen.getAllByLabelText('Alleen nog te kiezen')[1])
    expect(screen.getByText('Alles in dit blok is gekoppeld.')).toBeInTheDocument()
  })

  it('lege in-gebruik-lijst = één zin "mapping niet nodig", geen tabel en geen filter', () => {
    render(<Harnas start={[]} />)
    expect(screen.getByTestId('odoo-mapping-leeg')).toHaveTextContent('Geen boekingsgeheugen of open regels om te vertalen — mapping niet nodig.')
    expect(screen.queryByTestId('odoo-mapping-tabel')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Alleen nog te kiezen')).not.toBeInTheDocument()
  })

  it('corrigeer-modus: geen filter, versie-badge "v2" alleen bij een gecorrigeerde rij, keuze meldt door naar de aanroeper', async () => {
    const gebruiker = userEvent.setup()
    const onKies = vi.fn()
    const stand: OdooMappingStandDto = {
      grootboek: [
        { soort: 'grootboek', rlz_id: 'gb-4808', rlz_code: '4808', rlz_naam: 'Huur materieel', odoo_id: 12, odoo_code: '424000', odoo_naam: 'Inhuur personeel', bron: 'handmatig', versie: 2, bevestigd_op: '2026-09-04T10:00:00Z', bevestigd_door_naam: 'Peter' },
        { soort: 'grootboek', rlz_id: 'gb-4699', rlz_code: '4699', rlz_naam: 'Diverse algemene kosten', odoo_id: 13, odoo_code: '4699', odoo_naam: 'Diverse algemene kosten', bron: 'zelfde_code', versie: 1, bevestigd_op: '2026-09-04T09:00:00Z', bevestigd_door_naam: 'Peter' },
      ],
      btw: [],
      odoo_grootboek: ODOO_GB,
      odoo_btw: ODOO_BTW,
      laatst_bevestigd_op: '2026-09-04T10:00:00Z',
      laatst_bevestigd_door_naam: 'Peter',
    }
    render(<Harnas start={rijenUitStand(stand)} modus="corrigeren" onKies={onKies} />)
    expect(screen.queryByLabelText('Alleen nog te kiezen')).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /Btw-tarieven/ })).not.toBeInTheDocument()
    const rij4808 = screen.getByTestId('odoo-mapping-rij-grootboek:gb-4808')
    expect(within(rij4808).getByText('v2')).toBeInTheDocument()
    expect(within(rij4808).getByText('handmatig')).toHaveClass('chip', 'handmatig')
    const rij4699 = screen.getByTestId('odoo-mapping-rij-grootboek:gb-4699')
    expect(within(rij4699).queryByText(/^v\d/)).not.toBeInTheDocument()

    await gebruiker.click(within(rij4699).getByRole('combobox'))
    await gebruiker.click(screen.getByRole('option', { name: /480800.*Huur materieel/ }))
    expect(onKies).toHaveBeenCalledWith(expect.objectContaining({ rlz_id: 'gb-4699', odoo_id: 13 }), 11)
  })
})
