// Cache-first stand accordeur-app (blok D2 opdracht 06-09, zelfde patroon als het bankscherm
// "laatst ververst HH:MM" — BESLISSINGEN "BANKSCHERM BLOK E"): de laatst geladen wachtrij +
// vragen worden lokaal bewaard en bij het openen DIRECT getoond, terwijl de verse stand stil op
// de achtergrond binnenkomt en de cache zonder flikkeren vervangt. Harde regels:
//   • één sleutel per GEBRUIKER (id uit het JWT) — nooit cross-user lekken; zonder gebruikers-id
//     wordt er niets bewaard of gelezen;
//   • gewist bij uitloggen, bij een server-side dode sessie (kill-switch/verlopen → login) en bij
//     "toestel ontkoppelen" — de cache leeft nooit langer dan de sessie waar hij bij hoort;
//   • de cache is WEERGAVE, geen waarheid: besluiten (akkoord/afwijzen) werken uitsluitend op
//     items die in de VERSE stand voorkomen (GoedkeurenFlow blokkeert de geldknoppen tot dan);
//     de optimistische verzendrij (besluitQueue.ts) is ongewijzigd.
// Opslag: localStorage van de (native) webview — geen secrets (tokens staan in de
// Keychain/Keystore), wel financiële weergavedata; de app-lock zit vóór het tonen. Zie het
// beslispunt in BESLISSINGEN over versleutelen op het slot-anker.

import type { AccordeurVraagDto, WachtrijItemDto } from './accordeurApi'

const SLEUTEL_PREFIX = 'accordeur-stand:'
/** Formaatversie — een oudere/afwijkende vorm wordt genegeerd (nooit een halve kaart tonen). */
const VERSIE = 1
/** Ouder dan dit wordt niet meer als startstand getoond (de kans op "verdwenen" items groeit). */
export const MAX_LEEFTIJD_MS = 7 * 24 * 60 * 60 * 1000

export interface BewaardeStand {
  items: WachtrijItemDto[]
  vragen: AccordeurVraagDto[]
  /** ISO-tijdstip van de verse stand waar deze cache van komt. */
  tijdstip: string
}

interface Envelop extends BewaardeStand {
  v: number
}

function sleutel(gebruikerId: string): string {
  return `${SLEUTEL_PREFIX}${gebruikerId}`
}

function opslag(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage
  } catch {
    return null
  }
}

export function leesStand(gebruikerId: string | null, nu: Date = new Date()): BewaardeStand | null {
  if (!gebruikerId) return null
  const store = opslag()
  if (!store) return null
  try {
    const ruw = store.getItem(sleutel(gebruikerId))
    if (!ruw) return null
    const env = JSON.parse(ruw) as Partial<Envelop>
    if (env.v !== VERSIE || !Array.isArray(env.items) || !Array.isArray(env.vragen) || typeof env.tijdstip !== 'string') {
      return null
    }
    const leeftijd = nu.getTime() - new Date(env.tijdstip).getTime()
    if (!Number.isFinite(leeftijd) || leeftijd < 0 || leeftijd > MAX_LEEFTIJD_MS) return null
    return { items: env.items, vragen: env.vragen, tijdstip: env.tijdstip }
  } catch {
    return null
  }
}

/** Bewaart de verse stand. Alleen DTO-velden (een lokale `verzend_fout` reist nooit mee). */
export function bewaarStand(
  gebruikerId: string | null,
  items: WachtrijItemDto[],
  vragen: AccordeurVraagDto[],
  nu: Date = new Date(),
): string | null {
  if (!gebruikerId) return null
  const store = opslag()
  if (!store) return null
  const tijdstip = nu.toISOString()
  const schoon = items.map((i) => {
    const { verzend_fout: _weg, ...rest } = i as WachtrijItemDto & { verzend_fout?: string }
    return rest
  })
  const env: Envelop = { v: VERSIE, items: schoon, vragen, tijdstip }
  try {
    store.setItem(sleutel(gebruikerId), JSON.stringify(env))
  } catch {
    // Opslag vol/geblokkeerd: de app werkt gewoon zonder cache.
    return null
  }
  return tijdstip
}

export function wisStand(gebruikerId: string | null): void {
  if (!gebruikerId) return
  const store = opslag()
  if (!store) return
  try {
    store.removeItem(sleutel(gebruikerId))
  } catch {
    // niets
  }
}

/** Alle standen weg — bij uitloggen/kill-switch/ontkoppelen (er is dan geen gebruikers-id meer
 * in geheugen om gericht te wissen, en er mag niets van een vorige gebruiker achterblijven). */
export function wisAlleStanden(): void {
  const store = opslag()
  if (!store) return
  try {
    const weg: string[] = []
    for (let i = 0; i < store.length; i++) {
      const k = store.key(i)
      if (k && k.startsWith(SLEUTEL_PREFIX)) weg.push(k)
    }
    weg.forEach((k) => store.removeItem(k))
  } catch {
    // niets
  }
}

/** "laatst ververst HH:MM" (vandaag) / "laatst ververst dd-mm HH:MM" — zelfde vorm als de
 * bankpaneelkop; eigen kopie omdat de accordeur-chunk geen kantoor-bundels laadt. */
export function verversTekst(iso: string | null, nu: Date = new Date()): string {
  if (!iso) return 'nog niet ververst'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return 'nog niet ververst'
  const tijd = d.toLocaleTimeString('nl-NL', { hour: '2-digit', minute: '2-digit' })
  const vandaag =
    d.getFullYear() === nu.getFullYear() && d.getMonth() === nu.getMonth() && d.getDate() === nu.getDate()
  if (vandaag) return `laatst ververst ${tijd}`
  return `laatst ververst ${d.toLocaleDateString('nl-NL', { day: '2-digit', month: '2-digit' })} ${tijd}`
}
