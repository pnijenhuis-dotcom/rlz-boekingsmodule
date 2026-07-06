# Antwoord vastgoedproject → RLZ-boekingsmodule (2026-07-04) — reactie op doc 13

> Reactie op `13_UPDATE_AAN_VASTGOEDPROJECT.md`. Doel: beide projecten op één lijn vóór jullie
> fase 1-deploy. Niets hierin blokkeert; open punt is eigenaarschap van het platform-fundament
> (zie §4).

## 1. Akkoord op jullie punten

Wij nemen over:

- **Cloud Scheduler + Cloud Run jobs** voor onze indexatie-/factuur-/signaleringsruns —
  Cloud Run-services schalen naar nul, dus onze scheduler draait anders nooit.
- **WORM-audit-log-export** (bucket retention lock).
- **Cloud Tasks-queue** voor externe schrijfacties.
- **Secret-rotatie** voor de gedeelde credential-store.
- **Signed URLs** voor documenttoegang.
- **Cloud Storage-retentie (7 jaar)** voor onze contract-/energielabel-PDF's — zelfde patroon als
  jullie factuurdocumenten.

## 2. Antwoord op jullie drie afstemmingsvragen

1. **Akkoord** dat WORM-audit, Cloud Tasks-patroon en secret-rotatie in het gedeelde fundament
   landen, i.p.v. per module verschillend.
2. **GCP-project/IAM:** akkoord om dit gezamenlijk op te zetten (service account per module,
   least privilege) vóór jullie fase-1-deploy. Vastgoed co-ontwerpt de IAM-structuur nu mee
   (schema `vastgoed` + service-accounts), maar deployt zelf pas in fase 3 — geen vroege
   vastgoed-deploy nodig.
   Openstaand beslispunt (Peter): **eigenaarschap platform-fundament.** Aanbeveling: aparte
   platform-repo met één eigenaar (auth, credential-store, entiteitenregister, IAM-as-code),
   beide modules als consumers — voorkomt twee auth-implementaties en stille afhankelijkheid van
   de module die het eerst deployt.
3. **HMAC-webhook-signing:** akkoord; ons ontvangst-endpoint verifieert de HMAC met key uit
   Secret Manager.

## 3. Vier verbeteringen die wij terugbrengen naar het gedeelde fundament / koppelvlak

1. **Auditvastlegging (laag 0) → bron voor jullie WORM-export.** Beide modules leggen mutaties
   append-only vast in één `audit_event`-vorm: `timestamptz`, actor (platform-auth user-id),
   module, tabel + record-id, actie, oude+nieuwe waarde (JSON), correlatie-id. Uniform schema
   zodat de WORM-export module-overstijgend werkt.
2. **AVG-retentie/pseudonimisering (platformbreed).** PII gescheiden van financiële data;
   verwijderverzoek (AVG art. 17) = pseudonimiseren, niet hard verwijderen (conform "niets
   verwijderen"); PII pas pseudonimiseren na relatie-einde + 7 jaar fiscale bewaarplicht. Beide
   modellen zo inrichten dat PII afsplitsbaar is.
3. **Row-Level Security als gedeeld scopingpatroon.** Beide modules scopen op entiteit/
   administratie via Postgres RLS-policies op DB-niveau (defense-in-depth boven app-laag).
   Platform-auth levert de scope-context (session variable) die de policies lezen.
4. **Webhook replay-bescherming (koppelvlak).** Bovenop HMAC: elk "factuur geboekt"-bericht
   draagt timestamp + unieke nonce; ontvanger weigert berichten buiten een venster (~5 min) of
   met een eerder geziene nonce.

## 4. Openstaand

Eigenaarschap platform-fundament (zie §2.2) — Peter beslist.

## 5. Aanvullende contractverbeteringen (2026-07-04)

Bij het verwerken van bovenstaande punten in het koppelcontract zijn drie losse verbeteringen
doorgevoerd (nu v1.3). Graag jullie bevestiging, zodat v1.3 door beide projecten wordt gedragen:

1. **Versiehistorie + versiebump.** De titel stond nog op v1.1 terwijl er op 2026-07-04 al twee
   inhoudelijke wijzigingen waren doorgevoerd (host→GCP, HMAC+replay) — een schending van de eigen
   regel "wijzigingen alleen met versienummer". Koppelcontract staat nu op v1.3 met een expliciete
   versiehistorie-tabel bovenaan.
2. **Integratietest tegen aparte RLZ-test-administratie i.p.v. verwijderen (§7.3).** De oude
   afspraak ("testdocumenten na afloop door mens verwijderd in RLZ") botste met de hard rule
   "niets verwijderen in andere systemen". Nieuwe afspraak: testen tegen een aparte
   RLZ-test-administratie, testboekingen storneren/terugboeken in plaats van hard verwijderen.
3. **`schema_version` in de push-payload (§3).** Het inbound-bericht draagt voortaan een
   schemaversie, zodat toekomstige koppelvlak-wijzigingen detecteerbaar en onderhandelbaar zijn
   in plaats van stilzwijgend te breken bij een format-wijziging.

— Vastgoedproject, 2026-07-04
