# DPIA-lichte toets — AI-extractie van boekhouddocumenten

> ⚠️ **Concept ter juridische toetsing — niet door een jurist opgesteld.**
> Dit is een lichte, gestructureerde risicotoets (pre-DPIA). De slotafweging in §6 — of een
> volledige DPIA (art. 35 AVG) nodig is — moet juridisch worden bevestigd.

## 1. Beschrijving van de verwerking

De module stuurt de inhoud van aangeleverde boekhouddocumenten (PDF-facturen, kassarapporten,
multi-factuur-PDF's) naar de Anthropic Claude API (model `claude-sonnet-5`) om
factuurgegevens voor te lezen: leverancier, datum, bedragen, regels, btw. Kenmerken:

- **AI alleen voor taal, code voor cijfers**: elke AI-uitkomst gaat door een deterministische
  controlelaag (regelsommen, btw-per-regel-check, verplichte velden); geen LLM in
  geldberekeningen.
- **Mens voor de knop op geld**: elk voorstel wordt door een medewerker gecontroleerd vóór
  boeking; automatisch boeken is opt-in per leverancier met onverkort blokkerende checks en
  werkt alleen op app-bevestigd boekingsgeheugen.
- **Gate default UIT**: de AI staat platform-breed uit (`intake_ai_ingeschakeld`,
  Beheerder-instelling met bevestigdialoog, elke wijziging in het audit log).

## 2. Noodzaak en proportionaliteit

Doel: handmatige overtypwerkzaamheden vervangen; het alternatief (volledig handmatig) is
foutgevoeliger en trager. De verwerking is beperkt tot documentinhoud die het kantoor toch al
onder ogen krijgt; er gaan geen aparte persoonsdossiers naar de AI. Minder ingrijpende
alternatieven (klassieke OCR-templates) zijn overwogen maar schalen niet over de
leveranciersvariëteit; de AI levert bovendien alleen een vóórstel, geen besluit.

## 3. Risico's

| # | Risico | Kans/impact (inschatting) |
|---|---|---|
| R1 | Persoonsgegevens (namen, IBAN's, adressen op facturen/urenstaten) gaan naar een verwerker in de VS | kans hoog (inherent), impact beperkt tot factuurcontext |
| R2 | BSN's op documenten (WKA-context, urenstaten) belanden in AI-output of index | zonder maatregelen reëel; impact hoog (BSN = extra beschermd) |
| R3 | Bijzondere categorieën "per ongeluk" in vrije tekst (bv. factuur van een zorgverlener impliceert gezondheidsinformatie) | kans laag-middel, impact middel |
| R4 | Foutieve extractie leidt tot verkeerde boeking/betaling | kans middel, financiële impact |
| R5 | Prompt-injectie: kwaadaardige tekst in een aangeleverd document stuurt de extractie | kans laag, impact beperkt door architectuur |
| R6 | Retentie bij de AI-leverancier langer/anders dan verwacht; toegang derden (VS) | kans laag, impact middel |
| R7 | Function creep: AI-gebruik breidt sluipend uit naar andere data (zoeken, chat) | kans middel zonder afspraak |

## 4. Reeds geborgde mitigaties (gebouwd + getest)

| Risico | Mitigatie |
|---|---|
| R1 | Anthropic-DPA met SCC's (checklist A); ZDR-optie; gate default UIT — géén AI op klantdata vóór de activatie-checklist rond is; dataminimalisatie (alleen documentinhoud) |
| R2 | **BSN-hardregel**: (a) prompt verbiedt extractie, (b) deterministisch post-filter `app/extractie/bsn.py` vóór persistentie (elfproef + verplichte BSN-context, negatieve labels overstemmen — bewust zo ontworpen dat factuurnummers niet vals maskeren), (c) preview maskeert, (d) BSN's worden nooit geïndexeerd; brondocument blijft alleen als bestand bewaard (WKA-bewaarplicht) |
| R3 | Er wordt niets uit documenten "gelezen" behalve boekhoudvelden; vrije-tekstvelden gaan door hetzelfde BSN-/persistentiefilter; geen profilering of afgeleide kenmerken |
| R4 | Deterministische controlelaag over elke extractie; harde blokkerende checks (duplicaat, regeltelling, verplichte velden, IBAN-wissel-vier-ogen, btw-per-regel); mens-in-de-lus; afwijkingen van het boekingsgeheugen oranje gemarkeerd, seed-only nooit groen; automatisch boeken opt-in mét volumerem |
| R5 | De AI-output is een gestructureerd voorstel dat door deterministische checks en een mens gaat; de AI heeft geen tools/schrijftoegang — een injectie kan hoogstens een fout voorstel opleveren dat door R4-mitigaties gevangen wordt |
| R6 | DPA + (aan te vragen) zero data retention; geen training op API-data volgens de Commercial Terms (verifiëren bij acceptatie); modelkeuze gepind op een ZDR-compatibel model |
| R7 | Zoeken gebruikt bewust uitsluitend lokaal aanwezige extractietekst (geen nieuwe AI-calls); elke nieuwe AI-toepassing = nieuw besluit + aanvulling op dit document |

Algemene waarborgen eromheen: RLS-scoping per administratie, TOTP-2FA, append-only audit op
elke handeling, envelope-versleutelde credentials, pseudonimisering na relatie-einde + 7 jaar.

## 5. Restrisico's (geaccepteerd of nog te beleggen)

1. **Vrije-tekst-PII gaat wél naar de API** zolang het geen BSN is (namen, adressen,
   omschrijvingen). Aanvaardbaar geacht binnen doel + DPA + ZDR; expliciet accepteren.
2. **VS-doorgifte** blijft juridisch kwetsbaar voor jurisprudentiewijzigingen (Schrems-lijn).
   Monitoren; ZDR verkleint de feitelijke blootstelling. Zie ook de CLOUD Act-notitie
   (register §9).
3. **Datalek-procedure** (meldplicht 72 u) is kantoorbreed nog niet beschreven — beleggen
   vóór activering.
4. **Klanten met gevoelige sectoren** (zorg, advocatuur): per administratie beoordelen of de
   AI-gate voor die administratie uit moet blijven zolang geen aanvullende afspraak met de
   klant bestaat.

## 6. Conclusie (te toetsen)

De verwerking is geen grootschalige, systematische verwerking van bijzondere categorieën en
bevat geen geautomatiseerde besluitvorming met rechtsgevolg (mens-in-de-lus is hard geborgd) —
een volledige DPIA lijkt daarmee niet verplicht, mits de mitigaties uit §4 en de acties uit
§5 staan. **Heroverwegen** (alsnog volledige DPIA) zodra: de AI-gate op grote schaal aan
staat voor administraties met stelselmatig gevoelige documentstromen, de AI-toepassing wordt
uitgebreid (R7), of automatische besluitvorming zonder menselijke controle wordt overwogen.
