import { afterEach, describe, expect, it, vi } from 'vitest'
import viteConfig from '../../vite.config'
import { haalIbanAccordeursOp, zetIbanAccordeurs } from '../document/ibanAccorderingApi'
import { haalMedewerkersOp } from '../vragen/vragenApi'
import {
  haalBoekenKillSwitchOp,
  haalInstellingenAdministratiesOp,
  zetAiExtractieInstelling,
  zetBoekenInstelling,
  zetBoekenKillSwitch,
  zetEigenaar,
  zetProjectInstelling,
} from './instellingenApi'

/** Proxy-guard (regressie op de browserreview-bug van 2026-07-15): een API-pad dat niet onder
 * een Vite-proxy-prefix valt, krijgt in dev stil Vite's SPA-fallback (index.html, status 200)
 * terug — de componenttests zien dat nooit, want die mocken fetch op de exacte URL. Deze test
 * toetst daarom élk pad dat de instellingen-helpers aanroepen tegen de échte proxy-prefixen
 * uit vite.config.ts: absoluut (leading slash, dus nooit relatief tegen de huidige route) én
 * gedekt door de proxy. Zelfde geest als de backend model-repo-drift-guard. */

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'

function proxyPrefixen(): string[] {
  const proxy = (viteConfig as { server?: { proxy?: Record<string, unknown> } }).server?.proxy
  if (!proxy) throw new Error('vite.config.ts heeft geen server.proxy — is de dev-proxy verdwenen?')
  return Object.keys(proxy)
}

/** Alle helpers die het Instellingen-scherm (incl. het IBAN-accordeur-veld en de
 * medewerkers-namen) gebruiken — nieuwe helper in het scherm? Hier registreren. */
const HELPER_AANROEPEN: Array<{ naam: string; roep: () => Promise<unknown> }> = [
  { naam: 'haalInstellingenAdministratiesOp', roep: () => haalInstellingenAdministratiesOp() },
  { naam: 'haalBoekenKillSwitchOp', roep: () => haalBoekenKillSwitchOp() },
  { naam: 'zetBoekenKillSwitch', roep: () => zetBoekenKillSwitch(true) },
  { naam: 'zetBoekenInstelling', roep: () => zetBoekenInstelling(ADMINISTRATIE_ID, true) },
  { naam: 'zetProjectInstelling', roep: () => zetProjectInstelling(ADMINISTRATIE_ID, true) },
  { naam: 'zetAiExtractieInstelling', roep: () => zetAiExtractieInstelling(ADMINISTRATIE_ID, true) },
  { naam: 'zetEigenaar', roep: () => zetEigenaar(ADMINISTRATIE_ID, null) },
  { naam: 'haalIbanAccordeursOp', roep: () => haalIbanAccordeursOp(ADMINISTRATIE_ID) },
  { naam: 'zetIbanAccordeurs', roep: () => zetIbanAccordeurs(ADMINISTRATIE_ID, []) },
  { naam: 'haalMedewerkersOp', roep: () => haalMedewerkersOp(ADMINISTRATIE_ID) },
]

describe('instellingen-API-helpers — paden absoluut en door de dev-proxy gedekt', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it.each(HELPER_AANROEPEN)('$naam roept een absoluut, geproxyd pad aan', async ({ roep }) => {
    const aangeroepen: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        aangeroepen.push(url)
        return Promise.resolve(
          new Response(JSON.stringify({}), { status: 200, headers: { 'Content-Type': 'application/json' } }),
        )
      }),
    )

    await roep()

    expect(aangeroepen).toHaveLength(1)
    const pad = aangeroepen[0]
    // Absoluut: begint met '/', nooit relatief tegen de huidige SPA-route.
    expect(pad, `pad "${pad}" is relatief`).toMatch(/^\//)
    // Vite-semantiek: een proxy-key is een prefix-match op het pad. '/instellingen/' staat
    // bewust mét slash (het kale '/instellingen' is de SPA-route) — startsWith dekt beide.
    const prefixen = proxyPrefixen()
    expect(
      prefixen.some((prefix) => pad.startsWith(prefix)),
      `pad "${pad}" valt onder geen enkele dev-proxy-prefix (${prefixen.join(', ')}) — ` +
        'Vite geeft er dan index.html op terug en JSON.parse faalt pas later',
    ).toBe(true)
  })
})
