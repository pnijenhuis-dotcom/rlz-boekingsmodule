// App-lock-kern (31-08, mockup app-lock-pincode.html): zwakke reeksen, code-anker-crypto,
// foutenteller (5 = lokaal gewist, credential_id blijft), biometrie-kopie en het refresh-token
// achter het slot (nativeSessie-integratie). Capacitor gestubd zoals in nativePasskey.test.ts.

import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { webcrypto } from 'node:crypto'
import {
  CODE_LENGTE,
  MAX_FOUTEN,
  bewaarCredentialId,
  haalCredentialId,
  isAppSlotIngesteld,
  isBiometrieAan,
  isOntgrendeld,
  isZwakkeCode,
  ontgrendelMetBiometrie,
  ontgrendelMetCode,
  resterendePogingen,
  stelCodeIn,
  vergrendel,
  wijzigCode,
  wisAppSlotLokaal,
  zetBiometrieAan,
} from './appSlot'
import { bewaarNatiefRefreshToken, haalNatiefRefreshToken } from './nativeSessie'
import { installeerFakeIndexedDb } from './fakeIndexedDb.testhulp'
import { leesLaatsteSlotfout } from './slotDiagnose'
import { appSlotBeschikbaar } from './appSlot'

// jsdom heeft geen WebCrypto — Node's implementatie is byte-compatibel.
if (!globalThis.crypto?.subtle) {
  Object.defineProperty(globalThis, 'crypto', { value: webcrypto, configurable: true })
}

// De slot-diagnose (api/slotDiagnose.ts) schrijft naar localStorage — in-memory vervanger als de omgeving er geen heeft.
if (typeof globalThis.localStorage === 'undefined' || typeof globalThis.localStorage?.getItem !== 'function') {
  const kv = new Map<string, string>()
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem: (k: string) => kv.get(k) ?? null,
      setItem: (k: string, v: string) => void kv.set(k, String(v)),
      removeItem: (k: string) => void kv.delete(k),
      clear: () => kv.clear(),
    },
  })
}

let opslag: Map<string, string>
let biometrieKluis: { waarde: string | null }
let biometrieWeigert: boolean

function stubCapacitor(): void {
  opslag = new Map()
  biometrieKluis = { waarde: null }
  biometrieWeigert = false
  ;(globalThis as { window?: unknown }).window ??= globalThis
  ;(window as unknown as { Capacitor: unknown }).Capacitor = {
    isNativePlatform: () => true,
    Plugins: {
      VeiligeOpslag: {
        zet: ({ sleutel, waarde }: { sleutel: string; waarde: string }) => {
          opslag.set(sleutel, waarde)
          return Promise.resolve()
        },
        haal: ({ sleutel }: { sleutel: string }) => Promise.resolve({ waarde: opslag.get(sleutel) ?? null }),
        verwijder: ({ sleutel }: { sleutel: string }) => {
          opslag.delete(sleutel)
          return Promise.resolve()
        },
      },
      AppSlot: {
        beschikbaar: () => Promise.resolve({ beschikbaar: true, soort: 'gezicht' }),
        zetSleutel: ({ waarde }: { waarde: string }) => {
          biometrieKluis.waarde = waarde
          return Promise.resolve()
        },
        haalSleutel: () => {
          if (biometrieWeigert) return Promise.reject(new Error('geannuleerd'))
          return Promise.resolve({ waarde: biometrieKluis.waarde })
        },
        wisSleutel: () => {
          biometrieKluis.waarde = null
          return Promise.resolve()
        },
      },
    },
  }
}

beforeEach(() => {
  stubCapacitor()
  vergrendel()
})

afterEach(() => {
  delete (window as unknown as { Capacitor?: unknown }).Capacitor
})

describe('isZwakkeCode', () => {
  it('weigert constante en op-/aflopende reeksen (incl. wrap-around)', () => {
    for (const zwak of ['00000', '11111', '12345', '54321', '90123', '09876', '67890']) {
      expect(isZwakkeCode(zwak), zwak).toBe(true)
    }
  })
  it('accepteert gewone codes en weigert niet-codes', () => {
    for (const ok of ['13579', '20406', '11211', '99889']) {
      expect(isZwakkeCode(ok), ok).toBe(false)
    }
    expect(isZwakkeCode('1234')).toBe(true)
    expect(isZwakkeCode('abcde')).toBe(true)
    expect(CODE_LENGTE).toBe(5)
  })
})

