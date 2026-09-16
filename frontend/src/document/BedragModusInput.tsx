import { useEffect, useState } from 'react'
import { bedragAlsGetal } from './bedrag'
import { type BedragModus, rekenOm } from './bedragModus'

function formatInvoer(waarde: number): string {
  return waarde.toFixed(2).replace('.', ',')
}

/** Bedragveld dat in de gekozen modus (netto/bruto) getoond én getypt wordt terwijl de opgeslagen waarde in de
 * `bron`-modus blijft (inkoopregels: netto; kassaregels: bruto). Tijdens het typen blijft de tekst van de gebruiker
 * staan (geen heen-en-weer-afronding); ná blur of een externe wijziging volgt de tekst de opgeslagen waarde. Zonder
 * percentage (geen btw-code) is omrekenen onmogelijk: het veld blijft in de bron-modus mét tooltip. */
export function BedragModusInput({
  waarde,
  bron,
  modus,
  percentage,
  onWijzig,
  ariaLabel,
  disabled,
  className,
  title,
  style,
}: {
  /** Opgeslagen waarde als tekst in de `bron`-modus (NL-invoer toegestaan). */
  waarde: string
  bron: BedragModus
  modus: BedragModus
  percentage: number | undefined
  /** Nieuwe waarde in de `bron`-modus (genormaliseerd naar "1234,56" bij omrekening, anders de getypte tekst). */
  onWijzig: (waardeInBronModus: string) => void
  ariaLabel: string
  disabled?: boolean
  className?: string
  title?: string
  style?: React.CSSProperties
}) {
  const omrekenbaar = percentage !== undefined && modus !== bron
  const toonModus: BedragModus = omrekenbaar ? modus : bron
  const afgeleid = (): string => {
    if (!omrekenbaar) return waarde
    const getal = bedragAlsGetal(waarde)
    return getal === null ? waarde : formatInvoer(rekenOm(getal, bron, modus, percentage))
  }
  const [tekst, setTekst] = useState<string>(afgeleid)
  const [focus, setFocus] = useState(false)
  useEffect(() => {
    if (!focus) setTekst(afgeleid())
    // eslint-disable-next-line react-hooks/exhaustive-deps -- alleen hersynchroniseren als de bron/modus verandert
  }, [waarde, modus, percentage, bron, focus])

  const label = toonModus === 'netto' ? 'Netto' : 'Bruto'
  const tip =
    !omrekenbaar && modus !== bron
      ? `Geen btw-code op deze regel — omrekenen naar ${modus} kan niet, het veld blijft ${bron}`
      : title
  return (
    <input
      aria-label={`${label} ${ariaLabel}`.trim()}
      inputMode="decimal"
      title={tip}
      className={className}
      style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums', ...style }}
      value={tekst}
      disabled={disabled}
      onFocus={() => setFocus(true)}
      onBlur={() => setFocus(false)}
      onChange={(e) => {
        const nieuw = e.target.value
        setTekst(nieuw)
        if (!omrekenbaar) {
          onWijzig(nieuw)
          return
        }
        const getal = bedragAlsGetal(nieuw)
        if (getal === null) {
          if (nieuw.trim() === '') onWijzig('')
          return
        }
        onWijzig(formatInvoer(rekenOm(getal, modus, bron, percentage)))
      }}
    />
  )
}
