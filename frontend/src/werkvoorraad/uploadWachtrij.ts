import { ApiError, BackendOnbereikbaarError } from '../api/client'
import type { UploadAlAanwezigDetailDto } from '../api/types'
import { UPLOAD_ACCEPT } from '../intake/intakeApi'

/* Bulk-upload (Peter 18-09: "180 documenten bij BLOW, gaat niet" — de zone las `files?.[0]`). Pure wachtrij-logica,
 * gedeeld door élke upload-plek (klantpagina/documentenlijst = KlantUpload, werkvoorraad-sleepzone = tenaamstelling-
 * routing): max 4 gelijktijdig, per bestand een status mét leesbare reden, Stoppen (lopende af, rest niet gestart),
 * Mislukte opnieuw, één samenvatting, één lijst-verversing ná afloop. De server blijft per bestand (bestaande route,
 * extractie via de wachtrij); de dedupe (sha256 → 'mogelijk duplicaat', UBL+PDF-bundel, nabundel) werkt per bestand. */

export const MAX_GELIJKTIJDIG = 4

export type UploadStatus =
  | 'wachten'
  | 'bezig'
  | 'klaar'
  /** Server kent deze bytes al in deze administratie (sha256 → 'mogelijk duplicaat van …') of het .eml was al verwerkt — géén fout. */
  | 'al_aanwezig'
  /** Antwoord bleef uit (onze 10 s-timer) — het bestand staat meestal al geregistreerd; nooit opnieuw aanbieden. */
  | 'onzeker'
  | 'fout'
  | 'gestopt'

export interface UploadItem {
  id: string
  bestand: File
  status: UploadStatus
  /** Leesbare uitkomst/reden voor de rij. */
  melding: string | null
  /** Mag "Mislukte opnieuw" dit item opnieuw aanbieden? (netwerk/429/5xx = ja; 413/415/422 = nee — zelfde bestand faalt weer.) */
  opnieuw: boolean
  /** Besluit Peter 18-09: bij 'al_aanwezig' het bestaande document (server-409 of mogelijk-duplicaat-vlag) — link "→ bestaand document". */
  bestaandDocumentId?: string | null
  bestaandAdministratieId?: string | null
}

/** Resultaat van één upload-aanroep — de aanroeper vertaalt zijn API-antwoord hiernaar. */
export interface UploadUitkomst {
  status: 'klaar' | 'al_aanwezig'
  melding: string | null
  bestaandDocumentId?: string | null
  bestaandAdministratieId?: string | null
}

/** Besluit Peter 18-09: het 409-detail van een byte-identieke directe upload (server: `DocumentAlAanwezig.als_detail`). */
export function alAanwezigDetail(detail: unknown): UploadAlAanwezigDetailDto | null {
  if (!detail || typeof detail !== 'object') return null
  const d = detail as Record<string, unknown>
  if (d.code !== 'al_aanwezig' || typeof d.bestaand_document_id !== 'string') return null
  return d as unknown as UploadAlAanwezigDetailDto
}

const STATUS_TEKST: Record<string, string> = {
  geboekt: 'geboekt',
  te_controleren: 'te controleren',
  klaar_om_te_boeken: 'klaar om te boeken',
  samengevoegd: 'samengevoegd',
  afgevoerd_duplicaat: 'afgevoerd als duplicaat',
  afgewezen: 'afgewezen',
}

export function alAanwezigMelding(d: UploadAlAanwezigDetailDto): string {
  const status = STATUS_TEKST[d.bestaand_status] ?? d.bestaand_status.replaceAll('_', ' ')
  const ref = d.bestaand_referentie ? `, ${d.bestaand_referentie}` : ''
  return `al aanwezig als "${d.bestaand_bestandsnaam}" (${status}${ref}) — niet opnieuw aangemaakt`
}

export type Uploader = (bestand: File) => Promise<UploadUitkomst>

let teller = 0
export function maakItems(bestanden: File[]): UploadItem[] {
  return bestanden.map((bestand) => ({
    id: `u${Date.now().toString(36)}-${(teller += 1)}`,
    bestand,
    status: 'wachten',
    melding: null,
    opnieuw: false,
  }))
}

const TOEGESTANE_SUFFIXEN = new Set(UPLOAD_ACCEPT.split(',').map((s) => s.trim().toLowerCase()))

export function suffixVan(naam: string): string {
  const i = naam.lastIndexOf('.')
  return i < 0 ? '' : naam.slice(i).toLowerCase()
}

