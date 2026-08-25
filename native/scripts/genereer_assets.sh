#!/usr/bin/env bash
# Iconen + splash voor beide schillen ÉN de PWA, herhaalbaar gegenereerd uit de canonieke
# beeldmerk-SVG `mockup/app-icoon-n.svg` (besluit Peter 2026-08-18: de N van Reisburo
# Nijenhuis, exact gereconstrueerd uit het familielogo — geometrie NIET aanpassen).
# Eén bron, nooit hand-bewerkte PNG's; het monogram en het verloop worden hier uit de
# bron-SVG geëxtraheerd, niet overgetekend.
#
# Rendering via NSImage/CoreSVG (osascript) — puur macOS, geen extra dependencies.
# NB niet qlmanage: dat plette transparantie naar opaak wit (latente bug ontdekt 2026-08-18 —
# de Android adaptive-foreground was daardoor een wit vlak; CoreSVG bewaart alpha wél).
#
# Regels die hier vastliggen:
# - App Store-icoon = FULL-BLEED vierkant (Apple maskt zelf; geen transparante hoeken).
# - Android adaptive: background = het wordmark-verloop als PNG per dichtheid,
#   foreground = alleen het monogram op transparant, geschaald binnen de safe zone
#   (66/108 dp-cirkel; verste monogram-hoek ±411 van het middelpunt → schaal 0.76).
# - Splash (beide platforms + alle dichtheden): het verloop schermvullend met het
#   monogram gecentreerd (besluit 2026-08-18) — donkere start, geen witflits.
# - PWA: frontend/public/icons/accordeur-icoon.svg = byte-kopie van de bron;
#   192/512/apple-touch-180 full-bleed uit dezelfde bron.
# - Kantoor-webapp (besluit Peter 25-08, feedbackronde deel 2 punt 3): favicon én het
#   beeldmerk in de zijbalk = frontend/public/beeldmerk-n.svg — de afgeronde variant
#   (rx 192/1024, een browsertab maskt niet zelf) uit dezelfde bron; het monogram zelf
#   blijft geometrisch onaangeraakt.
set -euo pipefail

HIER="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(cd "$HIER/.." && pwd)"
BRON="$REPO/mockup/app-icoon-n.svg"
WERK="$(mktemp -d)"
trap 'rm -rf "$WERK"' EXIT

[ -f "$BRON" ] || { echo "Bron-SVG ontbreekt: $BRON" >&2; exit 1; }

# ---- extractie uit de bron (geen duplicatie van geometrie) ---------------------------------------
DEFS="$(awk '/<defs>/,/<\/defs>/' "$BRON")"
MONOGRAM="$(awk '/<g transform/,/<\/g>/' "$BRON")"
[ -n "$DEFS" ] && [ -n "$MONOGRAM" ] || { echo "Extractie uit $BRON mislukt (defs/monogram)" >&2; exit 1; }
# Bounding box van het monogram in bron-coördinaten (tekenruimte 420x296 × 1.6 op (176,275)).
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

render() { # render <svg-bestand> <breedte> <hoogte> <doel-png>
  osascript -l JavaScript "$WERK/rasteriseer.js" "$1" "$2" "$3" "$4" >/dev/null
}

# ---- afgeleide SVG's -----------------------------------------------------------------------------
# Full-bleed vierkant (App Store, PWA): de bron zelf, met expliciete afmetingen.
cat > "$WERK/vierkant.svg" <<EOF
<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">
$DEFS
  <rect width="1024" height="1024" fill="url(#achtergrond)"/>
$MONOGRAM
</svg>
EOF

# Android legacy launcher: zelfde beeld, vooraf afgeronde hoeken (rx-verhouding als voorheen).
cat > "$WERK/launcher.svg" <<EOF
<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">
$DEFS
  <clipPath id="rond"><rect width="1024" height="1024" rx="192"/></clipPath>
  <g clip-path="url(#rond)">
    <rect width="1024" height="1024" fill="url(#achtergrond)"/>
$MONOGRAM
  </g>
</svg>
EOF

# Adaptive foreground: transparant canvas, alléén het monogram, geschaald in de safe zone.
cat > "$WERK/foreground.svg" <<EOF
<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">
  <g transform="translate(512 512) scale(0.76) translate(-512 -512)">
$MONOGRAM
  </g>
