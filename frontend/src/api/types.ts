export interface AdministratieDto {
  id: string
  naam: string
}

export interface MijnAdministratiesResponseDto {
  administraties: AdministratieDto[]
}

export interface DuplicaatReferentieDto {
  document_id: string
  bestandsnaam: string
  aangemaakt_op: string
}

/** Open afwijzing bij een document (mockup: chip "Afgewezen — ter controle" mét reden en wie
 * afwees in de werkvoorraad; banner + heropenen-knop op het controlescherm). */
export interface AfwijzingInfoDto {
  id: string
  reden: string
  afgewezen_door: string
  afgewezen_op: string
  toegewezen_aan: string
  status_voor_afwijzing: string
}

export interface AfwijzingDto {
  id: string
  document_id: string
  document_status: string
  reden: string
  status: string
  status_voor_afwijzing: string
  afgewezen_door: string
  afgewezen_op: string
  toegewezen_aan: string
  heropend_door: string | null
  heropend_op: string | null
}

/** Vier-ogen-IBAN-accordering (PART A-endpoints, docs/ontwerp/iban-wissel-accordering.md). */
export interface IbanAccorderingDto {
  id: string
  document_id: string
  document_status: string
  vendor_id: string
  nieuw_iban: string
  soort: 'regulier' | 'g_rekening'
  status: 'open' | 'geaccordeerd' | 'afgewezen'
  status_voor_accordering: string
  aangevraagd_door: string
  aangevraagd_op: string
  besloten_door: string | null
  besloten_op: string | null
  afwijs_reden: string | null
}

export interface IbanAccorderingLijstDto {
  accorderingen: IbanAccorderingDto[]
}

/** Lege lijst betekent: de actieve beheerder(s) zijn de accordeurs. */
export interface IbanAccordeursDto {
  accordeurs: string[]
}

/** Compacte urenmatch-stand voor de werkvoorraad-chip (factuurmatch fase 2, besluit 3 —
 * duplicaat-patroon: losse vlag bovenop de normale flow, geen status). */
export interface FactuurmatchKortDto {
  uitkomst: string
  verschil_bedrag: string | null
  verschil_uren: string | null
  tarief_ontbreekt: boolean
}

/** Volledige urenmatch-stand (controlescherm-banner; fase-3-match-sectie). */
export interface FactuurmatchDto {
  document_id: string
  veldwerker_naam: string | null
  uitkomst: string
  staten_som_uren: string
  staten_som_bedrag: string | null
  factuur_bedrag: string | null
  factuur_uren: string | null
  verschil_bedrag: string | null
  verschil_uren: string | null
  tarief_ontbreekt: boolean
  details: Record<string, unknown> | null
  berekend_op: string
  afwijking_bevestigd: boolean
  afwijking_bevestigd_op: string | null
}

/** 409-detail van de boek-/aanbiedenroute bij een onbevestigde match-afwijking. */
export interface MatchAfwijkingDetailDto {
  uitkomst: string
  staten_som_uren: string | null
  staten_som_bedrag: string | null
  factuur_bedrag: string | null
  factuur_uren: string | null
  verschil_bedrag: string | null
  verschil_uren: string | null
  tarief_ontbreekt: boolean
}

export interface MatchMailConceptDto {
  ontvanger_naam: string | null
  ontvanger_e_mail: string
  onderwerp: string
  tekst: string
}

/** Duplicaatsignaal (besluit 25-08, deel 2 punt 6): gecachete RLZ-duplicaatuitkomst —
 * 'geen' | 'mogelijk_duplicaat' | 'niet_toetsbaar' | 'onbekend'. Signalering: de live check op
 * het boekmoment blijft bindend. */
/** Al-betaald-signaal (besluit 25-08, deel 2 punt 1): onafgeletterde bankmutaties uit de lokale
 * cache met exact het factuurbedrag; `redenen` = matchreden(en). Signaal, nooit blokkerend. */
export interface AlBetaaldTrefferDto {
  mutatie_id: string
  boekdatum: string
  bedrag: string
  rekening_naam: string | null
  rekening_iban: string | null
  tegenpartij_naam: string | null
  omschrijving: string | null
  redenen: string[]
}

export interface AlBetaaldSignaalDto {
  toetsbaar: boolean
  treffers: AlBetaaldTrefferDto[]
}

/** Aanbetaling-open-signaal (25-08 deel 4 punt 3): een eerdere bank-directboeking op een
 * vooruitbetalingsrekening voor dezelfde leverancier (herkend op Entity of IBAN) die nog niet
 * verrekend is. Bedrag = string (Decimal, positief). */
export interface AanbetalingOpenTrefferDto {
  boeking_id: string
  payment_transaction_id: string
  bedrag: string
  boekdatum: string | null
  geboekt_op: string
  rlz_boekstuknummer: string | null
  entity_naam: string | null
  vooruit_ledger_id: string
  herkenning: 'entity' | 'iban'
}

export interface AanbetalingOpenDto {
  toetsbaar: boolean
  treffers: AanbetalingOpenTrefferDto[]
}

export interface DuplicaatSignaalKortDto {
  uitkomst: string
  aantal_treffers: number
  berekend_op: string
}

