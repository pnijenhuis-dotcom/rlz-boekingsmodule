#!/usr/bin/env bash
# Tabwissel-meting (blok 7 feedbackrun A 25-09, FV-18): start vite als die niet draait op POORT en laat
# scripts/tabwissel_meting.mjs (headless Chrome via CDP, échte klok) K × wisselen te_controleren ↔ klaar_om_te_boeken op
# een productie-achtige lijst. Standaard de reproductie-set van de opdracht: 400 én 2000 documenten, 20 wissels, plus
# 400 documenten mét 300 ms mock-latency (maakt niet-afgebroken fetches zichtbaar). Bewust NIET in overflow_sweep.sh
# (andere klok, andere vraag): dit is een regressiemeting, geen layout-sweep.
#
# Gebruik (vanuit frontend/):
#   scripts/tabwissel_meting.sh                       # drie metingen, grens 500 ms/wissel bij 400 docs (2000 docs: 2000 ms)
#   POORT=5207 DOCS="400" WISSELS=20 scripts/tabwissel_meting.sh
set -u
POORT="${POORT:-5199}"
WISSELS="${WISSELS:-20}"
BASIS="http://localhost:${POORT}"
cd "$(dirname "$0")/.."

VITE_PID=""
if ! curl -sf "${BASIS}/harness-werkvoorraad.html" >/dev/null 2>&1; then
  echo "vite draait niet op ${POORT} — start dev-server…"
  npx vite --port "$POORT" >/tmp/tabwissel_vite_${POORT}.log 2>&1 &
  VITE_PID=$!
  for _ in $(seq 1 60); do
    curl -sf "${BASIS}/harness-werkvoorraad.html" >/dev/null 2>&1 && break
    sleep 0.5
  done
fi
opruimen() { [ -n "$VITE_PID" ] && kill "$VITE_PID" 2>/dev/null; }
trap opruimen EXIT

FOUTEN=0
meet() {
  local docs="$1" latency="$2" maxms="$3"
  echo "== ${docs} documenten · ${WISSELS} wissels · latency ${latency} ms · grens ${maxms} ms =="
  node scripts/tabwissel_meting.mjs --poort="$POORT" --docs="$docs" --wissels="$WISSELS" --latency="$latency" --max-ms="$maxms" || FOUTEN=$((FOUTEN + 1))
  echo
}
if [ -n "${DOCS:-}" ]; then
  meet "$DOCS" "${LATENCY:-0}" "${MAX_MS:-500}"
else
  meet 400 0 500
  meet 2000 0 2000
  meet 400 300 500
fi
if [ "$FOUTEN" -gt 0 ]; then
  echo "Tabwissel-meting GEFAALD: ${FOUTEN} meting(en) buiten de grens of mislukt."
  exit 1
fi
echo "Tabwissel-meting groen."