</svg>
EOF

# Adaptive background: alleen het verloop.
cat > "$WERK/background.svg" <<EOF
<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">
$DEFS
  <rect width="1024" height="1024" fill="url(#achtergrond)"/>
</svg>
EOF

splash_svg() { # splash_svg <breedte> <hoogte> -> pad naar svg
  local b="$1" h="$2" mb mh
  mb=$(( (b < h ? b : h) * 40 / 100 ))              # monogram-breedte = 40% van de korte zijde
  mh=$(( mb * MONO_H / MONO_B ))
  cat > "$WERK/splash-${b}x${h}.svg" <<EOF
<svg xmlns="http://www.w3.org/2000/svg" width="$b" height="$h">
$DEFS
  <rect width="$b" height="$h" fill="url(#achtergrond)"/>
  <svg x="$(( (b - mb) / 2 ))" y="$(( (h - mh) / 2 ))" width="$mb" height="$mh" viewBox="$MONO_X $MONO_Y $MONO_B $MONO_H">
$MONOGRAM
  </svg>
</svg>
EOF
  echo "$WERK/splash-${b}x${h}.svg"
}

# ---- PWA (frontend/public) -----------------------------------------------------------------------
ICONS="$REPO/frontend/public/icons"
cp "$BRON" "$ICONS/accordeur-icoon.svg"
render "$WERK/vierkant.svg" 512 512 "$ICONS/accordeur-512.png"
render "$WERK/vierkant.svg" 192 192 "$ICONS/accordeur-192.png"
render "$WERK/vierkant.svg" 180 180 "$ICONS/apple-touch-icon-accordeur.png"

# ---- Kantoor-webapp (frontend/public) ------------------------------------------------------------
# Vector volstaat: browsers renderen SVG-favicons scherp op elke dichtheid; de zijbalk laadt hetzelfde
# bestand als <img>. Afgeronde hoeken zitten in het bestand (geen CSS-afhankelijkheid voor de tab).
cp "$WERK/launcher.svg" "$REPO/frontend/public/beeldmerk-n.svg"

# ---- iOS -----------------------------------------------------------------------------------------
render "$WERK/vierkant.svg" 1024 1024 "$HIER/ios/App/App/Assets.xcassets/AppIcon.appiconset/AppIcon-512@2x.png"

SPLASH_IOS="$(splash_svg 2732 2732)"
for naam in splash-2732x2732.png splash-2732x2732-1.png splash-2732x2732-2.png; do
  render "$SPLASH_IOS" 2732 2732 "$HIER/ios/App/App/Assets.xcassets/Splash.imageset/$naam"
done

# ---- Android -------------------------------------------------------------------------------------
RES="$HIER/android/app/src/main/res"

dichtheden=(mdpi hdpi xhdpi xxhdpi xxxhdpi)
launcher=(48 72 96 144 192)
adaptive=(108 162 216 324 432)
for i in "${!dichtheden[@]}"; do
  d="${dichtheden[$i]}"
  render "$WERK/launcher.svg" "${launcher[$i]}" "${launcher[$i]}" "$RES/mipmap-$d/ic_launcher.png"
  render "$WERK/launcher.svg" "${launcher[$i]}" "${launcher[$i]}" "$RES/mipmap-$d/ic_launcher_round.png"
  render "$WERK/foreground.svg" "${adaptive[$i]}" "${adaptive[$i]}" "$RES/mipmap-$d/ic_launcher_foreground.png"
  render "$WERK/background.svg" "${adaptive[$i]}" "${adaptive[$i]}" "$RES/mipmap-$d/ic_launcher_background.png"
done

# Splash: elke bestaande drawable-variant op zijn eigen afmetingen opnieuw renderen.
find "$RES" -name "splash.png" | while read -r bestand; do
  b=$(sips -g pixelWidth "$bestand" | awk '/pixelWidth/ {print $2}')
  h=$(sips -g pixelHeight "$bestand" | awk '/pixelHeight/ {print $2}')
  svg="$(splash_svg "$b" "$h")"
  render "$svg" "$b" "$h" "$bestand"
done

echo "Assets gegenereerd uit $BRON (App Store 1024, iOS-splash 2732, Android launcher/adaptive/splash, PWA 512/192/180 + SVG-kopie, kantoor-webapp beeldmerk-n.svg)."
