/** Gebaar-wiskunde voor de eigen zoomlaag van de PDF-weergave (Peter 15-09: knijpzoom werkt niet in de native WebView /
 * PWA-standalone en scrolt de hele app mee). PUUR — geen DOM: schaal-clamp, knijp-schaal met focuspunt (het punt onder
 * de vingers blijft op zijn plek), dubbeltik = 2× op de tikplek (of terug naar 1×), pannen binnen de grenzen van het
 * ingezoomde canvas. Alles in CSS-pixels van de viewport (het vak waarin de pagina's staan). */

export const ZOOM_MIN = 1
export const ZOOM_MAX = 4
export const DUBBELTIK_SCHAAL = 2

export interface ZoomStand {
  schaal: number
  /** Verschuiving van de inhoud t.o.v. de viewport, in CSS-px (≤ 0 = naar links/boven geschoven). */
  x: number
  y: number
}

export interface Viewport {
  breedte: number
  hoogte: number
}

export const BEGINSTAND: ZoomStand = { schaal: 1, x: 0, y: 0 }

export function clampSchaal(schaal: number): number {
  if (!Number.isFinite(schaal)) return ZOOM_MIN
  return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, schaal))
}

/** Houdt de inhoud binnen het vak: nooit een lege rand aan een kant zolang de inhoud groter is dan het vak;
 * `inhoudHoogte` = hoogte van álle pagina's samen op schaal 1 (in CSS-px). */
export function clampVerschuiving(stand: ZoomStand, viewport: Viewport, inhoudHoogte: number): ZoomStand {
  const schaal = clampSchaal(stand.schaal)
  const breed = viewport.breedte * schaal
  const hoog = inhoudHoogte * schaal
  const minX = Math.min(0, viewport.breedte - breed)
  const minY = Math.min(0, viewport.hoogte - hoog)
  return {
    schaal,
    x: Math.min(0, Math.max(minX, stand.x)),
    y: Math.min(0, Math.max(minY, stand.y)),
  }
}

/** Nieuwe stand ná een schaalverandering rond een focuspunt (in viewport-CSS-px): het inhoudspunt onder de vinger blijft
 * onder de vinger. inhoud = (focus − x) / schaal → nieuwe x = focus − inhoud × nieuweSchaal. */
export function zoomRond(stand: ZoomStand, nieuweSchaal: number, focus: { x: number; y: number }): ZoomStand {
  const schaal = clampSchaal(nieuweSchaal)
  const inhoudX = (focus.x - stand.x) / stand.schaal
  const inhoudY = (focus.y - stand.y) / stand.schaal
  return { schaal, x: focus.x - inhoudX * schaal, y: focus.y - inhoudY * schaal }
}

/** Knijpen: afstand tussen twee vingers nu t.o.v. bij het begin → schaalfactor op de beginschaal, rond het middelpunt. */
export function knijp(
  begin: ZoomStand,
  beginAfstand: number,
  huidigeAfstand: number,
  middelpunt: { x: number; y: number },
): ZoomStand {
  if (beginAfstand <= 0) return begin
  return zoomRond(begin, begin.schaal * (huidigeAfstand / beginAfstand), middelpunt)
}

/** Dubbeltik: op 1× → 2× op de tikplek; anders terug naar 1× (beginstand). */
export function dubbeltik(stand: ZoomStand, tikplek: { x: number; y: number }): ZoomStand {
  if (stand.schaal > ZOOM_MIN + 0.01) return BEGINSTAND
  return zoomRond(stand, DUBBELTIK_SCHAAL, tikplek)
}

/** Pannen met één vinger: verschuiving optellen (de aanroeper clampt). */
export function pan(stand: ZoomStand, dx: number, dy: number): ZoomStand {
  return { ...stand, x: stand.x + dx, y: stand.y + dy }
}

export function afstand(a: { x: number; y: number }, b: { x: number; y: number }): number {
  return Math.hypot(a.x - b.x, a.y - b.y)
}

export function middelpunt(a: { x: number; y: number }, b: { x: number; y: number }): { x: number; y: number } {
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }
}

/** Renderschaal voor pdf.js: scherp blijven bij inzoomen zonder onbegrensd geheugen — de canvas wordt getekend op de
 * hoogst GEBRUIKTE zoomstap (1, 2, 3 of 4) × devicePixelRatio (max 3), nooit hoger dan nodig. */
export function renderStap(schaal: number): number {
  return Math.min(ZOOM_MAX, Math.max(1, Math.ceil(clampSchaal(schaal) - 0.001)))
}
