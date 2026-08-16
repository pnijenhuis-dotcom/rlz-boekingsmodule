#!/usr/bin/env bash
# Overflow-sweep (nazorg designsysteem 2026-08-16, patroon overgenomen van de
# vastgoed-mobiele-sweep): géén horizontale pagina-overflow op 1440/1170/1024/768, in licht
# én donker, over alle visuele harnassen. Leunt op de OverflowBadge (src/dev/overflowBadge.tsx):
# headless Chrome dumpt de DOM en dit script asserteert dat de badge "past" zegt — bij
# "OVERFLOW" benoemt de badge zelf de diepste boosdoeners, die printen we mee.
#
# Gebruik (vanuit frontend/):
#   scripts/overflow_sweep.sh                  # start zelf vite op poort 5199 als die niet draait
#   SCREENSHOT_DIR=/pad scripts/overflow_sweep.sh   # legt per meting ook een screenshot vast
set -u

POORT="${POORT:-5199}"
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
BASIS="http://localhost:${POORT}"
HARNASSEN=(harness.html harness-werkvoorraad.html "harness-werkvoorraad.html?klant=1" harness-gebruikers.html harness-instellingen.html)
BREEDTES=(1440 1170 1024 768)

if [ ! -x "$CHROME" ]; then
  echo "Chrome niet gevonden op: $CHROME (zet CHROME=...)" >&2
  exit 2
fi

cd "$(dirname "$0")/.."

VITE_PID=""
if ! curl -sf "${BASIS}/harness.html" >/dev/null 2>&1; then
  echo "vite draait niet op ${POORT} — start dev-server…"
  npx vite --port "$POORT" >/tmp/overflow_sweep_vite.log 2>&1 &
  VITE_PID=$!
  for _ in $(seq 1 40); do
    curl -sf "${BASIS}/harness.html" >/dev/null 2>&1 && break
    sleep 0.5
  done
fi
opruimen() { [ -n "$VITE_PID" ] && kill "$VITE_PID" 2>/dev/null; }
trap opruimen EXIT

FOUTEN=0
METINGEN=0
for harnas in "${HARNASSEN[@]}"; do
  for donker in "" 1; do
    for breedte in "${BREEDTES[@]}"; do
      if [[ "$harnas" == *\?* ]]; then url="${BASIS}/${harnas}&"; else url="${BASIS}/${harnas}?"; fi
      [ -n "$donker" ] && url="${url}donker=1"
      url="${url%\?}"; url="${url%&}"
      label="${harnas} $( [ -n "$donker" ] && echo donker || echo licht ) ${breedte}px"
      METINGEN=$((METINGEN + 1))

      extra=()
      if [ -n "${SCREENSHOT_DIR:-}" ]; then
        mkdir -p "$SCREENSHOT_DIR"
        naam=$(echo "$label" | tr ' /?=' '____')
        extra=(--screenshot="${SCREENSHOT_DIR}/${naam}.png")
      fi
      # ${extra[@]+…}: macOS bash 3.2 ziet een lege array onder set -u als unbound.
      dom=$("$CHROME" --headless=new --disable-gpu --hide-scrollbars \
        --window-size="${breedte},1600" --virtual-time-budget=5000 \
        ${extra[@]+"${extra[@]}"} --dump-dom "$url" 2>/dev/null)

      if echo "$dom" | grep -q 'OVERFLOW —'; then
        FOUTEN=$((FOUTEN + 1))
        echo "❌ ${label}"
        # De badge somt de boosdoeners op als "→ element [links..rechts]" — print die mee.
        echo "$dom" | grep -o 'OVERFLOW — scrollWidth [0-9]* / viewport [0-9]*' | head -1 | sed 's/^/   /'
        echo "$dom" | grep -o '→ [^<]*' | head -8 | sed 's/^/   /'
      elif echo "$dom" | grep -q 'past —'; then
        echo "✅ ${label}"
      else
        FOUTEN=$((FOUTEN + 1))
        echo "❓ ${label} — badge niet gevonden (render mislukt? zie /tmp/overflow_sweep_vite.log)"
      fi
    done
  done
done

echo
if [ "$FOUTEN" -gt 0 ]; then
  echo "Sweep GEFAALD: ${FOUTEN}/${METINGEN} metingen met overflow of renderfout."
  exit 1
fi
echo "Sweep groen: ${METINGEN} metingen zonder horizontale pagina-overflow."
