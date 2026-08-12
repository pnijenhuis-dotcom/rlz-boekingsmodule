# Toetsingsmemo voor de jurist — AVG-pakket RLZ Boekingsmodule

> Van: P. Nijenhuis, Administratiekantoor Nijenhuis · Datum: 2026-08-11
> Bijgevoegd: zes conceptdocumenten (hierna). Alle stukken zijn intern opgesteld (met
> AI-ondersteuning) en **niet door een jurist geschreven** — vandaar dit verzoek.

## Context in vijf zinnen

Het kantoor voert boekhoudingen voor tientallen klanten in Exact Reeleezee en heeft daarvoor
een eigen verwerkingsmodule gebouwd (documentintake, AI-ondersteunde factuurherkenning,
boeken, bankverwerking, klant-goedkeuring via een mobiele app). De AI-functie (Anthropic
Claude API, VS) staat nu **uit** en gaat pas aan als dit pakket juridisch rond is. Hosting
verhuist in september naar Google Cloud (regio Nederland). Er is bewust veel technisch
geborgd: mens-in-de-lus op elke boeking, BSN's worden nooit door de AI verwerkt of opgeslagen,
volledige audit-trail, toegang per administratie afgeschermd. De vraag is of de juridische
basis onder dit geheel klopt.

## Toetsvragen — waar we een expliciet oordeel op vragen

**Vraag 1 (document 3 — de dragende kwalificatie).** Wij concluderen op basis van de
NBA/NOB-richtsnoeren dat het kantoor voor de administratievoering **zelfstandig
verwerkingsverantwoordelijke** is (geen verwerker), zodat géén verwerkersovereenkomsten met
klanten nodig zijn maar wél de informatieplicht geldt. Deelt u die kwalificatie? Dit draagt
het hele pakket: als het "verwerker" wordt, draait de subverwerker-redenering (vraag 3) om.

**Vraag 2 (document 3, §4).** Is het concept-tekstblok voor de opdrachtvoorwaarden juridisch
houdbaar en volledig (rol, doel/grondslag, dienstverleners incl. VS-doorgifte, bewaartermijn,
betrokkenen, beveiliging, datalekken)? Graag redigeren waar nodig.

**Vraag 3 (document 2).** Volstaan de voorgenomen DPA's (Anthropic met zero-data-retention en
SCC's; Google Cloud CDPA met EU-regio; Exact-verwerkersovereenkomst) voor de VS-doorgifte aan
Anthropic, mede in het licht van de Schrems-jurisprudentie? Zijn er aanvullende maatregelen
die u nodig acht vóór activering?

**Vraag 4 (document 4).** Deelt u de conclusie dat een volledige DPIA (art. 35) niet
verplicht is, gegeven mens-in-de-lus, de BSN-hardregel en de genoemde heroverwegingstriggers?

**Vraag 5 (document 1).** Is het verwerkingsregister naar vorm en inhoud art. 30-conform;
mist u verwerkingen of velden?

**Vraag 6 (document 6).** Is de datalek-procedure conform art. 33/34, en zijn de vuistregels
in stap 3 (wel/niet melden) verdedigbaar als kantoorbeleid?

**Vraag 7 (document 5, bijlage A).** De klant-accordeurs (gebruikers van onze
goedkeurings-app) accepteren bij activering gebruiksvoorwaarden + privacyverklaring; wij
positioneren dat uitdrukkelijk als informatielaag, niet als AVG-grondslag. Klopt die
positionering, en is de concept-akkoordtekst bruikbaar?

**Vraag 8 (algemeen).** Wat mist er in dit pakket dat u wél zou verwachten voor een kantoor
van deze omvang (bv. privacyverklaring website, register verwerkingen buiten de module,
geheimhoudingsbedingen personeel)?

**Vraag 9 (groepsstructuur).** De software en de hosting (Google Cloud-organisatie) zijn
eigendom van PDL Powerhouse B.V.; de verwerkingsverantwoordelijke voor de klantdata is het
kantoor. Als kantoor en PDL verschillende rechtspersonen zijn: volstaat een intra-groep
verwerkersovereenkomst tussen kantoor en PDL (PDL als hosting-/softwareverwerker), en heeft u
daar een modeltekst voor? Zo ja, dan hoort PDL ook als verwerker in het register (document 1).

## Volgorde-afhankelijkheid

Wij activeren de AI-functie en de cloud-migratie pas ná uw akkoord op vragen 1, 3 en 4
(activatie-checklist, document 5). Vragen 2, 6, 7 en 8 mogen in een tweede ronde.
