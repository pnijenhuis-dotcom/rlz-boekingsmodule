import { Button } from './Button'

/** Paginering voor lijsten die niet mogen omvallen bij tientallen rijen (feedbackronde 25-08
 * deel 3, punt 3 — /gebruikers). Puur presentatie: de aanroeper houdt `pagina` en snijdt zelf.
 * Verbergt zich bij één pagina; "1–25 van 63" + vorige/volgende. */
export const PAGINA_GROOTTE = 25

export function paginaSlice<T>(items: T[], pagina: number, grootte: number = PAGINA_GROOTTE): T[] {
  const start = (pagina - 1) * grootte
  return items.slice(start, start + grootte)
}

export function aantalPaginas(totaal: number, grootte: number = PAGINA_GROOTTE): number {
  return Math.max(1, Math.ceil(totaal / grootte))
}

export function Paginering({
  pagina,
  totaal,
  grootte = PAGINA_GROOTTE,
  onPagina,
  label = 'rijen',
}: {
  pagina: number
  totaal: number
  grootte?: number
  onPagina: (pagina: number) => void
  label?: string
}) {
  const paginas = aantalPaginas(totaal, grootte)
  if (totaal <= grootte) return null
  const start = (pagina - 1) * grootte + 1
  const eind = Math.min(totaal, pagina * grootte)
  return (
    <nav
      className="paginering"
      aria-label="Paginering"
      style={{ display: 'flex', alignItems: 'center', gap: 10, justifyContent: 'flex-end', marginTop: 10 }}
    >
      <span className="hint" style={{ margin: 0 }}>
        {start}–{eind} van {totaal} {label}
      </span>
      <Button variant="secundair" maat="klein" disabled={pagina <= 1} onClick={() => onPagina(pagina - 1)} aria-label="Vorige pagina">
        ‹ Vorige
      </Button>
      <span className="hint" style={{ margin: 0 }}>
        pagina {pagina} / {paginas}
      </span>
      <Button
        variant="secundair"
        maat="klein"
        disabled={pagina >= paginas}
        onClick={() => onPagina(pagina + 1)}
        aria-label="Volgende pagina"
      >
        Volgende ›
      </Button>
    </nav>
  )
}