export interface DocumentListItemDto {
  id: string
  bestandsnaam: string
  status: string
  bron: string
  /** 'inkoopfactuur' | 'kassarapport' — kassarapport routeert naar het omzetreview-scherm. */
  soort: string
  mogelijk_duplicaat_van: DuplicaatReferentieDto | null
  toegewezen_aan: string | null
  aangemaakt_op: string
  laatst_gewijzigd_op: string
  afwijzing: AfwijzingInfoDto | null
  /** Kopgegevens uit boekvoorstel/extractie (mockup-kolommen Leverancier + Bedrag) — null
   * zolang er nog niets geëxtraheerd of opgeslagen is. Bedrag als string (Decimal). */
  leverancier: string | null
  totaalbedrag: string | null
  factuurdatum: string | null
  /** Autoboeken-opt-in per leverancier: geboekt zónder menselijke boek-klik — voedt de
   * werkvoorraad-chip "automatisch" en het filter "Automatisch geboekt". */
  automatisch_geboekt: boolean
  /** Factuurmatch (fase 2): urenmatch-stand van een veldwerker-factuur — voedt de chip
   * "urenmatch wijkt af". Null/afwezig = geen match van toepassing. */
  factuurmatch?: FactuurmatchKortDto | null
  /** Accordeur aan de beurt (C2 26-08): alleen bij status ter_accordering — de kolom "Toegewezen"
   * toont "<naam> · laag N" in plaats van "—". */
  accordeur_aan_de_beurt?: AccordeurAanDeBeurtDto | null
  /** Bugfix-run 28-08: alle lagen akkoord maar het boeken ná het laatste akkoord faalde — de
   * kolom "Toegewezen" toont de chip "boeken ná akkoord mislukt" mét de reden. Null = geen. */
  accordering_boek_fout?: string | null
  /** Punt 24 (opruimrun 28-08): klant-akkoord compleet én nog niet geboekt — opnieuw aanbieden is
   * server-side geweigerd (409); de bulk-checkbox staat uit mét uitleg "boek direct". */
  klant_akkoord_compleet?: boolean
  /** Duplicaatsignaal (25-08, deel 2 punt 6): voedt de chip "mogelijk duplicaat in RLZ" + het
   * filter. Null/afwezig = nog niet getoetst. */
  duplicaatsignaal?: DuplicaatSignaalKortDto | null
}

export interface AccordeurAanDeBeurtDto {
  gebruiker_id: string
  naam: string
  laag: number
}

export interface DocumentListResponseDto {
  documenten: DocumentListItemDto[]
}

/** Autoboeken-opt-in per leverancier (Instellingen, Beheerder-only — CLAUDE.md-poort vóór het
 * eerste autoboeken van inkoopfacturen). Naam kan null zijn zolang de vendor-sync geen naam
 * kent. */
export interface LeverancierAutoboekenDto {
  vendor_id: string
  naam: string | null
  autoboeken_ingeschakeld: boolean
}

export interface LeverancierAutoboekenLijstDto {
  leveranciers: LeverancierAutoboekenDto[]
}

/** Autoboek-kandidaten (blok B 01-09, mockup autoboek-kandidaten.html, migratie 0095): één rij per
 * (administratie, leverancier) met de deterministische onderbouwing; tabs Kandidaten / Actief /
 * Heroverwegen. Bedragen als string (Decimal-precisie). */
export interface AutoboekKandidaatRijDto {
  administratie_id: string
  administratie_naam: string
  vendor_id: string
  leverancier_naam: string | null
  reeks_ongewijzigd: number
  correcties: number
  open_vragen: number
  kwalificeert: boolean
  actief: boolean
  actief_sinds: string | null
  redenen: string[]
  chips: string[]
  heroverweeg_signalen: string[]
  laatste_factuur_datum: string | null
  laatste_factuur_bedrag: string | null
  laatste_document_id: string | null
  snooze_reden: string | null
  snooze_op: string | null
  berekend_op: string
}

export interface AutoboekTellersDto {
  kandidaten: number
  actief: number
  heroverwegen: number
  verborgen: number
  administraties_met_kandidaten: number
  drempel: number
  laatste_run_op: string | null
}

export interface AutoboekKandidatenLijstDto {
  rijen: AutoboekKandidaatRijDto[]
  totaal: number
  pagina: number
  per_pagina: number
  tellers: AutoboekTellersDto
}

export interface AutoboekAanzetUitkomstDto {
  administratie_id: string
  vendor_id: string
  status: 'aangezet' | 'overgeslagen' | 'fout' | string
  reden: string | null
}

export interface AutoboekBulkAanzettenResultaatDto {
  uitkomsten: AutoboekAanzetUitkomstDto[]
  aangezet: number
  overgeslagen: number
}

/** Werkvoorraad-klantenlijst met tellers (mockup #werkvoorraad "Overzicht per klant"). */
export interface WerkvoorraadKlantDto {
  administratie_id: string
  naam: string
  te_controleren: number
  klaar_om_te_boeken: number
  vragen: number
  afgewezen: number
  bij_klant: number
  iban_wachtend: number
  /** Factuurmatch (fase 2): signaal-teller — open documenten met een match-afwijking (de
   * documenten zelf zitten al in een status-teller hierboven). */
  match_afwijkingen?: number
  /** Duplicaatsignaal (25-08, deel 2 punt 6): open documenten met gecachet 'mogelijk_duplicaat'. */
  duplicaat_signalen?: number
  /** Terugkerende facturen (blok B 30-08): leveranciers met een actief "verwachte factuur ontbreekt". */
  terugkerend_signalen?: number
}

export interface WerkvoorraadOverzichtDto {
  klanten: WerkvoorraadKlantDto[]
}

export interface DocumentGebeurtenisDto {
  van_status: string | null
  naar_status: string
  actor_id: string
  /** True als de overgang door de achtergrondworker (systeem-actor) is gezet — de tijdlijn
   * toont dan herkenbaar "systeem" i.p.v. een menselijke handeling. */
  actor_is_systeem: boolean
  detail: Record<string, unknown> | null
  tijdstip: string
}

