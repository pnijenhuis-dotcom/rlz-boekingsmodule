/** Offline werken in de veld-app (run B punt 5, Peter 18-09 "alle punten"; mockup uren-uitvoerder-v3.html scherm ⑤).
 *
 * Een dagregel die niet verzonden kan worden (geen netwerk, backend onbereikbaar) gaat in een lokale WACHTRIJ in
 * IndexedDB — een eigen database naast het slot (`api/webVeiligeOpslag.ts`), de waarde versleuteld op HETZELFDE anker als
 * het app-slot (`api/appSlot.ts::versleutelAlsSlotActief`). Zonder actief slot (kantoor-dev zonder slotmodus) valt de
 * opslag terug op een leesbare `plain:`-waarde — de veld-app draait in de praktijk altijd achter het slot (0029).
 * De wachtrij wordt verzonden bij het `online`-event, bij het openen van de app en ná elke geslaagde verversing; een
 * 409 `weekstaat_bevroren` (de week is intussen ingediend/gekeurd) is een CONFLICT mét beide standen — nooit stil
 * overschrijven. Indienen blijft online-only. Dit bestand is puur (geen React) en testbaar met de fake IndexedDB. */
import { ApiError, BackendOnbereikbaarError } from '../api/client'
import { ontsleutelSlotWaarde, versleutelAlsSlotActief } from '../api/appSlot'
import type { WeekProjectKaartDto } from './urenApi'

export const OFFLINE_DB_NAAM = 'rlz-uren-offline'
export const OFFLINE_STORE_NAAM = 'wachtrij'
const PLAIN_PREFIX = 'plain:'

export interface ZetDagPayload {
  bron?: 'handmatig' | 'kopie'
  administratie_id: string
  project_id: string
  jaar: number
  weeknummer: number
  datum: string
  uren: string
  m2: string | null
  doorfactureren?: boolean | null
  opmerking: string | null
  namens_zzper_id: string | null
}

/** De 409-body van `PUT /uren/zzp/dag` op een bevroren week (CONTRACT_5): beide standen voor de conflict-sheet. */
export interface BevrorenConflictDetail {
  code: 'weekstaat_bevroren'
  detail?: string
  status: string
  server_regel: { uren: string; m2: string | null; opmerking: string | null; doorfactureren: boolean | null } | null
}

export interface OfflineRegel {
  sleutel: string
  payload: ZetDagPayload
  bewaard_op: string
  /** Gezet zodra verzenden een 409 `weekstaat_bevroren` opleverde; de regel blijft staan tot de gebruiker kiest. */
  conflict: BevrorenConflictDetail | null
  /** Andere serverfout bij verzenden (bv. 422) — zichtbaar, de regel blijft staan tot de gebruiker 'm weghaalt. */
  fout: string | null
}

export function offlineSleutel(p: Pick<ZetDagPayload, 'administratie_id' | 'project_id' | 'datum' | 'namens_zzper_id'>): string {
  return `${p.administratie_id}|${p.project_id}|${p.datum}|${p.namens_zzper_id ?? ''}`
}

/** Geen verbinding: fetch gooide vóór een response (TypeError) óf onze client vertaalde dat/502-504 al naar
 * BackendOnbereikbaarError. Alleen dán gaat een regel in de wachtrij — elke andere fout blijft een gewone fout. */
export function isGeenVerbinding(err: unknown): boolean {
  if (err instanceof BackendOnbereikbaarError) return true
  return err instanceof TypeError
}

export function bevrorenConflict(err: unknown): BevrorenConflictDetail | null {
  if (!(err instanceof ApiError) || err.status !== 409) return null
  // FastAPI zet de body onder `detail`; de client geeft dat object door als `err.detail` (contract-afwijking 1: daarbinnen staat de
  // tekst nogmaals als `detail`). Defensief: een body die het object nóg een niveau dieper draagt, wordt ook herkend.
  let d = err.detail as (Partial<BevrorenConflictDetail> & { detail?: unknown }) | undefined
  if (d && typeof d === 'object' && d.code === undefined && d.detail && typeof d.detail === 'object') d = d.detail as Partial<BevrorenConflictDetail>
  if (!d || typeof d !== 'object' || d.code !== 'weekstaat_bevroren') return null
  return { code: 'weekstaat_bevroren', detail: typeof d.detail === 'string' ? d.detail : err.message, status: d.status ?? 'ingediend', server_regel: d.server_regel ?? null }
}

