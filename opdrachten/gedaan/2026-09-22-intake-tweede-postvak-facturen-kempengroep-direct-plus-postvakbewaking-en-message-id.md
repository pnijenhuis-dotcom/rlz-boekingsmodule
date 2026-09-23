uitgevoerd 2026-09-23, rapport: docs/rapporten/2026-09-23-intake-tweede-postvak-kempengroep-message-id-postvakbewaking.md (poging 2 ná WIP-branch; audit-skelet docs/rapporten/2026-09-23-intake-postvak-audit.md)

Domeinen: intake-extractie, reconciliatie, werkloop-productie

# OPDRACHT 22-09 — Intake: facturen@kempengroep.nl als tweede postvak DIRECT lezen (geen forward meer), postvak-bewaking
# "ontvangen vs verwerkt" (incl. gelezen + Spam), verwerkt-administratie op Message-ID i.p.v. de gelezen-vlag

**Aanleiding (Peter 22-09):** "er zijn facturen gemaild die niet in onze module staan". Feiten: de intake leest alléén `UNSEEN` in de
INBOX van facturen@ak-nijenhuis.nl (`intake/postvak.py`, gelezen-vlag = verwerkt-administratie); een groot deel van de facturen komt
binnen op facturen@kempengroep.nl (Google Workspace) en wordt vandaar automatisch doorgestuurd. Verliespaden die de module nooit ziet:
Gmail stuurt eigen spam-/duplicaatclassificaties niet door; doorsturen breekt SPF → strikte-DMARC-afzenders landen bij ak-nijenhuis in
Spam (niet INBOX); een mens die de mailbox open heeft zet berichten op gelezen vóór de intake ze ziet. Intake draait wél (22-09 16:10
verwerkt, verzamelbak 1). Beide domeinen = Google.

**Stand 22-09 14:2x (Cowork + Peter):** Google Workspace-organisatie = kempenrecreatie.nl (kempengroep.nl secundair domein);
IMAP staat org-breed AAN (gecontroleerd in de beheerdersconsole, niets gewijzigd); facturen@kempengroep.nl is een echt
gebruikersaccount ("facturen algemeen", 7,39 GB); tweestapsverificatie + app-wachtwoord "RLZ intake" door Peter aangemaakt;
**secret `INTAKE_KEMPENGROEP_IMAP_WACHTWOORD` bestaat (versie 1, user-managed replicatie europe-west4 — de org-policy
`gcp.resourceLocations` weigert `automatic`/global; neem dat op in `docs/regels/werkloop-productie.md` voor élk volgend secret) mét
`secretAccessor` voor run-jobs@.** Klikpunt A is dus gedaan; alleen de forward uitzetten blijft ná de eerste groene run.
Bijvangst voor Peter (niet in deze run): alle vier de domeinen tonen in de console "Status van e-mailconfiguratie: Actie vereist"
(DKIM/DMARC waarschijnlijk incompleet — verklaart mede de spam-classificatie); kevin@kempenrecreatie.nl staat sinds 18-05-2024 als
"wachtwoordlek" open terwijl de medewerker weg is.

