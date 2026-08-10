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
}

export interface UitnodigingAccepterenResponseDto {
  totp_setup_token: string
  otpauth_uri: string
  secret: string
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
}

export interface BoekenResponseDto {
  document_id: string
  status: string
  rlz_document_id: string
  rlz_boekstuknummer: string | null
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
  status: 'open' | 'beantwoord' | 'ingetrokken'
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

export interface ZoekResponseDto {
  term: string
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
}

export interface ArchiefResponseDto {
  documenten: ArchiefDocumentDto[]
}
