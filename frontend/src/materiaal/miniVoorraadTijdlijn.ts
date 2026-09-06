// Mini-voorraad op het controlescherm (mockup mini-voorraad.html blok 1): de instroom-melding ná boeken
// (toast) en de tijdlijnregels voor de notities die de backend ín de boek-/tegenboek-transactie schrijft
// (`app/mini_voorraad/instroom.py`: detail-sleutel `mini_voorraad_bijgewerkt` resp. `mini_voorraad_teruggedraaid`
// mét een blok {regels, nieuwe_producten | producten, boek_cyclus, tekst}). Pure tekstfuncties — geen
// aantallen berekend, alleen weergegeven.
import type { MiniVoorraadInstroomDto } from '../api/types'

export const MINI_VOORRAAD_NOTITIE_SOORT = 'mini_voorraad_bijgewerkt'
export const MINI_VOORRAAD_STORNO_SOORT = 'mini_voorraad_teruggedraaid'

/** "Mini-voorraad bijgewerkt — 3 regels · nieuw — controleer naam: Kanaalplaatvork speciaal" (geen nieuwe =
 * alleen de telling; overgeslagen regels worden geteld, de redenen staan in de tijdlijn). */
export function miniVoorraadMelding(info: MiniVoorraadInstroomDto): string {
  const regels = `${info.regels} ${info.regels === 1 ? 'regel' : 'regels'}`
  const nieuw = info.nieuwe_producten.length > 0 ? ` · nieuw — controleer naam: ${info.nieuwe_producten.join(', ')}` : ''
  const over = info.overgeslagen && info.overgeslagen.length > 0 ? ` · ${info.overgeslagen.length} overgeslagen` : ''
  return `Mini-voorraad bijgewerkt — ${regels}${nieuw}${over}`
}

/** Herkent de tijdlijn-notitie: de soortnaam als sleutel mét het blok eronder (de gebouwde vorm), óf als
 * `soort`-/`notitie`-veld (contract-varianten). Fail-closed: onbekend = geen regel. */
export function isMiniVoorraadNotitie(detail: Record<string, unknown>): boolean {
  return (
    MINI_VOORRAAD_NOTITIE_SOORT in detail ||
    MINI_VOORRAAD_STORNO_SOORT in detail ||
    detail.soort === MINI_VOORRAAD_NOTITIE_SOORT ||
    detail.notitie === MINI_VOORRAAD_NOTITIE_SOORT ||
    detail.soort === MINI_VOORRAAD_STORNO_SOORT ||
    detail.notitie === MINI_VOORRAAD_STORNO_SOORT ||
    'mini_voorraad' in detail
  )
}

function alsInstroom(blok: unknown): MiniVoorraadInstroomDto | null {
  if (!blok || typeof blok !== 'object') return null
  const b = blok as Record<string, unknown>
  if (typeof b.regels !== 'number') return null
  const strings = (x: unknown) => (Array.isArray(x) ? x.filter((s): s is string => typeof s === 'string') : [])
  return { regels: b.regels, nieuwe_producten: strings(b.nieuwe_producten), overgeslagen: strings(b.overgeslagen) }
}

function tekstUit(blok: unknown): string | null {
  if (!blok || typeof blok !== 'object') return null
  const t = (blok as Record<string, unknown>).tekst
  return typeof t === 'string' && t.trim() ? t : null
}

/** Tekst voor de tijdlijnregel: de letterlijke servertekst (`tekst` in het blok of op het detail) wint; anders
 * opgebouwd uit het instroom-blok; anders een neutrale regel. Overgeslagen regels (redenen) worden benoemd. */
export function miniVoorraadTijdlijnTekst(detail: Record<string, unknown>): string {
  const storno = detail[MINI_VOORRAAD_STORNO_SOORT]
  if (storno !== undefined || detail.soort === MINI_VOORRAAD_STORNO_SOORT || detail.notitie === MINI_VOORRAAD_STORNO_SOORT) {
    const blok = (storno && typeof storno === 'object' ? storno : detail) as Record<string, unknown>
    const basis = tekstUit(blok) ?? (typeof blok.regels === 'number' ? `Mini-voorraad teruggedraaid — ${blok.regels} ${blok.regels === 1 ? 'regel' : 'regels'}` : 'Mini-voorraad teruggedraaid')
    const producten = Array.isArray(blok.producten) ? blok.producten.filter((s): s is string => typeof s === 'string') : []
    return producten.length > 0 ? `${basis} · ${producten.join(', ')}` : basis
  }
  const genest = detail[MINI_VOORRAAD_NOTITIE_SOORT] ?? detail.mini_voorraad
  const letterlijk = tekstUit(genest) ?? tekstUit(detail)
  const blok = alsInstroom(genest) ?? alsInstroom(detail)
  const basis = letterlijk ?? (blok ? miniVoorraadMelding({ ...blok, overgeslagen: [] }) : 'Mini-voorraad bijgewerkt')
  const overgeslagen = blok?.overgeslagen ?? []
  return overgeslagen.length > 0 && !basis.includes('overgeslagen') ? `${basis} · overgeslagen: ${overgeslagen.join('; ')}` : basis
}
