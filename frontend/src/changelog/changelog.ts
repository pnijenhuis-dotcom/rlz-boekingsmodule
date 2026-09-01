// "Wat is nieuw" (best-practice-punt D1, 01-09): het hand-gecureerde changelog-bestand
// WAT_IS_NIEUW.md is de ENE bron (Code vult 'm bij elke feature-commit aan); deze module parseert
// het deterministisch en houdt de gelezen-stand per gebruiker bij in localStorage (licht, geen
// server-infra — bewuste keuze: het is een gemak, geen boekhoudkundig feit). Geen AI.
import bron from './WAT_IS_NIEUW.md?raw'

export interface Release {
  /** Stabiele sleutel: datum + slug van de titel (de gelezen-stand verwijst hiernaar). */
  id: string
  datum: string
  titel: string
  punten: string[]
}

const KOP = /^## (\d{4}-\d{2}-\d{2}) — (.+?)\s*$/

function slug(tekst: string): string {
  return tekst
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 60)
}

/** Parseert het markdown-bestand: "## JJJJ-MM-DD — Titel" + "- punt"-regels. Commentaar en lege
 * regels worden genegeerd; een bullet zonder kop of een kop zonder bullets is een vormfout (test). */
export function parseChangelog(tekst: string): Release[] {
  const releases: Release[] = []
  let huidig: Release | null = null
  let inCommentaar = false
  for (const ruw of tekst.split('\n')) {
    const regel = ruw.trimEnd()
    if (regel.startsWith('<!--')) inCommentaar = true
    if (inCommentaar) {
      if (regel.endsWith('-->')) inCommentaar = false
      continue
    }
    const kop = KOP.exec(regel)
    if (kop) {
      huidig = { id: `${kop[1]}-${slug(kop[2])}`, datum: kop[1], titel: kop[2], punten: [] }
      releases.push(huidig)
      continue
    }
    if (regel.startsWith('- ')) {
      if (!huidig) throw new Error(`Changelog: punt zonder release-kop: "${regel}"`)
      huidig.punten.push(regel.slice(2).trim())
      continue
    }
    if (regel.trim() !== '' && !regel.startsWith('#')) {
      throw new Error(`Changelog: onbekende regel (alleen "## datum — titel" en "- punt"): "${regel}"`)
    }
  }
  return releases
}

export const RELEASES: Release[] = parseChangelog(bron)

export function nieuwsteRelease(releases: Release[] = RELEASES): Release | null {
  return releases[0] ?? null
}

const SLEUTEL = 'rlz.watisnieuw.gelezen'

function sleutelVoor(gebruikerId: string): string {
  return `${SLEUTEL}.${gebruikerId}`
}

/** Laatst gelezen release-id van deze gebruiker op dit apparaat (null = nog nooit geopend). */
export function gelezenRelease(gebruikerId: string | null): string | null {
  if (!gebruikerId) return null
  try {
    return window.localStorage.getItem(sleutelVoor(gebruikerId))
  } catch {
    return null
  }
}

export function markeerGelezen(gebruikerId: string | null, releases: Release[] = RELEASES): void {
  const nieuwste = nieuwsteRelease(releases)
  if (!gebruikerId || !nieuwste) return
  try {
    window.localStorage.setItem(sleutelVoor(gebruikerId), nieuwste.id)
  } catch {
    // localStorage geblokkeerd: geen gelezen-stand, de dot blijft — nooit een crash.
  }
}

/** Ongelezen-dot: de nieuwste release verschilt van wat deze gebruiker het laatst opende. */
export function isOngelezen(gebruikerId: string | null, releases: Release[] = RELEASES): boolean {
  const nieuwste = nieuwsteRelease(releases)
  if (!nieuwste) return false
  return gelezenRelease(gebruikerId) !== nieuwste.id
}
