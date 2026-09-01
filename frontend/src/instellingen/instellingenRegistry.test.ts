// Guard-tests Instellingen v3 (ontwerpnotitie ⑥, marker-discipline): élk nav-item en élke
// detailpagina-tab heeft een registry-entry — een nieuwe module zonder entry is hier rood.
// Plus: rol×sectie-matrix fail-closed, landing per rol, deterministische zoeker.
import { describe, expect, it } from 'vitest'
import {
  DETAIL_TABS,
  eersteSectieVoor,
  NAV_GROEPEN,
  NAV_ITEMS,
  OUDE_SECTIE_REDIRECTS,
  REGISTRY,
  SECTIE_PADEN,
  zichtbareNavGroepen,
  zichtbareNavItems,
  zichtbareTabs,
  zoekInstellingen,
} from './instellingenRegistry'

const ADMINISTRATIES = [
  { id: 'a1', naam: 'ARVUM B.V.' },
  { id: 'a2', naam: 'A.Y. Holding BV' },
  { id: 'a3', naam: 'Kempen Facilities B.V.' },
]

describe('instellingenRegistry — guard (élk nav-item en élke tab heeft een registry-entry)', () => {
  it('elk nav-item heeft precies één sectie-entry zonder anker', () => {
    for (const item of NAV_ITEMS) {
      const entries = REGISTRY.filter((e) => e.doel.soort === 'sectie' && e.doel.sectie === item.pad && !e.doel.anker)
      expect(entries, `nav-item "${item.pad}" mist een registry-entry (of heeft er meerdere)`).toHaveLength(1)
      expect(entries[0].beheerder, `beheerder-vlag van entry "${entries[0].id}" ≠ nav-item`).toBe(item.beheerder)
    }
  })

  it('elke detailpagina-tab heeft precies één tab-entry', () => {
    for (const tab of DETAIL_TABS) {
      const entries = REGISTRY.filter((e) => e.doel.soort === 'tab' && e.doel.tab === tab.pad)
      expect(entries, `tab "${tab.pad}" mist een registry-entry (of heeft er meerdere)`).toHaveLength(1)
    }
  })

  it('elke registry-entry wijst naar een bestaande sectie of tab; ids en synoniemen zijn gevuld en uniek', () => {
    const ids = new Set<string>()
    const tabPaden = new Set(DETAIL_TABS.map((t) => t.pad))
    for (const e of REGISTRY) {
      expect(ids.has(e.id), `dubbel id ${e.id}`).toBe(false)
      ids.add(e.id)
      expect(e.synoniemen.length).toBeGreaterThan(0)
      if (e.doel.soort === 'sectie') expect(SECTIE_PADEN.has(e.doel.sectie), `${e.id} → onbekende sectie`).toBe(true)
      else expect(tabPaden.has(e.doel.tab), `${e.id} → onbekende tab`).toBe(true)
    }
  })

  it('de drie nav-groepen staan in de mockup-volgorde met de mockup-items', () => {
    expect(NAV_GROEPEN.map((g) => g.titel)).toEqual(['Administraties', 'Platform', 'Kantoor'])
    expect(NAV_GROEPEN[0].items.map((i) => i.pad)).toEqual(['administraties', 'accordering', 'autoboeken', 'doorbelasting'])
    expect(NAV_GROEPEN[1].items.map((i) => i.pad)).toEqual(['boeken', 'intake-ai'])
    expect(NAV_GROEPEN[2].items.map((i) => i.pad)).toEqual(['gebruikers', 'beveiliging', 'materiaal'])
    // Crediteuren is géén instelling meer (→ Inzicht); de oude URL redirect.
    expect(SECTIE_PADEN.has('crediteuren')).toBe(false)
    expect(OUDE_SECTIE_REDIRECTS.crediteuren).toBe('/crediteuren')
  })
})

