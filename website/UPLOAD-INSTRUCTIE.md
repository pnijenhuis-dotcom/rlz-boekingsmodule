# Upload-instructie website administratiekantoornijenhuis.nl (TransIP)

Voor Peter — stap voor stap, via TransIP → Bestandsbeheer van de webhosting.
Datum: 2026-08-18. De site is volledig statisch (geen PHP, geen database, geen JavaScript).

## Wat zit er in deze map

| Bestand/map | Wat het is |
|---|---|
| `index.html` | homepage |
| `privacy.html` | privacyverklaring (versie 18-08-2026) |
| `gegevensverwerking.html` | gegevensverwerking & verwerkers (versie 18-08-2026) |
| `stijl.css` | alle vormgeving |
| `assets/` | logo (`logo.png`) + social-media-voorbeeld (`og-beeld.png`) |
| `favicon.svg`, `favicon-32.png`, `apple-touch-icon.png` | het N-beeldmerk als site-icoon |
| `robots.txt`, `sitemap.xml` | zoekmachine-netheid |
| `.well-known/apple-app-site-association` | **kopie-vangnet** voor de app-koppeling — zie hieronder |
| `UPLOAD-INSTRUCTIE.md` | dit bestand (hoeft niet mee, meesturen is onschadelijk) |

## ⚠️ Eerst dit: de map `.well-known` is heilig

Op de hosting staat `/.well-known/apple-app-site-association` — dat bestand koppelt de
goedkeur-app (passkeys/Face ID) aan het domein. **Verwijder of overschrijf de map
`.well-known` op de hosting nooit.** Zet in Bestandsbeheer eerst *verborgen bestanden
tonen* aan (bestanden die met een punt beginnen zijn anders onzichtbaar), zodat je 'm ziet
en er niet per ongeluk overheen werkt.

Deze uploadmap bevat een kopie van hetzelfde bestand als vangnet: als je de héle mapinhoud
uploadt, blijft `.well-known` dus sowieso gevuld met de juiste inhoud. De kopie is
byte-gelijk aan wat er hoort te staan (`{"webcredentials":{"apps":["VRQP26CX43.nl.aknijenhuis.goedkeuren"]}}`).

**Controle na élke wijziging op de hosting:** open
`https://administratiekantoornijenhuis.nl/.well-known/apple-app-site-association`
in de browser → je moet exact die ene JSON-regel zien (geen foutpagina, geen HTML).

## Stap 1 — Veiligste route: eerst preview in een submap (aanbevolen)

1. Log in op TransIP → webhosting `administratiekantoornijenhuis.nl` → Bestandsbeheer.
2. Ga naar de webroot (de map waar ook `wp-content` en `index.php` staan — meestal `www`).
3. Maak daar een nieuwe map `nieuw`.
4. Upload **alle bestanden en mappen uit deze uploadmap** in `nieuw/`
   (de `.well-known`-kopie mag je bij deze previewstap weglaten — die hoort alleen in de webroot).
5. Bekijk `https://administratiekantoornijenhuis.nl/nieuw/` — alle drie de pagina's, ook op
   je telefoon. WordPress blijft intussen gewoon de hoofdsite; er is niets kapot te maken.

De interne links zijn relatief, dus de site werkt in een submap én in de webroot identiek.

## Stap 2 — Live zetten (als de preview goed is)

1. Upload dezelfde bestanden nu **in de webroot zelf** (naast de wp-mappen):
   `index.html`, `privacy.html`, `gegevensverwerking.html`, `stijl.css`, `robots.txt`,
   `sitemap.xml`, `favicon.svg`, `favicon-32.png`, `apple-touch-icon.png` en de map `assets/`.
   Laat de map `nieuw/` gerust nog even staan (of ruim 'm op — maakt niet uit).
2. **Laat alle WordPress-bestanden staan** (`wp-admin/`, `wp-content/`, `wp-includes/`,
   `wp-*.php`, `index.php`, `.htaccess`). Niets verwijderen in deze stap.
3. Open de homepage in een privé-/incognitovenster. Twee mogelijke uitkomsten:
   - **Je ziet de nieuwe site** → de server geeft `index.html` voorrang op `index.php`. Klaar;
     WordPress draait nog wel, maar is onzichtbaar. Opruimen = stap 3, later, bewust.
   - **Je ziet nog WordPress** → de server geeft `index.php` voorrang. Dan is stap 3 nodig om
     de nieuwe site zichtbaar te maken. De losse pagina's
     (`/privacy.html`, `/gegevensverwerking.html`) werken in beide gevallen al wél direct.
4. Controleer de `.well-known`-URL (zie boven) en `/privacy.html` + `/gegevensverwerking.html`.

## Stap 3 — WordPress uitzetten: een aparte, bewuste stap

Doe dit pas als je een paar dagen tevreden bent met de nieuwe site. **Eerst een backup**:
download via Bestandsbeheer de wp-mappen (of gebruik de TransIP-backupfunctie) en maak in
phpMyAdmin een export van de WordPress-database.

De lichtste vorm (omkeerbaar, niets weg):

1. Hernoem in de webroot `index.php` → `index.php.uit` — de server valt dan terug op
   `index.html` en de nieuwe site is de voorpagina. Terugdraaien = terug hernoemen.
2. Open `.htaccess` (verborgen bestand). Het blok tussen `# BEGIN WordPress` en
   `# END WordPress` stuurt onbekende URL's naar WordPress. Bestaande bestanden (onze
   pagina's) raakt dat niet, maar oude WordPress-URL's tonen dan een kapotte site. Wil je
   dat die netjes op onze homepage uitkomen: vervang het WordPress-blok door niets (na
   backup van het bestand) — onbekende URL's geven dan de standaard 404 van de hosting.

Definitief verwijderen (weken later, optioneel): `wp-admin/`, `wp-content/`,
`wp-includes/` en alle `wp-*.php` verwijderen + het WordPress-blok uit `.htaccess`. De map
`.well-known` en onze bestanden **laten staan**. Daarna kan ook de MySQL-database bij
TransIP worden opgezegd. Alleen doen mét backup en als je zeker bent — er is geen haast.

## Wat deze upload NIET raakt

- **E-mail**: MX-records/mail staan los van de webhosting-bestanden — niets verandert.
- **De app** (`app.administratiekantoornijenhuis.nl`): eigen subdomein naar Cloud Run —
  niets verandert, zolang `.well-known` op de apex intact blijft (daarom het vangnet).
- **DNS**: er verhuist niets. (Cloudflare of een andere DNS-/CDN-verhuizing is bewust
  afgewezen: het risico voor mail, app-subdomein en de app-koppeling weegt niet op tegen
  de winst voor een simpele statische site — zie docs/BESLISSINGEN.md.)

## Teksten bijwerken (later)

De privacy- en verwerkingsteksten zijn afgeleid uit `docs/avg/` (stand 18-08-2026). Wijzigt
daar iets wezenlijks (bijv. ZDR-uitkomst Anthropic, nieuwe verwerker), dan werken we de
pagina's in `website/` bij, verhogen de versiedatum bovenaan de pagina én in `sitemap.xml`,
en upload je alleen de gewijzigde bestanden opnieuw.
