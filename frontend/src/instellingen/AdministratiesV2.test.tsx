// Chips per administratie-rij (v2 30-08 + feedback Peter 30-08): afwijkingen/modules eerst (fel),
// daarna de werkelijke stand "aan volgens default" als gedempte (stil) chip — nooit beide voor
// hetzelfde veld. Pure unit-tests op chipsVoor; de tabel-rendering zit in InstellingenScreen.test.tsx.
import { describe, expect, it } from 'vitest'
import type { AdministratieInstellingenDto } from '../api/types'
import { chipsVoor } from './AdministratiesV2'

function administratie(overrides: Partial<AdministratieInstellingenDto> = {}): AdministratieInstellingenDto {
  return {
    id: 'aaaaaaaa-0000-0000-0000-000000000001',
    naam: 'Testklant B.V.',
    boeken_ingeschakeld: true,
    project_verplicht: false,
    ai_extractie_ingeschakeld: true,
    eigenaar_gebruiker_id: null,
    is_vastgoed: false,
    verkoop_autoboeken_ingeschakeld: false,
    uren_meerwerk_ingeschakeld: false,
    uren_dagmax_uren: '12',
    afdelingen_ingeschakeld: false,
    voorraad_ingeschakeld: false,
    ...overrides,
  }
}

describe('chipsVoor — werkelijke stand per rij (feedback Peter 30-08)', () => {
  it('boeken/AI aan volgens default = stille ✓-chip mét titel, géén warn-chip', () => {
    const chips = chipsVoor(administratie({ boeken_ingeschakeld: true, ai_extractie_ingeschakeld: true }))
    expect(chips).toContainEqual({ tekst: 'Boeken ✓', variant: 'stil', titel: 'boeken aan — default' })
    expect(chips).toContainEqual({ tekst: 'AI-extractie ✓', variant: 'stil', titel: 'AI-extractie aan — default' })
    expect(chips.map((c) => c.tekst)).not.toContain('Boeken UIT (afwijking)')
    expect(chips.map((c) => c.tekst)).not.toContain('AI-extractie UIT (afwijking)')
  })

  it('boeken/AI uit = felle warn-chip, géén stille chip — nooit beide voor hetzelfde veld', () => {
    const chips = chipsVoor(administratie({ boeken_ingeschakeld: false, ai_extractie_ingeschakeld: false }))
    expect(chips).toContainEqual({ tekst: 'Boeken UIT (afwijking)', variant: 'warn' })
    expect(chips).toContainEqual({ tekst: 'AI-extractie UIT (afwijking)', variant: 'warn' })
    expect(chips.map((c) => c.tekst)).not.toContain('Boeken ✓')
    expect(chips.map((c) => c.tekst)).not.toContain('AI-extractie ✓')
  })

  it('gemengd per veld: uit = warn, aan = stil — elk veld precies één chip', () => {
    const chips = chipsVoor(administratie({ boeken_ingeschakeld: false, ai_extractie_ingeschakeld: true }))
    const teksten = chips.map((c) => c.tekst)
    expect(teksten).toContain('Boeken UIT (afwijking)')
    expect(teksten).toContain('AI-extractie ✓')
    expect(teksten).not.toContain('Boeken ✓')
    expect(teksten).not.toContain('AI-extractie UIT (afwijking)')
  })

  it('stille stand-chips staan ACHTERAAN — afwijkingen en modules eerst', () => {
    const chips = chipsVoor(administratie({ is_vastgoed: true, ai_extractie_ingeschakeld: false }))
    const laatste = chips[chips.length - 1]
    expect(laatste).toEqual({ tekst: 'Boeken ✓', variant: 'stil', titel: 'boeken aan — default' })
    const stilIndex = chips.findIndex((c) => c.variant === 'stil')
    expect(chips.slice(0, stilIndex).every((c) => c.variant !== 'stil')).toBe(true)
    expect(chips.slice(stilIndex).every((c) => c.variant === 'stil')).toBe(true)
  })
})

describe('chipsVoor — facturatiemodule niet afgenomen (spoedopdracht 01-09 blok A)', () => {
  it('verkoopmodule_afwezig = warn-chip "geen facturatiemodule" mét uitleg-titel', () => {
    const chips = chipsVoor(administratie({ verkoopmodule_afwezig: true }))
    const chip = chips.find((c) => c.tekst === 'geen facturatiemodule')
    expect(chip?.variant).toBe('warn')
    expect(chip?.titel).toContain('facturatiemodule niet afgenomen')
    expect(chip?.titel).toContain('herprobe')
  })

  it('zonder het kenmerk bestaat de chip niet', () => {
    expect(chipsVoor(administratie({})).some((c) => c.tekst === 'geen facturatiemodule')).toBe(false)
  })
})
