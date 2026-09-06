// Parallel laden van de verse stand (blok D3 opdracht 06-09): wachtrij én "vragen aan u" starten
// TEGELIJK (vóór 06-09 begon de vragen-fetch pas ná het wachtrij-antwoord — één extra
// netwerk-rondje op de koude start). Daarnaast een voorlader: zodra het access-token er is maar
// de gebruiker nog een scherm vóór de wachtrij ziet (web: het ontgrendelscherm van de 24-uurs-
// cadans), kan de fetch al lopen — GoedkeurenFlow neemt het resultaat over bij het monteren.
//
// Bewust NIET: een fetch starten vóór de stille refresh is afgerond. Het access-token leeft
// alleen in geheugen (OWASP, api/client.ts) — op een koude start is er dus géén "oud token";
// een fetch zonder token levert alleen een 401 op die even lang duurt als de refresh zelf.
// apiFetch doet bij een 401 al precies één refresh (single-flight) + één retry — geen tweede
// mechanisme hier. In de native schil staat het refresh-token achter het app-slot: de refresh
// (en dus de fetch) kan pas ná het ontgrendelen — dat is de cadans, geen tekortkoming.

import { haalVragenAanMij, haalWachtrij, type AccordeurVraagDto, type WachtrijItemDto } from './accordeurApi'

export interface VerseStand {
  items: WachtrijItemDto[]
  /** null = de vragen-fetch mislukte (tolerant — mag de wachtrij nooit blokkeren). */
  vragen: AccordeurVraagDto[] | null
}

/** Wachtrij + vragen parallel; de wachtrij-fout (incl. 403 voorwaarden) gooit door, de
 * vragen-fout wordt null. */
export async function laadVerseStand(): Promise<VerseStand> {
  const vragenBelofte = haalVragenAanMij().then(
    (r) => r.items,
    () => null,
  )
  const { items } = await haalWachtrij()
  const vragen = await vragenBelofte
  return { items, vragen }
}

/** Hoe lang een voorgeladen stand nog als "vers genoeg" geldt om over te nemen. */
export const VOORLAAD_MAX_LEEFTIJD_MS = 30_000

let voorgeladen: { belofte: Promise<VerseStand>; gestart: number } | null = null

/** Start (idempotent) de verse fetch op de achtergrond. Fouten worden hier niet gemeld — de
 * afnemer (GoedkeurenFlow) ziet ze via de belofte; zonder afnemer verdwijnen ze stil (het is een
 * optimalisatie, geen bron van waarheid). */
export function voorlaadStand(nu: number = Date.now()): void {
  if (voorgeladen && nu - voorgeladen.gestart < VOORLAAD_MAX_LEEFTIJD_MS) return
  const belofte = laadVerseStand()
  belofte.catch(() => {})
  voorgeladen = { belofte, gestart: nu }
}

/** Neemt de voorgeladen belofte over (éénmalig) als die vers genoeg is; anders null. */
export function neemVoorgeladenStand(nu: number = Date.now()): Promise<VerseStand> | null {
  if (!voorgeladen) return null
  const { belofte, gestart } = voorgeladen
  voorgeladen = null
  return nu - gestart < VOORLAAD_MAX_LEEFTIJD_MS ? belofte : null
}

export function resetVoorladerVoorTests(): void {
  voorgeladen = null
}