export interface DocumentDetailDto {
  id: string
  administratie_id: string | null
  bestandsnaam: string
  status: string
  bron: string
  soort: string
  mogelijk_duplicaat_van: DuplicaatReferentieDto | null
  toegewezen_aan: string | null
  aangemaakt_op: string
  laatst_gewijzigd_op: string
  veldvoorstel: Record<string, unknown> | null
  afwijzing: AfwijzingInfoDto | null
  /** Factuurmatch (fase 2): actuele urenmatch-stand — null als geen match van toepassing. */
  factuurmatch?: FactuurmatchDto | null
  /** Steigerbouw-run D6: materiaalcontrole (verhuur-crediteur) — null zonder koppeling. */
  materiaalmatch?: import('../planning/transportApi').MateriaalmatchDto | null
  /** Blok "Uit de e-mail" (feedbackronde 25-08 deel 3 punt 1b) — alleen bij mail-herkomst. */
  herkomst_mail?: HerkomstMailDto | null
  /** Aangeleverd origineel (bv. IMG_0412.HEIC) als het document een omgezette afbeelding is (punt 2). */
  bron_bestandsnaam?: string | null
  /** Gelezen tenaamstelling uit de intake — voedt de "onthoud"-optie in de verplaats-modal (27/28-08 punt 6a). */
  tenaamstelling?: string | null
  tijdlijn: DocumentGebeurtenisDto[]
}

export interface HerkomstMailDto {
  afzender: string | null
  onderwerp: string | null
  ontvangen_op: string | null
  /** null = geen tekstdeel óf bericht van vóór migratie 0069 (geen backfill). */
  body_tekst: string | null
  bron: string
}

export interface UploadResponseDto {
  document_id: string
  status: string
  mogelijk_duplicaat_van: DuplicaatReferentieDto | null
}

export interface DocumentActieResponseDto {
  document_id: string
  status: string
}

export interface TokenPaarResponseDto {
  access_token: string
  token_type: string
  /** Alleen in de native schil (fase 4, X-Native-Client): het refresh-token voor
   * Keychain/Keystore — web-responses dragen dit veld niet (cookie-only, Auth-0010-b). */
  refresh_token?: string | null
  /** Ontgrendel-frequentie (besluit Peter 27-08): alleen op de stille refresh van een
   * apparaat-gebonden accordeur-/veldsessie — true = passkey-ontgrendeling nodig (laatste
   * ceremonie op dit apparaat > 24 u geleden), false = direct door. Ontbreekt op kantoor-
   * responses en op login-/ontgrendel-antwoorden. */
  ontgrendeling_nodig?: boolean | null
}

export interface UitnodigingAccepterenResponseDto {
  /** 'totp' (kantoor-rollen; totp-velden gevuld) of 'passkey' (klant-accordeur;
   * passkey_setup_token gevuld — accordeur-activeringsflow, besluit 2026-08-11). */
  soort: 'totp' | 'passkey'
  totp_setup_token: string | null
  otpauth_uri: string | null
  secret: string | null
  passkey_setup_token: string | null
}

export interface GrootboekOptieDto {
  ledger_id: string
  code: string
  naam: string
  soort: number
}

export interface GrootboekLijstDto {
  rekeningen: GrootboekOptieDto[]
}

export interface TaxrateOptieDto {
  id: string
  naam: string | null
  /** Fractie als string, bv. "0.2100" voor 21% (Decimal-serialisatie, zie api/client.ts). Null
   * als RLZ geen percentage teruggaf voor deze btw-code. */
  percentage: string | null
}

export interface TaxrateLijstDto {
  btw_codes: TaxrateOptieDto[]
}

export interface VendorOptieDto {
  id: string
  naam: string | null
}

export interface VendorLijstDto {
  crediteuren: VendorOptieDto[]
}

export interface ProjectOptieDto {
  id: string
  naam: string | null
}

export interface ProjectLijstDto {
  projecten: ProjectOptieDto[]
}

export interface BoekvoorstelRegelDto {
  /** DB-id van de opgeslagen boekvoorstel-regel — de doorbelasting-verdeling verwijst hiernaar
   * als `bron_regel_id`. Null voor prefill-regels die nog niet opgeslagen zijn (op een geboekt
   * document dus altijd gevuld). */
  id: string | null
  ledger_id: string | null
  taxrate_id: string | null
  project_id: string | null
  netto_bedrag: string | null
  btw_bedrag: string | null
  omschrijving: string | null
  /** Herkomst van de btw-code (feedbackronde 26-08 punt 3): 'factuur' = door code afgeleid uit
   * netto/btw van de gelezen regel (prefill); null = leeg, of van de mens/het geheugen. */
  btw_bron?: string | null
}

export interface BoekvoorstelDto {
  document_id: string
  vendor_id: string | null
  referentie: string | null
  factuurdatum: string | null
  /** Vervaldatum (C1 26-08) + oranje signaal bij een implausibele termijn (> 90 dagen, geen blokkade). */
  vervaldatum?: string | null
  vervaldatum_signaal?: string | null
  totaalbedrag: string | null
  rlz_boekstuknummer: string | null
  opgeslagen: boolean
  regels: BoekvoorstelRegelDto[]
  /** Fix 3 (2026-07-10): effectieve samenvoeg-stand (voorkeur per crediteur, default aan),
   * of samenvoegen kan (false bij projectplicht — daar is per-regel hard) en de door de backend
   * berekende één-regel-variant voor de samengevoegde weergave. */
  regels_samenvoegen: boolean
  samenvoegen_toegestaan: boolean
  samengevoegde_regel: BoekvoorstelRegelDto | null
  /** Letterlijke "btw verlegd"-vermelding uit de extractie (punt 3, 26-08) — HINT bij een
   * 0%-regel zonder btw-code, nooit een invulling. */
  btw_verlegd_vermelding?: string | null
  /** Afdeling (blok A 28-08): keuze op het document + prefill uit het leverancier-geheugen
   * (alleen zolang er geen keuze staat; herkomst-chip "vorige keuze bij <leverancier>"). */
  afdeling_id?: string | null
  afdeling_prefill_id?: string | null
  afdeling_prefill_leverancier?: string | null
}

