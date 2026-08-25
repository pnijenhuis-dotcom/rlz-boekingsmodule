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
  /** Duplicaatsignaal (25-08, deel 2 punt 6): voedt de chip "mogelijk duplicaat in RLZ" + het
   * filter. Null/afwezig = nog niet getoetst. */
  duplicaatsignaal?: DuplicaatSignaalKortDto | null
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
  tijdlijn: DocumentGebeurtenisDto[]
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
}

export interface BoekvoorstelDto {
  document_id: string
  vendor_id: string | null
  referentie: string | null
  factuurdatum: string | null
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

export interface AdministratieInstellingenDto {
  id: string
  naam: string
  boeken_ingeschakeld: boolean
  project_verplicht: boolean
  ai_extractie_ingeschakeld: boolean
  eigenaar_gebruiker_id: string | null
  /** Verkoop-autoboeken (migratie 0051): de schakelaar bestaat alleen voor
   * vastgoed-administraties — daarbuiten toont de kolom een streepje. */
  is_vastgoed: boolean
  verkoop_autoboeken_ingeschakeld: boolean
  /** Uren & meerwerk (migratie 0056): steigerbouw-tak, opt-in per administratie. */
  uren_meerwerk_ingeschakeld: boolean
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
}

export interface DoorbelastingVerdeelRegelInputDto {
  bron_regel_id: string
  mapping_id: string
  percentage: string
  doel_kosten_ledger_id: string | null
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
}

export interface DoorbelastingRunDto {
  id: string
  document_id: string
  status: string
  laatste_fout: Record<string, unknown> | null
  regels: DoorbelastingVerdeelRegelDto[]
  previews: DoorbelastingPreviewDto[]
  checks: CheckRapportDto
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
