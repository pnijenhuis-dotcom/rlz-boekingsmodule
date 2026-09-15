# Btw verlegd herkennen zonder het woord "verlegd" — kolomcode "V" en verlegd-leverancier (Peter 15-09, casus Olieman 32948)

**In gewone taal:** Een bouwleverancier zette alleen een "V" in de btw-kolom en rekende 0 % btw; nergens stond "verlegd", dus de
module liet het btw-veld leeg en Peter vulde het zelf. Nu herkent de module die kolomcode, en herkent ze een leverancier die
eerder met btw verlegd is geboekt of volgens de KvK een bouwbedrijf is, en zet ze het verlegd-tarief alvast voor (oranje, met de
reden erbij); een gewone vrijgestelde factuur blijft leeg.

**Werkt in productie:** niet gemeten (deploy volgt op de Stop-hook; meetlat hieronder). STAP-0 op de projectvraag is wél lees-only
op productie gedaan.

## Gebouwd

| Punt | Wat | Waar |
|---|---|---|
| 1a | AI leest per regel de btw-kolomtekst letterlijk voor (regel-key `bc`, sentinel-string, geen union) | `app/extractie/service.py` |
| 1b | Kolomcode deterministisch: `is_verlegd_kolomcode` ("V", "VL", "verl.", "btw verlegd", "reverse charge"; "0%"/"vrij"/"H" nooit) + `verlegd_kolomcode_voor_factuur` (alle regels mét bedrag) → veldvoorstel `btw_verlegd_kolom` + per regel `btw_kolom`/`btw_kolom_verlegd`; `_factuur_is_verlegd` = (vermelding óf kolomcode) én btw 0 | `app/extractie/controle.py`, `app/documenten/boekvoorstel.py` |
| 1c | `bepaal_verlegd_basis`: vermelding → kolomcode → leverancier-geheugen (eerdere boekingen op een verlegd-tarief, `regel_prefill.leverancier_verlegd_boekingen`) → KvK-SBI 41/42/43 (`kvk.verwerk_basisprofiel` levert `sbi_codes`, `kvk.is_bouw_sbi`; alleen mét échte KvK-configuratie, fout = None) — telkens én btw 0; chip-detail 'kolomcode "V" op alle regels · <tariefherkomst>' enz. | `app/documenten/boekvoorstel.py`, `app/documenten/regel_prefill.py`, `app/integraties/kvk.py` |
| 2 | Vrijgesteld/0 % zonder basis blijft leeg — negatieve gouden-set-casus (telecom, kolom "vrij") | casus z |
| 3 | Project uit "Betreft: werk Uitweg 30 Woerdense Verlaat": STAP-0 lees-only `rlz-lezen --pad Projects` op Bouwadvies Oost Nederland B.V. → **0 projecten in RLZ**; er is niets om tegen te matchen en de motor vult nooit zonder kandidaat. Geen bouw nodig; kop-omschrijving en grootboek-uit-geheugen zijn bestaand. | rapport |
| 4 | Gouden-set-casus z `tests/keten/fixtures/z_verlegd_kolomcode_v/` (geanonimiseerd, kolom "V" behouden) + varianten tweede termijn / vrijgesteld | `tests/keten/test_z_verlegd_kolomcode.py` |

## Tests

`tests/extractie/test_verlegd_kolomcode.py` (26), `tests/documenten/test_verlegd_basis.py` (7), casus z (3); tests/extractie +
boekvoorstel + verlegd-keuze + casussen c/f/w + export-deterministisch + keten-guard + schema-unionlimiet: 323 groen. Frontend
ongewijzigd (chip-detail is bestaand veld); WAT_IS_NIEUW-blok.

## Meetlat ná deploy (Peter)

Bij de tweede Olieman-termijn (zelfde leverancier, 0 %): btw-veld gevuld met het verlegd-tarief (chip "uit factuur verlegd" mét
"leverancier eerder verlegd geboekt (1×)" of 'kolomcode "V"'), grootboek uit het geheugen, kop-omschrijving gevuld — alleen "Boeken"
nodig. Project blijft leeg tot Bouwadvies Oost Nederland een project in RLZ heeft.

## Beslispunten (default gekozen)

- "Administratie is btw-plichtig ondernemer": geen eigen vlag; de poort is het bestaan van een verlegd-tarief in de administratie
  (anders kiest `bepaal_verlegd_taxrate` niets). Default: zo laten.
- KvK-lookup in de prefill: één externe call per document, alleen als terugval (geen vermelding/kolomcode/geheugen), alleen bij een
  leverancier mét KvK-nummer en échte KvK-configuratie; uitval = stil leeg btw-veld (zoals vóór 15-09). Default: geen chip.
