import { statusChipKlasse, statusLabel } from './status'

export function StatusChip({ status }: { status: string }) {
  return <span className={`chip ${statusChipKlasse(status)}`}>{statusLabel(status)}</span>
}
