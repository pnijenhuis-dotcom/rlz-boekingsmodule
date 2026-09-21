# Regels per domein — index (Peter 17-09)

Élk domein heeft één regelsbestand mét de volledige, woordelijke CLAUDE.md-tekst en een LEESPLICHT. De kolom code-paden koppelt
élk pakket onder `backend/app/` en élke map onder `frontend/src/` (plus scripts/native/docs) aan precies één domein — de
guard `backend/tests/unit/test_regels_index.py` eist dat élk pakket/élke map hier staat en dat élke LEESPLICHT-verwijzing in
CLAUDE.md naar een bestaand bestand wijst. Een opdracht in `opdrachten/inbox/` draagt de kopregel `Domeinen: a, b`; ontbreekt die,
dan leidt CC de domeinen af uit de geraakte paden via deze tabel en noemt dat expliciet in het rapport (sectie "Gelezen regels").

| Domein | Bestand | Code-paden |
|---|---|---|
| Werkvoorraad, documentenlijst en controlescherm | `docs/regels/werkvoorraad-controlescherm.md` | `backend/app/werkvoorraad/**`, `backend/app/documenten/**`, `backend/app/geheugen/**`, `backend/app/vragen/**`, `backend/app/zoeken/**`, `backend/app/tijd.py`, `frontend/src/werkvoorraad/**`, `frontend/src/document/**`, `frontend/src/vragen/**`, `frontend/src/zoeken/**`, `frontend/src/api/**` |
| Kantoor-frontend: IA, designpass, componenten, changelog | `docs/regels/kantoor-frontend.md` | `frontend/src/shell/**`, `frontend/src/ui/**`, `frontend/src/styles/**`, `frontend/src/changelog/**`, `frontend/src/dev/**`, `frontend/src/*.tsx`, `frontend/src/*.ts`, `frontend/src/*.css`, `mockup/**` |
| Administraties, RLZ-/Odoo-koppelingen, sync en instellingen | `docs/regels/administraties-instellingen.md` | `backend/app/beheer/**`, `backend/app/groepen/**`, `backend/app/sync/**`, `backend/app/rlz/**`, `backend/app/odoo/**`, `backend/app/backends/**`, `backend/app/integraties/**`, `backend/app/registersync/**`, `backend/app/credentialstore/**`, `backend/app/terugkerend/**`, `frontend/src/instellingen/**`, `frontend/src/terugkerend/**` |
| Auth, rollen, scope, RLS, app-auth en gebruikersbeheer | `docs/regels/auth-toegang.md` | `backend/app/auth/**`, `backend/app/security/**`, `backend/app/berichten/**`, `frontend/src/auth/**`, `frontend/src/gebruikers/**` |
| Btw: codes, defaults, verlegd, buitenland | `docs/regels/btw.md` | `backend/app/extractie/controle.py` |
| Duplicaten en crediteuren | `docs/regels/duplicaten-crediteuren.md` | `backend/app/crediteuren/**`, `frontend/src/crediteuren/**` |
| E-mail-intake, verzamelbak, splitsing en AI-extractie | `docs/regels/intake-extractie.md` | `backend/app/intake/**`, `backend/app/extractie/**`, `backend/app/aikosten/**`, `frontend/src/intake/**` |
| Automatisch boeken, autoboek-kandidaten en de AI-plausibiliteitstoets | `docs/regels/autoboeken-ai.md` | `backend/app/autoboek_kandidaten/**`, `backend/app/aitoets/**` |
| Reconciliatie, bewaking en meldingen | `docs/regels/reconciliatie.md` | `backend/app/reconciliatie/**`, `backend/app/bewaking/**`, `frontend/src/reconciliatie/**` |
| Verplichtingen/offertes, projecten, projectverdeling, contract-ontleding en voorraad | `docs/regels/verplichtingen-projecten-voorraad.md` | `backend/app/verplichting/**`, `backend/app/projecten/**`, `backend/app/projectverdeling/**`, `backend/app/mini_voorraad/**`, `backend/app/voorraad/**`, `frontend/src/verplichting/**`, `frontend/src/projecten/**`, `frontend/src/projectverdeling/**`, `frontend/src/voorraad/**` |
| Uren & meerwerk, planning, werkopdrachten, veldwerkers | `docs/regels/uren-planning-veldwerkers.md` | `backend/app/uren/**`, `backend/app/materiaal/**`, `frontend/src/uren/**`, `frontend/src/meerwerk/**`, `frontend/src/planning/**`, `frontend/src/veldwerkers/**`, `frontend/src/materiaal/**` |
| Omzetboekingen, omzetbronnen en het verkoopfactuur-boekpad | `docs/regels/omzet.md` | `backend/app/omzet/**`, `backend/app/verkoop/**`, `backend/app/waarborg/**`, `frontend/src/omzet/**`, `frontend/src/verkoop/**`, `frontend/src/waarborg/**` |
| Bank: sync, matchmotor, afletteren, splitsen, batches | `docs/regels/bank.md` | `backend/app/bank/**`, `frontend/src/bank/**` |
| Kempen-doorbelasting en intercompany | `docs/regels/doorbelasting-intercompany.md` | `backend/app/doorbelasting/**`, `backend/app/intercompany/**`, `frontend/src/doorbelasting/**` |
| Klant-accordering, accordeur-/veldwerker-app, native store-apps en OTA | `docs/regels/accordering-native-app.md` | `backend/app/accordering/**`, `backend/app/afdelingen/**`, `backend/app/appupdate/**`, `frontend/src/accordering/**`, `frontend/src/accordeur/**`, `frontend/src/afdelingen/**`, `native/**` |
| Vastgoedgroep Nederland → Odoo (run 1 + run 2) en het pandenregister | `docs/regels/vgg-odoo-migratie.md` | `backend/app/migratie/**`, `backend/app/panden/**`, `scripts/gcp/vgg_*.sh` |
| Activa / MVA | `docs/regels/activa.md` | `backend/app/activa/**`, `frontend/src/activa/**` |
| Werkloop, nametingen, deploy en productie-toegang | `docs/regels/werkloop-productie.md` | `backend/app/db/**`, `backend/app/lezen/**`, `backend/app/cli.py`, `backend/app/main.py`, `backend/app/config.py`, `backend/migrations/**`, `scripts/**`, `.github/**`, `opdrachten/**`, `docs/rapporten/**` |