/** Splitst in toegestaan (PDF, UBL/XML, .eml, foto) en geweigerd (op naam) — geweigerde bestanden tellen als fout
 * "bestandstype niet ondersteund" zodat niets stil wegvalt. Verborgen OS-bestanden (.DS_Store, ._x) vallen weg. */
export function filterToegestaan(bestanden: File[]): { toegestaan: File[]; geweigerd: File[] } {
  const toegestaan: File[] = []
  const geweigerd: File[] = []
  for (const b of bestanden) {
    if (b.name.startsWith('.')) continue
    ;(TOEGESTANE_SUFFIXEN.has(suffixVan(b.name)) ? toegestaan : geweigerd).push(b)
  }
  return { toegestaan, geweigerd }
}

/** Vertaalt een gegooide fout naar status + leesbare reden + herkansbaarheid. */
export function classificeerFout(
  err: unknown,
): Pick<UploadItem, 'status' | 'melding' | 'opnieuw' | 'bestaandDocumentId' | 'bestaandAdministratieId'> {
  if (err instanceof BackendOnbereikbaarError) {
    if (err.oorzaak === 'timeout') {
      return {
        status: 'onzeker',
        melding: 'antwoord bleef uit — het document staat waarschijnlijk al in de lijst ("Wordt verwerkt…"); niet opnieuw aanbieden',
        opnieuw: false,
      }
    }
    return { status: 'fout', melding: 'geen verbinding — opnieuw proberen', opnieuw: true }
  }
  if (err instanceof ApiError) {
    switch (err.status) {
      case 409: {
        const d = alAanwezigDetail(err.detail)
        if (d) {
          return {
            status: 'al_aanwezig',
            melding: alAanwezigMelding(d),
            opnieuw: false,
            bestaandDocumentId: d.bestaand_document_id,
            bestaandAdministratieId: d.bestaand_administratie_id ?? null,
          }
        }
        return { status: 'al_aanwezig', melding: `al aanwezig: ${err.message}`, opnieuw: false }
      }
      case 413:
        return { status: 'fout', melding: 'te groot (maximaal 20 MB per bestand)', opnieuw: false }
      case 415:
        return { status: 'fout', melding: err.message || 'bestandstype niet ondersteund', opnieuw: false }
      case 422:
        return { status: 'fout', melding: err.message || 'bestand onbruikbaar', opnieuw: false }
      case 429:
        return { status: 'fout', melding: 'server vraagt even te wachten (te veel verzoeken) — opnieuw proberen', opnieuw: true }
      default:
        if (err.status >= 500) return { status: 'fout', melding: `serverfout (${err.status}) — opnieuw proberen`, opnieuw: true }
        return { status: 'fout', melding: err.message || `fout (${err.status})`, opnieuw: false }
    }
  }
  return { status: 'fout', melding: err instanceof Error ? err.message : 'upload mislukt', opnieuw: true }
}

export interface Voortgang {
  totaal: number
  afgerond: number
  fouten: number
}

export function voortgang(items: UploadItem[]): Voortgang {
  const afgerond = items.filter((i) => i.status !== 'wachten' && i.status !== 'bezig').length
  const fouten = items.filter((i) => i.status === 'fout').length
  return { totaal: items.length, afgerond, fouten }
}

export function voortgangTekst(items: UploadItem[]): string {
  const v = voortgang(items)
  return `${v.afgerond} van ${v.totaal}${v.fouten ? ` · ${v.fouten} ${v.fouten === 1 ? 'fout' : 'fouten'}` : ''}`
}

/** "180 aangeboden · 176 nieuw · 3 al aanwezig · 1 fout" — alleen niet-nul onderdelen ná "aangeboden". */
export function samenvatting(items: UploadItem[]): string {
  const tel = (s: UploadStatus) => items.filter((i) => i.status === s).length
  const delen = [`${items.length} aangeboden`]
  const nieuw = tel('klaar')
  if (nieuw) delen.push(`${nieuw} nieuw`)
  const al = tel('al_aanwezig')
  if (al) delen.push(`${al} al aanwezig`)
  const onzeker = tel('onzeker')
  if (onzeker) delen.push(`${onzeker} onzeker (controleer de lijst)`)
  const fout = tel('fout')
  if (fout) delen.push(`${fout} ${fout === 1 ? 'fout' : 'fouten'}`)
  const gestopt = tel('gestopt')
  if (gestopt) delen.push(`${gestopt} niet gestart (gestopt)`)
  return delen.join(' · ')
}