describe('instellingenRegistry — rol×sectie-matrix fail-closed + landing per rol', () => {
  it('Beheerder ziet alles; Boekhouding alleen Beveiliging; B+P Beveiliging + Materiaalcatalogus; onbekend/null alleen Beveiliging', () => {
    const paden = (rol: string | null) => zichtbareNavItems(rol).map((i) => i.pad)
    expect(paden('beheerder')).toEqual(NAV_ITEMS.map((i) => i.pad))
    expect(paden('boekhouding')).toEqual(['beveiliging'])
    expect(paden('boekhouding_projecten')).toEqual(['beveiliging', 'materiaal'])
    expect(paden('toekomstige_rol')).toEqual(['beveiliging'])
    expect(paden(null)).toEqual(['beveiliging'])
  })

  it('lege groepen krijgen geen kop', () => {
    expect(zichtbareNavGroepen('boekhouding').map((g) => g.titel)).toEqual(['Kantoor'])
    expect(zichtbareNavGroepen('beheerder').map((g) => g.titel)).toEqual(['Administraties', 'Platform', 'Kantoor'])
  })

  it('landing: Beheerder → administraties, Boekhouding → beveiliging, B+P → materiaal, onbekend → beveiliging', () => {
    expect(eersteSectieVoor('beheerder')).toBe('administraties')
    expect(eersteSectieVoor('boekhouding')).toBe('beveiliging')
    expect(eersteSectieVoor('boekhouding_projecten')).toBe('materiaal')
    expect(eersteSectieVoor('onbekend')).toBe('beveiliging')
  })

  it('tabs volgen de toon-regel: Doorbelasting bij bron óf doel, Uren/Voorraad alleen bij opt-in', () => {
    expect(zichtbareTabs({}).map((t) => t.pad)).toEqual(['algemeen', 'boeken-ai', 'accordering'])
    expect(zichtbareTabs({ doorbelasting_doel: true }).map((t) => t.pad)).toContain('doorbelasting')
    expect(zichtbareTabs({ doorbelasting_ingeschakeld: true }).map((t) => t.pad)).toContain('doorbelasting')
    expect(zichtbareTabs({ uren_meerwerk_ingeschakeld: true, voorraad_ingeschakeld: true }).map((t) => t.pad)).toEqual([
      'algemeen',
      'boeken-ai',
      'accordering',
      'uren-materiaal',
      'voorraad',
    ])
  })
})

describe('instellingenRegistry — deterministische zoeker', () => {
  const zoek = (q: string, rol: string | null = 'beheerder') => zoekInstellingen(q, { rol, administraties: ADMINISTRATIES })

  it('"accordering arvum" → administratie-specifieke tab-deep-link éérst, dan het nav-item en de bulkactie (mockup-voorbeeld)', () => {
    const r = zoek('accordering arvum')
    expect(r[0]).toMatchObject({ naam: 'Klant-accordering — ARVUM B.V.', pad: '/instellingen/administraties/a1?tab=accordering' })
    expect(r[0].waar).toBe('Administraties › ARVUM B.V. › tab Klant-accordering')
    expect(r.map((t) => t.naam)).toContain('Klant-accordering — alle administraties')
    expect(r.map((t) => t.naam)).toContain("Bulk: klant-accordering instellen op meerdere BV's")
    expect(r.some((t) => t.administratie?.id === 'a2')).toBe(false)
  })

  it('alleen een administratienaam → de Algemeen-tab van die administratie', () => {
    const r = zoek('kempen')
    expect(r[0]).toMatchObject({ pad: '/instellingen/administraties/a3', naam: 'Algemeen — Kempen Facilities B.V.' })
  })

  it('generieke zoekwoorden landen op het nav-item (synoniemen, prefix-match, accent-ongevoelig, stabiele volgorde)', () => {
    expect(zoek('noodstop')[0].pad).toBe('/instellingen/boeken')
    expect(zoek('passk')[0].pad).toBe('/instellingen/beveiliging')
    expect(zoek('Gebruikers')[0].pad).toBe('/gebruikers')
    expect(zoek('provisie').map((t) => t.pad)).toContain('/instellingen/doorbelasting')
    expect(zoek('limiet').map((t) => t.pad)).toContain('/instellingen/intake-ai#kosten')
    expect(zoek('provisie')).toEqual(zoek('provisie'))
  })

  it('is fail-closed per rol: Boekhouding ziet alleen Beveiliging-treffers en nooit administratie-deep-links', () => {
    expect(zoek('accordering arvum', 'boekhouding')).toEqual([])
    expect(zoek('passkey', 'boekhouding').every((t) => t.pad.startsWith('/instellingen/beveiliging'))).toBe(true)
    expect(zoek('administraties', 'boekhouding')).toEqual([])
    expect(zoek('materiaal', 'boekhouding_projecten')[0].pad).toBe('/instellingen/materiaal')
  })

  it('lege of onbekende zoekterm → geen treffers (geen gokken, geen AI)', () => {
    expect(zoek('')).toEqual([])
    expect(zoek('   ')).toEqual([])
    expect(zoek('xyzzy-onbekend')).toEqual([])
  })
})