// ---- IndexedDB ----------------------------------------------------------------------------------------------------

function idbBeschikbaar(): boolean {
  return typeof indexedDB !== 'undefined'
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const verzoek = indexedDB.open(OFFLINE_DB_NAAM, 1)
    verzoek.onupgradeneeded = () => {
      const db = verzoek.result
      if (!db.objectStoreNames.contains(OFFLINE_STORE_NAAM)) db.createObjectStore(OFFLINE_STORE_NAAM)
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
    const tx = db.transaction(OFFLINE_STORE_NAAM, modus)
    return await wachtOp(werk(tx.objectStore(OFFLINE_STORE_NAAM)))
  } finally {
    try {
      db.close()
    } catch {
      // sluiten is best-effort
    }
  }
}

/** Sleutel-index náást de regels (één vaste sleutel) — de fake én echte IndexedDB kennen zo geen cursor-afhankelijkheid. */
const INDEX_SLEUTEL = '__index__'

async function leesIndex(): Promise<string[]> {
  const ruw = await metStore<unknown>('readonly', (s) => s.get(INDEX_SLEUTEL))
  if (typeof ruw !== 'string') return []
  try {
    const lijst = JSON.parse(ruw) as unknown
    return Array.isArray(lijst) ? lijst.filter((x): x is string => typeof x === 'string') : []
  } catch {
    return []
  }
}

async function schrijfIndex(sleutels: string[]): Promise<void> {
  await metStore('readwrite', (s) => s.put(JSON.stringify(sleutels), INDEX_SLEUTEL))
}

async function versleutel(regel: OfflineRegel): Promise<string> {
  const tekst = JSON.stringify(regel)
  return (await versleutelAlsSlotActief(tekst)) ?? `${PLAIN_PREFIX}${tekst}`
}

async function ontsleutel(waarde: unknown): Promise<OfflineRegel | null> {
  if (typeof waarde !== 'string') return null
  const tekst = waarde.startsWith(PLAIN_PREFIX) ? waarde.slice(PLAIN_PREFIX.length) : await ontsleutelSlotWaarde(waarde)
  if (!tekst) return null
  try {
    const r = JSON.parse(tekst) as OfflineRegel
    return r && typeof r.sleutel === 'string' && r.payload ? { ...r, conflict: r.conflict ?? null, fout: r.fout ?? null } : null
  } catch {
    return null
  }
}

export async function leesWachtrij(): Promise<OfflineRegel[]> {
  if (!idbBeschikbaar()) return []
  try {
    const sleutels = await leesIndex()
    const uit: OfflineRegel[] = []
    for (const sleutel of sleutels) {
      const regel = await ontsleutel(await metStore<unknown>('readonly', (s) => s.get(sleutel)))
      if (regel) uit.push(regel)
    }
    return uit.sort((a, b) => a.bewaard_op.localeCompare(b.bewaard_op))
  } catch {
    return []
  }
}

/** Bewaart (of vervangt — zelfde dag, zelfde project) een regel; geeft de bijgewerkte wachtrij terug. */
export async function bewaarInWachtrij(payload: ZetDagPayload, nu: Date = new Date()): Promise<OfflineRegel[]> {
  const regel: OfflineRegel = { sleutel: offlineSleutel(payload), payload, bewaard_op: nu.toISOString(), conflict: null, fout: null }
  await schrijfRegel(regel)
  return leesWachtrij()
}

async function schrijfRegel(regel: OfflineRegel): Promise<void> {
  if (!idbBeschikbaar()) throw new Error('Geen lokale opslag beschikbaar')
  const sleutels = await leesIndex()
  const waarde = await versleutel(regel)
  await metStore('readwrite', (s) => s.put(waarde, regel.sleutel))
  if (!sleutels.includes(regel.sleutel)) await schrijfIndex([...sleutels, regel.sleutel])
}

export async function verwijderUitWachtrij(sleutel: string): Promise<OfflineRegel[]> {
  if (!idbBeschikbaar()) return []
  await metStore('readwrite', (s) => s.delete(sleutel))
  await schrijfIndex((await leesIndex()).filter((k) => k !== sleutel))
  return leesWachtrij()
}

