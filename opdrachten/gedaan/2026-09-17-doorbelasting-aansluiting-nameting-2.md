> uitgevoerd 2026-09-17 (via nameting-workflow run 35212801971, bot 08685c6; herkoppeling werkt in productie: ja; aansluiting 928 sluit / 59 ontbreekt / 2 bedrag / 166 inkoop zonder verkoop — beslispunten), rapport: docs/rapporten/2026-09-17-doorbelasting-aansluiting-nameting-2.md

# OPDRACHT 17-09 — Doorbelasting-aansluiting Kempen Facilities: productienameting via de nameting-workflow (lees-only; géén writes)

Vervolg op `opdrachten/gedaan/2026-09-17-doorbelasting-aansluiting-nameting.md` (rapport
`docs/rapporten/2026-09-17-doorbelasting-aansluiting-nameting.md`): stap 0 strandde op de verlopen gcloud-gebruikerssessie. De meting
staat nu als dispatch-onderdeel `doorbelasting-aansluiting` in `.github/workflows/nameting.yml` (WIF als `nameting@`, geen lokale gcloud nodig).

## Stap 0 — voorwaarden (stoppen mét melding als één ontbreekt)
- De deploy van de commit die `nameting.yml` uitbreidde is groen, óf alleen rood op de stap "OTA-webbundel …" (bucket-klikpunt Peter) mét
  stappen 8 en 9 groen (`gh run view <id> --json jobs`). De workflow-file staat op `main` (`gh workflow view nameting` toont het onderdeel).
- `gh auth status` groen.

## Stap 1 — meting (lees-only)
- `gh workflow run nameting -f onderdeel=doorbelasting-aansluiting` → `gh run watch <id>` (≤ 15 min). De nameting-bot commit
  `verkenning/nameting-doorbelasting-aansluiting-<dd-mm>.txt` naar main → `git pull --ff-only origin main` (werkboom moet schoon zijn) en lees
  het bestand: CLI-tabellen (exit 3 = webfilter → meting ongeldig, niet doorrekenen) + Cloud-Logging-regels "herkoppeling doelentiteiten:
  open=… gekoppeld=…" van `rlz-sync` — verwacht: Kempen Chalets GEKOPPELD (exact), Mantelzorgwoning al gekoppeld (01-09), overige `geen`/al gekoppeld.
- Werkt gcloud lokaal inmiddels wél (`gcloud auth print-access-token`): het oorspronkelijke recept `scripts/gcp/nameting.sh
  doorbelasting-aansluiting --bron "Kempen Facilities" --jaar 2026` mag óók, zelfde uitvoer.

## Stap 2 — oordeel
- Verwachting Peter: alles sluit. Elke rij in "Ontbreekt in doel" / "Bedrag afwijkt" / "Doel niet in module" / "Inkoop zonder verkoop" letterlijk
  in het rapport mét boekstuknummer; open spiegel-taken (aantal + bedrag). Niets bouwen bij een afwijking — rapporteren; beslispunt alleen als een
  categorie structureel is (bv. Zenvoices-facturen zonder verkoop bij de bron).

## Afronding
- BESLISSINGEN "DOORBELASTING — AANSLUITING KF ↔ DOELENTITEITEN + HERKOPPELING (Peter 12-09/16-09)": alinea "Nameting 17-09" → uitkomst +
  "werkt in productie: ja/nee"; rapport `docs/rapporten/2026-09-1x-doorbelasting-aansluiting-nameting-2.md` + INDEX.