## Opdracht
A. **Tweede kanaal `facturen_kempengroep`** naast `facturen` en `declaraties` (bestaand patroon `ImapInstellingen.voor_kanaal`,
   `_SETTINGS_PREFIX_PER_KANAAL`, eigen job `rlz-intake-imap-kempengroep` in deploy.yml mét `--command python` + eigen envs/secret
   `INTAKE_KEMPENGROEP_IMAP_WACHTWOORD`, scheduler zelfde cadans als `rlz-intake-imap`, ACTIEF niet gepauzeerd, f3_jobs.sh + IAM).
   Verwerking identiek (tenaamstelling leidend, afzender hint; kanaal in het intake-bericht en de tijdlijn zichtbaar: "via
   facturen@kempengroep.nl"). Klikpunten Peter (in het rapport letterlijk): in Google Workspace IMAP aanzetten voor die mailbox +
   app-wachtwoord aanmaken en ZELF in Secret Manager zetten (`gcloud secrets versions add …` — nooit via CC/Cowork); ná de eerste
   groene run de automatische forward in Gmail UITZETTEN (anders komt alles dubbel; tot die tijd vangt de duplicaat-afvoer het:
   byte-identiek = `samengevoegd`, zelfde referentie+bedrag = duplicaat-afvoer — test dat pad expliciet op twee kanalen).
B. **Verwerkt-administratie op Message-ID** (migratie: tabel `intake_bericht_verwerkt(kanaal, message_id, uid, verwerkt_op,
   uitkomst)`): de fetch leest `ALL` (of `SINCE` de laatste run − 7 dagen) in INBOX **én `[Gmail]/Spam`**, verwerkt wat nog niet in
   de tabel staat, en zet de gelezen-vlag alleen nog als bijproduct. Een mens die de mailbox opent kan zo niets meer laten verdwijnen.
   Spam-treffers: wél verwerken, mét chip "uit Spam" + LET-OP-bevinding `intake_uit_spam` (afzender + domein) zodat Peter de
   afzender kan whitelisten. Herstelrun eenmalig ná deploy (job-image): laatste 60 dagen van beide postvakken incl. Spam nalopen,
   alles wat ontbreekt alsnog verwerken (bestaande dedup houdt dubbelen tegen), rapport per bericht: verwerkt / al bekend /
   niet verwerkbaar.
C. **Postvak-bewaking (reconciliatieblok `intake`, dagelijks):** per kanaal: berichten in het postvak sinds gisteren (IMAP-telling
   INBOX + Spam, ongeacht gelezen) vs. verwerkt (tabel B) vs. documenten aangemaakt/verzamelbak/niet-verwerkbaar; verschil > 0 =
   actie-bevinding mét de Message-ID's en knop "Nu verwerken"; verbinding mislukt = systeemfout (nooit stil). Dagtellers in de
   reconciliatiemail. Voor de overgangsperiode: teller "dubbel via forward" apart.
D. **Dubbele mailbox-audit — EERST, vóór de rest (Peter 22-09 avond: "laat hem de mailbox goed controleren welke facturen wel en
   niet zijn doorgekomen, dubbele controle"). Lees-only CLI `intake-postvak-audit --sinds 2026-07-01` op de job-image (beide
   IMAP-credentials staan op de job; nameting@ kan dit niet):**
   1. Bron: élk bericht in facturen@kempengroep.nl (INBOX + Spam + "Alle e-mail", gelezen én ongelezen) mét bijlage(n) PDF/UBL/afbeelding
      → per bericht: Message-ID, datum, afzender, onderwerp, bestandsnamen + sha256 per bijlage.
   2. Doorgifte: dezelfde set in facturen@ak-nijenhuis.nl (INBOX + Spam + "Alle e-mail"): koppel op het oorspronkelijke Message-ID
      (Gmail-forward behoudt `Message-ID` van de bron óf zet hem in `References`/`In-Reply-To`; handmatige "Fwd:" = nieuw Message-ID →
      dan matchen op bijlage-sha256, daarna op bestandsnaam + bedrag uit de PDF-tekst als laatste redmiddel, en dát zichtbaar labelen).
      Per bronbericht: aangekomen ja/nee, in welke map (INBOX/Spam), gelezen-vlag.
   3. Module: koppel op `intake_bericht.message_id` en op bijlage-hash naar `document` (status, administratie, boekstuk) of
      verzamelbak/duplicaat-afvoer/niet-verwerkbaar.
   Rapporttabel per bronbericht: **ontvangen kempengroep → aangekomen ak-nijenhuis (map) → verwerkt module (documentstatus)**, mét de
   drie uitvalcategorieën geteld: (a) nooit doorgestuurd, (b) aangekomen in Spam en daardoor overgeslagen, (c) aangekomen in INBOX
   maar niet verwerkt (gelezen-vlag / andere oorzaak — benoem 'm). Plus de omgekeerde controle: berichten in ak-nijenhuis mét
   factuurbijlage zonder module-spoor die NIET uit kempengroep komen (rechtstreekse leveranciers). Alles wat mist gaat mét de bestaande
   dedup alsnog de intake in (herstelrun B), nooit dubbel; het rapport noemt per bericht wat er is gebeurd. Geen PII buiten
   afzenderadres/onderwerp/bestandsnaam. Dit rapport is Peters antwoord — vóór de bouw van A–C opleveren als apart rapport
   `docs/rapporten/2026-09-2x-intake-postvak-audit.md`.
E. Tests (fetch leest gelezen berichten, Spam-map, idempotentie op Message-ID, twee kanalen zelfde bijlage = samengevoegd, telling
   mét verschil = bevinding, verbinding stuk = systeemfout); rapport + INDEX + Gelezen regels; BESLISSINGEN "INTAKE — TWEEDE POSTVAK
   KEMPENGROEP DIRECT + MESSAGE-ID-ADMINISTRATIE + POSTVAKBEWAKING (Peter 22-09)"; regels intake-extractie; WAT_IS_NIEUW; CLAUDE.md
   één regel; les `Platform/registers/verbeteringen.md`: "een gelezen-vlag is geen verwerkt-administratie; wat de module niet
   ontvangt telt ze niet — dus tel aan de bron".
