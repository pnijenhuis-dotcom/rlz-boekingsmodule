// Web-terugval voor de VeiligeOpslag (app-auth zonder passkey, besluit Peter 08-09-2026, blok 3
// PWA): de accordeur-PWA in de browser krijgt hetzelfde slot-model als de native app — het
// refresh-token leeft versleuteld achter het lokale anker (api/appSlot.ts) in IndexedDB, met
// exact dezelfde `zet/haal/verwijder`-interface als de Capacitor-plugin (Keychain/Keystore).
//
// Fail-closed en strikt begrensd (contract §5a): de adapter is ALLEEN actief als
//   (a) het pad op `/accordeur` begint (de accordeur-oppervlakte) óf de slot-vlag
//       `localStorage['accordeur-slot-modus'] === '1'` staat, én
//   (b) WebCrypto (`crypto.subtle`) én IndexedDB bestaan (secure context — op een http-LAN-adres
//       ontbreekt crypto.subtle en is er dus géén slot; de app zegt dat dan eerlijk).
// Buiten die twee voorwaarden bestaat de adapter niet en merkt de kantoor-webapp hier NIETS van
// (guard: `client.test.ts` — kantoor-pad byte-identiek).
//
// IndexedDB i.p.v. localStorage: het gaat om een (versleuteld) refresh-token; IndexedDB is
// origin-gebonden, niet synchroon leesbaar door elke script-regel en overleeft — anders dan
// sessionStorage — het sluiten van de browser (het toestel = factor 1, de toegangscode factor 2).

export const SLOT_MODUS_SLEUTEL = 'accordeur-slot-modus'

const DB_NAAM = 'accordeur-slot'
const STORE_NAAM = 'kv'

export interface WebVeiligeOpslagAdapter {
  zet(opties: { sleutel: string; waarde: string }): Promise<void>
  haal(opties: { sleutel: string }): Promise<{ waarde: string | null }>
  verwijder(opties: { sleutel: string }): Promise<void>
}

function opAccordeurPad(): boolean {
  const pad = window.location?.pathname ?? ''
  return pad === '/accordeur' || pad.startsWith('/accordeur/')
}

function slotVlagStaat(): boolean {
  try {
    return localStorage.getItem(SLOT_MODUS_SLEUTEL) === '1'
  } catch {
    return false
  }
}

/** True als de PWA-slotmodus hier geldt: accordeur-oppervlakte (of vlag) + werkende WebCrypto +
 * IndexedDB. Elke andere pagina (kantoor-web) → false, altijd. */
export function webSlotModusActief(): boolean {
  if (typeof window === 'undefined') return false
  if (!opAccordeurPad() && !slotVlagStaat()) return false
  const cryptoOk = typeof crypto !== 'undefined' && typeof crypto.subtle?.deriveKey === 'function'
  const idbOk = typeof indexedDB !== 'undefined' && indexedDB !== null
  return cryptoOk && idbOk
}

/** Alleen de accordeur-oppervlakte zonder slot-mogelijkheid (bv. http zonder secure context):
 * de app toont dan een eerlijke melding i.p.v. een activatiescherm dat nooit kan slagen. */
export function webSlotOnmogelijkOpAccordeur(): boolean {
  if (typeof window === 'undefined') return false
  if (!opAccordeurPad()) return false
  return !webSlotModusActief()
}

/** Zet/wis de slot-vlag (na een geslaagde activatie in de PWA resp. bij loskoppelen). De vlag
 * is een hulpmiddel — op `/accordeur` is de modus ook zonder vlag actief. */
export function zetWebSlotModus(aan: boolean): void {
  try {
    if (aan) localStorage.setItem(SLOT_MODUS_SLEUTEL, '1')
    else localStorage.removeItem(SLOT_MODUS_SLEUTEL)
  } catch {
    // opslag geblokkeerd — de padvoorwaarde blijft de hoofdschakel
  }
}

// ---- IndexedDB-kv ---------------------------------------------------------------------------------

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const verzoek = indexedDB.open(DB_NAAM, 1)
    verzoek.onupgradeneeded = () => {
      const db = verzoek.result
      if (!db.objectStoreNames.contains(STORE_NAAM)) db.createObjectStore(STORE_NAAM)
    }
    verzoek.onsuccess = () => resolve(verzoek.result)
    verzoek.onerror = () => reject(verzoek.error ?? new Error('IndexedDB openen mislukt'))
    verzoek.onblocked = () => reject(new Error('IndexedDB geblokkeerd'))
  })
}

function wachtOp<T>(verzoek: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    verzoek.onsuccess = () => resolve(verzoek.result)
    verzoek.onerror = () => reject(verzoek.error ?? new Error('IndexedDB-verzoek mislukt'))
  })
}

async function metStore<T>(modus: IDBTransactionMode, werk: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await openDb()
  try {
    const tx = db.transaction(STORE_NAAM, modus)
    return await wachtOp(werk(tx.objectStore(STORE_NAAM)))
  } finally {
    try {
      db.close()
    } catch {
      // sluiten is best-effort
    }
  }
}

let adapter: WebVeiligeOpslagAdapter | null = null

/** De IndexedDB-adapter (singleton). Aanroeper (nativeSessie.veiligeOpslagPlugin) toetst eerst
 * `webSlotModusActief()` — de adapter zelf doet die poort niet nog eens. */
export function webVeiligeOpslag(): WebVeiligeOpslagAdapter {
  adapter ??= {
    async zet({ sleutel, waarde }) {
      await metStore('readwrite', (store) => store.put(waarde, sleutel))
    },
    async haal({ sleutel }) {
      const waarde = await metStore<unknown>('readonly', (store) => store.get(sleutel))
      return { waarde: typeof waarde === 'string' ? waarde : null }
    },
    async verwijder({ sleutel }) {
      await metStore('readwrite', (store) => store.delete(sleutel))
    },
  }
  return adapter
}
