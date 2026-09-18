uitgevoerd 2026-09-18, rapport: docs/rapporten/2026-09-18-volumerem-handmatig.md

Domeinen: autoboeken-ai, werkvoorraad-controlescherm, werkloop-productie

# SPOED 18-09 — Volumerem 20/dag blokkeert HANDMATIG boeken (Peter 18-09: "Dagelijkse limiet van 20 boekingen bereikt")

**Feit:** Peter boekt vandaag handmatig een stapel bonnen (BLOW, 180 documenten) en krijgt ná 20 stuks
"Dagelijkse limiet van 20 boekingen bereikt voor deze administratie" (`documenten/boeken.py::toets_volumerem`,
`settings.max_boekingen_per_dag_per_administratie = 20`, code-default; niet gezet in deploy.yml). De rem telt élke overgang → geboekt
van vandaag, ongeacht wie boekte. Enige uitzondering nu: ná compleet klant-akkoord (punt 23, 28-08: 200/dag).

**Waarom fout:** de rem is per ontwerp een noodrem tegen runaway-automatisering ("geen normale-bedrijfsvoering-limiet", config.py). Een
mens die 20× bewust op Boeken drukt ís de normale bedrijfsvoering; de rem blokkeert nu het werk van het kantoor tot middernacht en
het bericht zegt niet wat je kunt doen. Zelfde denkfout als punt 23 destijds voor klant-akkoord.

## Regel (bindend; volledige tekst naar `docs/regels/autoboeken-ai.md`)
1. **De 20/dag-rem geldt uitsluitend voor automatische boekingen** (autoboek-opt-ins, autoboek-kandidaten-activering, bank-auto-
   afletteren/-boeken, verkoop/Vastly-autoboek, omzet-auto, waarborg, doorbelasting-spiegel die uit een automatische bron volgt,
   herstel-CLI zonder mens). Teller = alleen overgangen → geboekt mét herkomst 'automatisch' (de bestaande 'automatisch'-markering/
   `extra_overgang_detail`; ontbreekt die markering op een pad → dat pad eerst markeren, niet raden).
2. **Handmatig boeken (kantoor-actor op de knop, incl. bulk-selectie in de lijst) krijgt een eigen hoge noodrem**: setting
   `max_handmatige_boekingen_per_dag_per_administratie = 500` (env-overschrijfbaar), tekst "Noodrem: 500 handmatige boekingen vandaag
   in deze administratie — neem contact op met de Beheerder", zichtbaar in het scherm én in de reconciliatiemail als LET-OP.
3. Ná klant-akkoord blijft 200 (punt 23) — of vervalt in dezelfde 500 als het één teller wordt; kies het eenvoudigste en documenteer.
4. **Meldingstekst bij élke rem noemt de rem, de teller en de handeling** ("20 van 20 automatische boekingen vandaag · handmatig boeken
   kan gewoon door"), nooit alleen "limiet bereikt".
5. Alle vijf remmen (`documenten/boeken.py`, `bank/boeken.py`, `omzet/boeken.py`, `waarborg/boeken.py`, `verkoop/boeken.py`) via ÉÉN
   helper `volumerem.toets(session, administratie_id, *, herkomst: 'mens' | 'automatisch' | 'na_klant_akkoord')` — geen vijf kopieën.

## Bouw & tests
Helper + settings; per boekpad de herkomst expliciet meegeven (grep op `VolumeremBereikt` = de vijf plekken + herstel-CLI); tests: 20
automatische + 1 handmatige → handmatige gaat door; 500 handmatige → noodrem; teller telt alleen echte overgangen (bestaande bugfix
blijft); autoboek-pad blijft op 20 stoppen mét zichtbare `boek_fout`. Rapport `docs/rapporten/2026-09-18-volumerem-handmatig.md` + INDEX
+ Gelezen regels; BESLISSINGEN "VOLUMEREM — ALLEEN AUTOMATISCH (Peter 18-09)"; WAT_IS_NIEUW. Nameting: BLOW vandaag > 20 handmatig
geboekt zonder rem — "werkt in productie: ja/nee".

## Vandaag, vóór de deploy (klikpunt Peter, alleen als hij nu door wil)
Peter kan de bestaande default ophogen op de draaiende service zonder code (de volgende deploy zet de envset weer volledig, dus dit is
tijdelijk en daarna vervangen door regel 1–2):
`gcloud run services update rlz-backend --region europe-west4 --update-env-vars MAX_BOEKINGEN_PER_DAG_PER_ADMINISTRATIE=500`
CC: neem deze env-var NIET op in deploy.yml (de code-fix maakt hem overbodig); meld in het rapport of de var nog op de service stond.
