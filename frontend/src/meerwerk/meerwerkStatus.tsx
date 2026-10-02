// Punt 12 run A (02-10): ÉÉN statusdefinitie voor meerwerk — Beoordelen › Meerwerk en het blok "Meerwerk" op de
// projectpagina tekenen dezelfde badge uit dezelfde bron (backend `MeerwerkStatus`: gemeld · goedgekeurd · doorbelast ·
// afgewezen). Teal = actie, groen = status (designpass v2); paars = de meerwerk-kleur van de veld-app.
import { Badge } from '../ui/basis'
import type { MeerwerkDto } from './meerwerkApi'

export type MeerwerkStatus = MeerwerkDto['status']

/** Volgorde = de levensloop van een melding; labels zoals het kantoor ze leest (Beoordelen-filters). */
export const MEERWERK_STATUS_VOLGORDE: readonly MeerwerkStatus[] = ['gemeld', 'goedgekeurd', 'doorbelast', 'afgewezen']

export const MEERWERK_STATUS_LABEL: Record<MeerwerkStatus, string> = {
  gemeld: 'gemeld — te beoordelen',
  goedgekeurd: 'goedgekeurd — nog doorbelasten',
  doorbelast: 'doorbelast (gefactureerd)',
  afgewezen: 'afgewezen — eigen rekening',
}

export function meerwerkStatusBadge(item: Pick<MeerwerkDto, 'status' | 'verkoopfactuur_referentie'>) {
  switch (item.status) {
    case 'gemeld':
      return <Badge variant="paars">gemeld</Badge>
    case 'goedgekeurd':
      return <Badge variant="warn">nog doorbelasten</Badge>
    case 'doorbelast':
      return <Badge variant="ok">doorbelast{item.verkoopfactuur_referentie ? ` · ${item.verkoopfactuur_referentie}` : ''}</Badge>
    case 'afgewezen':
      return <Badge variant="danger">afgewezen · eigen rekening</Badge>
  }
}
