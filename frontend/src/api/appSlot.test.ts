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

// jsdom heeft geen WebCrypto — Node's implementatie is byte-compatibel.
if (!globalThis.crypto?.subtle) {
  Object.defineProperty(globalThis, 'crypto', { value: webcrypto, configurable: true })
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

  it('wijzigt de code alleen met de juiste huidige code', async () => {
    await stelCodeIn('13579')
    expect(await wijzigCode('99999', '24680')).toBe('fout')
    expect(await wijzigCode('13579', '24680')).toBe('ok')
    vergrendel()
    expect(await ontgrendelMetCode('13579')).toBe('fout')
    expect(await ontgrendelMetCode('24680')).toBe('ok')
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
