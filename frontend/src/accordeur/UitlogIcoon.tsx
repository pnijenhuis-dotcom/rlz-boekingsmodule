/** Power-icoon voor de uitlogknop (Android-bouwronde 29-08). Vervangt het tekstglyph ⏻ (U+23FB):
 * de Android-WebView/Roboto heeft dat teken niet en toonde een tofu-blokje (emulator API 36,
 * WebView 133); iOS/desktop hadden 'm wel. Inline SVG in currentColor = font-onafhankelijk,
 * zelfde maat als de andere header-glyphs. Decoratief: de knop draagt zelf aria-label/title. */
export function UitlogIcoon() {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      width="1em"
      height="1em"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      style={{ display: 'inline-block', verticalAlign: '-0.125em' }}
    >
      <path d="M12 3v9" />
      <path d="M7.05 6.05a7 7 0 1 0 9.9 0" />
    </svg>
  )
}
