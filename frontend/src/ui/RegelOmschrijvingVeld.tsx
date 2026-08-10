/** Regel-omschrijving zonder afkappen (blok C 2026-08-10, kliktest Peter): een gewone <input>
 * kapt lange omschrijvingen visueel af. Dit veld loopt door op 2 regels (textarea, zelfde
 * invoer-styling) en toont bij hover de volledige tekst (title). Geldt overal waar
 * regel-omschrijvingen bewerkt worden — verkoop-review én inkoop-controlescherm. Enter blijft
 * uit de waarde (regel-omschrijvingen zijn één logische regel; RLZ kent geen harde returns). */
export function RegelOmschrijvingVeld({
  ariaLabel,
  waarde,
  onWijzig,
  disabled,
}: {
  ariaLabel: string
  waarde: string
  onWijzig: (waarde: string) => void
  disabled?: boolean
}) {
  return (
    <textarea
      className="regel-omschrijving-veld"
      aria-label={ariaLabel}
      title={waarde || undefined}
      value={waarde}
      rows={2}
      disabled={disabled}
      onChange={(e) => onWijzig(e.target.value.replace(/[\r\n]+/g, ' '))}
    />
  )
}
