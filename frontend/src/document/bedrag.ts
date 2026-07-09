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

/** Btw-bedrag afleiden uit netto x percentage (design-pass taak 3) — code voor cijfers, geen AI:
 * een zuivere berekening op de al-gesynchroniseerde taxrate-percentage, geen extractie. Rondt af
 * op 2 decimalen (het voorstel is altijd overschrijfbaar, dus geen noodzaak voor bankersrounding
 * of een expliciete afrondingsrichting). `percentage` is de fractie (0.21 voor 21%), niet 21. */
export function berekenBtwBedrag(netto: number, percentage: number): number {
  return Math.round(netto * percentage * 100) / 100
}
