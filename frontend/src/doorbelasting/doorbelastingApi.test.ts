import { afterEach, describe, expect, it, vi } from 'vitest'
import viteConfig from '../../vite.config'
import {
  boekDoorbelastingRun,
  boekSpiegelAlsnog,
  haalDoorbelastingInstellingOp,
  haalDoorbelastingMappingsOp,
  haalDoorbelastingRunOp,
  haalDoorbelastingToggleOp,
  haalSpiegelTakenOp,
  slaDoorbelastingVerdelingOp,
  startDoorbelastingRun,
  stornoDoorbelastingBoeking,
  wijzigDoorbelastingMapping,
  zetDoorbelastingInstelling,
  zetDoorbelastingToggle,
  zetSpiegelDoelGbs,
} from './doorbelastingApi'

/** Proxy-guard (zelfde patroon als instellingenApi.test.ts, regressie op de vergeten-prefix-bug):
 * élk pad dat de doorbelasting-helpers aanroepen moet absoluut zijn én onder een échte
 * Vite-proxy-prefix vallen — anders geeft dev stil Vite's SPA-fallback (index.html, 200) terug
 * en faalt het pas bij JSON.parse. `/doorbelasting` staat sinds blok 1 in proxy-prefixes.json. */

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const RUN_ID = 'cccccccc-0000-0000-0000-000000000003'
const MAPPING_ID = 'dddddddd-0000-0000-0000-000000000004'
const BOEKING_ID = 'eeeeeeee-0000-0000-0000-000000000005'

function proxyPrefixen(): string[] {
  const proxy = (viteConfig as { server?: { proxy?: Record<string, unknown> } }).server?.proxy
  if (!proxy) throw new Error('vite.config.ts heeft geen server.proxy — is de dev-proxy verdwenen?')
  return Object.keys(proxy)
}

const HELPER_AANROEPEN: Array<{ naam: string; roep: () => Promise<unknown> }> = [
  { naam: 'haalDoorbelastingToggleOp', roep: () => haalDoorbelastingToggleOp(ADMINISTRATIE_ID) },
  { naam: 'zetDoorbelastingToggle', roep: () => zetDoorbelastingToggle(ADMINISTRATIE_ID, true) },
  { naam: 'haalDoorbelastingInstellingOp', roep: () => haalDoorbelastingInstellingOp(ADMINISTRATIE_ID) },
  {
    naam: 'zetDoorbelastingInstelling',
    roep: () =>
      zetDoorbelastingInstelling(ADMINISTRATIE_ID, {
        provisie_percentage: '5',
        btw_taxrate_id: null,
        omzet_ledger_id: null,
        provisie_omzet_ledger_id: null,
      }),
  },
  { naam: 'haalDoorbelastingMappingsOp', roep: () => haalDoorbelastingMappingsOp(ADMINISTRATIE_ID) },
  {
    naam: 'wijzigDoorbelastingMapping',
    roep: () => wijzigDoorbelastingMapping(ADMINISTRATIE_ID, MAPPING_ID, { actief: false }),
  },
  { naam: 'startDoorbelastingRun', roep: () => startDoorbelastingRun(ADMINISTRATIE_ID, DOCUMENT_ID) },
  { naam: 'haalDoorbelastingRunOp', roep: () => haalDoorbelastingRunOp(ADMINISTRATIE_ID, RUN_ID) },
  {
    naam: 'slaDoorbelastingVerdelingOp',
    roep: () => slaDoorbelastingVerdelingOp(ADMINISTRATIE_ID, RUN_ID, []),
  },
  { naam: 'boekDoorbelastingRun', roep: () => boekDoorbelastingRun(ADMINISTRATIE_ID, RUN_ID) },
  { naam: 'haalSpiegelTakenOp', roep: () => haalSpiegelTakenOp(ADMINISTRATIE_ID) },
  {
    naam: 'zetSpiegelDoelGbs',
    roep: () => zetSpiegelDoelGbs(ADMINISTRATIE_ID, BOEKING_ID, { regel_gbs: {} }),
  },
  { naam: 'boekSpiegelAlsnog', roep: () => boekSpiegelAlsnog(ADMINISTRATIE_ID, BOEKING_ID) },
  {
    naam: 'stornoDoorbelastingBoeking',
    roep: () => stornoDoorbelastingBoeking(ADMINISTRATIE_ID, BOEKING_ID, 'dubbel doorbelast'),
  },
]

describe('doorbelasting-API-helpers — paden absoluut en door de dev-proxy gedekt', () => {
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
    expect(pad, `pad "${pad}" is relatief`).toMatch(/^\//)
    const prefixen = proxyPrefixen()
    expect(
      prefixen.some((prefix) => pad.startsWith(prefix)),
      `pad "${pad}" valt onder geen enkele dev-proxy-prefix (${prefixen.join(', ')}) — ` +
        'Vite geeft er dan index.html op terug en JSON.parse faalt pas later',
    ).toBe(true)
  })
})
