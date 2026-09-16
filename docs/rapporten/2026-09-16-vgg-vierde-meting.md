# Rapport 16-09 (nacht) — VGG run 2 blok 9 vervolg: VIERDE METING ná deploy (lees-only; géén Odoo-/RLZ-writes)

Opdracht: `opdrachten/gedaan/2026-09-17-vgg-vierde-meting-na-deploy.md`. Vervolg op `2026-09-16-vgg-schrijf-b.md` (1001-model gebouwd,
niet gemeten). **Werkt in productie: ja** — het 1001-model draait op de gedeployde job-image en de sectie "1001-model" staat in het rapport.

## Stap 0 — voorwaarden

- `gcloud auth print-access-token` groen (Peter opnieuw ingelogd), project `rlz-boekhouding`.
- Deploy-runs 16-09 avond groen (laatste `a256040`, 19:51 UTC); `vgg_blok7_nameting.sh c` toetste zelf service = álle jobs (geen drift).

## Stap 1 — meting

- `scripts/gcp/vgg_blok7_nameting.sh c` → `vgg-replay --dry-run --administratie Vastgoedgroep` op de job-image, executie
  `rlz-reconciliatie-jszfj`, gestart 22:45, klaar ná ~40 min (1.096 documenten per document gelezen, 1.147 RLZ-calls, 0 webfilter-treffers,
  241,6 s gewacht door de token-bucket).
- Uitvoer: `verkenning/nameting-vgg-replay-16-09-cc.txt` (1.692 regels). Het script schrijft standaard `…-16-09.txt`, de naam van het
  bot-bestand van 05:30 UTC (stand vóór blok 9); dat bestand is ná de run uit git hersteld en de uitvoer als `-cc` bewaard.
- **Rapportregels tegen de koppen (eerste echte meting van `print_gedoseerd`, nazorg blok 8):**

| Sectie | Kop zegt | Rijen geteld |
|---|---|---|
| 1001-model | 164 | 164 |
| Niet vertaalbaar | 888 | 888 |
| Zonder pand | 7 | 7 |
| Ongemapte RLZ-rekeningen | 58 | 58 |

  Geen regel weggevallen; Cloud Logging hield het volledige rapport.

## Stap 2 — oordeel (drie standen)

**ROOD — 6 verschillen (15-09: 4).** Verwacht was ROOD uitsluitend op debiteuren/crediteuren; er zijn twee nieuwe verschillen buiten
de groepen. Volgens de regel "wijkt het af: rapporteren, niets bouwen" is er niets doorgerekend of gebouwd.

| Onderdeel | Gemeten 16-09 |
|---|---|
| 1001-model | 164 memoriaal-1001-regels: 140 gekoppeld → outstanding BNK1 (140 via `PaymentReferenceList`, 0 via bedrag + datum ± 3 d), 24 zonder bankmutatie → tussenrekening, 0 meerduidig |
| Outstanding BNK1 | bekend: 135000 Payments in transit (id 132) via de 1012-resolutie van blok 8 — het verwachte KLIKPUNT is er niet meer |
| Tussenrekeninggroep | −153.750,00 / −513.125,61 = 1001 zonder mutatie 122.165,86 / 386.451,35 + open mutaties 0,00 / −37.567,97 + afletterstand SCHRIJF c −275.915,86 / −862.008,99 (Σ sluit cent-exact) |
| Bankgroep | 120.000,00 / 399.177,22 = −122.165,86 / −386.451,35 + 0,00 / 37.567,97 + restant RLZ-opruimpunten/afletterstand 242.165,86 / 748.060,60 (Σ sluit; 15-09 zónder model: 61.166,85 / 216.201,20) |
| Crediteuren / debiteuren | −5.879.086,77 / −11.161.386,48 en 4.644.333,67 / 8.811.303,25 — ongewijzigd, ROOD tot SCHRIJF c |
| Nieuw: 3606 | RLZ 0,00 vs Odoo 986.569,81 → verschil ná RJ-220-schoning −100.000,00 per 31-12-2025 / **−363.300,00** per 16-09-2026 |
| Nieuw: 3607 | verschil −20.000,00 / −20.000,00 |
| Overig | 0 leesfouten, 0 zonder regels, 0 regelsom ≠ totaal, memoriaal uit balans 0, resultaatposten Σ 0,00, betalingsverschillen 1, geblokkeerd partner 2 (RLZ-04-00000109, RLZ-25-00000111), volledigheidstoets sluit voor alle vier de typen, btw 0 regels |

### De afwijking, mét de regels uit de 1001-tabel

De twee nieuwe verschillen vallen exact samen met twee herclassificatierijen die op 15-09 óók al in het rapport stonden, toen zonder verschil:

| Van | Naar | Bedrag | Documenten |
|---|---|---|---|
| ongemapt:1001 | 3606 | € 363.300,00 | 13 |
| ongemapt:1001 | 3607 | € 20.000,00 | 1 |

Sinds blok 9 gaat de 1001-zijde van die 14 aanbetalings-memorialen via het 1001-model naar outstanding BNK1 (132). De RJ-220-herclassificatie
en de vergelijking "geschoond voor RJ 220" rekenen dezelfde regel nog als 1001 → rol-rekening, zodat Odoo-3606 en -3607 nu tegenover RLZ
0,00 een restant houden dat precies de herclassificatie is. In de 1001-tabel staan die 14 regels niet apart gemarkeerd (0 rijen noemen
3606/3607); ze zitten tussen de 140 gekoppelde regels. De 24 regels zonder bankmutatie staan letterlijk in de tabel, o.a.:

| Boekstuk | Regel | Datum | Bedrag |
|---|---|---|---|
| RLZ-06-00000068 | 2 | 2025-11-17 | € 75.000,00 |
| RLZ-06-00000222 | 2 | 2026-06-29 | € 100.000,00 |
| RLZ-06-00000099 | 2 | 2026-01-12 | € 32.500,00 |
| RLZ-06-00000102 | 2 | 2026-01-12 | € 22.000,00 |
| RLZ-28-00000013…17 | 1 | 2025-07/08 | −20.000 / 8.100 / 12.000 / −1.000 / 9.880 |

Alle 140 koppelingen komen via `PaymentReferenceList`; de terugval op bedrag + datum ± 3 d had in deze administratie geen werk.

## Beslispunten Peter (alleen bij afwijking — default + notitie)

1. **3606/3607-schoning (default: eerst als lees-only rapportfix vóór een vijfde meting).** Hypothese: de schoning moet de
   1001-model-bestemming volgen (regel al op 132 → geen herclassificatie vanuit 1001), óf de herclassificatie hoort op de tegenzijde van de
   aanbetaling. Niet gebouwd in deze run (regel stap 2). Geen SCHRIJF c op basis van dit rapport.
2. **Restanten "afletterstand SCHRIJF c" in tussenrekening- en bankgroep** blijven verzamelcategorieën (−275.915,86 / 242.165,86 per
   31-12-2025); ze sluiten de som, maar zijn geen verklaring per mutatie. Default: accepteren als SCHRIJF-c-stand, zoals in blok 9 beschreven.

## Vastgelegd

- BESLISSINGEN "VASTGOEDGROEP NEDERLAND → ODOO — RUN 2 BLOK 9 …" → nieuwe subkop "Blok C — VIERDE METING UITGEVOERD 16-09 22:45" mét
  uitkomstentabel en "werkt in productie: ja".
- `verkenning/nameting-vgg-replay-16-09-cc.txt` gecommit; bot-bestand `-16-09.txt` ongewijzigd.
