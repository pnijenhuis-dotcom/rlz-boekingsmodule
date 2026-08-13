/** Weergave-afspraken voor de doorbelasting-boekingstatussen (backend
 * DoorbelastingBoekingStatus) — één plek zodat sectie, reviewscherm en resultaatlijst dezelfde
 * chips tonen. */

export interface StatusChipStand {
  klasse: string
  label: string
}

export function boekingStatusChip(status: string): StatusChipStand {
  switch (status) {
    case 'geboekt':
      return { klasse: 'ok', label: 'geboekt ✓' }
    case 'spiegel_open':
      return { klasse: 'vraag', label: 'spiegel open — taak' }
    case 'half_geboekt':
      return { klasse: 'blokkerend', label: 'half geboekt' }
    case 'gestorneerd':
      return { klasse: 'geheugen', label: 'gestorneerd' }
    default:
      return { klasse: 'blokkerend', label: status }
  }
}

/** Bedrag-string van de backend (punt-decimaal) naar NL-weergave; onparseerbaar = de bron
 * ongewijzigd tonen (nooit stil een bedrag vervormen). */
export function formatEuroString(bedrag: string): string {
  const getal = Number(bedrag)
  if (!Number.isFinite(getal)) return bedrag
  return getal.toLocaleString('nl-NL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** Percentage-string (punt-decimaal, bv. "33.33") naar NL-invoer/weergave ("33,33") zonder
 * overbodige nullen ("50.00" → "50"). */
export function formatPercentage(percentage: string): string {
  const getal = Number(percentage)
  if (!Number.isFinite(getal)) return percentage
  return String(getal).replace('.', ',')
}