export interface GeheugenVeldVoorstelDto {
  waarde: string | null
  /** Winnend gewicht / totaal gewicht van de meegewogen stemmen (0.0 zonder voorstel). */
  confidence: number
  /** Aantal observaties dat de winnende waarde steunt (ongewogen telling). */
  telling: number
  oranje: boolean
  reden: string | null
  /** True zodra ≥1 app-observatie de winnende waarde dekt; false = uitsluitend rlz_seed →
   * altijd oranje met hint "uit historie, nog niet bevestigd" (Peters ontwerp 2026-07-14). */
  app_bevestigd: boolean
}

/** Boekingsgeheugen-voorstel (B6, backend/app/geheugen/router.py): per veld (GB/btw/project) een
 * default + confidence + oranje-vlag. Een voorstel is een default, nooit een beslissing — de
 * harde checks (incl. projectplicht) blijven onverkort blokkerend. */
export interface GeheugenVoorstelDto {
  gb: GeheugenVeldVoorstelDto
  btw: GeheugenVeldVoorstelDto
  project: GeheugenVeldVoorstelDto
}

export interface CheckResultaatDto {
  naam: string
  ok: boolean
  melding: string
  /** Punt 14 (28-08): oranje signaal — ok (geen blokkade) maar de controleur moet kijken. */
  signaal?: boolean
}

/** Punt 14 (28-08): dubbel-signalering bestaande crediteuren (Instellingen › Crediteuren). */
export interface DubbeleCrediteurDto {
  vendor_id: string
  naam: string | null
  btw_nummer: string | null
  kvk_nummer: string | null
  ibans: string[]
}
export interface DubbelGroepDto {
  soort: 'btw_nummer' | 'kvk_nummer' | 'iban' | 'naam'
  sleutel: string
  crediteuren: DubbeleCrediteurDto[]
}
export interface DubbeleCrediteurenResponseDto {
  aantal_crediteuren: number
  groepen: DubbelGroepDto[]
}
export interface CrediteurKvkDto {
  kvk_nummer: string
  gevonden: boolean
  naam: string | null
  rechtsvorm: string | null
  plaats: string | null
  uitgeschreven: boolean | null
  testomgeving: boolean
}

export interface CheckRapportDto {
  geblokkeerd: boolean
  resultaten: CheckResultaatDto[]
}

export interface BoekvoorstelMetChecksDto {
  boekvoorstel: BoekvoorstelDto
  checks: CheckRapportDto
  /** Factuurmatch (fase 2): de vers herberekende urenmatch-stand na deze opslag. */
  factuurmatch?: FactuurmatchDto | null
  /** Steigerbouw-run D6: materiaalcontrole (verhuur-crediteur) — null zonder koppeling. */
  materiaalmatch?: import('../planning/transportApi').MateriaalmatchDto | null
}

export interface BoekenResponseDto {
  document_id: string
  status: string
  rlz_document_id: string
  rlz_boekstuknummer: string | null
  /** "Boeken + doorbelasten" (besluit 25-08): resultaat per doelentiteit (mapping-id → status)
   * van de klaargezette doorbelasting; null = er was geen. */
  doorbelasting_run_id?: string | null
  doorbelasting?: Record<string, string> | null
  /** Zichtbare fout als de doorbelasting ná de geslaagde inkoopboeking (deels) mislukte. */
  doorbelasting_fout?: string | null
}

export interface ProjectVerplichtDto {
  verplicht: boolean
}

export interface BoekenIngeschakeldDto {
  ingeschakeld: boolean
}

/** Resultaat van de vastgoed-toggle (avondrun 26-08, PATCH /administraties/{id}/is-vastgoed):
 * UIT neemt verkoop-autoboeken zichtbaar mee uit — de server meldt dat expliciet. */
export interface IsVastgoedResultaatDto {
  is_vastgoed: boolean
  verkoop_autoboeken_ingeschakeld: boolean
  verkoop_autoboeken_uitgezet: boolean
}

/** Eerste-sync-run (wizard 26-08 punt 5 / rij-status 27-08) — spiegel van beheer/schemas.py. */
export interface EersteSyncRunDto {
  run_id: string | null
  status: 'geen' | 'wachtrij' | 'bezig' | 'klaar' | 'fout' | string
  onderdelen: Record<string, { status: string; aangemaakt?: number | null; bijgewerkt?: number | null; fout?: string }> | null
  aangevraagd_op: string | null
  beeindigd_op: string | null
  fout_reden: string | null
}

