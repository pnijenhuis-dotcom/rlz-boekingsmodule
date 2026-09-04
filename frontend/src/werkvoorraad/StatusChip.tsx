import { statusChipKlasse, statusLabel } from './status'

/** Documentstatus als dot + label (designpass v2, mockup .status): geen pil, één gekleurde stip
 * vóór het label. De kleurklasse komt uit status.ts (zelfde namen als de teller-chips).
 * `soort` is optioneel en alleen nodig waar het label per documentsoort afwijkt (blok B 04-09:
 * een verplichting is "Klaar voor accordering", geen "Klaar om te boeken"). */
export function StatusChip({ status, title, soort }: { status: string; title?: string; soort?: string | null }) {
  return (
    <span className={`status ${statusChipKlasse(status)}`} title={title}>
      {statusLabel(status, soort)}
    </span>
  )
}
