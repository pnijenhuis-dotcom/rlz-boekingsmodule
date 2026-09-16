# OPDRACHT 17-09 — Doorbelasting-aansluiting Kempen Facilities: productienameting ná deploy (lees-only; géén writes)

Vervolg op `opdrachten/gedaan/2026-09-16-doorbelasting-aansluiting-kf-en-herkoppeling.md` (rapport
`docs/rapporten/2026-09-16-doorbelasting-aansluiting.md`): de code staat, productie is niet gemeten.

## Stap 0 — voorwaarden (stoppen mét melding als één ontbreekt)
- `gcloud auth print-access-token` werkt; deploy van de commits van 16-09 nacht groen; service én álle jobs op hetzelfde beeld.

## Stap 1 — meting (lees-only)
- `scripts/gcp/nameting.sh doorbelasting-aansluiting --bron "Kempen Facilities" --jaar 2026` → uitvoer bewaren als
  `verkenning/nameting-doorbelasting-aansluiting-<dd>-09.txt`; exit 3 = webfilter → meting ongeldig, niet doorrekenen.
- Cloud Logging van de eerste `sync-alles` ná deploy (job rlz-sync): regel "herkoppeling doelentiteiten: open=… gekoppeld=…" —
  verwacht: Kempen Chalets GEKOPPELD (exact), Mantelzorgwoning al gekoppeld (01-09), overige rijen `geen` of al gekoppeld.

## Stap 2 — oordeel
- Verwachting Peter: alles sluit. Elke rij in "Ontbreekt in doel" / "Bedrag afwijkt" / "Doel niet in module" / "Inkoop zonder
  verkoop" letterlijk in het rapport mét boekstuknummer; open spiegel-taken (aantal + bedrag). Niets bouwen bij een afwijking —
  rapporteren; beslispunt alleen als een categorie structureel is (bv. Zenvoices-facturen zonder verkoop bij de bron).

## Afronding
- BESLISSINGEN "DOORBELASTING — AANSLUITING KF ↔ DOELENTITEITEN + HERKOPPELING (Peter 12-09/16-09)": rij blok 3 → uitkomst +
  "werkt in productie: ja/nee"; rapport `docs/rapporten/2026-09-1x-doorbelasting-aansluiting-nameting.md` + INDEX.