export interface AdministratieInstellingenDto {
  id: string
  naam: string
  boeken_ingeschakeld: boolean
  project_verplicht: boolean
  ai_extractie_ingeschakeld: boolean
  eigenaar_gebruiker_id: string | null
  /** Vastgoed-koppeling (Beheerder-toggle sinds 26-08, S2-draaiboek R1): stuurt de
   * factuur_geboekt-/gestorneerd-events naar Vastly, het VASTLY-VERKOOP-boekpad en route A.
   * Verkoop-autoboeken (migratie 0051) bestaat alleen bij is_vastgoed — daarbuiten een streepje. */
  is_vastgoed: boolean
  verkoop_autoboeken_ingeschakeld: boolean
  /** Uren & meerwerk (migratie 0056): steigerbouw-tak, opt-in per administratie. */
  uren_meerwerk_ingeschakeld: boolean
  /** Signaal >N uur per dag (A6, migratie 0072) — drempel per administratie, default 12. */
  uren_dagmax_uren: string
  /** Afdelingen (blok A 28-08, migratie 0084): AAN = afdeling verplicht op élk inkoopdocument +
   * accorderingsroute per afdeling; UIT = veld onzichtbaar. */
  afdelingen_ingeschakeld: boolean
  /** Voorraad bijhouden (blok D 28-08, migratie 0086): opt-in controle-laag mi-schema. */
  voorraad_ingeschakeld: boolean
  /** Koppelstand (wizard 26-08 punt 5): RLZ-id, webservice-gebruiker (null = geen credential —
   * nooit het wachtwoord) en of de laatste rechten-probe groen was (null = nog nooit). */
  rlz_admin_id?: string | null
  webservice_username?: string | null
  probe_groen?: boolean | null
  /** Facturatiemodule niet afgenomen (migratie 0093, 01-09 — casus A.Y. Holding 2 + Abbegaa):
   * SalesInvoices gaf 403 bij de rechten-probe; verkoop-rakende leesroutes slaan deze
   * administratie over. Een herprobe mét SalesInvoices ok haalt het kenmerk weg. */
  verkoopmodule_afwezig?: boolean
  /** Eerste-sync-stand (wizard-nazorg 27-08): laatste run; de rij toont 'm zolang die niet
   * volledig groen is (status ≠ klaar) mét herstartknop. null/ontbrekend = nog nooit gestart. */
  eerste_sync?: EersteSyncRunDto | null
  /** v2 30-08 (mockup instellingen-administraties-v2): meta-regel, chips, sync-kolom, archiefspoor. */
  eigenaar_naam?: string | null
  iban_accordeurs_aantal?: number
  afgeletterd_event_ingeschakeld?: boolean
  doorbelasting_ingeschakeld?: boolean
  /** v3 01-09: deze administratie is DOEL van minstens één actieve doorbelasting-mapping (spiegel-kant) —
   * de detailpagina toont de Doorbelasting-tab bij bron óf doel. */
  doorbelasting_doel?: boolean
  bank_autoboeken_ingeschakeld?: boolean
  accordering_ingeschakeld?: boolean
  laatste_sync_op?: string | null
  gearchiveerd_op?: string | null
  gearchiveerd_door_naam?: string | null
}

export interface ArchiveringResultaatDto {
  gearchiveerd_op: string
  credential_ingetrokken: boolean
  open_documenten: number
}

export interface AdministratieInstellingenLijstDto {
  administraties: AdministratieInstellingenDto[]
}

/** Eén vraag over een document (vragenworkflow PART A, backend/app/documenten/vragen.py).
 * `status_voor_vraag` is de herkomst-status: beantwoorden/intrekken zetten het document daar
 * exact naar terug. `document_status` reist mee zodat de UI een weesvraag op een verwijderd
 * document herkent (niet actief tonen). */
export interface VraagDto {
  id: string
  document_id: string
  document_bestandsnaam: string
  document_status: string
  /** Totaalbedrag uit het boekvoorstel (Decimal serialiseert als string), null zonder voorstel. */
  totaalbedrag: string | null
  vraag_tekst: string
  /** 'beantwoord' = legacy (één-antwoord-model vóór migratie 0064); nieuwe vragen sluiten met
   * 'afgehandeld' (besluit Peter 25-08: alleen de vraagsteller). */
  status: 'open' | 'beantwoord' | 'ingetrokken' | 'afgehandeld'
  status_voor_vraag: string
  gesteld_door: string
  gesteld_op: string
  toegewezen_aan: string
  antwoord_tekst: string | null
  beantwoord_door: string | null
  beantwoord_op: string | null
  ingetrokken_door: string | null
  ingetrokken_op: string | null
  ingetrokken_reden: string | null
  /** Dialoog (0064): wie aan zet is, afhandeling, de thread (oudste eerst) en de server-side
   * poort-uitkomst voor de "Afgehandeld"-knop (UI-hint — de server hertoetst). */
  aan_de_beurt: string
  afgehandeld_door: string | null
  afgehandeld_op: string | null
  berichten: VraagBerichtDto[]
  mag_afhandelen: boolean
}

export interface VraagBerichtDto {
  id: string
  auteur_id: string
  tekst: string
  geplaatst_op: string
}

export interface VraagLijstDto {
  vragen: VraagDto[]
}

/** Toewijsbare medewerker (vraagmodal): bewust alleen id + naam. */
export interface MedewerkerDto {
  id: string
  naam: string
  /** Blok B5 (26-08): klant-accordeur — toewijsbaar als "vraag aan de klant" (antwoordt in de app). */
  is_klant_accordeur?: boolean
}

export interface MedewerkersLijstDto {
  medewerkers: MedewerkerDto[]
}

export interface EigenaarDto {
  eigenaar_gebruiker_id: string | null
}

/* ---------- Omzetmodule (kassarapporten, mockup #omzetreview) ---------- */

export interface OmzetRegelDto {
  categorie: string
  categorie_sleutel: string | null
  omzet_bedrag: string | null
  kostprijs_bedrag: string | null
  omzet_ledger_id: string | null
  taxrate_id: string | null
  kostprijs_ledger_id: string | null
  /** 'mapping' (onthouden) | 'nieuw' (blokkerend tot ingesteld) | 'opgeslagen'. */
  herkomst: string
}

