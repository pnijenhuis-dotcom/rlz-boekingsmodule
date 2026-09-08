// Web-terugval van de VeiligeOpslag (app-auth zonder passkey 08-09, contract §5a): de IndexedDB-
// adapter bestaat ALLEEN op de accordeur-oppervlakte (pad of vlag) mét WebCrypto + IndexedDB; de
// kantoor-web ziet 'm nooit. Plus de doorschakeling in nativeSessie (`veiligeOpslagPlugin`,
// `slotModus`, `slotSessieBeschikbaar`).

import { webcrypto } from 'node:crypto'
import { afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest'
import { installeerFakeIndexedDb } from './fakeIndexedDb.testhulp'
import { natieveSessieBeschikbaar, slotModus, slotSessieBeschikbaar, veiligeOpslagPlugin } from './nativeSessie'
import { SLOT_MODUS_SLEUTEL, webSlotModusActief, webVeiligeOpslag, zetWebSlotModus } from './webVeiligeOpslag'

if (!globalThis.crypto?.subtle) {
  Object.defineProperty(globalThis, 'crypto', { value: webcrypto, configurable: true })
}

// Node 22+ schaduwt window.localStorage in de jsdom-testomgeving — in-memory vervanger (patroon standCache.test.ts).
beforeAll(() => {
  const opslag = new Map<string, string>()
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: {
      getItem: (k: string) => opslag.get(k) ?? null,
      setItem: (k: string, v: string) => void opslag.set(k, String(v)),
      removeItem: (k: string) => void opslag.delete(k),
      clear: () => opslag.clear(),
      key: (i: number) => [...opslag.keys()][i] ?? null,
      get length() {
        return opslag.size
      },
    } as Storage,
  })
})

let idb: ReturnType<typeof installeerFakeIndexedDb>

beforeEach(() => {
  idb = installeerFakeIndexedDb()
  window.history.pushState({}, '', '/')
  localStorage.removeItem(SLOT_MODUS_SLEUTEL)
})

afterEach(() => {
  idb.herstel()
  window.history.pushState({}, '', '/')
  localStorage.removeItem(SLOT_MODUS_SLEUTEL)
})

describe('webSlotModusActief — strikt begrensd tot de accordeur-oppervlakte', () => {
  it('kantoor-pad zonder vlag → false (de kantoor-web merkt niets)', () => {
    expect(webSlotModusActief()).toBe(false)
    expect(veiligeOpslagPlugin()).toBeNull()
    expect(slotModus()).toBeNull()
    expect(slotSessieBeschikbaar()).toBe(false)
    expect(natieveSessieBeschikbaar()).toBe(false)
  })

  it('/accordeur (en dieper) → true; /accordeurtje niet', () => {
    window.history.pushState({}, '', '/accordeur')
    expect(webSlotModusActief()).toBe(true)
    window.history.pushState({}, '', '/accordeur/activeren?uitnodiging=x')
    expect(webSlotModusActief()).toBe(true)
    window.history.pushState({}, '', '/accordeurtje')
    expect(webSlotModusActief()).toBe(false)
  })

  it('de slot-vlag maakt de modus ook buiten /accordeur actief; zetWebSlotModus(false) wist de vlag', () => {
    zetWebSlotModus(true)
    expect(localStorage.getItem(SLOT_MODUS_SLEUTEL)).toBe('1')
    expect(webSlotModusActief()).toBe(true)
    expect(slotModus()).toBe('web')
    expect(slotSessieBeschikbaar()).toBe(true)
    zetWebSlotModus(false)
    expect(webSlotModusActief()).toBe(false)
  })

  it('zonder IndexedDB → false, ook op /accordeur (fail-closed)', () => {
    window.history.pushState({}, '', '/accordeur')
    idb.herstel()
    expect(webSlotModusActief()).toBe(false)
    expect(veiligeOpslagPlugin()).toBeNull()
  })
})

describe('IndexedDB-adapter — zelfde interface als de native plugin', () => {
  it('zet/haal/verwijder over de kv-store', async () => {
    const adapter = webVeiligeOpslag()
    await adapter.zet({ sleutel: 'a', waarde: '1' })
    expect((await adapter.haal({ sleutel: 'a' })).waarde).toBe('1')
    expect((await adapter.haal({ sleutel: 'b' })).waarde).toBeNull()
    await adapter.verwijder({ sleutel: 'a' })
    expect((await adapter.haal({ sleutel: 'a' })).waarde).toBeNull()
    expect(idb.data.get('accordeur-slot')?.get('kv')?.size).toBe(0)
  })

  it('veiligeOpslagPlugin() geeft in de web-slotmodus de adapter terug (native plugin gaat vóór)', async () => {
    window.history.pushState({}, '', '/accordeur')
    const plugin = veiligeOpslagPlugin()
    expect(plugin).not.toBeNull()
    await plugin!.zet({ sleutel: 'x', waarde: 'y' })
    expect(idb.data.get('accordeur-slot')?.get('kv')?.get('x')).toBe('y')
  })
})
