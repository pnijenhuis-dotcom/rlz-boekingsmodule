import { statusChipKlasse, statusLabel } from './status'

/** Documentstatus als dot + label (designpass v2, mockup .status): geen pil, één gekleurde stip
 * vóór het label. De kleurklasse komt uit status.ts (zelfde namen als de teller-chips). */
export function StatusChip({ status, title }: { status: string; title?: string }) {
  return (
    <span className={`status ${statusChipKlasse(status)}`} title={title}>
      {statusLabel(status)}
    </span>
  )
}
