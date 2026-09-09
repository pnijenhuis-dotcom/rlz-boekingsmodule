// Bundel 09-09 blok 1: de run draagt twee mailkanalen (actie = kantoor, systeem = beheer) in één samengestelde
// waarde "actie=<s>;systeem=<s>"; runs van vóór 09-09 dragen één kale status. De standregel op Inzicht › Reconciliatie
// toont beide leesbaar en crasht nooit op een onbekende sleutel.
import { describe, expect, it } from 'vitest'
import { mailStatusTekst } from './reconciliatieApi'

describe('mailStatusTekst (twee mailkanalen)', () => {
  it('samengesteld → per kanaal een leesbaar label', () => {
    expect(mailStatusTekst('actie=verzonden;systeem=niet_nodig')).toBe('actiemail verzonden · systeemmail niet nodig')
    expect(mailStatusTekst('actie=niet_nodig;systeem=mislukt')).toBe('actiemail niet nodig · systeemmail mislukt')
    expect(mailStatusTekst('actie=verzonden;systeem=niet_geconfigureerd')).toBe(
      'actiemail verzonden · systeemmail niet geconfigureerd',
    )
  })

  it('kale status (run van vóór 09-09) → het bestaande label', () => {
    expect(mailStatusTekst('verzonden')).toBe('verzonden')
    expect(mailStatusTekst('niet_nodig')).toBe('niet nodig')
  })

  it('leeg/onbekend → leeg of de sleutel, nooit een crash', () => {
    expect(mailStatusTekst(null)).toBe('')
    expect(mailStatusTekst(undefined)).toBe('')
    expect(mailStatusTekst('nieuw_kanaal=raar_status')).toBe('nieuw_kanaal raar status')
    expect(mailStatusTekst('actie=verzonden;kapot')).toBe('actiemail verzonden')
  })
})
