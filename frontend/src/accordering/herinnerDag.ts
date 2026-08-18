/** Dagrem-helpers voor de handmatige herinner-knop (veegrun 2026-08-18).
 *
 * De server remt op de Europe/Amsterdam-kalenderdag (accordering/herinnering.py::_vandaag,
 * DB-uniek op (document, datum)); deze helpers spiegelen exact die vergelijking zodat de
 * knop al vóór de klik disabled staat — geen fout-ná-klik meer. NB `laatst_herinnerd`
 * bevat alleen geslaagde verzendingen (status 'verzonden'): een mislukte of overgeslagen
 * poging telt niet mee en de knop blijft dan actief (herkansing, bedoeld gedrag). */

const TIJDZONE = 'Europe/Amsterdam'

function kalenderdag(d: Date): string {
  return d.toLocaleDateString('nl-NL', { timeZone: TIJDZONE })
}

export function isVandaagHerinnerd(verzondenOp: string | null | undefined, nu: Date = new Date()): boolean {
  if (!verzondenOp) return false
  const verzonden = new Date(verzondenOp)
  if (Number.isNaN(verzonden.getTime())) return false
  return kalenderdag(verzonden) === kalenderdag(nu)
}

export function herinnerTijdLabel(verzondenOp: string): string {
  return new Date(verzondenOp).toLocaleTimeString('nl-NL', {
    timeZone: TIJDZONE,
    hour: '2-digit',
    minute: '2-digit',
  })
}
