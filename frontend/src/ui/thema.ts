/** Thema-resolutie kantoor-console (fase 1 modernisering, mockup/kantoor-modern.html —
 * Vastly-patroon): een expliciete gebruikerskeuze (localStorage) wint altijd; zonder keuze
 * volgt de console het systeem. De accordeur-PWA heeft een eigen, losstaand thema
 * (`--acc-*`-tokens, data-thema op .acc) en wordt hier bewust niet door geraakt. */
export type Thema = 'licht' | 'donker'

const OPSLAG_SLEUTEL = 'rlz-thema'

export function leesOpgeslagenThema(): Thema | null {
  const opgeslagen = localStorage.getItem(OPSLAG_SLEUTEL)
  return opgeslagen === 'licht' || opgeslagen === 'donker' ? opgeslagen : null
}

export function bewaarThema(thema: Thema) {
  localStorage.setItem(OPSLAG_SLEUTEL, thema)
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