describe('code-anker', () => {
  it('stelt in, vergrendelt en ontgrendelt met de juiste code', async () => {
    await stelCodeIn('13579')
    expect(await isAppSlotIngesteld()).toBe(true)
    expect(isOntgrendeld()).toBe(true)
    vergrendel()
    expect(isOntgrendeld()).toBe(false)
    expect(await ontgrendelMetCode('13570')).toBe('fout')
    expect(await resterendePogingen()).toBe(MAX_FOUTEN - 1)
    expect(await ontgrendelMetCode('13579')).toBe('ok')
    expect(isOntgrendeld()).toBe(true)
    // Geslaagde ontgrendeling reset de teller.
    expect(await resterendePogingen()).toBe(MAX_FOUTEN)
  })

  it('wist ná 5 foute codes alles behalve het credential_id (uitsluitings-sleutel)', async () => {
    await stelCodeIn('13579')
    await bewaarCredentialId('cred-abc')
    await bewaarNatiefRefreshToken('geheim-token')
    vergrendel()
    for (let i = 0; i < MAX_FOUTEN - 1; i++) {
      expect(await ontgrendelMetCode('00001')).toBe('fout')
    }
    expect(await ontgrendelMetCode('00001')).toBe('uitgesloten')
    expect(await isAppSlotIngesteld()).toBe(false)
    expect(await haalNatiefRefreshToken()).toBeNull()
    expect(await haalCredentialId()).toBe('cred-abc')
  })

  it('wijzigt de code op het anker in geheugen — zonder tweede verificatie tegen de opslag', async () => {
    await stelCodeIn('13579')
    expect(opslag.get('appslot_slot')).toMatch(/^v2\./)
    // Bewijs dat er niet opnieuw tegen de opgeslagen wrap geverifieerd wordt: zelfs zonder slot-waarde in
    // de opslag slaagt het wijzigen (het anker staat in het geheugen sinds stap 1 / het instellen).
    opslag.delete('appslot_slot')
    expect(await wijzigCode('24680')).toBe('ok')
    vergrendel()
    expect(await ontgrendelMetCode('13579')).toBe('fout')
    expect(await ontgrendelMetCode('24680')).toBe('ok')
  })

  it('niet-ontgrendeld slot → eigen uitkomst, geen teller-verhoging, opslag onaangeraakt', async () => {
    await stelCodeIn('13579')
    const voor = opslag.get('appslot_slot')
    vergrendel()
    expect(await wijzigCode('24680')).toBe('niet_ontgrendeld')
    expect(await resterendePogingen()).toBe(MAX_FOUTEN)
    expect(opslag.get('appslot_slot')).toBe(voor)
    expect(await ontgrendelMetCode('13579')).toBe('ok')
  })

  it('schrijffout bij wijzigen → fout, oude code blijft gelden (niets stil geslikt)', async () => {
    await stelCodeIn('13579')
    const voor = opslag.get('appslot_slot')
    const plugins = (window as unknown as { Capacitor: { Plugins: { VeiligeOpslag: { zet: unknown } } } }).Capacitor.Plugins
    const echteZet = plugins.VeiligeOpslag.zet as (o: { sleutel: string; waarde: string }) => Promise<void>
    plugins.VeiligeOpslag.zet = ({ sleutel, waarde }: { sleutel: string; waarde: string }) =>
      sleutel === 'appslot_slot' ? Promise.reject(new Error('Opslag-schrijffout: kluis dicht')) : echteZet({ sleutel, waarde })
    expect(await wijzigCode('24680')).toBe('fout')
    plugins.VeiligeOpslag.zet = echteZet
    expect(opslag.get('appslot_slot')).toBe(voor)
    vergrendel()
    expect(await ontgrendelMetCode('24680')).toBe('fout')
    expect(await ontgrendelMetCode('13579')).toBe('ok')
    // De reden staat lokaal in de slot-diagnose — sleutelnaam + reden, nooit een waarde.
    const diag = leesLaatsteSlotfout()
    expect(diag?.handeling).toBe('schrijf')
    expect(diag?.sleutel).toBe('appslot_slot')
    expect(diag?.reden).toContain('kluis dicht')
    expect(JSON.stringify(diag)).not.toContain(voor!.slice(3, 20))
  })

  it('schrijven "lukt" maar terug lezen geeft iets anders → fout + oude stand hersteld', async () => {
    await stelCodeIn('13579')
    const voor = opslag.get('appslot_slot')
    const plugins = (window as unknown as { Capacitor: { Plugins: { VeiligeOpslag: { zet: unknown } } } }).Capacitor.Plugins
    const echteZet = plugins.VeiligeOpslag.zet as (o: { sleutel: string; waarde: string }) => Promise<void>
    // Alleen de EERSTE schrijfactie op de slot-sleutel komt vervormd aan (de herstel-schrijfactie daarna niet).
    let vervormd = false
    plugins.VeiligeOpslag.zet = ({ sleutel, waarde }: { sleutel: string; waarde: string }) => {
      if (sleutel === 'appslot_slot' && !vervormd) {
        vervormd = true
        return echteZet({ sleutel, waarde: `${waarde}kapot` })
      }
      return echteZet({ sleutel, waarde })
    }
    expect(await wijzigCode('24680')).toBe('fout')
    plugins.VeiligeOpslag.zet = echteZet
    expect(opslag.get('appslot_slot')).toBe(voor)
    vergrendel()
    expect(await ontgrendelMetCode('13579')).toBe('ok')
  })

  it('legacy: twee losse sleutels (salt + wrap) blijven leesbaar en migreren bij de eerste ontgrendeling', async () => {
    await stelCodeIn('13579')
    const [, salt, iv, cipher] = opslag.get('appslot_slot')!.split('.')
    opslag.delete('appslot_slot')
    opslag.set('appslot_salt', salt)
    opslag.set('appslot_wrap', `${iv}.${cipher}`)
    vergrendel()
    expect(await isAppSlotIngesteld()).toBe(true)
    expect(await ontgrendelMetCode('00001')).toBe('fout')
    expect(await ontgrendelMetCode('13579')).toBe('ok')
    expect(opslag.get('appslot_slot')).toBe(`v2.${salt}.${iv}.${cipher}`)
    expect(opslag.has('appslot_salt')).toBe(false)
    expect(opslag.has('appslot_wrap')).toBe(false)
  })

  it('legacy + mislukte migratie: de losse sleutels blijven staan, niemand raakt buitengesloten', async () => {
    await stelCodeIn('13579')
    const [, salt, iv, cipher] = opslag.get('appslot_slot')!.split('.')
    opslag.delete('appslot_slot')
    opslag.set('appslot_salt', salt)
    opslag.set('appslot_wrap', `${iv}.${cipher}`)
    vergrendel()
    const plugins = (window as unknown as { Capacitor: { Plugins: { VeiligeOpslag: { zet: unknown } } } }).Capacitor.Plugins
    const echteZet = plugins.VeiligeOpslag.zet as (o: { sleutel: string; waarde: string }) => Promise<void>
    plugins.VeiligeOpslag.zet = ({ sleutel, waarde }: { sleutel: string; waarde: string }) =>
      sleutel === 'appslot_slot' ? Promise.reject(new Error('kluis dicht')) : echteZet({ sleutel, waarde })
    expect(await ontgrendelMetCode('13579')).toBe('ok')
    expect(opslag.has('appslot_salt')).toBe(true)
    expect(opslag.has('appslot_wrap')).toBe(true)
    // Wijzigen faalt dan eerlijk en laat de legacy-stand intact.
    expect(await wijzigCode('24680')).toBe('fout')
    plugins.VeiligeOpslag.zet = echteZet
    vergrendel()
    expect(await ontgrendelMetCode('13579')).toBe('ok')
  })
})

