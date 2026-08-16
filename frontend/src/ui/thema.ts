/** Thema-resolutie kantoor-console (fase 1 modernisering, mockup/kantoor-modern.html —
 * Vastly-patroon): een expliciete gebruikerskeuze (localStorage) wint altijd; zonder keuze
 * volgt de console het systeem. De accordeur-PWA heeft een eigen, losstaand thema
 * (`--acc-*`-tokens, data-thema op .acc) en wordt hier bewust niet door geraakt. */
export type Thema = 'licht' | 'donker'

const OPSLAG_SLEUTEL = 'rlz-thema'

/* localStorage kan ontbreken of gooien (vitest-jsdom zonder storage, Safari private mode) —
 * het thema mag daar nooit op omvallen: zonder opslag geen onthouden keuze, verder alles
 * gewoon werkend (initThema draait sinds 2026-08-16 op moduleniveau, vóór React). */
export function leesOpgeslagenThema(): Thema | null {
  try {
    const opgeslagen = window.localStorage.getItem(OPSLAG_SLEUTEL)
    return opgeslagen === 'licht' || opgeslagen === 'donker' ? opgeslagen : null
  } catch {
    return null
  }
}

export function bewaarThema(thema: Thema) {
  try {
    window.localStorage.setItem(OPSLAG_SLEUTEL, thema)
  } catch {
    // Geen opslag = keuze geldt alleen deze sessie — bewust stil, dit is een nice-to-have.
  }
}

export function systeemThema(): Thema {
  // jsdom (tests) kent geen matchMedia — dan licht als neutrale default.
  if (typeof window.matchMedia !== 'function') return 'licht'
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'donker' : 'licht'
}

/** De klasse gaat op <html> én <body>: tokens.css en de Tailwind-dark-variant kijken naar
 * `.dark`, de oudere scherm-CSS (components.css) naar `body.dark` — beide blijven kloppen. */
export function pasThemaToe(thema: Thema) {
  const donker = thema === 'donker'
  document.documentElement.classList.toggle('dark', donker)
  document.body.classList.toggle('dark', donker)
}

export function huidigThema(): Thema {
  return document.documentElement.classList.contains('dark') ? 'donker' : 'licht'
}

export function initThema() {
  pasThemaToe(leesOpgeslagenThema() ?? systeemThema())
}
