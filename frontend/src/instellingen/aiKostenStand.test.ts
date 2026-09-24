// Guard D1 (BUG Peter 24-09): "geblokkeerd" staat er uitsluitend op de LIVE stand; `limiet_bereikt` (sticky maandfeit)
// mag nooit meer een blokkade-tekst geven — beide vlaggen los van elkaar getoetst.
import { describe, expect, it } from 'vitest'
import { bepaalAiKostenStand } from './aiKostenStand'
import type { AiKostenStatusDto } from './instellingenApi'

function status(over: Partial<AiKostenStatusDto> = {}): AiKostenStatusDto {
  return {
    maand: '2026-09',
    verbruik_eur: '102.23',
    limiet_eur: '150.00',
    percentage: 68,
    waarschuwing_80: true,
    limiet_bereikt: true,
    geblokkeerd: false,
    limiet_bereikt_op: '2026-09-23T17:05:00Z',
    limiet_bij_bereiken_eur: '100.00',
    weer_actief_sinds: '2026-09-23T19:22:00Z',
    wachten_op_heraanbieding: 202,
    ...over,
  }
}

describe('bepaalAiKostenStand', () => {
  it('limiet_bereikt=true + geblokkeerd=false → géén blokkade-tekst, wél "weer actief" mét historie en wachtende documenten', () => {
    const stand = bepaalAiKostenStand(status())
    expect(stand.soort).toBe('weer_actief')
    expect(stand.tekst).not.toMatch(/geblokkeerd/i)
    expect(stand.tekst).toMatch(/AI-verwerking weer actief sinds/)
    expect(stand.tekst).toMatch(/limiet bereikt op .* bij € 100\.00; daarna verhoogd naar € 150\.00/)
    expect(stand.tekst).toMatch(/202 documenten wachten op heraanbieding/)
    expect(stand.wachten).toBe(202)
  })

  it('geblokkeerd=true → rode blokkade-tekst (ook als limiet_bereikt om wat voor reden false zou zijn)', () => {
    for (const limiet_bereikt of [true, false]) {
      const stand = bepaalAiKostenStand(status({ geblokkeerd: true, limiet_bereikt, verbruik_eur: '150.10' }))
      expect(stand.soort).toBe('geblokkeerd')
      expect(stand.tekst).toMatch(/AI-verwerking is geblokkeerd/)
      expect(stand.tekst).toMatch(/2026-09: € 150\.10 van € 150\.00/)
    }
  })

  it('weer actief zonder wachtende documenten zegt dat; zonder tijdstippen blijft de regel leesbaar', () => {
    const stand = bepaalAiKostenStand(status({ wachten_op_heraanbieding: 0, weer_actief_sinds: null, limiet_bereikt_op: null }))
    expect(stand.soort).toBe('weer_actief')
    expect(stand.tekst).toBe('AI-verwerking weer actief (limiet daarna verhoogd naar € 150.00); niets wacht meer op heraanbieding.')
  })

  it('alleen de 80%-waarschuwing → oranje; niets → geen melding', () => {
    expect(bepaalAiKostenStand(status({ limiet_bereikt: false })).soort).toBe('waarschuwing')
    expect(bepaalAiKostenStand(status({ limiet_bereikt: false, waarschuwing_80: false })).soort).toBe('geen')
  })
})