export interface OmzetVoorstelDto {
  document_id: string
  periode_start: string | null
  periode_eind: string | null
  rapport_totaal_omzet: string | null
  rapport_totaal_kostprijs: string | null
  /** In code berekend (omzet / kostprijs × 100), nooit door de AI. */
  marge_pct: string | null
  regels: OmzetRegelDto[]
  voorraad_ledger_id: string | null
  opgeslagen: boolean
  rapport_titel: string | null
  entiteit_naam: string | null
}

export interface OmzetVoorstelMetChecksDto {
  voorstel: OmzetVoorstelDto
  checks: CheckRapportDto
}

export interface OmzetRegelInputDto {
  categorie: string
  omzet_bedrag: string | null
  kostprijs_bedrag: string | null
  omzet_ledger_id: string | null
  taxrate_id: string | null
  kostprijs_ledger_id: string | null
}

export interface OmzetVoorstelInputDto {
  periode_start: string | null
  periode_eind: string | null
  rapport_totaal_omzet: string | null
  rapport_totaal_kostprijs: string | null
  regels: OmzetRegelInputDto[]
  voorraad_ledger_id: string | null
  mapping_onthouden: boolean
}

export interface OmzetBoekenResponseDto {
  document_id: string
  status: string
  verkoop_rlz_id: string
  verkoop_referentie: string | null
  verkoop_boekstuknummer: string | null
  memoriaal_rlz_id: string | null
  memoriaal_boekstuknummer: string | null
}

/* ---------- Verkoopmodule (Vastly VASTLY-VERKOOP-facturen, koppelcontract §2d) ---------- */

export interface VerkoopRegelDto {
  volgnummer: number
  omschrijving: string | null
  /** Decimals serialiseren als string — bedragen nooit als JS-float over de lijn. */
  netto_bedrag: string | null
  btw_bedrag: string | null
  /** RLZ-grootboekcode uit de UBL (cbc:AccountingCost, BT-133). */
  gb_code: string | null
  ledger_id: string | null
  taxrate_id: string | null
  /** 'bekend' | 'onbekend' (code niet in de grootboek-cache) | 'ontbreekt' (geen code in de UBL). */
  gb_code_status: string
  /** 'ubl' (deterministisch uit de UBL gelezen) | 'opgeslagen' (eerder door een mens bevestigd). */
  herkomst: string
  /** Factuur-btw (blok A 2026-08-10): UNCL5305-categorie uit de UBL (S/E/Z/AE) of null. */
  btw_categorie: string | null
  /** Het UBL-percentage (21.00) als string — puur weergave; de fractie-normalisatie is server-side. */
  btw_percentage_ubl: string | null
  /** True = de btw-code volgt deterministisch uit de factuur en is niet te wijzigen. */
  btw_vergrendeld: boolean
  /** 'factuur' | 'onthouden' (eerder gekozen bij ambiguïteit) | null. */
  btw_bron: string | null
  /** Bij echte ambiguïteit (≥ 2 passende RLZ-tarieven): de toegestane keuzeset — eenmalig
   * kiezen, daarna onthouden per administratie. */
  btw_kandidaten: string[]
}

export interface VerkoopVoorstelDto {
  document_id: string
  debiteur_naam: string | null
  factuurnummer: string | null
  factuurdatum: string | null
  totaalbedrag_incl: string | null
  is_creditnota: boolean
  gecrediteerd_factuurnummer: string | null
  regels: VerkoopRegelDto[]
  opgeslagen: boolean
  rlz_boekstuknummer: string | null
}

export interface VerkoopVoorstelMetChecksDto {
  voorstel: VerkoopVoorstelDto
  checks: CheckRapportDto
}

export interface VerkoopRegelInputDto {
  omschrijving: string | null
  netto_bedrag: string | null
  btw_bedrag: string | null
  gb_code: string | null
  ledger_id: string | null
  taxrate_id: string | null
}

export interface VerkoopVoorstelInputDto {
  debiteur_naam: string | null
  factuurnummer: string | null
  factuurdatum: string | null
  totaalbedrag_incl: string | null
  regels: VerkoopRegelInputDto[]
}

export interface VerkoopBoekenResponseDto {
  document_id: string
  status: string
  verkoop_rlz_id: string
  verkoop_referentie: string | null
  verkoop_boekstuknummer: string | null
}

/* ---------- Waarborg (§2d-waarborgroute v1.11, backend/app/waarborg/router.py) ---------- */

export interface WaarborgVoorstelDto {
  document_id: string
  bericht_id: string
  verhuurder_entiteit: string
  contract_referentie: string
  huurder: string
  /** Decimals serialiseren als string — bedragen nooit als JS-float over de lijn. */
  bedrag: string
  richting: string
  datum: string
  balans_gb_code: string
  balans_ledger_id: string | null
  /** 'bekend' | 'onbekend' (blokkerend — code uit het bericht bestaat niet in dit schema). */
  balans_gb_status: string
  tegenrekening_ledger_id: string | null
  status: string
  rlz_boekstuknummer: string | null
}

export interface WaarborgBoekenResponseDto {
  document_id: string
  status: string
  memoriaal_rlz_id: string
  rlz_boekstuknummer: string | null
}

/* ---------- Zoeken + Archief (mockup #zoeken, backend/app/zoeken/router.py) ---------- */

export interface ZoekVraagHitDto {
  vraag_tekst: string
  antwoord_tekst: string | null
  status: string
}

