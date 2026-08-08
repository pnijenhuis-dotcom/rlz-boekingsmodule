import fs from 'node:fs'
import path from 'node:path'
import type { IncomingMessage } from 'node:http'
import { describe, expect, it } from 'vitest'
import proxyPrefixes from '../../proxy-prefixes.json'
import { bouwProxyMap, isDocumentNavigatie } from '../../proxyRegels'

/** Structurele guard op de proxy-bugklasse (derde herhaling, browserreview 2026-08-07): een
 * API-pad dat buiten de dev-proxy valt krijgt in dev stil Vite's SPA-fallback (index.html,
 * status 200) terug. Deze test scant daarom AUTOMATISCH álle bronbestanden onder src/ op
 * letterlijke paden in apiJson/apiFetch/apiPostJson/fetch-aanroepen en toetst elk pad tegen de
 * uit de backend-router gegenereerde prefixlijst (proxy-prefixes.json) — geen handmatig
 * registerlijstje meer dat kan achterlopen. De backend-kant wordt bewaakt door
 * tests/unit/test_proxy_prefixes_dump.py (router ↔ JSON). */

const SRC = path.resolve(__dirname, '..')

function alleBronbestanden(map: string): string[] {
  return fs
    .readdirSync(map, { withFileTypes: true })
    .flatMap((item) => {
      const volledig = path.join(map, item.name)
      if (item.isDirectory()) return alleBronbestanden(volledig)
      if (!/\.tsx?$/.test(item.name) || /\.test\.tsx?$/.test(item.name)) return []
      return [volledig]
    })
}

/** Vangt het eerste argument van elke API-aanroep zolang het met een letterlijke '/' begint;
 * template-interpolatie (`/administraties/${id}/…`) telt mee tot aan de eerste `${`, wat voor
 * prefix-dekking precies genoeg is. */
const AANROEP_REGEX = /(?:apiJson|apiFetch|apiPostJson|ruweFetch|fetch)\s*(?:<[^>(]*>)?\(\s*[`'"](\/[^`'"$]*)/g

function apiPadenIn(bestand: string): string[] {
  const bron = fs.readFileSync(bestand, 'utf8')
  return Array.from(bron.matchAll(AANROEP_REGEX), (m) => m[1])
}

function isGedekt(pad: string): boolean {
  return (
    proxyPrefixes.exacte_paden.some((exact) => pad === exact || pad.startsWith(`${exact}/`)) ||
    proxyPrefixes.segmenten.some((segment) => pad.startsWith(`${segment}/`))
  )
}

describe('dev-proxy-dekking over álle bronbestanden', () => {
  const bestanden = alleBronbestanden(SRC)
  const perBestand = bestanden
    .map((bestand) => ({ bestand: path.relative(SRC, bestand), paden: apiPadenIn(bestand) }))
    .filter(({ paden }) => paden.length > 0)

  it('vindt aanroepen (guard tegen extractie-rot): elk *Api.ts-bestand levert minstens één pad', () => {
    const apiBestanden = bestanden.filter((b) => b.endsWith('Api.ts'))
    expect(apiBestanden.length).toBeGreaterThan(0)
    for (const bestand of apiBestanden) {
      expect(apiPadenIn(bestand).length, `${bestand} leverde geen enkel API-pad op — regex stuk of pad niet letterlijk?`).toBeGreaterThan(0)
    }
  })

  it.each(perBestand)('$bestand: alle paden absoluut en door de dev-proxy gedekt', ({ paden }) => {
    for (const pad of paden) {
      expect(pad, `pad "${pad}" is relatief`).toMatch(/^\//)
      expect(
        isGedekt(pad),
        `pad "${pad}" valt buiten proxy-prefixes.json — nieuwe backend-prefix? ` +
          'Ververs met (cd backend && .venv/bin/python -m app.proxy_prefixes); ' +
          'roept dit een kaal segment aan dat ook een SPA-route is, kies dan een dieper pad.',
      ).toBe(true)
    }
  })

  it('regressie 2026-08-07: de paden van de twee kapotte schermen zijn gedekt', () => {
    // Bank-overzicht en verzamelbak gaven "<!doctype … is not valid JSON".
    expect(isGedekt('/bank/overzicht')).toBe(true)
    expect(isGedekt('/verzamelbak')).toBe(true)
    expect(isGedekt('/intake/eml')).toBe(true)
  })

  describe('regressie kliktest 2026-08-08: document-navigatie naar /bank/ blijft SPA', () => {
    // Navigatie mét trailing slash (/bank/) matcht de segment-key 'bank/' en kwam als kale
    // backend-404-JSON bij de gebruiker. De bypass moet document-navigaties de SPA laten
    // serveren en fetch/XHR gewoon blijven proxien.
    const navigatieHeaders = {
      accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
      'sec-fetch-dest': 'document',
    }
    const fetchHeaders = { accept: 'application/json', 'sec-fetch-dest': 'empty' }
    const downloadHeaders = { accept: '*/*', 'sec-fetch-dest': 'empty' }

    it('herkent een document-navigatie alleen aan Accept text/html ÉN sec-fetch-dest=document', () => {
      expect(isDocumentNavigatie(navigatieHeaders)).toBe(true)
      expect(isDocumentNavigatie(fetchHeaders)).toBe(false)
      expect(isDocumentNavigatie(downloadHeaders)).toBe(false)
      expect(isDocumentNavigatie({})).toBe(false)
    })

    it('elke proxy-entry heeft de bypass: navigatie → /index.html, fetch → geproxied', () => {
      const proxy = bouwProxyMap(proxyPrefixes, 'http://localhost:8000')
      expect(Object.keys(proxy).length).toBeGreaterThan(0)
      expect(Object.keys(proxy)).toContain('/bank/')
      for (const [key, entry] of Object.entries(proxy)) {
        expect(entry.target, `entry "${key}" mist target`).toBe('http://localhost:8000')
        expect(
          entry.bypass({ headers: navigatieHeaders } as unknown as IncomingMessage),
          `entry "${key}": document-navigatie moet de SPA krijgen`,
        ).toBe('/index.html')
        expect(
          entry.bypass({ headers: fetchHeaders } as unknown as IncomingMessage),
          `entry "${key}": fetch/XHR moet geproxied blijven`,
        ).toBeUndefined()
      }
    })
  })

  it('geen SPA-route wordt door een exacte proxy-key geschaduwd (document-navigatie blijft SPA)', () => {
    const appBron = fs.readFileSync(path.join(SRC, 'App.tsx'), 'utf8')
    const spaRoutes = Array.from(appBron.matchAll(/path="(\/[^"*]*)"/g), (m) => m[1])
    expect(spaRoutes.length).toBeGreaterThan(0)
    for (const route of spaRoutes) {
      const topSegment = `/${route.split('/')[1] ?? ''}`
      expect(
        proxyPrefixes.exacte_paden.includes(topSegment),
        `SPA-route "${route}" botst met exact backend-pad "${topSegment}" — document-navigatie zou naar de backend gaan`,
      ).toBe(false)
    }
  })
})
