#!/usr/bin/env bash
# Store-assets (fase 5) — iconen + splash voor beide schillen, herhaalbaar gegenereerd uit de
# canonieke accordeur-icoon-SVG (frontend/public/icons/accordeur-icoon.svg): één bron, nooit
# hand-bewerkte PNG's. Rendering via macOS Quick Look (qlmanage) — geen extra dependencies.
#
# Regels die hier vastliggen:
# - App Store-icoon = FULL-BLEED vierkant (Apple maskt zelf; geen transparante hoeken).
# - Android adaptive: achtergrondkleur #0e1514 (values/ic_launcher_background.xml) +
#   foreground = alleen het vinkje, geschaald binnen de safe zone (~60% van het canvas).
# - Splash (beide platforms + alle dichtheden): effen #0e1514 met het icoon gecentreerd —
#   zelfde donkere start als de webview-achtergrond in capacitor.config.ts (geen witflits).
set -euo pipefail

HIER="$(cd "$(dirname "$0")/.." && pwd)"
WERK="$(mktemp -d)"
trap 'rm -rf "$WERK"' EXIT

DONKER="#0e1514"
PANEEL="#16211f"
GROEN="#5cb3a8"
VINKJE="M136 264 L224 352 L384 176"

render() { # render <svg-bestand> <max-afmeting> <doel-png>
  local uit
  qlmanage -t -s "$2" -o "$WERK" "$1" >/dev/null 2>&1
  uit="$WERK/$(basename "$1").png"
  mv "$uit" "$3"
}

# ---- bron-SVG's ----------------------------------------------------------------------------------
cat > "$WERK/store-icoon.svg" <<EOF
<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 512 512">
  <rect width="512" height="512" fill="$DONKER"/>
  <rect x="24" y="24" width="464" height="464" rx="80" fill="$PANEEL"/>
  <path d="$VINKJE" fill="none" stroke="$GROEN" stroke-width="56" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
EOF

cat > "$WERK/launcher.svg" <<EOF
<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
  <rect width="512" height="512" rx="96" fill="$DONKER"/>
  <rect x="24" y="24" width="464" height="464" rx="80" fill="$PANEEL"/>
  <path d="$VINKJE" fill="none" stroke="$GROEN" stroke-width="56" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
EOF

# Adaptive foreground: transparant canvas, alléén het vinkje in de safe zone (~60%).
cat > "$WERK/foreground.svg" <<EOF
<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
  <g transform="translate(256 256) scale(0.58) translate(-256 -256)">
    <path d="$VINKJE" fill="none" stroke="$GROEN" stroke-width="56" stroke-linecap="round" stroke-linejoin="round"/>
  </g>
</svg>
EOF

splash_svg() { # splash_svg <breedte> <hoogte> -> pad naar svg
  local b="$1" h="$2" icoon
  icoon=$(( (b < h ? b : h) * 35 / 100 ))
  cat > "$WERK/splash-${b}x${h}.svg" <<EOF
<svg xmlns="http://www.w3.org/2000/svg" width="$b" height="$h">
  <rect width="$b" height="$h" fill="$DONKER"/>
  <svg x="$(( (b - icoon) / 2 ))" y="$(( (h - icoon) / 2 ))" width="$icoon" height="$icoon" viewBox="0 0 512 512">
    <rect width="512" height="512" rx="96" fill="$DONKER"/>
    <rect x="24" y="24" width="464" height="464" rx="80" fill="$PANEEL"/>
    <path d="$VINKJE" fill="none" stroke="$GROEN" stroke-width="56" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>
</svg>
EOF
  echo "$WERK/splash-${b}x${h}.svg"
}

# ---- iOS -----------------------------------------------------------------------------------------
render "$WERK/store-icoon.svg" 1024 "$HIER/ios/App/App/Assets.xcassets/AppIcon.appiconset/AppIcon-512@2x.png"

SPLASH_IOS="$(splash_svg 2732 2732)"
for naam in splash-2732x2732.png splash-2732x2732-1.png splash-2732x2732-2.png; do
  render "$SPLASH_IOS" 2732 "$HIER/ios/App/App/Assets.xcassets/Splash.imageset/$naam"
done

# ---- Android -------------------------------------------------------------------------------------
RES="$HIER/android/app/src/main/res"

dichtheden=(mdpi hdpi xhdpi xxhdpi xxxhdpi)
launcher=(48 72 96 144 192)
foreground=(108 162 216 324 432)
for i in "${!dichtheden[@]}"; do
  d="${dichtheden[$i]}"
  render "$WERK/launcher.svg" "${launcher[$i]}" "$RES/mipmap-$d/ic_launcher.png"
  render "$WERK/launcher.svg" "${launcher[$i]}" "$RES/mipmap-$d/ic_launcher_round.png"
  render "$WERK/foreground.svg" "${foreground[$i]}" "$RES/mipmap-$d/ic_launcher_foreground.png"
done

# Splash: elke bestaande drawable-variant op zijn eigen afmetingen opnieuw renderen.
find "$RES" -name "splash.png" | while read -r bestand; do
  b=$(sips -g pixelWidth "$bestand" | awk '/pixelWidth/ {print $2}')
  h=$(sips -g pixelHeight "$bestand" | awk '/pixelHeight/ {print $2}')
  svg="$(splash_svg "$b" "$h")"
  render "$svg" "$(( b > h ? b : h ))" "$bestand"
done

echo "Assets gegenereerd (icoon 1024, iOS-splash 2732, Android launcher/adaptive/splash)."
