# Ontwerp — KvK-gebaseerde crediteur-dedup (uitgewerkt, GEPARKEERD)

> **Status: uitgewerkt / geparkeerd** (register: `docs/BESLISSINGEN.md`). Bouwen pas als aan
> beide voorwaarden is voldaan: (1) de KvK Basisprofiel-API is daadwerkelijk voor deze module
> beschikbaar (zie "Afhankelijkheid" onderaan) én (2) het RLZ-KvK-veld is live geverifieerd.
> Geen feature-code schrijven vóór die tijd. Dit document is de canonieke vastlegging van de
> eerder in een sessie uitgewerkte aanpak (capture na verlies — zie WERKWIJZE v1.4,
> pre-feature-ritueel).

## Aanleiding

De huidige crediteur-dedup (`backend/app/sync/service.py::maak_crediteur_aan`, vendor-GUID in
`backend/app/documenten/rlz_ids.py`) matcht uitsluitend op **genormaliseerde naam** (lowercase,
whitespace-collapse) binnen de administratie; de RLZ-vendor-GUID is
`UUIDv5(administratie + genormaliseerde naam)`. Dat is idempotent voor een dubbele klik, maar
fragiel op twee punten:

1. **Naamvarianten maken dubbele relaties.** "Bouwbedrijf Jansen B.V." vs "Jansen Bouw BV" vs
   "BOUWBEDRIJF JANSEN" zijn drie verschillende genormaliseerde namen → drie GUID's → drie
   crediteuren in RLZ voor dezelfde onderneming.
2. **De check is cache-afhankelijk.** De naam-match loopt tegen `VendorCache`; een crediteur die
   handmatig in RLZ is aangemaakt en nog niet gesynct is wordt gemist, waarna we een tweede
   PUT-ten. Het KvK-nummer is het stabiele ondernemings-anker dat naamvarianten en cache-gaten
   overleeft.

## Matchvolgorde (bij crediteur bepalen/aanmaken voor een document)

a. **KvK-match binnen de administratie wint.** Geëxtraheerd KvK-nummer aanwezig én een
   `VendorCache`-rij met hetzelfde KvK-nummer → die crediteur gebruiken, ongeacht naamverschil.
b. **Naam-fallback** (huidige genormaliseerde-naam-match) blijft bestaan maar is expliciet de
   zwakkere route: treffer wordt als naam-match gemarkeerd (zichtbaar voor de controleur), niet
   stilzwijgend gelijkgesteld aan een KvK-match.
c. **Geen cache-treffer → live RLZ-check vóór de PUT.** Query op RLZ zelf (op KvK-veld; anders op
   naam) om een niet-gesyncte, handmatig aangemaakte vendor te vinden. Bestaat die → **de
   bestaande RLZ-vendor adopteren** (id overnemen in de cache) in plaats van een tweede aan te
   maken. Pas als ook RLZ niets heeft, volgt de PUT.

## Extractie

- `kvk_nummer` wordt een **gestructureerd kopveld** in de extractie, expliciet **buiten het
  BSN-filter** (zelfde patroon als IBAN: gestructureerd veld, geen vrije tekst-lek).
- Validatie: **8-cijfer formaatcheck, géén elfproef** — KvK-nummers hebben geen betrouwbare
  checksum; een elfproef zou geldige nummers afkeuren.
- **Vestigingsnummer (12 cijfers) → ondernemingsnummer (8 cijfers) normaliseren**: facturen
  vermelden soms het vestigingsnummer; dedup ankert op de onderneming.
- KvK-nummer reist in request-**bodies**, nooit in URL's (zelfde regel als IBAN; geen
  identificerende nummers in logs/access-logs via de querystring).

## Opslag

- Nieuwe kolom `kvk_nummer` op `boekhouding.vendor_cache` + index op
  `(administratie_id, kvk_nummer)`.
- De sync vult de kolom uit het RLZ-Vendor-veld. **Exacte RLZ-veldnaam nog verifiëren** via
  `Help/ResourceModel` + live respons (RLZ heeft het veld zeker; de al gesyncte `brondata`
  bevat het) — niet gokken, eerst verifiëren (zelfde les als de AccountTypeEnum-verificatie).
- **Backfill uit `brondata`**: de kolom is voor bestaande rijen te vullen zonder her-sync, omdat
  `VendorCache.brondata` (JSONB) de volledige RLZ-respons al bewaart.

## Aanmaken (nieuwe crediteur)

- KvK-nummer opslaan bij aanmaak.
- **Naam normaliseren via KvK Basisprofiel**: de officiële handelsnaam overnemen als
  crediteurnaam, zichtbaar voor de gebruiker (geen stille substitutie). Materiële afwijking
  tussen factuurnaam en KvK-handelsnaam → **eerst laten bevestigen** door de mens, dan pas
  aanmaken.
- **KvK-API down → nooit blokkeren.** Degraderen naar het huidige gedrag (naam zoals
  geëxtraheerd/ingevoerd) + zichtbare marker "KvK niet geverifieerd"; verificatie kan later
  alsnog.
- De **vendor-GUID blijft op naam bevroren** (`rlz_ids.py`-recept ongewijzigd): bestaande GUID's
  blijven geldig, KvK is een extra matchlaag — geen migratie van bestaande vendor-id's.

## Duplicaat-signalering (bestaande dubbelen)

- Endpoint + weergave die per crediteur de **bestaande crediteuren met hetzelfde KvK-nummer**
  binnen de administratie toont (lijst, geen actieknop op RLZ-data).
- **NOOIT automatisch samenvoegen of verwijderen in RLZ** — kernprincipe 3 (niets verwijderen in
  externe systemen); samenvoegen/opschonen is een menselijke actie in RLZ zelf. Wij signaleren
  alleen.

## Guardrails

- **Buitenlandse en KvK-loze leveranciers nooit blokkeren**: geen KvK-nummer is een normale
  situatie (buitenlandse crediteur, particulier, eenmalige leverancier), geen fout. Alle
  KvK-logica is additief; de naam-route blijft volledig functioneren.
- Crediteur-aanmaken blijft achter de bestaande **schrijf-failsafe** (zelfde poort als boeken —
  zie `sync/router.py`); de KvK-laag verandert daar niets aan.

## Afhankelijkheid: KvK Basisprofiel-connector

De KvK Basisprofiel-client bestaat vandaag alleen in de vastgoedmodule
(`layer2_integraties/kvk.py`; `Platform/registers/koppelingen.md`). Afspraak (OPEN_ITEMS,
akkoord RLZ 2026-07-09): **rule of two** — zodra een tweede project (deze module) de bron nodig
heeft, verhuist de connector naar een gedeelde platform-connector. Dat is een
**platform-interfacewijziging**: formeel besluit met akkoord van beide projecten + versienummer
(besluit 0006-procedure), geen stille refactor. Tot die tijd is deze feature geparkeerd; dit
ontwerp is er om bij deblokkering direct te kunnen bouwen zonder her-uitvragen.
