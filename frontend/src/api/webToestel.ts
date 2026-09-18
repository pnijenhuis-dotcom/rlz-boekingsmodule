/** Web-toestel (PWA/browsertab) — diagnose en waarborgen voor de app-auth zonder passkey op een browser (SPOED 18-09,
 * casus "Edge op Android-tablet logt steeds uit"). Alles LOKAAL (localStorage/sessionStorage), nooit naar de server.
 *
 * Wat de data van 18-09 liet zien: server-side werd het toestel nooit afgewezen (alle verversingen 200); de gebruiker zag
 * ná élke volledige paginaherlaad (Android-terugknop uit de app, pull-to-refresh, tabblad-herstel) opnieuw het
 * toegangscode-scherm omdat het ontgrendelde anker alleen in het JS-geheugen leefde — dat voelt als "uitgelogd". Dit
 * bestand bundelt de zichtbaarheid (persistente opslag ja/nee, PWA of browsertab, laatste tokenverlenging) en de
 * eerlijke melding als de browseropslag wél gewist is. */

export const OPSLAG_PERSISTENT_SLEUTEL = 'accordeur-opslag-persistent'
export const LAATSTE_VERLENGING_SLEUTEL = 'accordeur-laatste-verlenging'
export const BEGINSCHERM_NUDGE_WEG_SLEUTEL = 'accordeur-beginscherm-nudge-weg'

export type OpslagPersistent = 'ja' | 'nee' | 'onbekend'
export type WeergaveModus = 'native' | 'pwa' | 'browser'

/** Melding op het activatiescherm als het toestel eerder gekoppeld was (slot-vlag staat) maar de browseropslag leeg is:
 * géén stil uitloggen — zeg wat er gebeurde en wat de gebruiker nu kan doen. */
export const OPSLAG_GEWIST_MELDING =
  'Je toestel is niet meer gekoppeld: de opslag van deze browser is gewist (bijv. "browsegegevens wissen bij afsluiten", ' +
  'een privévenster of te weinig ruimte). Koppel opnieuw met een koppelcode van een ander toestel (daar: Toegang › ' +
  'Telefoon/app koppelen) of vraag het kantoor om een herstel-link. Zet de app daarna op je beginscherm — dan blijft hij ingelogd.'

function veiligLocalStorage(): Storage | null {
  try {
    return typeof localStorage !== 'undefined' ? localStorage : null
  } catch {
    return null
  }
}

/** Vraag de browser de opslag van deze site als "persistent" te markeren (niet wegruimen bij ruimtegebrek). Chrome/Edge
 * Android geven dit vanzelf aan een geïnstalleerde PWA; in een gewoon tabblad weigeren ze meestal. De uitkomst gaat in de
 * diagnose (nooit naar de server). */
export async function vraagPersistenteOpslag(): Promise<OpslagPersistent> {
  let uitkomst: OpslagPersistent = 'onbekend'
  try {
    const storage = (navigator as Navigator & { storage?: { persist?: () => Promise<boolean>; persisted?: () => Promise<boolean> } }).storage
    if (storage?.persisted && (await storage.persisted())) uitkomst = 'ja'
    else if (storage?.persist) uitkomst = (await storage.persist()) ? 'ja' : 'nee'
  } catch {
    uitkomst = 'onbekend'
  }
  veiligLocalStorage()?.setItem(OPSLAG_PERSISTENT_SLEUTEL, uitkomst)
  return uitkomst
}

export function leesOpslagPersistent(): OpslagPersistent | null {
  const w = veiligLocalStorage()?.getItem(OPSLAG_PERSISTENT_SLEUTEL)
  return w === 'ja' || w === 'nee' || w === 'onbekend' ? w : null
}

/** Hoe draait de app hier: native schil, geïnstalleerde PWA (standalone) of gewoon browsertabblad. */
export function weergaveModus(): WeergaveModus {
  const capacitor = (globalThis as { Capacitor?: { isNativePlatform?: () => boolean } }).Capacitor
  if (capacitor?.isNativePlatform?.()) return 'native'
  try {
    const standalone =
      (typeof matchMedia === 'function' && matchMedia('(display-mode: standalone)').matches) ||
      (navigator as Navigator & { standalone?: boolean }).standalone === true
    return standalone ? 'pwa' : 'browser'
  } catch {
    return 'browser'
  }
}

/** Ná élke geslaagde tokenverversing: tijdstip lokaal noteren (diagnose "laatste tokenverlenging"). */
export function noteerTokenVerlenging(nu: Date = new Date()): void {
  veiligLocalStorage()?.setItem(LAATSTE_VERLENGING_SLEUTEL, nu.toISOString())
}

export function leesLaatsteTokenVerlenging(): string | null {
  return veiligLocalStorage()?.getItem(LAATSTE_VERLENGING_SLEUTEL) ?? null
}

function ddmmHHMM(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getDate())}-${pad(d.getMonth() + 1)} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** Staart voor de diagnoseregel in ⚙ Toegang: modus · opslag persistent · laatste tokenverlenging. */
export function webDiagnoseStaart(): string {
  const modus = weergaveModus()
  const modusLabel = modus === 'native' ? 'app' : modus === 'pwa' ? 'beginscherm-app (PWA)' : 'browsertab'
  const persistent = leesOpslagPersistent()
  const persistentLabel = persistent === null ? 'niet gevraagd' : persistent
  const verlenging = ddmmHHMM(leesLaatsteTokenVerlenging())
  return ` · modus: ${modusLabel} · opslag persistent: ${persistentLabel} · laatste tokenverlenging: ${verlenging || 'nog geen'}`
}

/** Toon de "Zet op je beginscherm"-kaart: alleen in een browsertab (niet PWA/native), zolang de gebruiker 'm niet wegklikte. */
export function toonBeginschermNudge(): boolean {
  if (weergaveModus() !== 'browser') return false
  return veiligLocalStorage()?.getItem(BEGINSCHERM_NUDGE_WEG_SLEUTEL) !== '1'
}

export function beginschermNudgeWeg(): void {
  veiligLocalStorage()?.setItem(BEGINSCHERM_NUDGE_WEG_SLEUTEL, '1')
}

/** Browser-specifieke stappen voor "zet op je beginscherm" (Edge en Chrome op Android; anders generiek). */
export function beginschermStappen(userAgent: string = navigator.userAgent): string {
  if (/Edg\//.test(userAgent)) return 'Edge: tik op ⋯ (onderaan) → "Toevoegen aan telefoon" → Installeren.'
  if (/Android/.test(userAgent) || /X11; Linux/.test(userAgent)) return 'Chrome: tik op ⋮ (rechtsboven) → "Toevoegen aan startscherm" of "App installeren".'
  if (/iPhone|iPad/.test(userAgent)) return 'Safari: tik op Delen → "Zet op beginscherm".'
  return 'Browsermenu → "Toevoegen aan startscherm" / "App installeren".'
}
