// Chips per administratie-rij (v2 30-08 + feedback Peter 30-08): afwijkingen/modules eerst (fel),
// daarna de werkelijke stand "aan volgens default" als gedempte (stil) chip — nooit beide voor
// hetzelfde veld. Pure unit-tests op chipsVoor; de tabel-rendering zit in InstellingenScreen.test.tsx.
import { describe, expect, it } from 'vitest'
import type { AdministratieInstellingenDto, EersteSyncRunDto } from '../api/types'
import { chipsVoor, syncFoutTooltip } from './AdministratiesV2'
import { AUTOBOEKEN_LEREN_NIET_TOEGESTAAN_TEKST } from './instellingenApi'

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
    mini_voorraad_ingeschakeld: false,
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

describe('chipsVoor — Autoboeken (leren en boeken) per administratie (blok A bundel 10-09)', () => {
  it('schakelaar aan = groene STATUS-chip "autoboeken"; niet toegestaan (doorbelasting) = stille chip mét de 409-tekst als title', () => {
    const aan = chipsVoor(administratie({ autoboeken_leren_ingeschakeld: true, autoboeken_leren_toegestaan: true }))
    expect(aan.find((c) => c.tekst === 'autoboeken')?.variant).toBe('ok')
    const kempen = chipsVoor(administratie({ doorbelasting_ingeschakeld: true, autoboeken_leren_ingeschakeld: false, autoboeken_leren_toegestaan: false }))
    const chip = kempen.find((c) => c.tekst === 'n.v.t. — doorbelasting')
    expect(chip?.variant).toBe('stil')
    expect(chip?.titel).toBe(AUTOBOEKEN_LEREN_NIET_TOEGESTAAN_TEKST)
    expect(kempen.some((c) => c.tekst === 'autoboeken')).toBe(false)
  })

  it('uit + toegestaan (of ouder antwoord zonder velden) = geen chip — alleen een afwijking krijgt een chip', () => {
    expect(chipsVoor(administratie({ autoboeken_leren_ingeschakeld: false, autoboeken_leren_toegestaan: true })).some((c) => /autoboeken|doorbelasting/.test(c.tekst))).toBe(false)
    expect(chipsVoor(administratie({})).some((c) => c.tekst === 'autoboeken' || c.tekst === 'n.v.t. — doorbelasting')).toBe(false)
  })
})

describe('syncFoutTooltip — rij-chip "sync-fout" (nachtrun 10/11-09 blok 1)', () => {
  const run: EersteSyncRunDto = {
    run_id: 'r1',
    status: 'fout',
    onderdelen: {
      taxrates: { status: 'klaar', aangemaakt: 3, bijgewerkt: 0 },
      ledgers: { status: 'fout', fout: 'Reeleezee weigert GET Ledgers (HTTP 403) — leesrecht Grootboek. RLZ zegt: "Actie niet toegestaan bij huidige gebruikersrechten"\ntweede regel' },
    },
    aangevraagd_op: null,
    beeindigd_op: null,
    fout_reden: 'Niet alle onderdelen gelukt: ledgers — zie details per onderdeel',
  }

  it('= eerste regel van de eerste rode onderdeel-stand (mét het letterlijke RLZ-antwoord), niet de run-samenvatting', () => {
    expect(syncFoutTooltip(run)).toBe('Reeleezee weigert GET Ledgers (HTTP 403) — leesrecht Grootboek. RLZ zegt: "Actie niet toegestaan bij huidige gebruikersrechten"')
  })

  it('zonder rode onderdeel-tekst: fout_reden; zonder alles: vaste tekst', () => {
    expect(syncFoutTooltip({ ...run, onderdelen: null })).toBe('Niet alle onderdelen gelukt: ledgers — zie details per onderdeel')
    expect(syncFoutTooltip({ ...run, onderdelen: null, fout_reden: null })).toBe('eerste sync mislukt')
    expect(syncFoutTooltip(null)).toBe('eerste sync mislukt')
  })
})


describe('chipsVoor — groepskenmerk (blok 8 run 11-09)', () => {
  it('lid van een groep = stille chip "groep: <naam>" mét code in de titel; zonder groep geen chip', () => {
    const chips = chipsVoor(administratie({ groep_id: 'g1', groep_naam: 'Kempen groep', groep_code: 'KEMPENGROEP', groep_actief: true }))
    const chip = chips.find((c) => c.tekst === 'groep: Kempen groep')
    expect(chip?.variant).toBe('stil')
    expect(chip?.titel).toContain('KEMPENGROEP')
    expect(chipsVoor(administratie()).some((c) => c.tekst.startsWith('groep:'))).toBe(false)
  })

  it('gearchiveerde groep: lid blijft lid, chip zegt het', () => {
    const chips = chipsVoor(administratie({ groep_id: 'g1', groep_naam: 'Kempen groep', groep_code: 'KEMPENGROEP', groep_actief: false }))
    expect(chips.map((c) => c.tekst)).toContain('groep: Kempen groep (gearchiveerd)')
  })
})
