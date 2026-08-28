#!/usr/bin/env bash
# Grafische Play-listing-assets uit dezelfde bron als alle iconen (mockup/app-icoon-n.svg —
# geometrie nooit aanpassen; zie genereer_assets.sh). Android-bouwronde 28-08.
#
#   store-assets/play/icoon-512.png              — Play "App icon": 512×512, 32-bit PNG, full-bleed
#                                                  (Play maskt zelf; identiek aan het PWA-icoon)
#   store-assets/play/feature-graphic-1024x500.png — Play "Feature graphic" (VERPLICHT voor een
#                                                  listing): wordmark-verloop, monogram links,
#                                                  productnaam + ondertitel rechts
#
# Rendering via NSImage/CoreSVG (osascript), zelfde renderer als genereer_assets.sh — geen
# extra dependencies. Screenshots komen hier NIET uit: die maak je in de Android-emulator
# (PLAY_DRAAIBOEK.md §6 — de iPhone-screenshots hebben een verhouding > 2:1 en worden door
# Play geweigerd).
set -euo pipefail

HIER="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(cd "$HIER/.." && pwd)"
BRON="$REPO/mockup/app-icoon-n.svg"
DOEL="$HIER/store-assets/play"
WERK="$(mktemp -d)"
trap 'rm -rf "$WERK"' EXIT
mkdir -p "$DOEL"

[ -f "$BRON" ] || { echo "Bron-SVG ontbreekt: $BRON" >&2; exit 1; }
DEFS="$(awk '/<defs>/,/<\/defs>/' "$BRON")"
MONOGRAM="$(awk '/<g transform/,/<\/g>/' "$BRON")"
[ -n "$DEFS" ] && [ -n "$MONOGRAM" ] || { echo "Extractie uit $BRON mislukt" >&2; exit 1; }
MONO_X=176; MONO_Y=275; MONO_B=672; MONO_H=474

cat > "$WERK/rasteriseer.js" <<'EOF'
ObjC.import('AppKit');
function run(argv) {
  const bron = argv[0], b = parseInt(argv[1]), h = parseInt(argv[2]), doel = argv[3];
  const img = $.NSImage.alloc.initWithContentsOfFile(bron);
  if (img.isNil() || !img.valid) throw 'SVG niet leesbaar: ' + bron;
  const rep = $.NSBitmapImageRep.alloc.initWithBitmapDataPlanesPixelsWidePixelsHighBitsPerSampleSamplesPerPixelHasAlphaIsPlanarColorSpaceNameBytesPerRowBitsPerPixel(
    null, b, h, 8, 4, true, false, $.NSDeviceRGBColorSpace, 0, 0);
  const ctx = $.NSGraphicsContext.graphicsContextWithBitmapImageRep(rep);
  $.NSGraphicsContext.saveGraphicsState;
  $.NSGraphicsContext.setCurrentContext(ctx);
  ctx.imageInterpolation = $.NSImageInterpolationHigh;
  img.drawInRectFromRectOperationFraction($.NSMakeRect(0, 0, b, h), $.NSZeroRect, $.NSCompositingOperationCopy, 1.0);
  $.NSGraphicsContext.restoreGraphicsState;
  const png = rep.representationUsingTypeProperties($.NSBitmapImageFileTypePNG, $.NSDictionary.dictionary);
  if (!png.writeToFileAtomically(doel, true)) throw 'PNG niet weggeschreven: ' + doel;
  return 'ok';
}
EOF
render() { osascript -l JavaScript "$WERK/rasteriseer.js" "$1" "$2" "$3" "$4" >/dev/null; }

# Icoon 512 — full-bleed vierkant, exact het PWA-/App Store-beeld.
cat > "$WERK/icoon.svg" <<EOF
<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 1024 1024">
$DEFS
  <rect width="1024" height="1024" fill="url(#achtergrond)"/>
$MONOGRAM
</svg>
EOF
render "$WERK/icoon.svg" 512 512 "$DOEL/icoon-512.png"

# Feature graphic 1024×500 — monogram links (hoogte 270), tekst rechts (maat zo dat
# "Boekingsmodule" ruim binnen 1024 px blijft — zichtcontrole 28-08). Tekst in een
# systeemfont (Helvetica Neue, aanwezig op elke Mac); de kleuren zijn de wordmark-tokens
# (wit + mint #57b3a7, zelfde als de accent-driehoeken).
MB=$(( 270 * MONO_B / MONO_H ))
cat > "$WERK/feature.svg" <<EOF
<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="500">
$DEFS
  <rect width="1024" height="500" fill="url(#achtergrond)"/>
  <svg x="72" y="115" width="$MB" height="270" viewBox="$MONO_X $MONO_Y $MONO_B $MONO_H">
$MONOGRAM
  </svg>
  <text x="$(( 72 + MB + 56 ))" y="232" font-family="Helvetica Neue, Helvetica, Arial, sans-serif" font-size="56" font-weight="600" fill="#ffffff">Nijenhuis</text>
  <text x="$(( 72 + MB + 56 ))" y="296" font-family="Helvetica Neue, Helvetica, Arial, sans-serif" font-size="56" font-weight="600" fill="#ffffff">Boekingsmodule</text>
  <text x="$(( 72 + MB + 56 ))" y="350" font-family="Helvetica Neue, Helvetica, Arial, sans-serif" font-size="28" font-weight="400" fill="#57b3a7">Facturen goedkeuren</text>
</svg>
EOF
render "$WERK/feature.svg" 1024 500 "$DOEL/feature-graphic-1024x500.png"

echo "Play-assets gegenereerd in $DOEL: icoon-512.png, feature-graphic-1024x500.png"
