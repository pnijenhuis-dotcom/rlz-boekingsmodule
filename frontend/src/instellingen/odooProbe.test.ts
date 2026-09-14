import { describe, expect, it } from 'vitest'
import { ApiError, BackendOnbereikbaarError } from '../api/client'
import { normaliseerOdooUrl, odooKoppelFout, odooProbeGroen, odooProbeOk, odooProbeSamenvatting, vertaalOdooFouttekst } from './odooProbe'

/** Odoo-koppelwizard nazorg 14-09 — pure helpers: URL-normalisatie (spiegel van app/odoo/ids.py), foutvertaling
 * (exception-namen uit oude probe-rapporten), de ok-toets mét toelichting en de rij-context bij een time-out. */

describe('normaliseerOdooUrl (punt 4)', () => {
  it.each([
    'https://universal-steigers.odoo.com/odoo',
    'https://universal-steigers.odoo.com/web',
    'https://universal-steigers.odoo.com/odoo/action-123?debug=1',
    'https://universal-steigers.odoo.com/',
    'https://Universal-Steigers.odoo.com/odoo/#home',
    '  universal-steigers.odoo.com  ',
  ])('%s → scheme + host', (invoer) => {
    expect(normaliseerOdooUrl(invoer)).toBe('https://universal-steigers.odoo.com')
  })

  it('http en poort blijven; onleesbaar = null', () => {
    expect(normaliseerOdooUrl('http://localhost:8069/odoo')).toBe('http://localhost:8069')
    expect(normaliseerOdooUrl('')).toBeNull()
    expect(normaliseerOdooUrl('ftp://x.odoo.com')).toBeNull()
    expect(normaliseerOdooUrl('onzin')).toBeNull()
    expect(normaliseerOdooUrl('https://geen host.nl')).toBeNull()
  })
})

describe('ok-toets mét toelichting (punt 1)', () => {
  it('"ok (memoriaal-dagboek: MEM)" telt als ok — spiegel van is_ok', () => {
    expect(odooProbeOk('ok')).toBe(true)
    expect(odooProbeOk('ok (memoriaal-dagboek: MEM)')).toBe(true)
    expect(odooProbeOk('ok (geen lock dates)')).toBe(true)
    expect(odooProbeOk('okee')).toBe(false)
    expect(odooProbeOk('geen leesrecht')).toBe(false)
    expect(odooProbeGroen({ verbinding: 'ok', 'dagboek:memoriaal': 'ok (memoriaal-dagboek: MEM)' })).toBe(true)
    expect(odooProbeSamenvatting({ verbinding: 'ok', 'dagboek:memoriaal': 'ok (memoriaal-dagboek: MEM)' })).toBe('Rechten-probe groen: verbinding · memoriaal-dagboek')
  })
})

describe('vertaalOdooFouttekst (punt 4, bestaande koppelingen)', () => {
  it('vertaalt exception-namen naar één leesbare zin en laat de rest staan', () => {
    expect(vertaalOdooFouttekst('Odoo niet bereikbaar: HTTPStatusError')).toBe(
      'Odoo niet bereikbaar: Odoo antwoordde met een HTTP-fout — controleer of de URL alleen het domein is (bv. https://naam.odoo.com)',
    )
    expect(vertaalOdooFouttekst('niet bereikbaar: ConnectError')).toContain('geen verbinding met de host')
    expect(vertaalOdooFouttekst('niet bereikbaar: httpx.ReadTimeout')).toContain('time-out — Odoo antwoordde niet op tijd')
    expect(vertaalOdooFouttekst('404 op /json/2/res.company/search_read — controleer of de URL alleen het domein is')).toBe(
      '404 op /json/2/res.company/search_read — controleer of de URL alleen het domein is',
    )
    expect(vertaalOdooFouttekst('geen schrijfrecht op account.move')).toBe('geen schrijfrecht op account.move')
  })
})

describe('odooKoppelFout (punt 3, context per company)', () => {
  it('time-out draagt de company en "probeer deze company los", nooit de kale backend-melding', () => {
    const f = odooKoppelFout(new BackendOnbereikbaarError('timeout', 'AbortError'), { companyId: 7, naam: 'Lusso Chalets' })
    expect(f.bericht).toBe('probe onderbroken (time-out na 90 s) van company 7 (Lusso Chalets) — probeer deze company los')
    expect(f.onbereikbaar).toBe(true)
    const g = odooKoppelFout(new BackendOnbereikbaarError('server', 'HTTP 502'), { companyId: 5, naam: null })
    expect(g.bericht).toBe('backend niet bereikbaar tijdens de probe van company 5 (gateway-fout) — probeer deze company los')
    expect(g.bericht).not.toContain('De backend is momenteel niet bereikbaar')
  })

  it('409/422 mét leeg rapport = alleen bericht; mét rapport = rapport erbij', () => {
    const conflict = odooKoppelFout(new ApiError(409, 'company 6 is gereserveerd als migratiedoel voor administratie ‹VGG›', { bericht: 'x', rapport: {} }))
    expect(conflict).toEqual({ bericht: 'company 6 is gereserveerd als migratiedoel voor administratie ‹VGG›', rapport: null })
    const rood = odooKoppelFout(new ApiError(422, 'Rechten-probe niet groen', { bericht: 'x', rapport: { boeken: 'geen schrijfrecht' } }))
    expect(rood.rapport).toEqual({ boeken: 'geen schrijfrecht' })
  })
})