describe('refresh-token achter het slot', () => {
  it('slaat versleuteld op en is alleen ontgrendeld leesbaar', async () => {
    await stelCodeIn('13579')
    await bewaarNatiefRefreshToken('token-123')
    expect(opslag.get('refresh_token')).toMatch(/^slot\.v1\./)
    expect(await haalNatiefRefreshToken()).toBe('token-123')
    vergrendel()
    expect(await haalNatiefRefreshToken()).toBeNull()
    await ontgrendelMetCode('13579')
    expect(await haalNatiefRefreshToken()).toBe('token-123')
  })

  it('zet een bestaand plain token (legacy) om bij het instellen van het slot', async () => {
    await bewaarNatiefRefreshToken('legacy-token')
    expect(opslag.get('refresh_token')).toBe('legacy-token')
    await stelCodeIn('13579')
    expect(opslag.get('refresh_token')).toMatch(/^slot\.v1\./)
    expect(await haalNatiefRefreshToken()).toBe('legacy-token')
  })
})

describe('biometrie-gemakslaag', () => {
  it('ontgrendelt via de kopie en valt bij weigering stil terug (geen teller)', async () => {
    await stelCodeIn('13579')
    expect(await zetBiometrieAan()).toBe(true)
    expect(await isBiometrieAan()).toBe(true)
    vergrendel()
    biometrieWeigert = true
    expect(await ontgrendelMetBiometrie()).toBe(false)
    expect(await resterendePogingen()).toBe(MAX_FOUTEN)
    biometrieWeigert = false
    expect(await ontgrendelMetBiometrie()).toBe(true)
    expect(isOntgrendeld()).toBe(true)
  })

  it('wisAppSlotLokaal ruimt ook de biometrie-kopie op', async () => {
    await stelCodeIn('13579')
    await zetBiometrieAan()
    await wisAppSlotLokaal()
    expect(biometrieKluis.waarde).toBeNull()
    expect(await isBiometrieAan()).toBe(false)
  })
})

