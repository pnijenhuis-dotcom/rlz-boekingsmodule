// Testhulp (geen productiecode): minimale in-memory IndexedDB voor jsdom, dat zelf geen IndexedDB
// heeft. Dekt precies het oppervlak dat api/webVeiligeOpslag.ts gebruikt (open → onupgradeneeded/
// onsuccess, objectStoreNames.contains, createObjectStore, transaction().objectStore().get/put/
// delete, close). Callbacks lopen via queueMicrotask, zodat de hulp óók werkt onder
// vi.useFakeTimers() (die setTimeout bevriest maar microtasks niet).

type Callback = ((this: unknown, ev: unknown) => void) | null

class FakeRequest<T> {
  result!: T
  error: Error | null = null
  onsuccess: Callback = null
  onerror: Callback = null
  onupgradeneeded: Callback = null
  onblocked: Callback = null
}

function slaag<T>(req: FakeRequest<T>, result: T): FakeRequest<T> {
  queueMicrotask(() => {
    req.result = result
    req.onsuccess?.call(req, { target: req })
  })
  return req
}

class FakeStore {
  private readonly data: Map<string, string>
  constructor(data: Map<string, string>) {
    this.data = data
  }
  get(sleutel: string) {
    return slaag(new FakeRequest<unknown>(), this.data.get(sleutel))
  }
  put(waarde: string, sleutel: string) {
    this.data.set(sleutel, waarde)
    return slaag(new FakeRequest<unknown>(), sleutel)
  }
  delete(sleutel: string) {
    this.data.delete(sleutel)
    return slaag(new FakeRequest<unknown>(), undefined)
  }
}

class FakeDb {
  private readonly stores: Map<string, Map<string, string>>
  objectStoreNames = { contains: (naam: string) => this.stores.has(naam) }
  constructor(alleData: Map<string, Map<string, string>>) {
    this.stores = alleData
  }
  createObjectStore(naam: string) {
    if (!this.stores.has(naam)) this.stores.set(naam, new Map())
    return new FakeStore(this.stores.get(naam)!)
  }
  transaction(naam: string) {
    const data = this.stores.get(naam)
    if (!data) throw new Error(`store ${naam} bestaat niet`)
    return { objectStore: () => new FakeStore(data) }
  }
  close() {}
}

/** Installeert `indexedDB` op globalThis en geeft de ruwe opslag terug (db → store → sleutel → waarde)
 * zodat een test kan controleren wát er staat (bv. het `slot.v1.`-prefix). Roep `herstel()` in afterEach. */
export function installeerFakeIndexedDb(): { data: Map<string, Map<string, Map<string, string>>>; herstel: () => void } {
  const data = new Map<string, Map<string, Map<string, string>>>()
  const vorige = (globalThis as { indexedDB?: unknown }).indexedDB
  const fake = {
    open(naam: string) {
      const req = new FakeRequest<FakeDb>()
      const nieuw = !data.has(naam)
      if (nieuw) data.set(naam, new Map())
      const db = new FakeDb(data.get(naam)!)
      queueMicrotask(() => {
        req.result = db
        if (nieuw) req.onupgradeneeded?.call(req, { target: req })
        req.onsuccess?.call(req, { target: req })
      })
      return req
    },
  }
  Object.defineProperty(globalThis, 'indexedDB', { configurable: true, value: fake })
  return {
    data,
    herstel: () => {
      if (vorige === undefined) delete (globalThis as { indexedDB?: unknown }).indexedDB
      else Object.defineProperty(globalThis, 'indexedDB', { configurable: true, value: vorige })
    },
  }
}
