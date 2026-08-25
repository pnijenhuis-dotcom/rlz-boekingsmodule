import { useLayoutEffect, useRef } from 'react'

/** Regel-omschrijving zonder afkappen (blok C 2026-08-10, kliktest Peter): een gewone <input>
 * kapt lange omschrijvingen visueel af. Dit veld loopt door over meerdere regels (textarea,
 * zelfde invoer-styling) en toont bij hover de volledige tekst (title). Geldt overal waar
 * regel-omschrijvingen bewerkt worden — verkoop-review én inkoop-controlescherm. Enter blijft
 * uit de waarde (regel-omschrijvingen zijn één logische regel; RLZ kent geen harde returns).
 *
 * Regelrij-UI 25-08 (screenshot Peter, LUSSO): het veld groeit mee met de inhoud — de oude vaste
 * twee regels kapten "Factuur 260988 — samengevoegd (…)" alsnog af. Hoogte volgt scrollHeight
 * (minimaal één regel), ook bij een smallere kolom of een langere waarde ná extractie. */
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
  const ref = useRef<HTMLTextAreaElement>(null)

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    // Eerst inklappen, dan meten: anders krimpt het veld nooit terug na wissen.
    el.style.height = 'auto'
    if (el.scrollHeight > 0) el.style.height = `${el.scrollHeight}px`
  }, [waarde])

  return (
    <textarea
      ref={ref}
      className="regel-omschrijving-veld"
      aria-label={ariaLabel}
      title={waarde || undefined}
      value={waarde}
      rows={1}
      disabled={disabled}
      onChange={(e) => onWijzig(e.target.value.replace(/[\r\n]+/g, ' '))}
    />
  )
}