/** Accorderingsstap bij een zoekresultaat — besluit 'akkoord' | 'afgewezen' | null (open),
 * besluit_bron bv. 'staande_goedkeuring' (automatisch akkoord). */
export interface ZoekAccorderingHitDto {
  volgnummer: number
  accordeur_naam: string | null
  besluit: string | null
  besluit_bron: string | null
  besloten_op: string | null
}

export interface ZoekDocumentHitDto {
  document_id: string
  administratie_id: string
  administratie_naam: string
  /** 'inkoopfactuur' | 'kassarapport' | 'verkoopfactuur' — bepaalt het reviewscherm. */
  soort: string
  status: string
  bestandsnaam: string
  leverancier: string | null
  referentie: string | null
  rlz_boekstuknummer: string | null
  /** Decimal serialiseert als string — bedragen nooit als JS-float over de lijn. */
  totaalbedrag: string | null
  factuurdatum: string | null
  aangemaakt_op: string
  automatisch_geboekt: boolean
  vragen: ZoekVraagHitDto[]
  accordering: ZoekAccorderingHitDto[]
}

export interface ZoekAuditHitDto {
  tijdstip: string
  actor_naam: string | null
  actie: string
  administratie_naam: string
  detail: Record<string, unknown> | null
}

/** Administratie waarvan de naam matcht — link naar de klantpagina (veegrun 2026-08-18). */
export interface ZoekAdministratieHitDto {
  administratie_id: string
  naam: string
}

export interface ZoekResponseDto {
  term: string
  administraties: ZoekAdministratieHitDto[]
  documenten: ZoekDocumentHitDto[]
  audit: ZoekAuditHitDto[]
}

/** Geboekt document in het archief (bewaarplicht 7 jaar) — PDF/UBL via het bestaande
 * bestand-endpoint. */
export interface ArchiefDocumentDto {
  document_id: string
  soort: string
  bestandsnaam: string
  leverancier: string | null
  referentie: string | null
  rlz_boekstuknummer: string | null
  totaalbedrag: string | null
  factuurdatum: string | null
  geboekt_op: string | null
  automatisch_geboekt: boolean
  tegengeboekt: boolean
}

export interface ArchiefResponseDto {
  documenten: ArchiefDocumentDto[]
}

/* --- Kempen-doorbelasting (blok 3, besluit Peter 2026-08-13) --------------------------------
 * Spiegel van backend/app/doorbelasting/schemas.py; Decimals reizen als strings (punt-decimaal).
 */

export interface DoorbelastingInstellingDto {
  administratie_id: string
  provisie_percentage: string
  btw_taxrate_id: string | null
  omzet_ledger_id: string | null
  provisie_omzet_ledger_id: string | null
}

export interface DoorbelastingInstellingInputDto {
  provisie_percentage: string
  btw_taxrate_id: string | null
  omzet_ledger_id: string | null
  provisie_omzet_ledger_id: string | null
}

export interface DoorbelastingMappingDto {
  id: string
  doelentiteit_naam: string
  doel_customer_guid: string
  /** null = doelentiteit nog niet onboarded (geen eigen administratie in het platform). */
  doel_administratie_id: string | null
  intercompany: boolean
  provisie_kosten_ledger_id: string | null
  laatste_kosten_ledger_id: string | null
  actief: boolean
}

/** Partial-mutatie: alleen meegegeven velden wijzigen (backend: exclude_unset). */
export interface DoorbelastingMappingWijzigingDto {
  doel_administratie_id?: string | null
  intercompany?: boolean
  provisie_kosten_ledger_id?: string | null
  actief?: boolean
}

export interface DoorbelastingVerdeelRegelDto {
  id: string
  bron_regel_id: string
  mapping_id: string
  percentage: string
  /** Server-berekend netto-deel (grootste-rest) — de client rekent nooit zelf bindend. */
  netto_deel: string
  doel_kosten_ledger_id: string | null
  /** Doorbelasting × projecten (25-08, deel 2 punt 2): project in de DOEL-administratie; bij een
   * multi-project-verdeling één rij per project met hetzelfde percentage. */
  project_id?: string | null
  project_naam?: string | null
  project_aandeel?: string | null
  verdeelbasis?: 'm2' | 'gelijk' | null
  m2?: string | null
}

export interface DoorbelastingVerdeelRegelInputDto {
  bron_regel_id: string
  mapping_id: string
  percentage: string
  doel_kosten_ledger_id: string | null
  /** Projecten in de doel-administratie (leeg = geen); bij > 1 is `verdeelbasis` verplicht. */
  project_ids?: string[]
  verdeelbasis?: 'm2' | 'gelijk' | null
}

/** Project van een doel-administratie voor de verdeel-UI (25-08, deel 2 punt 2a/b). */
export interface DoelProjectDto {
  id: string
  naam: string
  is_actief: boolean
  contract_m2: string | null
}

export interface DoelProjectenDto {
  doel_administratie_id: string | null
  project_verplicht: boolean
  projecten: DoelProjectDto[]
}

export interface DoorbelastingProjectPreviewDto {
  project_id: string
  naam: string
  netto_totaal: string
}

export interface VerdeelsleutelKortDto {
  id: string
  naam: string
  versie: number
  toegepast_op: string | null
}

export interface VerdeelsleutelDoelInputDto {
  mapping_id: string
  percentage: string
  doel_kosten_ledger_id: string | null
  projecten: string[] | 'alle_actief'
  verdeelbasis: 'm2' | 'gelijk' | null
}

export interface VerdeelsleutelInputDto {
  naam: string
  doelen: VerdeelsleutelDoelInputDto[]
}

