// WCAG-contrast — pure, deterministische rekenfuncties (geen DOM) voor de contrast-audit op de
// kleurtokens (designpass v2, 26-08 — Vastly-patroon kleur-restyle 21-08). Formules: WCAG 2.x
// relatieve luminantie + contrastratio (https://www.w3.org/TR/WCAG21/#dfn-relative-luminance).

export interface Rgb {
  r: number
  g: number
  b: number
}

/** "#rgb" of "#rrggbb" → {r,g,b} (0-255). Gooit op elke andere vorm. */
export function hexNaarRgb(hex: string): Rgb {
  const kaal = hex.trim().replace(/^#/, '')
  const vol =
    kaal.length === 3
      ? kaal
          .split('')
          .map((c) => c + c)
          .join('')
      : kaal
  if (!/^[0-9a-fA-F]{6}$/.test(vol)) {
    throw new Error(`Geen geldige hexkleur: ${hex}`)
  }
  return {
    r: parseInt(vol.slice(0, 2), 16),
    g: parseInt(vol.slice(2, 4), 16),
    b: parseInt(vol.slice(4, 6), 16),
  }
}

function lineair(kanaal: number): number {
  const c = kanaal / 255
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)
}

/** Relatieve luminantie (0 = zwart, 1 = wit). */
export function relatieveLuminantie(hex: string): number {
  const { r, g, b } = hexNaarRgb(hex)
  return 0.2126 * lineair(r) + 0.7152 * lineair(g) + 0.0722 * lineair(b)
}

/** WCAG-contrastratio tussen twee hexkleuren (1:1 … 21:1). */
export function contrastRatio(voorgrond: string, achtergrond: string): number {
  const l1 = relatieveLuminantie(voorgrond)
  const l2 = relatieveLuminantie(achtergrond)
  const [licht, donker] = l1 >= l2 ? [l1, l2] : [l2, l1]
  return (licht + 0.05) / (donker + 0.05)
}

/** Solide blend van `boven` met dekking `alpha` over `onder` — de hex die color-mix/rgba in de
 * praktijk oplevert, zodat semi-transparante vlakken tóch deterministisch te toetsen zijn. */
export function blend(boven: string, alpha: number, onder: string): string {
  const b = hexNaarRgb(boven)
  const o = hexNaarRgb(onder)
  const kanaal = (x: number, y: number) => Math.round(x * alpha + y * (1 - alpha))
  const hex = (n: number) => n.toString(16).padStart(2, '0')
  return `#${hex(kanaal(b.r, o.r))}${hex(kanaal(b.g, o.g))}${hex(kanaal(b.b, o.b))}`
}

/** Alle `--naam: #hex;`-declaraties binnen het eerste blok dat met `selector {` begint.
 * Leest de tokens rechtstreeks uit de CSS-bron — één bron, geen gekopieerde hexen die kunnen
 * driften. Andere waarden (rgba, var(), px) worden bewust overgeslagen. */
export function lokaleTokens(css: string, selector: string): Record<string, string> {
  const start = css.indexOf(`${selector} {`)
  if (start === -1) throw new Error(`Selector niet gevonden: ${selector}`)
  const eind = css.indexOf('}', start)
  const blok = css.slice(start, eind)
  const tokens: Record<string, string> = {}
  for (const m of blok.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{3,6})\s*;/g)) {
    tokens[m[1]] = m[2]
  }
  return tokens
}
