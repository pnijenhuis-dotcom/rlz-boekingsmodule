/** Pure datum-helpers voor de DatePicker (Vastly-port e, 2026-08-07).
 *
 * Contract: de API-waarde is ALTIJD ISO `jjjj-mm-dd` (of null); `dd-mm-jjjj` is puur weergave.
 * De helpers vermijden bewust tijdzone-vallen: kalendervalidatie via een UTC-round-trip en
 * Date→ISO zonder toISOString (die schuift over UTC en kan een dag verspringen). */

export function maskeerDatumInvoer(ruw: string): string {
  const cijfers = ruw.replace(/\D/g, '').slice(0, 8)
  return [cijfers.slice(0, 2), cijfers.slice(2, 4), cijfers.slice(4, 8)].filter(Boolean).join('-')
}

export function weergaveNaarIso(weergave: string): string | null {
  const m = /^(\d{2})-(\d{2})-(\d{4})$/.exec(weergave)
  if (!m) return null
  const [, dd, mm, jjjj] = m
  const proef = new Date(Date.UTC(+jjjj, +mm - 1, +dd))
  if (proef.getUTCFullYear() !== +jjjj || proef.getUTCMonth() !== +mm - 1 || proef.getUTCDate() !== +dd) {
    return null
  }
  return `${jjjj}-${mm}-${dd}`
}

export function isoNaarWeergave(iso: string | null): string {
  if (!iso) return ''
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso)
  if (!m) return ''
  const [, jjjj, mm, dd] = m
  return `${dd}-${mm}-${jjjj}`
}

/** Lexicografisch vergelijken is correct voor jjjj-mm-dd. */
export function binnenGrenzen(iso: string, min?: string, max?: string): boolean {
  if (min && iso < min) return false
  if (max && iso > max) return false
  return true
}

/** Soepele blur-parser (bugfix 07-09 — "Tab/blur wist ingevulde datum"): naast het kanonieke
 * dd-mm-jjjj accepteert dit ook d-m-jjjj, dd-mm-jj (2-cijferig jaar → 20jj), ddmmjjjj (geen
 * scheidingsteken) en dezelfde vormen met '/' of '.' als scheidingsteken (bv. 7/9/2026,
 * 07.09.2026). Ongeldige vorm of ongeldige kalenderdatum (bv. 31-02) → null; de aanroeper
 * beslist dan zelf over de foutmelding — deze functie wist nooit iets. */
export function parseSoepeleDatum(ruw: string): string | null {
  const tekst = ruw.trim()
  if (!tekst) return null
  const metScheidingsteken = /^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2}|\d{4})$/.exec(tekst)
  const zonderScheidingsteken = metScheidingsteken ? null : /^(\d{2})(\d{2})(\d{4})$/.exec(tekst)
  const match = metScheidingsteken ?? zonderScheidingsteken
  if (!match) return null
  const [, ddRuw, mmRuw, jjjjRuw] = match
  const dd = ddRuw.padStart(2, '0')
  const mm = mmRuw.padStart(2, '0')
  const jjjj = jjjjRuw.length === 2 ? String(2000 + Number(jjjjRuw)) : jjjjRuw
  return weergaveNaarIso(`${dd}-${mm}-${jjjj}`)
}

export function isoNaarDate(iso: string): Date {
  const [jjjj, mm, dd] = iso.split('-').map(Number)
  return new Date(jjjj, mm - 1, dd)
}

export function dateNaarIso(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
