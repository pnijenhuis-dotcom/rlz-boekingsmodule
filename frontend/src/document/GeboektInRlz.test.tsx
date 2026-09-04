import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { GeboektInRlzDto } from '../api/types'
import { GeboektInRlzChip, GeboektInRlzRegel, geboektInRlzTooltip } from './GeboektInRlz'

/** Odoo-adapter blok E (03-09, mockup §3): "Geboekt in Odoo · nr · company" is dezelfde plek en vorm als het
 * RLZ-patroon (Elissen); additief komen de kruisverwijzing van een reversal en de btw-cent-override-chip mee.
 * Voor een RLZ-stand zonder die velden verandert niets (regressie op blok C 02-09). */

const RLZ: GeboektInRlzDto = {
  regel: 'Geboekt in RLZ · boekstuk RLZ-04-00002001 · Universal Nederland B.V.',
  boekstuknummer: 'RLZ-04-00002001',
  rlz_document_id: 'x',
  tegenpartij: 'Universal Nederland B.V.',
  tegenpartij_rol: 'crediteur',
  geboekt_op: '2026-09-02T10:00:00Z',
  memoriaal_boekstuknummer: null,
  vindplaats_hint: null,
}

const ODOO: GeboektInRlzDto = {
  regel: 'Geboekt in Odoo · BILL/2026/09/0001 · Universal Steigerbouw',
  boekstuknummer: 'BILL/2026/09/0001',
  rlz_document_id: null,
  tegenpartij: 'Riwal Hoogwerkers',
  tegenpartij_rol: 'crediteur',
  geboekt_op: '2026-09-03T20:14:00Z',
  memoriaal_boekstuknummer: null,
  vindplaats_hint: 'in Odoo: Boekhouding → Leveranciers → Facturen',
  backend: 'odoo',
  company_naam: 'Universal Steigerbouw',
  tegenboeking_boekstuknummer: 'RBILL/2026/09/0002',
  kruisverwijzing: 'Reversal · RBILL/2026/09/0002 ↔ BILL/2026/09/0001',
  btw_override: true,
}

describe('GeboektInRlz — RLZ ongewijzigd', () => {
  it('chip = de serverregel, tooltip zonder extra regels, géén override-chip', () => {
    render(<GeboektInRlzChip stand={RLZ} />)
    const chip = screen.getByTestId('geboekt-in-rlz-chip')
    expect(chip).toHaveTextContent(RLZ.regel)
    expect(chip).toHaveAttribute('title', RLZ.regel)
    expect(screen.queryByTestId('btw-override-chip')).not.toBeInTheDocument()
    expect(geboektInRlzTooltip(RLZ)).toBe(RLZ.regel)
  })
})

describe('GeboektInRlz — Odoo (blok E)', () => {
  it('tooltip draagt regel, kruisverwijzing en vindplaats-hint als aparte regels', () => {
    expect(geboektInRlzTooltip(ODOO)).toBe(`${ODOO.regel}\nReversal · RBILL/2026/09/0002 ↔ BILL/2026/09/0001\nin Odoo: Boekhouding → Leveranciers → Facturen`)
  })

  it('chip toont de Odoo-regel (mét company, notitie ④) en de btw-cent-override-chip ernaast', () => {
    render(<GeboektInRlzChip stand={ODOO} />)
    expect(screen.getByTestId('geboekt-in-rlz-chip')).toHaveTextContent('Geboekt in Odoo · BILL/2026/09/0001 · Universal Steigerbouw')
    expect(screen.getByTestId('btw-override-chip')).toHaveTextContent('btw-cent-override')
    expect(screen.getByTestId('btw-override-chip')).toHaveClass('chip', 'afwijking')
  })

  it('regel op een reviewscherm: kruisverwijzing als eigen regel + vindplaats-hint + override-chip', () => {
    render(<GeboektInRlzRegel stand={ODOO} />)
    expect(screen.getByTestId('geboekt-kruisverwijzing')).toHaveTextContent('Reversal · RBILL/2026/09/0002 ↔ BILL/2026/09/0001')
    expect(screen.getByText('in Odoo: Boekhouding → Leveranciers → Facturen')).toBeInTheDocument()
    expect(screen.getByTestId('btw-override-chip')).toBeInTheDocument()
  })

  it('zonder override en zonder kruisverwijzing: alleen de regel (creditnota-loze Odoo-boeking)', () => {
    render(<GeboektInRlzRegel stand={{ ...ODOO, btw_override: false, kruisverwijzing: null, tegenboeking_boekstuknummer: null }} />)
    expect(screen.queryByTestId('btw-override-chip')).not.toBeInTheDocument()
    expect(screen.queryByTestId('geboekt-kruisverwijzing')).not.toBeInTheDocument()
    expect(screen.getByText('Geboekt in Odoo · BILL/2026/09/0001 · Universal Steigerbouw')).toBeInTheDocument()
  })
})

describe('GeboektInRlz — boekdatum verschoven (Odoo-slotstuk 04-09, A2)', () => {
  const VERSCHOVEN: GeboektInRlzDto = {
    ...ODOO,
    btw_override: false,
    kruisverwijzing: null,
    tegenboeking_boekstuknummer: null,
    boekdatum_verschoven: 'boekdatum 01-01-2026 · factuurdatum 15-12-2025 valt in een in Odoo afgesloten periode',
  }

  it('tooltip krijgt de verschuiving als eigen regel, ná de kruisverwijzing en vóór de vindplaats-hint', () => {
    expect(geboektInRlzTooltip(VERSCHOVEN)).toBe(`${ODOO.regel}\nboekdatum 01-01-2026 · factuurdatum 15-12-2025 valt in een in Odoo afgesloten periode\nin Odoo: Boekhouding → Leveranciers → Facturen`)
    expect(geboektInRlzTooltip({ ...VERSCHOVEN, kruisverwijzing: ODOO.kruisverwijzing })).toBe(
      `${ODOO.regel}\n${ODOO.kruisverwijzing}\nboekdatum 01-01-2026 · factuurdatum 15-12-2025 valt in een in Odoo afgesloten periode\nin Odoo: Boekhouding → Leveranciers → Facturen`,
    )
  })

  it('detailkop: oranje chip "boekdatum verschoven" mét de regel als tooltip, naast de Odoo-chip', () => {
    render(<GeboektInRlzChip stand={VERSCHOVEN} />)
    const chip = screen.getByTestId('boekdatum-verschoven-chip')
    expect(chip).toHaveTextContent('boekdatum verschoven')
    expect(chip).toHaveClass('chip', 'afwijking')
    expect(chip).toHaveAttribute('title', VERSCHOVEN.boekdatum_verschoven)
    expect(screen.queryByTestId('btw-override-chip')).not.toBeInTheDocument()
  })

  it('reviewscherm-regel: chip + de verschuivingsregel als eigen regel; RLZ-stand en Odoo zonder verschuiving tonen niets extra', () => {
    render(<GeboektInRlzRegel stand={VERSCHOVEN} />)
    expect(screen.getByTestId('boekdatum-verschoven-chip')).toBeInTheDocument()
    expect(screen.getByTestId('geboekt-boekdatum-verschoven')).toHaveTextContent('boekdatum 01-01-2026 · factuurdatum 15-12-2025')
    render(<GeboektInRlzRegel stand={RLZ} />)
    render(<GeboektInRlzRegel stand={{ ...ODOO, boekdatum_verschoven: null }} />)
    expect(screen.getAllByTestId('boekdatum-verschoven-chip')).toHaveLength(1)
    expect(geboektInRlzTooltip(RLZ)).toBe(RLZ.regel)
  })
})