export function isBezig(items: UploadItem[]): boolean {
  return items.some((i) => i.status === 'wachten' || i.status === 'bezig')
}

/** Alle bestanden uit een drop — óók gesleepte MAPPEN (webkitGetAsEntry, recursief). Zonder entry-API: dataTransfer.files. */
export async function verzamelBestanden(dt: DataTransfer): Promise<File[]> {
  const items = Array.from(dt.items ?? [])
  const entries = items
    .map((it) => (typeof it.webkitGetAsEntry === 'function' ? it.webkitGetAsEntry() : null))
    .filter((e): e is FileSystemEntry => e !== null)
  if (entries.length === 0 || !entries.some((e) => e.isDirectory)) return Array.from(dt.files ?? [])
  const uit: File[] = []
  const leesEntry = async (entry: FileSystemEntry): Promise<void> => {
    if (entry.isFile) {
      const f = await new Promise<File | null>((ok) => (entry as FileSystemFileEntry).file(ok, () => ok(null)))
      if (f) uit.push(f)
      return
    }
    if (entry.isDirectory) {
      const lezer = (entry as FileSystemDirectoryEntry).createReader()
      // readEntries geeft porties (Chrome: 100) — herhalen tot leeg.
      for (;;) {
        const portie = await new Promise<FileSystemEntry[]>((ok) => lezer.readEntries(ok, () => ok([])))
        if (portie.length === 0) break
        for (const e of portie) await leesEntry(e)
      }
    }
  }
  for (const e of entries) await leesEntry(e)
  return uit
}

export interface WachtrijBesturing {
  /** Lopende uploads ronden af, wachtende worden 'gestopt'. */
  stop: () => void
  klaar: Promise<UploadItem[]>
}

/** Voert de wachtrij uit: max `maxGelijktijdig` tegelijk, `onUpdate` ná élke statuswissel met de volledige lijst
 * (immutabel). `items` mogen al eerdere uitkomsten dragen — alleen 'wachten' wordt gestart (Mislukte opnieuw zet ze
 * vooraf terug op 'wachten'). */
export function voerWachtrijUit(
  start: UploadItem[],
  uploader: Uploader,
  onUpdate: (items: UploadItem[]) => void,
  maxGelijktijdig = MAX_GELIJKTIJDIG,
): WachtrijBesturing {
  let items = start.map((i) => ({ ...i }))
  let gestopt = false
  const zet = (id: string, patch: Partial<UploadItem>) => {
    items = items.map((i) => (i.id === id ? { ...i, ...patch } : i))
    onUpdate(items)
  }
  const wachtrij = items.filter((i) => i.status === 'wachten').map((i) => i.id)

  const werker = async (): Promise<void> => {
    for (;;) {
      const id = wachtrij.shift()
      if (id === undefined) return
      if (gestopt) {
        zet(id, { status: 'gestopt', melding: 'niet gestart (gestopt)', opnieuw: true })
        continue
      }
      const item = items.find((i) => i.id === id)
      if (!item) continue
      zet(id, { status: 'bezig', melding: null })
      try {
        const uitkomst = await uploader(item.bestand)
        zet(id, {
          status: uitkomst.status,
          melding: uitkomst.melding,
          opnieuw: false,
          bestaandDocumentId: uitkomst.bestaandDocumentId ?? null,
          bestaandAdministratieId: uitkomst.bestaandAdministratieId ?? null,
        })
      } catch (err) {
        zet(id, classificeerFout(err))
      }
    }
  }
  const klaar = Promise.all(Array.from({ length: Math.max(1, Math.min(maxGelijktijdig, wachtrij.length)) }, werker)).then(
    () => items,
  )
  return {
    stop: () => {
      gestopt = true
    },
    klaar,
  }
}

/** Zet mislukte (en gestopte) items terug op 'wachten' voor een herkansing; al_aanwezig/onzeker/klaar blijven staan. */
export function markeerVoorHerkansing(items: UploadItem[]): UploadItem[] {
  return items.map((i) => (i.status === 'gestopt' || (i.status === 'fout' && i.opnieuw) ? { ...i, status: 'wachten', melding: null } : i))
}

export function aantalHerkansbaar(items: UploadItem[]): number {
  return items.filter((i) => i.status === 'gestopt' || (i.status === 'fout' && i.opnieuw)).length
}
