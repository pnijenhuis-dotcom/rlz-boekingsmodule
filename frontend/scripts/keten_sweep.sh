#!/usr/bin/env bash
# Gouden-set-sweep frontend (blok 0 herstelrun "Basis eerst" 08-09-2026; patroon overflow_sweep.sh): rendert per
# casus het echte controlescherm én de echte documentenlijst met de DTO's die de backend-ketentests exporteren
# (src/dev/keten/<casus>.json), schiet met headless Chrome een screenshot en vergelijkt die pixel-tolerant met de
# baseline in scripts/keten_baseline/ (scripts/keten_compare.mjs, geen npm-dependency).
#
# Gebruik (vanuit frontend/):
#   scripts/keten_sweep.sh                      # start zelf vite op poort 5199 als die niet draait
#   KETEN_UPDATE_BASELINE=1 scripts/keten_sweep.sh   # ververst de baseline (bewust, na een gewilde UI-wijziging)
# De eerste run zonder baseline maakt 'm aan (en meldt dat). Extra: de badge/marker in het harnas moet "klaar"
# zeggen (data geladen) — anders is de screenshot geen bewijs.
set -u

POORT="${POORT:-5199}"
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
BASIS="http://localhost:${POORT}"
BREEDTE="${KETEN_BREEDTE:-1440}"
HOOGTE="${KETEN_HOOGTE:-1800}"
CASUSSEN=(a_universal_nederland b_floor c_spot_services h_bdo m_incasso_factuur)
SCHERMEN=(detail lijst)

if [ ! -x "$CHROME" ]; then
  echo "Chrome niet gevonden op: $CHROME (zet CHROME=...)" >&2
  exit 2
fi

cd "$(dirname "$0")/.."
BASELINE_DIR="scripts/keten_baseline"
UIT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/keten_sweep.XXXXXX")"
mkdir -p "$BASELINE_DIR"

for casus in "${CASUSSEN[@]}"; do
  if [ ! -f "src/dev/keten/${casus}.json" ]; then
    echo "❓ fixture ontbreekt: src/dev/keten/${casus}.json — draai eerst de backend-ketentests (tests/keten)" >&2
    exit 2
  fi
done

# Blok 5 (10-09 avond): de fixtures zijn bevroren op de referentiedag van de gouden set (2026-09-08, zie
# backend/tests/keten/conftest.py REFERENTIE_TIJDSTIP). Draagt een fixture de datum van vandaag, dan drijft er een veld
# met de kalender mee en is de screenshot geen bewijs — zelfde toets als tests/keten/test_export_deterministisch.py,
# met dezelfde eerlijke blinde vlek: op de referentiedag zelf is de toets niet onderscheidend en wordt hij overgeslagen.
REFERENTIE_DAG="2026-09-08"
VANDAAG="$(date +%F)"
if [ "$VANDAAG" != "$REFERENTIE_DAG" ]; then
  if drift=$(grep -n -- "$VANDAAG" src/dev/keten/*.json); then
    echo "❌ fixture drijft met de kalender mee (datum van vandaag ${VANDAAG} in de export) — bevries de bron in" >&2
    echo "   backend/tests/keten/conftest.py (_bevries_ontvangst) en exporteer opnieuw:" >&2
    echo "$drift" | sed 's/^/   /' >&2
    exit 2
  fi
else
  echo "ℹ️  vandaag is de referentiedag (${REFERENTIE_DAG}) — kalender-drift-toets niet onderscheidend, overgeslagen"
fi

VITE_PID=""
if ! curl -sf "${BASIS}/harness-keten.html" >/dev/null 2>&1; then
  echo "vite draait niet op ${POORT} — start dev-server…"
  npx vite --port "$POORT" >"${UIT_DIR}/vite.log" 2>&1 &
  VITE_PID=$!
  for _ in $(seq 1 40); do
    curl -sf "${BASIS}/harness-keten.html" >/dev/null 2>&1 && break
    sleep 0.5
  done
fi
opruimen() { [ -n "$VITE_PID" ] && kill "$VITE_PID" 2>/dev/null; }
trap opruimen EXIT

FOUTEN=0
METINGEN=0
NIEUW=0
for casus in "${CASUSSEN[@]}"; do
  for scherm in "${SCHERMEN[@]}"; do
    naam="${casus}__${scherm}"
    url="${BASIS}/harness-keten.html?casus=${casus}&scherm=${scherm}"
    METINGEN=$((METINGEN + 1))
    shot="${UIT_DIR}/${naam}.png"
    dom=$("$CHROME" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=1 \
      --window-size="${BREEDTE},${HOOGTE}" --virtual-time-budget=8000 \
      --screenshot="$shot" --dump-dom "$url" 2>/dev/null)
    if ! echo "$dom" | grep -q 'data-keten-klaar="ja"'; then
      FOUTEN=$((FOUTEN + 1))
      echo "❓ ${naam} — harnas niet klaar (data niet geladen / render mislukt; zie ${UIT_DIR}/vite.log)"
      echo "$dom" | grep -o 'data-keten-onbekend="[^"]*"' | head -1 | sed 's/^/   /'
      continue
    fi
    if echo "$dom" | grep -q 'OVERFLOW —'; then
      FOUTEN=$((FOUTEN + 1))
      echo "❌ ${naam} — horizontale overflow"
      continue
    fi
    baseline="${BASELINE_DIR}/${naam}.png"
    if [ ! -f "$baseline" ] || [ "${KETEN_UPDATE_BASELINE:-}" = "1" ]; then
      cp "$shot" "$baseline"
      NIEUW=$((NIEUW + 1))
      echo "🆕 ${naam} — baseline gezet (${baseline})"
      continue
    fi
    if uitkomst=$(node scripts/keten_compare.mjs "$baseline" "$shot"); then
      echo "✅ ${naam} — ${uitkomst}"
    else
      FOUTEN=$((FOUTEN + 1))
      echo "❌ ${naam} — ${uitkomst}"
      echo "   nieuw: ${shot} · baseline: ${baseline} (gewilde wijziging? KETEN_UPDATE_BASELINE=1)"
    fi
  done
done

echo
if [ "$FOUTEN" -gt 0 ]; then
  echo "Keten-sweep GEFAALD: ${FOUTEN}/${METINGEN} metingen afwijkend of niet gerenderd. Screenshots: ${UIT_DIR}"
  exit 1
fi
echo "Keten-sweep groen: ${METINGEN} metingen (${NIEUW} nieuwe baselines). Screenshots: ${UIT_DIR}"
