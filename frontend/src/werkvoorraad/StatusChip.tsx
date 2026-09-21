import { statusChipKlasse, statusLabel, wordtGeboektLabel, wordtGeboektLooptVast } from './status'

/** Documentstatus als dot + label (designpass v2, mockup .status): geen pil, één gekleurde stip
 * vóór het label. De kleurklasse komt uit status.ts (zelfde namen als de teller-chips).
 * `soort` is optioneel en alleen nodig waar het label per documentsoort afwijkt (blok B 04-09:
 * een verplichting is "Klaar voor accordering", geen "Klaar om te boeken").
 * `laatstGewijzigdOp` (21-09): bij wordt_geboekt ná 5 min "Wordt geboekt… (loopt vast — N min)" mét oranje dot —
 * een eeuwige grijze stip bestaat niet meer (BUG rlz-boek-wachtrij 18→21-09). */
export function StatusChip({
  status,
  title,
  soort,
  laatstGewijzigdOp,
  nu,
}: {
  status: string
  title?: string
  soort?: string | null
  laatstGewijzigdOp?: string | null
  /** Testhaak: vaste klok. */
  nu?: number
}) {
  const vast = status === 'wordt_geboekt' && wordtGeboektLooptVast(laatstGewijzigdOp, nu)
  const label = status === 'wordt_geboekt' ? wordtGeboektLabel(laatstGewijzigdOp, nu) : statusLabel(status, soort)
  const titel = vast
    ? (title ?? 'De achtergrond-schrijver rondde deze boeking nog niet af — open het document en kies "Opnieuw indienen".')
    : title
  return (
    <span className={`status ${vast ? 'vraag' : statusChipKlasse(status)}`} title={titel} data-loopt-vast={vast ? '1' : undefined}>
      {label}
    </span>
  )
}