// App-auth zonder passkey (contract §5a/§5g, 08-09): hetzelfde slot op de IndexedDB-adapter in de PWA-
// slotmodus (geen Capacitor, pad /accordeur) — instellen, versleuteld token, 5× fout wist alles behalve
// het toestel-id; buiten de accordeur-oppervlakte bestaat er geen slot.
describe('web-adapter (PWA-slotmodus)', () => {
  let idb: ReturnType<typeof installeerFakeIndexedDb>
  beforeEach(() => {
    delete (window as unknown as { Capacitor?: unknown }).Capacitor
    idb = installeerFakeIndexedDb()
    window.history.pushState({}, '', '/accordeur')
  })
  afterEach(() => {
    idb.herstel()
    window.history.pushState({}, '', '/')
  })

  it('appSlotBeschikbaar: true op /accordeur mét IndexedDB, false op het kantoor-pad', () => {
    expect(appSlotBeschikbaar()).toBe(true)
    window.history.pushState({}, '', '/')
    expect(appSlotBeschikbaar()).toBe(false)
  })

  it('stelt in, bewaart het refresh-token versleuteld in IndexedDB en ontgrendelt met de code', async () => {
    await stelCodeIn('13579')
    await bewaarNatiefRefreshToken('token-web')
    const kv = idb.data.get('accordeur-slot')!.get('kv')!
    expect(kv.get('refresh_token')).toMatch(/^slot\.v1\./)
    expect(kv.get('appslot_slot')).toMatch(/^v2\./)
    vergrendel()
    expect(await haalNatiefRefreshToken()).toBeNull()
    expect(await ontgrendelMetCode('13579')).toBe('ok')
    expect(await haalNatiefRefreshToken()).toBe('token-web')
  })

  it('5× fout wist slot + token + biometrie-vlag, het toestel-id (meldsleutel) blijft', async () => {
    await stelCodeIn('13579')
    await bewaarCredentialId('cred-web')
    await bewaarNatiefRefreshToken('token-web')
    vergrendel()
    for (let i = 0; i < MAX_FOUTEN - 1; i++) expect(await ontgrendelMetCode('00001')).toBe('fout')
    expect(await ontgrendelMetCode('00001')).toBe('uitgesloten')
    expect(await isAppSlotIngesteld()).toBe(false)
    expect(await haalNatiefRefreshToken()).toBeNull()
    expect(await haalCredentialId()).toBe('cred-web')
    await wisAppSlotLokaal()
  })
})
