import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { BevindingDto } from './reconciliatieApi'
import {
  isWebhookAfleveringMislukt,
  isWebhookBevindingMetNuOpnieuw,
  isWebhookNietKoppelbaarVerlopen,
  isWebhookWachtOpOntvanger,
  NuOpnieuwActie,
  WebhookStatusChip,
  webhookStatusTekst,
} from './WebhookActies'

// Run A 02-10 punt 17 (Peter 02-10): een 409 `niet_koppelbaar` van Vastly is "nog niet koppelbaar" — status
// wacht_op_ontvanger mét cadans (1 u / 6 u / 24 u / dagelijks, max 14 dagen), daarna mislukt mét reden. De rij op
// Inzicht › Reconciliatie draagt de statuschip en de handeling "Nu opnieuw"; er is geen outbox-scherm.

function bevinding(overrides: Partial<BevindingDto> = {}): BevindingDto {
  return {
    id: 'bev-1',
    run_id: 'run-1',
    blok: 'webhooks',
    soort: 'meten',
    administratie_id: 'adm-1',
    administratie_naam: 'Rubicon Investments',
    vingerafdruk: 'vaf',
    tekst: 'AFWIJKING  webhooks Rubicon: factuur_geboekt RUB-2026-0041 wacht op de ontvanger …',
    titel: 'Vastly kan het event nog niet koppelen — RUB-2026-0041',
    wat: '…',
    doe: '…',
    details: [],
    sinds: '2026-10-02T12:00:00Z',
    nieuw: true,
    acceptatie: null,
    gezien: null,
    detail: {
      afwijking_soort: 'webhook_wacht_op_ontvanger',
      outbox_id: 'out-1',
      event: 'factuur_geboekt',
      referentie: 'RUB-2026-0041',
      reden: 'onbekende_administratie',
      sinds: '2026-10-02T12:00:00Z',
      volgende_poging_op: '2026-10-02T13:00:00Z',
      wacht_pogingen: 1,
      max_dagen: 14,
    },
    doel_pad: null,
    ...overrides,
  } as BevindingDto
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('WebhookActies (run A 02-10 punt 17 — 409 niet_koppelbaar = wacht op ontvanger)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('herkent de twee soorten alleen mét outbox_id én administratie', () => {
    expect(isWebhookWachtOpOntvanger(bevinding())).toBe(true)
    expect(isWebhookWachtOpOntvanger(bevinding({ blok: 'documenten' }))).toBe(false)
    expect(isWebhookWachtOpOntvanger(bevinding({ administratie_id: null }))).toBe(false)
    expect(isWebhookWachtOpOntvanger(bevinding({ detail: { afwijking_soort: 'webhook_wacht_op_ontvanger' } }))).toBe(false)
    const verlopen = bevinding({ soort: 'afwijking', detail: { afwijking_soort: 'webhook_niet_koppelbaar_verlopen', outbox_id: 'out-2', referentie: 'X', reden: 'onbekend_document', wacht_pogingen: 15, max_dagen: 14 } })
    expect(isWebhookNietKoppelbaarVerlopen(verlopen)).toBe(true)
    expect(isWebhookWachtOpOntvanger(verlopen)).toBe(false)
  })

  it('statuschip: wachtend = status + volgende poging + reden; verlopen = mislukt na 14 dagen + reden', () => {
    const wacht = webhookStatusTekst(bevinding())
    expect(wacht).toContain('wacht op ontvanger')
    expect(wacht).toContain('volgende poging')
    expect(wacht).toContain('onbekende_administratie')
    expect(wacht).toContain('poging 1')
    const verlopen = bevinding({ soort: 'afwijking', detail: { afwijking_soort: 'webhook_niet_koppelbaar_verlopen', outbox_id: 'out-2', referentie: 'X', reden: 'onbekend_document', wacht_pogingen: 15, max_dagen: 14 } })
    expect(webhookStatusTekst(verlopen)).toBe('mislukt na 14 dagen wachten · onbekend_document · 15 pogingen')
    render(<WebhookStatusChip bevinding={verlopen} />)
    expect(screen.getByText(/mislukt na 14 dagen wachten/)).toHaveAttribute('data-status', 'mislukt')
  })

  it('derde soort (02-10 avond, punt 17a): storing ná 7 dagen en 4xx-weigering = chip mislukt + Nu opnieuw', () => {
    const storing = bevinding({
      soort: 'afwijking',
      detail: { afwijking_soort: 'webhook_aflevering_mislukt', outbox_id: 'out-3', referentie: 'X', reden: 'HTTP 503: down', reden_soort: 'storing_verlopen', storing_pogingen: 9, max_dagen: 7 },
    })
    const payload = bevinding({
      soort: 'afwijking',
      detail: { afwijking_soort: 'webhook_aflevering_mislukt', outbox_id: 'out-4', referentie: 'Y', reden: '(HTTP 400): onbekende schema_version', reden_soort: 'payloadfout' },
    })
    expect(isWebhookAfleveringMislukt(storing)).toBe(true)
    expect(isWebhookWachtOpOntvanger(storing)).toBe(false)
    expect(isWebhookNietKoppelbaarVerlopen(storing)).toBe(false)
    expect(isWebhookBevindingMetNuOpnieuw(storing)).toBe(true)
    expect(isWebhookBevindingMetNuOpnieuw(bevinding())).toBe(true)
    expect(isWebhookBevindingMetNuOpnieuw(bevinding({ blok: 'documenten' }))).toBe(false)
    expect(webhookStatusTekst(storing)).toBe('mislukt na 7 dagen storing · HTTP 503: down · 9 pogingen')
    expect(webhookStatusTekst(payload)).toBe('geweigerd (payloadfout, herhalen zinloos) · (HTTP 400): onbekende schema_version')
    render(<WebhookStatusChip bevinding={storing} />)
    expect(screen.getByText(/mislukt na 7 dagen storing/)).toHaveAttribute('data-status', 'mislukt')
  })

  it('Nu opnieuw: één klik → POST mét administratie; afgeleverd = melding + hint; 409 zichtbaar naast de knop', async () => {
    const aanroepen: { url: string; body: unknown }[] = []
    let antwoord = jsonResponse({ outbox_id: 'out-1', administratie_id: 'adm-1', status_voor: 'wacht_op_ontvanger', status_na: 'afgeleverd', uitkomst: 'afgeleverd — resultaat verwerkt (ná 1 × wachten op de ontvanger)' })
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        aanroepen.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null })
        return Promise.resolve(antwoord)
      }),
    )
    const meldingen: string[] = []
    const gebruiker = userEvent.setup()
    const { unmount } = render(<NuOpnieuwActie bevinding={bevinding()} onGelukt={(m) => meldingen.push(m)} />)
    expect(screen.getByText(/wacht op ontvanger/)).toBeInTheDocument()
    await gebruiker.click(screen.getByRole('button', { name: 'RUB-2026-0041 nu opnieuw aanbieden' }))
    await waitFor(() => expect(meldingen).toHaveLength(1))
    expect(aanroepen[0].url).toContain('/reconciliatie/webhooks/out-1/nu-opnieuw')
    expect(aanroepen[0].body).toEqual({ administratie_id: 'adm-1' })
    expect(meldingen[0]).toContain('alsnog afgeleverd bij Vastly')
    expect(screen.getByText(/afgeleverd — afgeleverd — resultaat verwerkt/)).toBeInTheDocument()
    unmount()

    // 409: de rij wacht niet (meer) — zichtbaar naast de knop, nooit stil.
    antwoord = jsonResponse({ detail: "rij staat op afgeleverd en wacht niet op de ontvanger — 'Nu opnieuw' geldt alleen …" }, 409)
    render(<NuOpnieuwActie bevinding={bevinding()} onGelukt={(m) => meldingen.push(m)} />)
    await gebruiker.click(screen.getByRole('button', { name: 'RUB-2026-0041 nu opnieuw aanbieden' }))
    await waitFor(() => expect(screen.getByText(/wacht niet op de ontvanger/)).toBeInTheDocument())
    expect(meldingen).toHaveLength(1)
  })
})
