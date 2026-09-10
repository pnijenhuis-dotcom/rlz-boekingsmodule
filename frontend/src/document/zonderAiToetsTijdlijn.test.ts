import { describe, expect, it } from 'vitest'
import { aiToetsUitTijdlijnTekst, isAiToetsUitNotitie, isZonderAiToetsNotitie, zonderAiToetsTijdlijnTekst } from './zonderAiToetsTijdlijn'

describe('zonderAiToetsTijdlijn (blok 4 vervolgrun 10-09 avond)', () => {
  it('herkent alleen een GEBOEKT-detail mét zonder_ai_toets = true', () => {
    expect(isZonderAiToetsNotitie({ automatisch_geboekt: true, zonder_ai_toets: true, ai_toets_oorzaak: 'avg_gate' })).toBe(true)
    expect(isZonderAiToetsNotitie({ automatisch_geboekt: true })).toBe(false)
    expect(isZonderAiToetsNotitie({ zonder_ai_toets: false })).toBe(false)
    expect(isZonderAiToetsNotitie({ zonder_ai_toets: 'true' })).toBe(false)
  })

  it('tekst noemt de oorzaak leesbaar en de handeling (steekproef)', () => {
    expect(zonderAiToetsTijdlijnTekst({ zonder_ai_toets: true, ai_toets_oorzaak: 'kostengrens' })).toBe(
      'Automatisch geboekt zónder AI-toets — de toets viel technisch uit (AI-kostengrens bereikt); controleer steekproefsgewijs.',
    )
    expect(zonderAiToetsTijdlijnTekst({ zonder_ai_toets: true, ai_toets_oorzaak: 'api_key' })).toContain('geen API-key')
    expect(zonderAiToetsTijdlijnTekst({ zonder_ai_toets: true, ai_toets_oorzaak: 'ai_fout' })).toContain('AI-fout/timeout')
    expect(zonderAiToetsTijdlijnTekst({ zonder_ai_toets: true })).toContain('onbekende oorzaak')
    expect(zonderAiToetsTijdlijnTekst({ zonder_ai_toets: true, ai_toets_oorzaak: 'nieuw_iets' })).toContain('nieuw iets')
  })
})

describe('AI-toets uit (platform) — blok 3.2 vervolgrun 10-09 avond', () => {
  it('herkent het GEBOEKT-detail ai_toets_uit en geeft een leesbare tijdlijnregel', () => {
    expect(isAiToetsUitNotitie({ automatisch_geboekt: true, ai_toets_uit: true })).toBe(true)
    expect(isAiToetsUitNotitie({ automatisch_geboekt: true })).toBe(false)
    expect(isAiToetsUitNotitie({ automatisch_geboekt: true, zonder_ai_toets: true })).toBe(false)
    expect(aiToetsUitTijdlijnTekst()).toMatch(/platformbreed uit/)
    expect(aiToetsUitTijdlijnTekst()).toMatch(/Instellingen › Boeken/)
  })
})
