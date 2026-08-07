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

export function isoNaarDate(iso: string): Date {
  const [jjjj, mm, dd] = iso.split('-').map(Number)
  return new Date(jjjj, mm - 1, dd)
}

export function dateNaarIso(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