export interface VerdeelsleutelDto {
  id: string
  naam: string
  versie: number
  actief: boolean
  definitie: { doelen: VerdeelsleutelDoelInputDto[] }
  aangemaakt_op: string
}

export interface DoorbelastingPreviewDto {
  mapping_id: string
  doelentiteit_naam: string
  onboarded: boolean
  netto_totaal: string
  provisie_bedrag: string
  btw_bedrag: string
  /** Status van een bestaande niet-gestorneerde boeking voor deze doelentiteit, anders null. */
  boeking_status: string | null
  /** Boeking-id bij een bestaande niet-gestorneerde boeking — sleutel voor de storno- en
   * spiegel-taak-acties; null zolang er voor deze doelentiteit niets geboekt is. */
  boeking_id: string | null
  /** Rechtsgeldige factuur-PDF (blok A 26-08): 'aanwezig' (downloadbaar) | 'ontbreekt' (mét
   * reden) | null (boeking van vóór 26-08 — herstel-commando). */
  factuur_pdf_status?: string | null
  factuur_pdf_reden?: string | null
  factuur_pdf_bestandsnaam?: string | null
  /** Netto-deel per project binnen deze doelentiteit (25-08, deel 2 punt 2b). */
  projecten?: DoorbelastingProjectPreviewDto[]
}

export interface DoorbelastingRunDto {
  id: string
  document_id: string
  status: string
  laatste_fout: Record<string, unknown> | null
  regels: DoorbelastingVerdeelRegelDto[]
  previews: DoorbelastingPreviewDto[]
  checks: CheckRapportDto
  /** Welke verdeelsleutel(versie) op deze run is toegepast (25-08, punt 2c) — null = geen. */
  verdeelsleutel?: VerdeelsleutelKortDto | null
}

/** Resultaat van (spiegel-)boeken/storno: status per doelentiteit (mapping-id → status). */
export interface DoorbelastingBoekResultaatDto {
  per_doelentiteit: Record<string, string>
}

/** Eén kant van de storno-aangifte-toets (bron-verkoop of doel-spiegel); `reden` verklaart
 * een blokkade per kant (besluit Peter 2026-08-15: storno geblokkeerd zodra de periode in
 * een ingediende btw-aangifte valt — handmatige tegenboeking is dan de route). */
export interface StornoToetsKantDto {
  kant: string
  toegestaan: boolean
  reden: string | null
}

export interface StornoToetsBoekingDto {
  toegestaan: boolean
  melding: string | null
  kanten: StornoToetsKantDto[]
}

/** Per niet-gestorneerde boeking van een document: mag de storno-knop aan? */
export interface StornoToetsDto {
  per_boeking: Record<string, StornoToetsBoekingDto>
}

export interface SpiegelTaakDto {
  boeking_id: string
  document_id: string
  mapping_id: string
  doelentiteit_naam: string
  netto_totaal: string
  provisie_bedrag: string
  verkoop_referentie: string | null
  aangemaakt_op: string
}

/** GB-toewijzing voor een open spiegel-taak (gaten-scan-fix 2026-08-13): alleen GB's, nooit
 * bedragen/percentages — de verdeling zelf is bevroren zodra er geboekt is. */
export interface SpiegelDoelGbsInputDto {
  regel_gbs: Record<string, string>
  provisie_kosten_ledger_id?: string
}

/* --- tegenboek-pad (mockup tegenboek-mockup.html, akkoord Peter 22-08) ----------------------- */

export interface TegenboekVoorbeeldRegelDto {
  grootboek_code: string | null
  grootboek_naam: string | null
  omschrijving: string
  netto_bedrag: string
  btw_bedrag: string
}

export interface TegenboekBetaalstatusDto {
  betaald_bedrag: string
  open_bedrag: string
  volledig_afgeletterd: boolean
}

export interface TegenboekingInfoDto {
  soort: 'volledig' | 'vervang' | string
  reden: string
  boek_cyclus: number
  rlz_tegenboeking_id: string
  rlz_boekstuknummer: string | null
  origineel_betaald_bedrag: string | null
  aangemaakt_op: string
}

/** Leesroute: de knop "Tegenboeken…" verschijnt alléén bij storno_geblokkeerd (en zonder
 * bestaande tegenboeking voor de huidige cyclus). */
export interface TegenboekToetsDto {
  document_id: string
  storno_geblokkeerd: boolean
  blokkade_melding: string | null
  tegenboeking: TegenboekingInfoDto | null
  betaalstatus: TegenboekBetaalstatusDto | null
  voorbeeld: TegenboekVoorbeeldRegelDto[]
  referentie: string | null
  tegenboek_referentie: string
  leverancier_naam: string | null
  totaal_netto: string
  totaal_btw: string
}

export interface TegenboekenResponseDto {
  document_id: string
  soort: string
  status: string
  rlz_tegenboeking_id: string
  rlz_boekstuknummer: string | null
}

/** Antwoord op POST …/documenten/{id}/verplaats (addendum kantoor-run 27-08 punt 5). `status` is
 * de eindstatus ná de her-extractie in het doel; `leerregels_gecorrigeerd` leeg = de toewijzing
 * kwam niet uit het geheugen (alleen verplaatst). */
export interface DocumentVerplaatsResponseDto {
  document_id: string
  status: string
  van_administratie_id: string
  van_administratie_naam: string
  naar_administratie_id: string
  naar_administratie_naam: string
  leerregels_gecorrigeerd: string[]
  vragen_verhuisd: number
  vragen_hertoegewezen: number
  /** Punt 6a: True als op verzoek een tenaamstelling-regel naar het doel is geleerd. */
  tenaamstelling_geleerd?: boolean
}