export async function wisWachtrij(): Promise<void> {
  if (!idbBeschikbaar()) return
  for (const sleutel of await leesIndex()) await metStore('readwrite', (s) => s.delete(sleutel))
  await schrijfIndex([])
}

// ---- verzenden ----------------------------------------------------------------------------------------------------

export interface VerzendUitkomst {
  verzonden: OfflineRegel[]
  /** Nieuwe conflicten uit DEZE ronde (voor de sheet); oudere, al getoonde conflicten staan alleen in `open`. */
  nieuweConflicten: OfflineRegel[]
  open: OfflineRegel[]
  /** true = de ronde stopte op "geen verbinding" — de rest staat nog in `open`. */
  geenVerbinding: boolean
}

/** Verzendt de wachtrij in volgorde. Geen verbinding = stoppen (rest blijft); 409 bevroren = conflict markeren (blijft
 * staan tot de gebruiker kiest); andere serverfout = `fout` markeren (blijft staan, zichtbaar). Idempotent: een geslaagde
 * PUT verwijdert de regel. */
export async function verzendWachtrij(zend: (payload: ZetDagPayload) => Promise<unknown>): Promise<VerzendUitkomst> {
  const regels = await leesWachtrij()
  const verzonden: OfflineRegel[] = []
  const nieuweConflicten: OfflineRegel[] = []
  let geenVerbinding = false
  for (const regel of regels) {
    if (geenVerbinding) break
    try {
      await zend(regel.payload)
      await verwijderUitWachtrij(regel.sleutel)
      verzonden.push(regel)
    } catch (err) {
      if (isGeenVerbinding(err)) {
        geenVerbinding = true
        break
      }
      const conflict = bevrorenConflict(err)
      if (conflict) {
        const wasNieuw = regel.conflict === null
        await schrijfRegel({ ...regel, conflict, fout: null })
        if (wasNieuw) nieuweConflicten.push({ ...regel, conflict, fout: null })
        continue
      }
      const tekst = err instanceof Error ? err.message : 'Verzenden mislukt.'
      await schrijfRegel({ ...regel, fout: tekst })
    }
  }
  return { verzonden, nieuweConflicten, open: await leesWachtrij(), geenVerbinding }
}

// ---- weergave ------------------------------------------------------------------------------------------------------

export function kaartSleutel(k: Pick<WeekProjectKaartDto, 'administratie_id' | 'project_id'>): string {
  return `${k.administratie_id}|${k.project_id}`
}

export interface WachtrijInWeek {
  /** Kaarten mét de lokale (nog niet verzonden) uren in `dag_uren` gemengd — zodat de dagbalk en de kaartmeta kloppen. */
  kaarten: WeekProjectKaartDto[]
  /** Per kaart de datums met een bewaarde regel. */
  perKaart: Record<string, string[]>
  /** Alle datums in deze week met een bewaarde regel (bolletje in de dagbalk). */
  datums: Set<string>
  /** Regels van deze week die nog niet verzonden zijn. */
  regels: OfflineRegel[]
}

/** Mengt de wachtrij in de kaarten van één week (puur): alleen regels van deze week/deze kaarten tellen. */
export function pasWachtrijToe(kaarten: WeekProjectKaartDto[], wachtrij: OfflineRegel[], week: { jaar: number; weeknummer: number }): WachtrijInWeek {
  const regels = wachtrij.filter((r) => r.payload.jaar === week.jaar && r.payload.weeknummer === week.weeknummer)
  const perKaart: Record<string, string[]> = {}
  const datums = new Set<string>()
  const uit = kaarten.map((k) => {
    const eigen = regels.filter((r) => r.payload.administratie_id === k.administratie_id && r.payload.project_id === k.project_id)
    if (eigen.length === 0) return k
    const dag_uren = { ...(k.dag_uren ?? {}) }
    for (const r of eigen) {
      dag_uren[r.payload.datum] = r.payload.uren
      datums.add(r.payload.datum)
    }
    perKaart[kaartSleutel(k)] = eigen.map((r) => r.payload.datum).sort()
    return { ...k, dag_uren }
  })
  return { kaarten: uit, perKaart, datums, regels }
}

export function nogNietVerzondenLabel(aantal: number): string {
  return aantal === 1 ? '1 regel nog niet verzonden' : `${aantal} regels nog niet verzonden`
}
