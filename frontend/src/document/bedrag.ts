/** Normaliseert een door de gebruiker getypt bedrag naar punt-decimaal vóór verzending naar de
 * backend (design-pass taak P2). Accepteert zowel NL-notatie ("1.234,56") als al-genormaliseerd
 * punt-decimaal ("1234.56") — een komma in de invoer is het onderscheidende signaal voor
 * NL-notatie (punten zijn dan duizendtal-scheidingstekens en verdwijnen); zonder komma blijft de
 * invoer ongewijzigd. */
export function normaliseerBedrag(invoer: string): string {
  const schoon = invoer.trim()
  if (schoon.includes(',')) {
    return schoon.replace(/\./g, '').replace(',', '.')
  }
  return schoon
}

/** Voor de live aansluit-indicator (puur weergave, geen boekingslogica) — dezelfde normalisatie,
 * daarna een JS-getal. `null` bij een leeg of onherkenbaar bedrag (telt dan als 0 mee, net als de
 * backend-check die `None` als 0 behandelt bij het sommeren). */
export function bedragAlsGetal(invoer: string): number | null {
  const genormaliseerd = normaliseerBedrag(invoer)
  if (!genormaliseerd) return null
  const getal = Number(genormaliseerd)
  return Number.isFinite(getal) ? getal : null
}
