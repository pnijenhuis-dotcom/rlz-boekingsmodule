import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { ApiError, apiFetch, apiJson, apiPostJson } from '../api/client'
import type {
  BoekenResponseDto,
  BoekvoorstelDto,
  BoekvoorstelMetChecksDto,
  BoekvoorstelRegelDto,
  CheckRapportDto,
  DocumentActieResponseDto,
  GeheugenVeldVoorstelDto,
  GeheugenVoorstelDto,
  MatchAfwijkingDetailDto,
} from '../api/types'
import { alsAiVoorstel, zekerheidPct, type AiVoorstel, type VeldvoorstelBron } from './aiVoorstel'
import { bedragAlsGetal, berekenBtwBedrag, normaliseerBedrag } from './bedrag'
import { crediteurSuggesties } from './crediteurSuggesties'
import { toetsRegelsom } from './regelsom'
import {
  bepaalGeheugenChip,
  bepaalPrefill,
  haalGeheugenVoorstel,
  korteReden,
  omschrijvingSleutel,
  type HandmatigeVelden,
} from './geheugenVoorstel'
import { bepaalBtwStandaardChip, bepaalGbChip, btwBronUitDto, gbBronUitDto, type BtwBron, type GbBron } from './regelVoorstelChips'
import { Checkbox, Select } from '../ui/basis'
import { ChecksPopup } from '../ui/ChecksPopup'
import { MatchAfwijkingPopup } from '../ui/MatchAfwijkingPopup'
import { MateriaalAfwijkingPopup } from '../ui/MateriaalAfwijkingPopup'
import type { MateriaalmatchDto } from '../planning/transportApi'
import { DatePicker } from '../ui/DatePicker'
import { RegelOmschrijvingVeld } from '../ui/RegelOmschrijvingVeld'
import { KOLOM_PX, minimaleTabelbreedte } from './boekingsregelsKolommen'
import { IbanAanbiedenVorm } from './IbanAccorderingSectie'
import { NieuweCrediteurDialog, type NieuweCrediteurResultaat } from './NieuweCrediteurDialog'
import { SearchableCombobox, type ComboboxOptie } from './SearchableCombobox'
import {
  synchroniseerAlleCaches,
  useGrootboekOpties,
  useProjectOpties,
  useAfdelingen,
  useProjectVerplicht,
  useTaxrateOpties,
  useVendorOpties,
} from './useSyncOpties'
import { useAutoChecks } from './useAutoChecks'

/** Statische weergave van een gekozen optie (design-pass: read-only bij geboekt/verwijderd) —
 * zelfde code+omschrijving-vorm als de combobox zelf toont, alleen niet interactief. */
function optieWeergave(opties: ComboboxOptie[], id: string | null): string {
  if (!id) return '—'
  const optie = opties.find((o) => o.id === id)
  if (!optie) return id
  return optie.code ? `${optie.code} · ${optie.label}` : optie.label
}

interface StatischVeldProps {
  label: string
  waarde: string
}

/** Read-only equivalent van een invoerveld — géén disabled <input> (dat suggereert nog steeds
 * dat er iets bewerkbaar is), gewoon platte tekst op dezelfde plek in de layout. */
function StatischVeld({ label, waarde }: StatischVeldProps) {
  return (
    <div>
      <label>{label}</label>
      <p style={{ margin: 0, padding: '8px 0', fontSize: 13 }}>{waarde || '—'}</p>
    </div>
  )
}

interface RegelState {
  key: string
  ledgerId: string | null
  taxrateId: string | null
  projectId: string | null
  netto: string
  btw: string
  /** Design-pass taak 3: zodra de gebruiker zelf iets in het btw-veld typt, stopt de automatische
   * afleiding (netto x taxrate-percentage) met dat veld te overschrijven — "overschrijfbaar", dus
   * één keer aangeraakt blijft het van de gebruiker. Een geladen regel met een al opgeslagen
   * btw-bedrag telt ook als "handmatig" (kan een eerdere handmatige invoer zijn geweest). */
  btwHandmatig: boolean
  /** Herkomst van de vooringevulde btw-code (punt 3, 26-08): 'factuur' = door code afgeleid uit
   * netto/btw van de gelezen regel. Toont de chip "uit factuur (21%)" zolang de controleur het
   * veld niet zelf aanraakt — daarna is de keuze van de mens (zelfde regel als de AI-chip).
   * 'standaard' (blok E 04-09) = btw-default van de administratie, chip "standaard administratie". */
  btwBron: BtwBron | null
  /** Herkomst van het vooringevulde grootboek per regel (blok D 04-09, mockup blok 2): regel-geheugen
   * (groen), historie/conflict (oranje) of AI-classificatie (oranje "bevestig"). Zelfde chip-regel als
   * btwBron: weg zodra de mens het veld aanraakt; het kop-niveau-geheugen (GeheugenChipBlok) zwijgt
   * op het grootboek zolang deze regel-chip staat — de regel-treffer is specifieker. */
  gbBron: GbBron | null
  gbDetail: string | null
  omschrijving: string
  /** Laagste AI-zekerheidsscore van de vooringevulde regelvelden (alleen bij een vers, nog niet
   * opgeslagen AI-voorstel). Elke handmatige wijziging aan de regel wist de score — dan beschrijft
   * hij de inhoud niet meer. */
  aiZekerheid: number | null
  /** Boekingsgeheugen-koppeling: het opgehaalde voorstel dat bij deze regel hoort (leverancier-
   * niveau bij samengevoegd, regel-niveau bij gesplitst) + welke voorstel-velden de gebruiker
   * zelf heeft aangeraakt — die vult of markeert het geheugen daarna nooit meer. */
  geheugen: GeheugenVoorstelDto | null
  handmatigeVelden: HandmatigeVelden
  /** True als de voorstel-call voor deze regel mislukte: dat mag niet op een leeg geheugen
   * lijken ("niets verdwijnt stil") — rustige inline-indicatie, nooit blokkerend. */
  geheugenFout: boolean
}

/** Afrondingsmarge btw-hint (regelrij-UI 25-08): tot en met 1 cent is afronding, geen afwijking. */
const BTW_AFRONDINGSMARGE = 0.0105

const GEEN_HANDMATIGE_VELDEN: HandmatigeVelden = { ledgerId: false, taxrateId: false, projectId: false }

function nieuweRegel(): RegelState {
  return {
    key: crypto.randomUUID(),
    ledgerId: null,
    taxrateId: null,
    projectId: null,
    netto: '',
    btw: '',
    btwHandmatig: false,
    btwBron: null,
    gbBron: null,
    gbDetail: null,
    omschrijving: '',
    aiZekerheid: null,
    geheugen: null,
    handmatigeVelden: GEEN_HANDMATIGE_VELDEN,
    geheugenFout: false,
  }
}

function regelUitDtoRegel(r: BoekvoorstelRegelDto, aiZekerheid: number | null = null): RegelState {
  return {
    key: crypto.randomUUID(),
    ledgerId: r.ledger_id,
    taxrateId: r.taxrate_id,
    projectId: r.project_id,
    netto: r.netto_bedrag ?? '',
    btw: r.btw_bedrag ?? '',
    btwHandmatig: Boolean(r.btw_bedrag),
    btwBron: btwBronUitDto(r.btw_bron, r.taxrate_id),
    gbBron: r.ledger_id ? gbBronUitDto(r.gb_bron) : null,
    gbDetail: r.gb_voorstel_detail ?? null,
    omschrijving: r.omschrijving ?? '',
    aiZekerheid,
    geheugen: null,
    handmatigeVelden: GEEN_HANDMATIGE_VELDEN,
    geheugenFout: false,
  }
}

function regelsUitDto(dto: BoekvoorstelDto, ai: AiVoorstel | null): RegelState[] {
  if (dto.regels.length === 0) return [nieuweRegel()]
  // Sinds het compacte schema (2026-07-10) levert de AI één zekerheidsscore per regel.
  const aiScores =
    ai && ai.regels.length === dto.regels.length
      ? dto.regels.map((_, i) => ai.regel_zekerheid[i] ?? null)
      : null
  return dto.regels.map((r, i) => regelUitDtoRegel(r, aiScores ? aiScores[i] : null))
}

/** Fix 3: de per-regel-variant rechtstreeks uit het AI-veldvoorstel — nodig als het voorstel in
 * samengevoegde vorm is opgeslagen (dto.regels is dan de ene samengevoegde regel) en de
 * controleur alsnog wil splitsen. De AI blijft altijd alle regels extraheren; deze prefill is
 * daardoor altijd beschikbaar zolang er een AI-voorstel is. */
function regelsUitAi(ai: AiVoorstel): RegelState[] {
  if (ai.regels.length === 0) return [nieuweRegel()]
  return ai.regels.map((r, i) => ({
    key: crypto.randomUUID(),
    ledgerId: null,
    taxrateId: r.taxrate_id,
    projectId: null,
    netto: r.netto_bedrag ?? '',
    btw: r.btw_bedrag ?? '',
    btwHandmatig: Boolean(r.btw_bedrag),
    btwBron: btwBronUitDto(r.btw_bron, r.taxrate_id),
    // Client-side splitsing uit het AI-veldvoorstel kent geen regel-GB-voorstel (dat reist mee op de
    // server-prefill van dto.regels); de kop-niveau-engine vult 'm dan zoals voorheen.
    gbBron: null,
    gbDetail: null,
    omschrijving: r.omschrijving ?? '',
    aiZekerheid: ai.regel_zekerheid[i] ?? null,
    geheugen: null,
    handmatigeVelden: GEEN_HANDMATIGE_VELDEN,
    geheugenFout: false,
  }))
}

function formatEuro(bedrag: number): string {
  return bedrag.toLocaleString('nl-NL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** Gelezen bedrag uit het veldvoorstel-dict (backend levert punt-decimaal strings); null = niet gelezen. */
function veldvoorstelBedrag(veldvoorstel: Record<string, unknown> | null | undefined, sleutel: string): number | null {
  const waarde = veldvoorstel?.[sleutel]
  return typeof waarde === 'string' && waarde ? bedragAlsGetal(waarde) : null
}

interface LegeCacheBannerProps {
  naam: string
  bezig: boolean
  onSynchroniseren: () => void
}

/** Design-pass taak 3: duidelijke melding + herstelactie i.p.v. een blijkbaar-lege combobox
 * zonder verklaring. "Nu synchroniseren" verversen ALLE vier de caches (grootboek/btw/crediteuren/
 * projecten) tegelijk — een controleur die deze banner ziet, wil de hele administratie bijwerken. */
function LegeCacheBanner({ naam, bezig, onSynchroniseren }: LegeCacheBannerProps) {
  return (
    <div
      style={{
        background: 'var(--orange-bg)',
        color: 'var(--orange)',
        borderRadius: 8,
        padding: '9px 12px',
        fontSize: 12.5,
        marginBottom: 10,
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        flexWrap: 'wrap',
      }}
    >
      <span>Deze administratie is nog niet gesynchroniseerd voor {naam}.</span>
      <button type="button" className="btn secondary" disabled={bezig} onClick={onSynchroniseren}>
        {bezig ? 'Bezig…' : 'Nu synchroniseren'}
      </button>
    </div>
  )
}

type VendorMatch = 'exact' | 'fuzzy' | 'btw_nummer' | 'kvk_nummer' | 'iban'

const HERKENNING_LABEL: Record<string, string> = { btw_nummer: 'btw-nummer', kvk_nummer: 'KvK-nummer', iban: 'IBAN' }

interface AiChipProps {
  score: number
  drempel: number
  /** Crediteur-match-soort (punt 14, 28-08): nummer-match = groen mét herkomst, fuzzy = oranje. */
  match?: VendorMatch
  /** 'template' = deterministische terugval (geleerd leverancier-template, geen AI) — eigen chipvariant. */
  bron?: VeldvoorstelBron
}

/** Herkomst-chip bij een vooringevuld veld. AI: zekerheidsscore, oranje onder de drempel of bij een
 * fuzzy crediteur-match ("bij twijfel oranje, nooit gokken"), anders groen; een crediteur die op
 * btw-/KvK-nummer/IBAN herkend is (punt 14) is groen ongeacht de naam-score: het nummer is de sleutel.
 * Template (01-09): "uit template" — deterministisch gelezen via het geleerde template van deze
 * leverancier (lokale code, geen AI, geen score); de harde checks blijven de poort.
 * Verdwijnt zodra de controleur het veld aanpast — de herkomst beschrijft dan de inhoud niet meer. */
function AiChip({ score, drempel, match, bron }: AiChipProps) {
  const opNummer = match === 'btw_nummer' || match === 'kvk_nummer' || match === 'iban'
  const fuzzy = match === 'fuzzy'
  if (bron === 'template') {
    return (
      <span
        className="chip ok"
        title="Deterministisch gelezen via het geleerde template van deze leverancier (lokale code, geen AI). Het template reproduceert de laatste bevestigde facturen exact; de harde checks blijven de poort."
      >
        uit template{opNummer ? ` · herkend op ${HERKENNING_LABEL[match ?? '']}` : ''}
      </span>
    )
  }
  const laag = fuzzy || (!opNummer && score < drempel)
  const titel = opNummer
    ? `Crediteur herkend op ${HERKENNING_LABEL[match ?? '']} van de factuur (bekend van eerdere facturen of uit RLZ).`
    : fuzzy
      ? 'Crediteur benaderd op naam (fuzzy match tegen de crediteuren-cache) — controleer de keuze.'
      : 'Zekerheid van de AI-extractie voor dit veld.'
  return (
    <span className={`chip ${laag ? 'afwijking' : 'ok'}`} title={titel}>
      AI {zekerheidPct(score)}
      {fuzzy ? ' · naam benaderd' : opNummer ? ` · herkend op ${HERKENNING_LABEL[match ?? '']}` : ''}
    </span>
  )
}

interface GeheugenChipBlokProps {
  veld: GeheugenVeldVoorstelDto
  huidig: string | null
  handmatig: boolean
  opties: ComboboxOptie[]
}

/** Geheugen-chip onder een regel-combobox (UI-koppeling boekingsgeheugen): rustig groen bij hoge
 * confidence, oranje (bestaande afwijking-styling) bij laag vertrouwen óf wanneer de huidige
 * (extractie- of opgeslagen) waarde afwijkt van het geheugen — markeren, nooit overnemen.
 * Verdwijnt zodra de controleur het veld zelf aanraakt: die keuze is van de mens, de leerlus
 * leert er bij het boeken van. Bron beknopt in de tooltip (n observaties, confidence, reden). */
function GeheugenChipBlok({ veld, huidig, handmatig, opties }: GeheugenChipBlokProps) {
  const stand = bepaalGeheugenChip(veld, huidig, handmatig)
  if (!stand) return null
  const pct = zekerheidPct(stand.confidence)
  const bron = `Uit geheugen — ${stand.telling} observatie${stand.telling === 1 ? '' : 's'}, confidence ${pct}`
  if (stand.soort === 'afwijkend') {
    return (
      <div style={{ marginTop: 4 }}>
        <span
          className="chip afwijking"
          style={{ whiteSpace: 'normal', textAlign: 'left' }}
          title={`${bron}. De huidige waarde (uit de extractie of het opgeslagen voorstel) wijkt hiervan af — controleer de keuze.`}
        >
          Geheugen: {optieWeergave(opties, stand.waarde)}
        </span>
      </div>
    )
  }
  const hint = stand.oranje ? korteReden(stand.reden) : null
  return (
    <div style={{ marginTop: 4 }}>
      <span
        className={`chip ${stand.oranje ? 'afwijking' : 'ok'}`}
        title={stand.reden ? `${bron}. Let op: ${stand.reden}.` : `${bron}.`}
      >
        Geheugen {pct}
      </span>
      {hint && <div style={{ fontSize: 11, color: 'var(--orange)', marginTop: 2 }}>{hint}</div>}
    </div>
  )
}

/** Uitkomst van de boekknop voor de aanroeper (deel 4 punt 1: toast + doorloop naar het volgende
 * document van dezelfde klant). `staande_goedkeuring` = ter accordering aangeboden én direct
 * geboekt (alles_akkoord + geboekt in de response). `waarschuwing` = iets ging ná de geslaagde
 * hoofdactie (deels) mis en moet zichtbaar blijven (doorbelasting-fout, boek_fout). */
export interface GeboektInfo {
  uitkomst: 'geboekt' | 'ter_accordering' | 'staande_goedkeuring'
  referentie: string | null
  boekstuknummer: string | null
  waarschuwing?: string
}

/** Imperatieve brug voor een van buiten aangeleverde regel (aanbetaling-verrekenregel, deel 4
 * punt 3): elke nieuwe `volgnummer` voegt de regel één keer toe aan de regel-lijst. */
export interface ToeTeVoegenRegel {
  volgnummer: number
  ledger_id: string
  netto_bedrag: number
  btw_bedrag: number
  omschrijving: string
}

interface Props {
  administratieId: string
  documentId: string
  status: string
  veldvoorstel?: Record<string, unknown> | null
  onGeboekt: (info: GeboektInfo) => void
  onHersteld: () => void
  /** Vragenworkflow (mockup: "Vraag stellen…"-knop naast de boekknop): alleen meegegeven vanuit
   * statussen waaruit een vraag gesteld kan worden — undefined verbergt de knop. */
  onVraagStellen?: () => void
  /** Afwijzen-workflow (mockup: "Afwijzen…"-knop in de actiebalk): zelfde patroon —
   * alleen meegegeven vanuit statussen waaruit afgewezen kan worden. */
  onAfwijzen?: () => void
  /** IBAN-wissel vier-ogen (PART B): callback na het aanbieden van een afwijkend IBAN bij een
   * geblokkeerde IBAN-wissel-check — het detailscherm herlaadt dan (document gaat naar
   * wacht_op_iban_accordering en de accordering-sectie verschijnt). */
  onIbanAangeboden?: () => void
  /** Klaargezette doorbelasting (besluit 25-08, blok "Doorbelasten na boeken"): de knop wordt
   * "Boeken + doorbelasten" en is pas actief als óók de doorbelasting-checks groen zijn
   * (`geblokkeerd` + reden komen uit het blok; de server hertoetst). null/undefined = geen. */
  doorbelastingKlaargezet?: { runId: string; geblokkeerd: boolean; reden: string | null } | null
  /** Ná elke geslaagde opslag van het boekvoorstel (regels krijgen nieuwe id's) — het
   * doorbelasting-blok herlaadt dan zijn bron-regels + run. */
  onVoorstelOpgeslagen?: () => void
  /** Van buiten aangeleverde regel (aanbetaling-verrekenregel): wordt toegevoegd zodra het
   * volgnummer verandert — zelfde pad als "+ Regel toevoegen", dus mét checks-herrun. */
  toeTeVoegenRegel?: ToeTeVoegenRegel | null
  /** Actiebalk-positie (feedback Peter 27-08): de balk Afwijzen / Vraag stellen / Ter accordering /
   * Boeken (+ doorbelasten) rendert via een portal in dit element — het controlescherm zet dat
   * ÓNDER het blok "Doorbelasten na boeken" (eerst de verdeling zien, dan de besluitknoppen).
   * undefined = inline op de oude plek (losse panelen, tests); null = doel nog niet gemonteerd
   * (één commit) → even niets, zodat de balk nooit kort op de verkeerde plek flitst. */
  actiebalkDoel?: HTMLElement | null
  /** Sneltoetsen (werkstroom-run 27/28-08, punt 5): het paneel meldt zijn actieve besluitknop —
   * `boeken()` doet exact wat de knop doet (Boeken / Boeken + doorbelasten / Ter accordering),
   * `kanBoeken` spiegelt de disabled-stand. Stabiele callback verwacht (ref-patroon). */
  onActies?: (acties: { boeken: () => void; kanBoeken: boolean; boekLabel: string }) => void
  /** Onopgeslagen wijzigingen (punt 1c/5): true zolang een invoerwijziging nog niet (gedebounced)
   * is opgeslagen en gecontroleerd — het scherm vraagt dan bevestiging bij ‹ ›/Esc/pijltjes. */
  onOnopgeslagenWijzigingen?: (heeft: boolean) => void
  /** Controlescherm v2 (02-09): stand van de harde checks naar buiten (topbar-chip "alle controles
   * groen ✓"); de inklapregel "Controles" en de afwijkingen-banner rendert het paneel zelf. */
  onChecksStand?: (stand: ChecksStand | null) => void
  /** B1 (04-09): lege stand van de project-kolom = actie "Verdelen over projecten…" — opent het
   * Projectverdeling-blok (vaste regels en/of pro rato omzet) voor de regels zonder project. */
  onVerdelenGevraagd?: () => void
  /** B3-dekking (bugfix 04-09): telt op ná élke opslag van de projectverdeling — het paneel draait dan de
   * read-only checks opnieuw (POST …/boekvoorstel/checks, zonder het voorstel te schrijven), zodat "Verplichte
   * velden" en "Projectverdeling" de opgeslagen verdeling direct weerspiegelen. 0 = niets. */
  checksHerrunVersie?: number
  /** B3-dekking: true = de opgeslagen verdeling is geldig en dekt de regels zonder kolom-project — de hint onder de
   * boekingsregels toont dan "gedekt door de projectverdeling" in plaats van de actie. */
  verdelingDektRegels?: boolean
  /** Doel-element voor de inklapregel "Controles (n groen)" — onderaan de werk-kolom (v2 ①).
   * undefined = inline (tests); null = doel nog niet gemonteerd. */
  inklapDoel?: HTMLElement | null
}

export interface ChecksStand {
  bezig: boolean
  actueel: boolean
  rapport: BoekvoorstelMetChecksDto['checks'] | null
}

/** Controlescherm-uitbreiding (CLAUDE.md-taak 2.1, design-pass): kopgegevens + boekingsregels met
 * zoekbare GB-/btw-/project-comboboxen, harde checks zichtbaar (groen/blokkerend), live
 * aansluit-indicator, en de echte boekactie. */
export function BoekvoorstelPanel({
  administratieId,
  documentId,
  status,
  veldvoorstel,
  onGeboekt,
  onHersteld,
  onVraagStellen,
  onAfwijzen,
  onIbanAangeboden,
  doorbelastingKlaargezet = null,
  onVoorstelOpgeslagen,
  toeTeVoegenRegel = null,
  actiebalkDoel,
  onActies,
  onOnopgeslagenWijzigingen,
  onChecksStand,
  inklapDoel,
  onVerdelenGevraagd,
  checksHerrunVersie = 0,
  verdelingDektRegels = false,
}: Props) {
  const ai = useMemo(() => alsAiVoorstel(veldvoorstel), [veldvoorstel])
  // Chips alleen bij een vers (nog niet opgeslagen) AI-voorstel — na opslaan is de invoer van de
  // controleur, niet meer van de AI.
  const [aiChipsActief, setAiChipsActief] = useState(false)
  // "Btw verlegd"-vermelding uit de extractie (punt 3, 26-08) — hint bij 0%-regels zonder code.
  const [verlegdVermelding, setVerlegdVermelding] = useState<string | null>(null)
  const [cacheVersie, setCacheVersie] = useState(0)
  const { opties: grootboekOpties, fout: grootboekFout, laden: grootboekLaden } = useGrootboekOpties(administratieId, cacheVersie)
  const { opties: taxrateOpties, fout: taxrateFout, laden: taxrateLaden } = useTaxrateOpties(administratieId, cacheVersie)
  const percentageMap = useMemo(() => {
    const map: Record<string, number> = {}
    for (const optie of taxrateOpties) if (optie.percentage !== undefined) map[optie.id] = optie.percentage
    return map
  }, [taxrateOpties])
  const { opties: vendorOpties, fout: vendorFout, laden: vendorLaden } = useVendorOpties(administratieId, cacheVersie)
  const { opties: projectOpties, laden: projectLaden } = useProjectOpties(administratieId, cacheVersie)
  const projectVerplicht = useProjectVerplicht(administratieId)
  // Blok A 28-08 (mockup afdelingen.html §2): veld alleen zichtbaar als de toggle aan staat.
  const afdelingen = useAfdelingen(administratieId, cacheVersie)

  const [synchroniserenBezig, setSynchroniserenBezig] = useState(false)
  const [synchroniserenFout, setSynchroniserenFout] = useState<string | null>(null)

  const [laden, setLaden] = useState(true)
  const [ladenFout, setLadenFout] = useState<string | null>(null)
  const [vendorId, setVendorId] = useState<string | null>(null)
  const [referentie, setReferentie] = useState('')
  const [factuurdatum, setFactuurdatum] = useState('')
  const [vervaldatum, setVervaldatum] = useState('')
  const [vervaldatumSignaal, setVervaldatumSignaal] = useState<string | null>(null)
  const [afdelingId, setAfdelingId] = useState<string | null>(null)
  // Prefill uit het leverancier-geheugen: herkomst-chip "🧠 vorige keuze bij <leverancier>" tot de
  // mens het veld aanraakt (dan is het zijn keuze, geen voorstel meer).
  const [afdelingPrefill, setAfdelingPrefill] = useState<{ leverancier: string | null } | null>(null)
  const [totaalbedrag, setTotaalbedrag] = useState('')
  const [regels, setRegels] = useState<RegelState[]>([nieuweRegel()])
  const [boekstuknummer, setBoekstuknummer] = useState<string | null>(null)

  // Fix 3: standaard één samengevoegde boekingsregel, vinkje "splitsen per regel" — keuze wordt
  // per (administratie, crediteur) onthouden (backend LeverancierVoorkeur). De inactieve modus
  // bewaart zijn eigen regels zodat heen-en-weer schakelen geen invoer weggooit. Bij projectplicht
  // is samenvoegen hard uitgesloten (samenvoegen_toegestaan=false van de backend).
  const [regelsSamenvoegen, setRegelsSamenvoegen] = useState(true)
  const [samenvoegenToegestaan, setSamenvoegenToegestaan] = useState(true)
  const [samenvoegenBeschikbaar, setSamenvoegenBeschikbaar] = useState(false)
  const [inactieveRegels, setInactieveRegels] = useState<RegelState[]>([])

  // Fix 2: "nieuwe crediteur aanmaken in RLZ" vanaf het voorstelblok onder het crediteur-veld.
  // v2 ⑥: "+ Nieuwe crediteur in RLZ" als dialoog, voorgevuld uit de scan.
  const [nieuweCrediteurOpen, setNieuweCrediteurOpen] = useState(false)
  const [crediteurMelding, setCrediteurMelding] = useState<string | null>(null)

  const [checkRapport, setCheckRapport] = useState<CheckRapportDto | null>(null)
  // Design-pass taak 7: elke veldwijziging maakt het laatste checkresultaat ongeldig voor de
  // ACTUELE invoer — de knop "Boeken" mag dan niet meer aan staan, ook al was het vorige resultaat
  // groen. De rijen blijven zichtbaar (context), maar duidelijk gemarkeerd als verouderd.
  const [checksActueel, setChecksActueel] = useState(false)
  const [controlerenFout, setControlerenFout] = useState<string | null>(null)
  // Blok B 2026-08-10: geen "Controleren"-knop meer — checks draaien automatisch (bij openen
  // read-only, na elke wijziging gedebounced opslaan + checks); een server-side geblokkeerde
  // boekactie toont de gefaalde checks in een pop-up.
  const [wijzigingsVersie, setWijzigingsVersie] = useState(0)
  const wijzigingsVersieRef = useRef(0)
  const [popupChecks, setPopupChecks] = useState<{ melding: string | null; checks: CheckRapportDto } | null>(null)
  // Factuurmatch fase 2 (besluit 2): 409 mét detail.match = onbevestigde urenmatch-afwijking —
  // pop-up met de cijfers; bevestigen herhaalt de actie mét match_afwijking_bevestigd.
  const [popupMatch, setPopupMatch] = useState<{ melding: string | null; match: MatchAfwijkingDetailDto } | null>(
    null,
  )
  // Materiaalcontrole (steigerbouw-run D6): 409 mét detail.materiaalmatch — zelfde patroon,
  // eigen pop-up; bevestigen herhaalt de actie mét materiaal_afwijking_bevestigd.
  type MateriaalPopupInfo = Pick<MateriaalmatchDto, 'uitkomst' | 'aantal_regels_getoetst' | 'aantal_regels_afwijkend' | 'aantal_regels_onbekend'> & {
    regels?: NonNullable<MateriaalmatchDto['details']>['regels']
  }
  const [popupMateriaal, setPopupMateriaal] = useState<{ melding: string | null; match: MateriaalPopupInfo } | null>(null)
  // Reeds gegeven bevestigingen reizen mee bij een herhaalde poging (beide poorten kunnen achter elkaar bijten).
  const [bevestigingen, setBevestigingen] = useState<{ match: boolean; materiaal: boolean }>({ match: false, materiaal: false })
  const [boekenBezig, setBoekenBezig] = useState(false)
  const [boekenFout, setBoekenFout] = useState<string | null>(null)
  const [boekResultaat, setBoekResultaat] = useState<BoekenResponseDto | null>(null)
  // Klant-accordering (migratie 0033): staat de toggle aan, dan wordt de boekknop
  // "Ter accordering" — direct boeken is server-side sowieso dicht (AccorderingVereist).
  const [accorderingAan, setAccorderingAan] = useState(false)
  // Bugfix-run 28-08: is de LAATSTE accorderingsronde van dít document al afgerond (alle lagen
  // akkoord) maar staat het nog niet geboekt (boeken ná het akkoord faalde, of de oude stille
  // terugval naar klaar_om_te_boeken), dan is de knop weer "Boeken" — nooit een tweede ronde
  // naar de klant. De server-poort toetst hetzelfde (laatste ronde afgerond, bedrag ongewijzigd).
  const [klantAkkoordCompleet, setKlantAkkoordCompleet] = useState(false)
  const effectiefAccorderingAan = accorderingAan && !klantAkkoordCompleet
  const [herstellenBezig, setHerstellenBezig] = useState(false)
  const [herstellenFout, setHerstellenFout] = useState<string | null>(null)

  useEffect(() => {
    let actief = true
    setLaden(true)
    setLadenFout(null)
    apiJson<BoekvoorstelDto>(`/administraties/${administratieId}/documenten/${documentId}/boekvoorstel`)
      .then((dto) => {
        if (!actief) return
        const aiPrefill = !dto.opgeslagen && ai !== null
        setAiChipsActief(aiPrefill)
        setVendorId(dto.vendor_id)
        setReferentie(dto.referentie ?? '')
        setFactuurdatum(dto.factuurdatum ?? '')
        setVervaldatum(dto.vervaldatum ?? '')
        setVervaldatumSignaal(dto.vervaldatum_signaal ?? null)
        if (dto.afdeling_id) {
          setAfdelingId(dto.afdeling_id)
          setAfdelingPrefill(null)
        } else if (dto.afdeling_prefill_id) {
          // Voorstel uit het geheugen — vooraf ingevuld mét chip; de mens beslist (opslaan = keuze).
          setAfdelingId(dto.afdeling_prefill_id)
          setAfdelingPrefill({ leverancier: dto.afdeling_prefill_leverancier ?? null })
        } else {
          setAfdelingId(null)
          setAfdelingPrefill(null)
        }
        setTotaalbedrag(dto.totaalbedrag ?? '')
        setBoekstuknummer(dto.rlz_boekstuknummer)
        setVerlegdVermelding(dto.btw_verlegd_vermelding ?? ai?.btw_verlegd_vermelding ?? null)

        // Fix 3: bepaal de gesplitste én de samengevoegde variant, en welke actief start.
        const opgeslagenSamengevoegd = dto.opgeslagen && dto.regels_samenvoegen && dto.samenvoegen_toegestaan
        const gesplitst = opgeslagenSamengevoegd
          ? ai !== null
            ? regelsUitAi(ai) // dto.regels is hier de opgeslagen samengevoegde regel — splitsen prefillt uit het AI-voorstel
            : [nieuweRegel()]
          : regelsUitDto(dto, aiPrefill ? ai : null)
        const samengevoegd = opgeslagenSamengevoegd
          ? regelsUitDto(dto, null)
          : dto.samengevoegde_regel
            ? [regelUitDtoRegel(dto.samengevoegde_regel)]
            : null
        // Actieve modus volgt de dto-stand (voorkeur per crediteur, default samengevoegd); het
        // vinkje verschijnt alleen als er echt iets te splitsen valt (meer dan één factuurregel).
        const toegestaan = dto.samenvoegen_toegestaan ?? true
        const samenvoegenActief = toegestaan && Boolean(dto.regels_samenvoegen) && samengevoegd !== null
        setSamenvoegenToegestaan(toegestaan)
        setSamenvoegenBeschikbaar(toegestaan && samengevoegd !== null && gesplitst.length > 1)
        setRegelsSamenvoegen(samenvoegenActief)
        setRegels(samenvoegenActief && samengevoegd !== null ? samengevoegd : gesplitst)
        setInactieveRegels(samenvoegenActief || samengevoegd === null ? gesplitst : samengevoegd)
      })
      .catch((err: unknown) => {
        if (actief) setLadenFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
      .finally(() => {
        if (actief) setLaden(false)
      })
    return () => {
      actief = false
    }
  }, [administratieId, documentId, ai])

  // Kliktest-fix: het boekvoorstel bleek nog bewerkbaar na boeken — de backend blokkeert dit nu
  // hard (app/documenten/boekvoorstel.py::_BEVROREN_STATUSSEN), maar de UI hoort een onmogelijke
  // actie niet eens aan te bieden. isReadOnly geldt voor beide bevroren statussen; alleen bij
  // verwijderd is "herstellen" nog een geldige actie.
  const isGeboekt = status === 'geboekt'
  const isVerwijderd = status === 'verwijderd'
  // Afgewezen leest als bevroren voorstel: de banner op het detailscherm (reden + heropenen)
  // is de enige actie — bewerken of boeken kan pas weer ná heropenen.
  const isAfgewezen = status === 'afgewezen'
  // Klant-accordering (migratie 0033): een document dat bij de klant ligt is bevroren — de
  // accorderingssectie op het detailscherm (stappen + intrekken) is daar de enige actie.
  const isTerAccordering = status === 'ter_accordering'
  const isReadOnly = isGeboekt || isVerwijderd || isAfgewezen || isTerAccordering

  // UI-koppeling boekingsgeheugen (B6): zodra de crediteur bekend is (uit de extractie of een
  // handmatige keuze), per weergavemodus het geheugenvoorstel ophalen — samengevoegd =
  // leverancier-niveau (zonder omschrijving), gesplitst = per unieke regel-omschrijving, altijd
  // in de request-body. Bewust géén refetch per toetsaanslag in de omschrijving: crediteur en
  // modus zijn het signaal. De regels reizen via een ref mee zodat dit effect niet op elke
  // regel-wijziging opnieuw vuurt. Mislukt de call, dan degradeert het scherm stil naar "geen
  // voorstel" — de controleur kiest dan zelf, precies zoals vóór deze koppeling; de harde checks
  // draaien onverminderd op de uiteindelijke waarden.
  const regelsRef = useRef(regels)
  regelsRef.current = regels

  useEffect(() => {
    if (laden || isReadOnly) return
    if (!vendorId) {
      // Crediteur weggehaald: chips/foutindicatie van de vorige crediteur zouden misleiden.
      setRegels((huidig) =>
        huidig.some((r) => r.geheugen !== null || r.geheugenFout)
          ? huidig.map((r) => ({ ...r, geheugen: null, geheugenFout: false }))
          : huidig,
      )
      return
    }
    let actief = true
    const sleutels = regelsSamenvoegen
      ? [null]
      : [...new Set(regelsRef.current.map((r) => omschrijvingSleutel(r.omschrijving)))]
    void Promise.all(
      sleutels.map(async (sleutel) => {
        try {
          return [sleutel, await haalGeheugenVoorstel(administratieId, vendorId, sleutel)] as const
        } catch {
          return [sleutel, null] as const
        }
      }),
    ).then((paren) => {
      if (!actief) return
      const voorstellen = new Map<string | null, GeheugenVoorstelDto | null>(paren)
      const voorstelVoor = (r: RegelState) =>
        voorstellen.get(regelsSamenvoegen ? null : omschrijvingSleutel(r.omschrijving)) ?? null
      // Staleness vóór de functionele update bepalen: vult de prefill echt iets, dan is een
      // eerder checkresultaat niet meer actueel (zelfde regel als elke handmatige wijziging).
      const vultIets = regelsRef.current.some((r) => {
        const voorstel = voorstelVoor(r)
        return voorstel !== null && Object.keys(bepaalPrefill(r, voorstel, projectVerplicht)).length > 0
      })
      setRegels((huidig) =>
        huidig.map((r) => {
          // Regel kwam er ná het ophalen bij (sleutel onbekend): geen voorstel én geen fout.
          if (!voorstellen.has(regelsSamenvoegen ? null : omschrijvingSleutel(r.omschrijving))) return r
          const voorstel = voorstelVoor(r)
          if (voorstel === null) {
            // Call mislukt ≠ leeg geheugen: rustige inline-indicatie i.p.v. stilte.
            return r.geheugen === null && r.geheugenFout ? r : { ...r, geheugen: null, geheugenFout: true }
          }
          const vulling = bepaalPrefill(r, voorstel, projectVerplicht)
          const bijgewerkt: RegelState = { ...r, ...vulling, geheugen: voorstel, geheugenFout: false }
          // Zelfde automatische btw-afleiding als bij een handmatige btw-code-keuze.
          if (vulling.taxrateId && !bijgewerkt.btwHandmatig) {
            const percentage = percentageMap[vulling.taxrateId]
            const netto = bedragAlsGetal(bijgewerkt.netto)
            if (percentage !== undefined && netto !== null) {
              bijgewerkt.btw = formatEuro(berekenBtwBedrag(netto, percentage))
            }
          }
          return bijgewerkt
        }),
      )
      if (vultIets) setChecksActueel(false)
    })
    return () => {
      actief = false
    }
    // Bewust smalle deps (zie comment hierboven): regels via ref, percentageMap best-effort —
    // die opnemen zou per cache-refresh onnodige extra voorstel-requests veroorzaken.
  }, [administratieId, documentId, vendorId, regelsSamenvoegen, laden, isReadOnly, projectVerplicht])

  // Per kopveld: zekerheids-chip zolang de huidige invoer nog gelijk is aan wat de AI voorlas —
  // wijzigt de controleur het veld, dan beschrijft de score de inhoud niet meer en verdwijnt hij.
  const aiKop = useMemo(() => {
    if (!ai || !aiChipsActief || isReadOnly) return null
    const gelijkBedrag = (invoer: string, aiWaarde: string | null) => {
      const a = bedragAlsGetal(invoer)
      const b = aiWaarde !== null ? bedragAlsGetal(aiWaarde) : null
      return a !== null && b !== null && Math.abs(a - b) < 0.005
    }
    return {
      drempel: ai.zekerheid_drempel,
      bron: ai.bron,
      vendor:
        ai.vendor_suggestie && vendorId === ai.vendor_suggestie.vendor_id
          ? { score: ai.zekerheid.leverancier_naam ?? 0, match: ai.vendor_suggestie.match }
          : null,
      referentie:
        ai.factuurnummer !== null && referentie.trim() === ai.factuurnummer && ai.zekerheid.factuurnummer !== undefined
          ? { score: ai.zekerheid.factuurnummer }
          : null,
      factuurdatum:
        ai.factuurdatum !== null && factuurdatum === ai.factuurdatum && ai.zekerheid.factuurdatum !== undefined
          ? { score: ai.zekerheid.factuurdatum }
          : null,
      vervaldatum:
        ai.vervaldatum !== null && vervaldatum === ai.vervaldatum && ai.zekerheid.vervaldatum !== undefined
          ? { score: ai.zekerheid.vervaldatum }
          : null,
      totaalbedrag:
        gelijkBedrag(totaalbedrag, ai.totaal_incl) && ai.zekerheid.totaal_incl !== undefined
          ? { score: ai.zekerheid.totaal_incl }
          : null,
    }
  }, [ai, aiChipsActief, isReadOnly, vendorId, referentie, factuurdatum, vervaldatum, totaalbedrag])

  // Vervaldatum-signalen (C1 26-08), deterministisch en direct bij invoer: vóór de factuurdatum =
  // wordt door de harde check geblokkeerd (hier alvast rood), termijn > 90 dagen = oranje signaal
  // (geen blokkade) — dezelfde grens als checks.py::VERVALDATUM_TERMIJN_SIGNAAL_DAGEN.
  const vervaldatumHint = useMemo(() => {
    if (!vervaldatum || !factuurdatum) {
      return vervaldatumSignaal ? { tekst: vervaldatumSignaal, kleur: 'var(--orange)' } : null
    }
    const dagen = Math.round((Date.parse(vervaldatum) - Date.parse(factuurdatum)) / 86_400_000)
    if (Number.isNaN(dagen)) return null
    if (dagen < 0) return { tekst: 'Vervaldatum ligt vóór de factuurdatum — blokkeert boeken', kleur: 'var(--red)' }
    if (dagen > 90) {
      return {
        tekst: `Betaaltermijn van ${dagen} dagen is ongebruikelijk lang — controleer de vervaldatum`,
        kleur: 'var(--orange)',
      }
    }
    return null
  }, [vervaldatum, factuurdatum, vervaldatumSignaal])

  const veranderInvoer = () => {
    setChecksActueel(false)
    wijzigingsVersieRef.current += 1
    setWijzigingsVersie(wijzigingsVersieRef.current)
  }

  const wijzigVendorId = (id: string | null) => {
    setVendorId(id)
    veranderInvoer()
  }
  const wijzigReferentie = (waarde: string) => {
    setReferentie(waarde)
    veranderInvoer()
  }
  const wijzigFactuurdatum = (waarde: string) => {
    setFactuurdatum(waarde)
    veranderInvoer()
  }
  const wijzigTotaalbedrag = (waarde: string) => {
    setTotaalbedrag(waarde)
    veranderInvoer()
  }

  const wijzigRegel = (key: string, veld: keyof RegelState, waarde: string | null) => {
    setRegels((huidig) =>
      huidig.map((r) => {
        if (r.key !== key) return r
        // Elke handmatige wijziging: de AI-zekerheidsscore beschrijft deze regel niet meer.
        const bijgewerkt = { ...r, [veld]: waarde, aiZekerheid: null }
        if (veld === 'ledgerId' || veld === 'taxrateId' || veld === 'projectId') {
          // Vanaf nu is dit veld van de mens: het boekingsgeheugen vult of markeert het nooit meer.
          bijgewerkt.handmatigeVelden = { ...r.handmatigeVelden, [veld]: true }
        }
        if (veld === 'btw') {
          // Rechtstreekse invoer in het btw-veld zelf — vanaf nu is dit veld van de gebruiker;
          // leegmaken laat de automatische afleiding weer meedraaien (design-pass taak 3).
          bijgewerkt.btwHandmatig = waarde !== ''
        } else if ((veld === 'netto' || veld === 'taxrateId') && !bijgewerkt.btwHandmatig) {
          // Nog niet handmatig aangeraakt: btw-bedrag blijft live meebewegen met netto/percentage.
          const percentage = bijgewerkt.taxrateId ? percentageMap[bijgewerkt.taxrateId] : undefined
          const netto = bedragAlsGetal(bijgewerkt.netto)
          bijgewerkt.btw = percentage !== undefined && netto !== null ? formatEuro(berekenBtwBedrag(netto, percentage)) : ''
        }
        return bijgewerkt
      }),
    )
    veranderInvoer()
  }

  /** Fix 3: schakelen tussen samengevoegd en per-regel — beide modi bewaren hun eigen regels,
   * dus heen-en-weer schakelen gooit geen invoer weg. De keuze reist mee met de eerstvolgende
   * "Controleren" (PUT) en wordt daar als voorkeur per crediteur onthouden. */
  const wisselSamenvoegen = (samenvoegen: boolean) => {
    if (samenvoegen === regelsSamenvoegen) return
    setRegelsSamenvoegen(samenvoegen)
    setRegels(inactieveRegels)
    setInactieveRegels(regels)
    veranderInvoer()
  }

  const verwijderRegel = (key: string) => {
    setRegels((huidig) => (huidig.length > 1 ? huidig.filter((r) => r.key !== key) : huidig))
    veranderInvoer()
  }

  const voegRegelToe = () => {
    setRegels((r) => [...r, nieuweRegel()])
    veranderInvoer()
  }

  // Aanbetaling-verrekenregel (deel 4 punt 3): elke nieuwe aanlevering (volgnummer) wordt één
  // keer als regel toegevoegd — negatief netto op de vooruit-rekening, btw 0. Btw-code: het
  // 0%-tarief uit de sync-cache als dat eenduidig is ("Nul tarief"/enige 0%-optie), anders leeg
  // en kiest de mens. Niet in read-only (het scherm biedt de knop dan ook niet aan).
  const verwerktVolgnummer = useRef<number | null>(null)
  useEffect(() => {
    if (!toeTeVoegenRegel || isReadOnly) return
    if (verwerktVolgnummer.current === toeTeVoegenRegel.volgnummer) return
    verwerktVolgnummer.current = toeTeVoegenRegel.volgnummer
    const nulOpties = taxrateOpties.filter((o) => o.percentage === 0)
    const nulTarief =
      nulOpties.find((o) => /nul/i.test(o.label)) ?? (nulOpties.length === 1 ? nulOpties[0] : undefined)
    const regel: RegelState = {
      ...nieuweRegel(),
      ledgerId: toeTeVoegenRegel.ledger_id,
      taxrateId: nulTarief?.id ?? null,
      netto: toeTeVoegenRegel.netto_bedrag.toFixed(2),
      btw: toeTeVoegenRegel.btw_bedrag.toFixed(2),
      btwHandmatig: true,
      omschrijving: toeTeVoegenRegel.omschrijving,
      handmatigeVelden: { ledgerId: true, taxrateId: nulTarief !== undefined, projectId: false },
    }
    setRegels((r) => [...r, regel])
    veranderInvoer()
    // Bewust alleen op het volgnummer: taxrateOpties/isReadOnly zijn context, geen trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [toeTeVoegenRegel?.volgnummer])

  // Fix 2: de AI las een leveranciersnaam, maar het crediteur-veld is (nog) leeg — nooit een
  // leeg verplicht veld zonder handelingsperspectief. Voorstelblok met de gelezen naam +
  // zekerheid, klikbare koppel-suggesties uit de cache, en "nieuwe crediteur aanmaken in RLZ".
  const aiLeverancierNaam = ai?.leverancier_naam?.trim() || null
  const crediteurVoorstellen = useMemo(
    () => (aiLeverancierNaam ? crediteurSuggesties(aiLeverancierNaam, vendorOpties) : []),
    [aiLeverancierNaam, vendorOpties],
  )

  const naNieuweCrediteur = (resultaat: NieuweCrediteurResultaat) => {
    setNieuweCrediteurOpen(false)
    setCacheVersie((v) => v + 1)
    wijzigVendorId(resultaat.id)
    const delen: string[] = []
    if (resultaat.kvk_opgeslagen) delen.push('KvK')
    if (resultaat.btw_opgeslagen) delen.push('btw')
    if (resultaat.iban_vertrouwd) delen.push('IBAN vertrouwd')
    const w = resultaat.waarschuwingen ?? []
    setCrediteurMelding(
      `Crediteur „${resultaat.naam ?? ''}” aangemaakt in RLZ${delen.length ? ` · onthouden: ${delen.join(', ')}` : ''}${w.length ? ` · let op: ${w.join('; ')}` : ''}`,
    )
  }
  const naBestaandeCrediteur = (vendorId: string) => {
    // 409 = bestond al (bv. net gesynchroniseerd): de bestaande selecteren is voor de controleur
    // hetzelfde eindresultaat.
    setNieuweCrediteurOpen(false)
    setCacheVersie((v) => v + 1)
    wijzigVendorId(vendorId)
  }

  const nuSynchroniseren = async () => {
    setSynchroniserenBezig(true)
    setSynchroniserenFout(null)
    const fouten = await synchroniseerAlleCaches(administratieId)
    if (fouten.length > 0) setSynchroniserenFout(fouten.join('; '))
    setCacheVersie((v) => v + 1)
    setSynchroniserenBezig(false)
  }

  /** Opslaan + checks in één PUT — draait automatisch (gedebounced) na elke wijziging;
   * dit was de vroegere "Controleren"-knop. */
  const controleren = async () => {
    setControlerenFout(null)
    setBoekenFout(null)
    setBoekResultaat(null)
    const versieBijStart = wijzigingsVersieRef.current
    try {
      const resultaat = await apiJson<BoekvoorstelMetChecksDto>(
        `/administraties/${administratieId}/documenten/${documentId}/boekvoorstel`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            vendor_id: vendorId,
            referentie: referentie || null,
            factuurdatum: factuurdatum || null,
            vervaldatum: vervaldatum || null,
            // Blok A 28-08: alleen meesturen als de toggle aan staat (uit = veld onzichtbaar, keuze blijft).
            afdeling_id: afdelingen.ingeschakeld ? afdelingId : null,
            totaalbedrag: totaalbedrag ? normaliseerBedrag(totaalbedrag) : null,
            // Fix 3: de weergavekeuze reist mee en wordt backend-side als voorkeur per
            // (administratie, crediteur) onthouden; null = geen keuze door te geven.
            regels_samenvoegen: samenvoegenToegestaan ? regelsSamenvoegen : null,
            regels: regels.map((r) => ({
              ledger_id: r.ledgerId,
              taxrate_id: r.taxrateId,
              project_id: projectVerplicht ? r.projectId : null,
              netto_bedrag: r.netto ? normaliseerBedrag(r.netto) : null,
              btw_bedrag: r.btw ? normaliseerBedrag(r.btw) : null,
              omschrijving: r.omschrijving || null,
            })),
          }),
        },
      )
      if (wijzigingsVersieRef.current === versieBijStart) {
        setCheckRapport(resultaat.checks)
        setChecksActueel(true)
      }
      onVoorstelOpgeslagen?.()
    } catch (err) {
      setControlerenFout(err instanceof ApiError ? err.message : 'Checks uitvoeren mislukt.')
    }
  }

  /** Checks bij openen: read-only over het al opgeslagen voorstel, zonder te schrijven
   * (POST …/boekvoorstel/checks). Een document zonder opgeslagen voorstel geeft gewoon een
   * rapport over de prefill; een fout laat het paneel leeg — de debounce-run herstelt dat. */
  const checksBijOpenen = async () => {
    const versieBijStart = wijzigingsVersieRef.current
    const rapport = await apiJson<CheckRapportDto>(
      `/administraties/${administratieId}/documenten/${documentId}/boekvoorstel/checks`,
      { method: 'POST' },
    )
    // Vorm-validatie: alleen een écht CheckRapport toepassen — een onverwacht antwoord laat
    // het paneel in de neutrale beginstand (de debounce-run herstelt dat na een wijziging).
    if (wijzigingsVersieRef.current === versieBijStart && rapport && Array.isArray(rapport.resultaten)) {
      setCheckRapport(rapport)
      setChecksActueel(true)
    }
  }

  useEffect(() => {
    let actief = true
    apiJson<{ ingeschakeld: boolean }>(`/administraties/${administratieId}/accordering/instellingen`)
      .then((dto) => {
        if (actief) setAccorderingAan(dto.ingeschakeld)
      })
      .catch(() => {
        // Stil degraderen naar de gewone boekknop — de server blokkeert direct boeken toch hard.
        if (actief) setAccorderingAan(false)
      })
    apiJson<{ status: string } | null>(`/administraties/${administratieId}/accordering/documenten/${documentId}`)
      .then((dto) => {
        if (actief) setKlantAkkoordCompleet(dto?.status === 'afgerond')
      })
      .catch(() => {
        if (actief) setKlantAkkoordCompleet(false)
      })
    return () => {
      actief = false
    }
  }, [administratieId, documentId, status])

  const boeken = async (matchBevestigd = false, materiaalBevestigd = false) => {
    const vlaggen = { match: matchBevestigd || bevestigingen.match, materiaal: materiaalBevestigd || bevestigingen.materiaal }
    setBevestigingen(vlaggen)
    setBoekenBezig(true)
    setBoekenFout(null)
    try {
      // Accordering aan → de knop biedt het document ter accordering aan (zelfde 409-vorm bij
      // geblokkeerde checks als de boek-route); staande goedkeuringen kunnen direct tot boeken
      // leiden (alles_akkoord + geboekt in de response).
      const pad = effectiefAccorderingAan
        ? `/administraties/${administratieId}/accordering/documenten/${documentId}/aanbieden`
        : `/administraties/${administratieId}/documenten/${documentId}/boeken`
      const resp = await apiFetch(pad, {
        method: 'POST',
        // Alleen mét een bewuste bevestiging reist er een body mee — het kale POST-contract
        // blijft ongewijzigd (factuurmatch fase 2).
        ...(vlaggen.match || vlaggen.materiaal
          ? {
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ match_afwijking_bevestigd: vlaggen.match, materiaal_afwijking_bevestigd: vlaggen.materiaal }),
            }
          : {}),
      })
      const body: unknown = await resp.json().catch(() => null)

      const referentieVoorMelding = referentie.trim() || null
      if (resp.ok && effectiefAccorderingAan) {
        const resultaat = body as { geboekt: boolean; boek_fout: string | null; alles_akkoord: boolean }
        if (resultaat.boek_fout) setBoekenFout(resultaat.boek_fout)
        setPopupMatch(null)
        onGeboekt({
          uitkomst: resultaat.geboekt ? 'staande_goedkeuring' : 'ter_accordering',
          referentie: referentieVoorMelding,
          boekstuknummer: null,
          waarschuwing: resultaat.boek_fout ?? undefined,
        })
        return
      }
      if (resp.ok) {
        const resultaat = body as BoekenResponseDto
        setBoekResultaat(resultaat)
        setBoekstuknummer(resultaat.rlz_boekstuknummer)
        setPopupMatch(null)
        // "Boeken + doorbelasten": de inkoop staat; een (deels) mislukte doorbelasting is een
        // zichtbare melding (nooit stil) — herstel via de Doorbelasten-sectie op het document.
        if (resultaat.doorbelasting_fout) {
          setBoekenFout(`Inkoopfactuur geboekt; doorbelasting (deels) mislukt: ${resultaat.doorbelasting_fout}`)
        }
        onGeboekt({
          uitkomst: 'geboekt',
          referentie: referentieVoorMelding,
          boekstuknummer: resultaat.rlz_boekstuknummer,
          waarschuwing: resultaat.doorbelasting_fout
            ? `doorbelasting (deels) mislukt: ${resultaat.doorbelasting_fout}`
            : undefined,
        })
        return
      }

      // Bij BoekenGeblokkeerdDoorChecks (409) stuurt de router het CheckRapport mee in
      // detail.checks (een object, geen platte string) — dat kan de generieke apiJson/ApiError-
      // afhandeling niet uitpakken, dus hier rechtstreeks de rauwe Response gebruiken.
      const detail = body && typeof body === 'object' ? (body as { detail?: unknown }).detail : null
      if (resp.status === 409 && detail && typeof detail === 'object' && 'checks' in detail) {
        const { message, checks } = detail as { message?: string; checks: unknown }
        const rapport = checks as BoekvoorstelMetChecksDto['checks']
        setCheckRapport(rapport)
        setChecksActueel(true)
        // Blok B: de server-side herdraaide checks blokkeren → pop-up met de concrete
        // gefaalde check(s); de inline lijst blijft daarnaast staan.
        setPopupChecks({ melding: message ?? null, checks: rapport })
      } else if (resp.status === 409 && detail && typeof detail === 'object' && 'match' in detail) {
        // Factuurmatch fase 2: onbevestigde urenmatch-afwijking → bevestigingspop-up.
        const { message, match } = detail as { message?: string; match: MatchAfwijkingDetailDto }
        setPopupMatch({ melding: message ?? null, match })
      } else if (resp.status === 409 && detail && typeof detail === 'object' && 'materiaalmatch' in detail) {
        // Steigerbouw-run D6: onbevestigde materiaal-afwijking → eigen pop-up.
        const { message, materiaalmatch } = detail as { message?: string; materiaalmatch: MateriaalPopupInfo }
        setPopupMatch(null)
        setPopupMateriaal({ melding: message ?? null, match: materiaalmatch })
      } else {
        setBoekenFout(typeof detail === 'string' ? detail : resp.statusText || `Fout (${resp.status})`)
      }
    } catch (err) {
      setBoekenFout(err instanceof ApiError ? err.message : 'Boeken mislukt.')
    } finally {
      setBoekenBezig(false)
    }
  }

  const herstellen = async () => {
    setHerstellenBezig(true)
    setHerstellenFout(null)
    try {
      await apiPostJson<DocumentActieResponseDto>(
        `/administraties/${administratieId}/documenten/${documentId}/herstellen`,
        {},
      )
      onHersteld()
    } catch (err) {
      setHerstellenFout(err instanceof ApiError ? err.message : 'Herstellen mislukt.')
    } finally {
      setHerstellenBezig(false)
    }
  }

  const totaalAlsGetal = useMemo(() => bedragAlsGetal(totaalbedrag), [totaalbedrag])
  // Bugfix 04-09 (Huvanco): de aansluit-badge volgt EXACT de backend-beslisboom (document/regelsom.ts ↔
  // backend regelsom.py): ontbreekt de btw per regel, dan netto-vs-netto tegen het GELEZEN excl-totaal
  // (AI/template `totaal_excl`, UBL idem) of Σnetto + gelezen factuur-btw (`btw_bedrag` / UBL `totaal_btw`)
  // tegen incl — nooit meer stil Σnetto (excl) tegen het incl-totaal.
  const gelezenExcl = veldvoorstelBedrag(veldvoorstel, 'totaal_excl')
  const gelezenBtw = veldvoorstelBedrag(veldvoorstel, 'btw_bedrag') ?? veldvoorstelBedrag(veldvoorstel, 'totaal_btw')
  const regelsomToets = useMemo(
    () =>
      toetsRegelsom({
        netto: regels.map((r) => bedragAlsGetal(r.netto)),
        btw: regels.map((r) => bedragAlsGetal(r.btw)),
        totaalIncl: totaalAlsGetal,
        totaalExcl: gelezenExcl,
        factuurBtw: gelezenBtw,
      }),
    [regels, totaalAlsGetal, gelezenExcl, gelezenBtw],
  )

  // B3-dekking (bugfix 04-09): ná een opslag van de projectverdeling de read-only checks herdraaien — zonder
  // schrijven, zodat een lopende debounce-wijziging niet overschreven wordt (de versie-guard in checksBijOpenen
  // laat een intussen verouderd resultaat vallen).
  const checksBijOpenenRef = useRef(checksBijOpenen)
  checksBijOpenenRef.current = checksBijOpenen
  useEffect(() => {
    if (checksHerrunVersie === 0 || laden || ladenFout !== null || isReadOnly) return
    setChecksActueel(false)
    void checksBijOpenenRef.current().catch(() => undefined)
  }, [checksHerrunVersie, laden, ladenFout, isReadOnly])

  // Blok B 2026-08-10: checks draaien automatisch — bij openen (read-only) en gedebounced na
  // elke wijziging (opslaan + checks via de bestaande PUT). Geen "Controleren"-knop meer.
  const { checksBezig } = useAutoChecks({
    actief: !laden && ladenFout === null && !isReadOnly,
    wijzigingsVersie,
    bijOpenen: checksBijOpenen,
    bijWijziging: controleren,
  })

  // A2 (besluit 25-08): mét klaargezette doorbelasting moeten boek-checks én
  // doorbelasting-checks samen groen zijn vóór de knop actief wordt.
  const doorbelastingBlokkeert = doorbelastingKlaargezet?.geblokkeerd === true
  const kanBoeken =
    !laden &&
    ladenFout === null &&
    checkRapport !== null &&
    checksActueel &&
    !checkRapport.geblokkeerd &&
    !isReadOnly &&
    !doorbelastingBlokkeert
  const boekLabel = effectiefAccorderingAan
    ? doorbelastingKlaargezet
      ? 'Ter accordering (+ doorbelasten) →'
      : 'Ter accordering →'
    : klantAkkoordCompleet
      ? doorbelastingKlaargezet
        ? 'Boeken + doorbelasten (klant-akkoord compleet) ✓'
        : 'Boeken in RLZ (klant-akkoord compleet) ✓'
      : doorbelastingKlaargezet
        ? 'Boeken + doorbelasten ✓'
        : 'Boeken in RLZ ✓'

  // Punt 5: de actieve besluitknop naar buiten melden (sneltoets B doet exact de knop-klik);
  // `boeken` wisselt per render van identiteit → via ref, zodat de melding alleen bij een echte
  // standwijziging vuurt.
  const boekenRef = useRef(boeken)
  boekenRef.current = boeken
  const kanBoekenNu = kanBoeken && !boekenBezig
  useEffect(() => {
    onActies?.({ boeken: () => void boekenRef.current(), kanBoeken: kanBoekenNu, boekLabel })
  }, [onActies, kanBoekenNu, boekLabel])
  // Punt 1c/5: onopgeslagen = er is gewijzigd (versie > 0) en de debounce-run heeft de checks
  // nog niet actueel gemaakt (of loopt nog).
  const heeftOnopgeslagen = !isReadOnly && wijzigingsVersie > 0 && (!checksActueel || checksBezig)
  useEffect(() => {
    onOnopgeslagenWijzigingen?.(heeftOnopgeslagen)
  }, [onOnopgeslagenWijzigingen, heeftOnopgeslagen])
  useEffect(() => {
    if (isReadOnly) {
      onChecksStand?.(null)
      return
    }
    onChecksStand?.({ bezig: checksBezig, actueel: checksActueel, rapport: checkRapport })
  }, [onChecksStand, isReadOnly, checksBezig, checksActueel, checkRapport])

  if (laden) return <div className="panel">Boekvoorstel laden…</div>
  if (ladenFout) return <div className="fout">Kon boekvoorstel niet laden: {ladenFout}</div>
  const boekenTitel = isReadOnly
    ? undefined
    : checkRapport === null
      ? 'De harde checks draaien automatisch — boeken kan zodra alle checks groen zijn.'
      : !checksActueel
        ? 'Er zijn wijzigingen sinds de laatste controle — de checks draaien zo automatisch opnieuw.'
        : checkRapport.geblokkeerd
          ? 'Boeken geblokkeerd — een of meer harde checks zijn niet groen.'
          : doorbelastingBlokkeert
            ? `Boeken + doorbelasten geblokkeerd — ${doorbelastingKlaargezet?.reden ?? 'doorbelasting nog niet groen'}`
            : undefined
  return (
    <>
      {!isReadOnly && (
        <div className="panel crediteur-kaart" data-testid="crediteur-kaart">
          <h2>Crediteur</h2>
          {synchroniserenFout && <div className="fout">Synchroniseren gaf fouten: {synchroniserenFout}</div>}
          {!vendorLaden && vendorOpties.length === 0 && !vendorFout && (
            <LegeCacheBanner naam="crediteuren" bezig={synchroniserenBezig} onSynchroniseren={() => void nuSynchroniseren()} />
          )}
          {vendorFout && <div className="fout">Kon crediteuren niet laden: {vendorFout}</div>}
          <div style={{ maxWidth: 520 }}>

                <SearchableCombobox
                  label="Crediteur"
                  opties={vendorOpties}
                  waarde={vendorId}
                  onWijzig={wijzigVendorId}
                  vereist
                  fout={checkRapport?.geblokkeerd && vendorId === null}
                />
                {aiKop?.vendor && (
                  <div style={{ marginTop: 4 }}>
                    <AiChip score={aiKop.vendor.score} drempel={aiKop.drempel} match={aiKop.vendor.match} bron={aiKop.bron} />
                  </div>
                )}
                {/* Punt 14 (28-08): btw-/KvK-nummer van de leverancier uit de factuur — herkomst-chip conform
                    de andere kopvelden; wordt per crediteur onthouden zodra het voorstel mét crediteur is
                    opgeslagen (voedt nummer-match + duplicaat over crediteuren heen). */}
                {(ai?.btw_nummer || ai?.kvk_nummer) && (
                  <div className="hint" style={{ marginTop: 4, display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                    {ai?.btw_nummer && (
                      <span
                        className={`chip ${ai.btw_nummer_geverifieerd ? 'ok' : 'afwijking'}`}
                        title={
                          ai.btw_nummer_geverifieerd
                            ? 'Btw-nummer uit de factuur — vorm én elfproef/mod-97 kloppen.'
                            : 'Btw-nummer uit de factuur — vorm klopt, controlegetal niet te verifiëren (controleer).'
                        }
                      >
                        btw {ai.btw_nummer}
                      </span>
                    )}
                    {ai?.kvk_nummer && (
                      <span className="chip ok" title="KvK-nummer uit de factuur (8 cijfers).">
                        KvK {ai.kvk_nummer}
                      </span>
                    )}
                    <span>uit factuur</span>
                  </div>
                )}
                {vendorId === null && aiLeverancierNaam && (
                  <div style={{ marginTop: 6, display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 }}>
                    {/* Chip kort (nooit meerregelig); de gelezen naam als gewone tekst die netjes
                        binnen de grid-kolom afbreekt — een lange leveranciersnaam mag de layout
                        nooit openduwen (Peters visuele controle 2026-07-11). */}
                    <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, flexWrap: 'wrap' }}>
                      {ai?.zekerheid.leverancier_naam !== undefined && (
                        <span className="chip afwijking">AI {zekerheidPct(ai.zekerheid.leverancier_naam)}</span>
                      )}
                      <span style={{ fontSize: 12, color: 'var(--muted)', overflowWrap: 'anywhere', minWidth: 0 }}>
                        AI las: „{aiLeverancierNaam}” — geen eenduidige match in de crediteuren-cache.
                      </span>
                    </div>
                    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                      {crediteurVoorstellen.map((s) => (
                        <button
                          key={s.optie.id}
                          type="button"
                          className="btn secondary"
                          style={{ maxWidth: '100%' }}
                          onClick={() => wijzigVendorId(s.optie.id)}
                        >
                          Koppel aan „{s.optie.label}”
                        </button>
                      ))}
                      <button
                        type="button"
                        className="btn secondary"
                        style={{ maxWidth: '100%' }}
                        title="Maakt idempotent een crediteur aan in Reeleezee, voorgevuld met naam · KvK · btw · IBAN uit de scan"
                        onClick={() => setNieuweCrediteurOpen(true)}
                      >
                        + Nieuwe crediteur in RLZ
                      </button>
                    </div>
                  </div>
                )}
            
          </div>
          {/* KvK-/btw-mismatch-guard (v2 ⑥, casus Hello Kitchen Son ↔ Duiven): een naam-match met
              een ánder nummer wordt NOOIT stil voorgesteld — wél getoond, de mens kiest. */}
          {vendorId === null && ai?.vendor_waarschuwing && (
            <div className="waarschuwing" role="note" data-testid="crediteur-waarschuwing">
              ⚠ Dichtstbijzijnde naam-match <b>„{ai.vendor_waarschuwing.naam}”</b> heeft een{' '}
              <b>ánder {ai.vendor_waarschuwing.reden === 'kvk_afwijkend' ? 'KvK-nummer' : 'btw-nummer'}</b> (
              {ai.vendor_waarschuwing.kandidaat_nummer} i.p.v. {ai.vendor_waarschuwing.factuur_nummer} op de factuur) — waarschijnlijk een
              andere vestiging of entiteit. Niet automatisch voorgesteld.{' '}
              <button type="button" className="linkbtn" onClick={() => wijzigVendorId(ai.vendor_waarschuwing!.vendor_id)}>
                toch koppelen
              </button>
            </div>
          )}
          {crediteurMelding && (
            <div className="hint" style={{ color: 'var(--green)' }} role="status">
              {crediteurMelding}
            </div>
          )}
        </div>
      )}
      {nieuweCrediteurOpen && (
        <NieuweCrediteurDialog
          administratieId={administratieId}
          documentId={documentId}
          voorgevuld={{
            naam: aiLeverancierNaam ?? '',
            kvk_nummer: ai?.kvk_nummer ?? null,
            btw_nummer: ai?.btw_nummer ?? null,
            iban: typeof veldvoorstel?.iban === 'string' ? veldvoorstel.iban : null,
          }}
          herkomst={{ kvk: Boolean(ai?.kvk_nummer), btw: Boolean(ai?.btw_nummer), iban: typeof veldvoorstel?.iban === 'string' }}
          onAangemaakt={naNieuweCrediteur}
          onBestaand={naBestaandeCrediteur}
          onSluit={() => setNieuweCrediteurOpen(false)}
        />
      )}
      <div className="panel">
        <h2>Kopgegevens</h2>
        {isReadOnly ? (
          <div className="grid2">
            <StatischVeld label="Crediteur" waarde={optieWeergave(vendorOpties, vendorId)} />
            <StatischVeld label="Referentie / factuurnummer" waarde={referentie} />
            <StatischVeld label="Factuurdatum" waarde={factuurdatum} />
            <StatischVeld label="Vervaldatum" waarde={vervaldatum} />
            {afdelingen.ingeschakeld && (
              <StatischVeld
                label="Afdeling"
                waarde={afdelingen.afdelingen.find((a) => a.id === afdelingId)?.naam ?? ''}
              />
            )}
            <StatischVeld label="Totaalbedrag (incl. btw)" waarde={totaalbedrag ? `€ ${totaalbedrag}` : ''} />
          </div>
        ) : (
          <div className="grid2">
            <div>
              <label htmlFor="boekvoorstel-referentie">Referentie / factuurnummer</label>
              <input
                id="boekvoorstel-referentie"
                value={referentie}
                onChange={(e) => wijzigReferentie(e.target.value)}
              />
              {aiKop?.referentie && (
                <div style={{ marginTop: 4 }}>
                  <AiChip score={aiKop.referentie.score} drempel={aiKop.drempel} bron={aiKop.bron} />
                </div>
              )}
            </div>
            <div>
              <label htmlFor="boekvoorstel-datum">Factuurdatum</label>
              <DatePicker
                id="boekvoorstel-datum"
                value={factuurdatum || null}
                onChange={(v) => wijzigFactuurdatum(v ?? '')}
              />
              {aiKop?.factuurdatum && (
                <div style={{ marginTop: 4 }}>
                  <AiChip score={aiKop.factuurdatum.score} drempel={aiKop.drempel} bron={aiKop.bron} />
                </div>
              )}
            </div>
            <div>
              <label htmlFor="boekvoorstel-vervaldatum">Vervaldatum</label>
              <DatePicker
                id="boekvoorstel-vervaldatum"
                value={vervaldatum || null}
                onChange={(v) => {
                  setVervaldatum(v ?? '')
                  veranderInvoer()
                }}
              />
              {aiKop?.vervaldatum && (
                <div style={{ marginTop: 4 }}>
                  <AiChip score={aiKop.vervaldatum.score} drempel={aiKop.drempel} bron={aiKop.bron} />
                </div>
              )}
              {vervaldatumHint && (
                <div className="hint" style={{ marginTop: 4, color: vervaldatumHint.kleur }}>
                  {vervaldatumHint.tekst}
                </div>
              )}
            </div>
            {afdelingen.ingeschakeld && (
              <div data-testid="afdeling-veld">
                <label htmlFor="boekvoorstel-afdeling">Afdeling</label>
                <Select
                  id="boekvoorstel-afdeling"
                  value={afdelingId ?? ''}
                  onChange={(e) => {
                    setAfdelingId(e.target.value || null)
                    setAfdelingPrefill(null)
                    veranderInvoer()
                  }}
                >
                  <option value="">Kies afdeling…</option>
                  {afdelingen.afdelingen
                    .filter((a) => a.actief || a.id === afdelingId)
                    .map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.naam}
                        {!a.actief ? ' (gearchiveerd)' : ''}
                      </option>
                    ))}
                </Select>
                {afdelingPrefill && afdelingId && (
                  <div style={{ marginTop: 4 }}>
                    <span
                      className="chip geheugen"
                      title="Vorige keuze voor deze leverancier — een voorstel, opslaan maakt het uw keuze"
                    >
                      🧠 vorige keuze{afdelingPrefill.leverancier ? ` bij ${afdelingPrefill.leverancier}` : ''}
                    </span>
                  </div>
                )}
                {!afdelingId && (
                  <div className="hint" style={{ marginTop: 4, color: 'var(--red)' }}>
                    Afdeling ontbreekt — verplicht voor deze administratie
                  </div>
                )}
              </div>
            )}
            <div>
              <label htmlFor="boekvoorstel-totaal">Totaalbedrag (incl. btw)</label>
              <input
                id="boekvoorstel-totaal"
                inputMode="decimal"
                placeholder="1234,56"
                title="Bijvoorbeeld 1234,56 of 1234.56"
                // Kopgegevens-velden staan uniform links (feedbackronde 25-08 deel 3 punt 6);
                // rechts uitlijnen is voorbehouden aan de numerieke kolommen in de regeltabel.
                style={{ fontVariantNumeric: 'tabular-nums' }}
                value={totaalbedrag}
                onChange={(e) => wijzigTotaalbedrag(e.target.value)}
              />
              {aiKop?.totaalbedrag && (
                <div style={{ marginTop: 4 }}>
                  <AiChip score={aiKop.totaalbedrag.score} drempel={aiKop.drempel} bron={aiKop.bron} />
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="panel">
        <h2>Boekingsregels</h2>
        {!isReadOnly && !grootboekLaden && grootboekOpties.length === 0 && !grootboekFout && (
          <LegeCacheBanner naam="het grootboekschema" bezig={synchroniserenBezig} onSynchroniseren={() => void nuSynchroniseren()} />
        )}
        {!isReadOnly && !taxrateLaden && taxrateOpties.length === 0 && !taxrateFout && (
          <LegeCacheBanner naam="btw-codes" bezig={synchroniserenBezig} onSynchroniseren={() => void nuSynchroniseren()} />
        )}
        {!isReadOnly && projectVerplicht && !projectLaden && projectOpties.length === 0 && (
          <LegeCacheBanner naam="projecten" bezig={synchroniserenBezig} onSynchroniseren={() => void nuSynchroniseren()} />
        )}
        {!isReadOnly && (grootboekFout || taxrateFout) && (
          <div className="fout">Kon grootboek- en/of btw-cache niet laden — controleer of deze administratie gesynchroniseerd is.</div>
        )}
        {!isReadOnly && samenvoegenBeschikbaar && (
          <div style={{ marginBottom: 10, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <label className="vink-label">
              <Checkbox checked={!regelsSamenvoegen} onChange={(e) => wisselSamenvoegen(!e.target.checked)} />
              Splitsen per regel
            </label>
            <span className="hint" style={{ margin: 0, flex: '1 1 260px', minWidth: 0 }}>
              {regelsSamenvoegen
                ? `Samengevoegd tot één boekingsregel (${inactieveRegels.length} factuurregels gelezen) — keuze wordt per leverancier onthouden.`
                : 'Losse factuurregels — keuze wordt per leverancier onthouden.'}
            </span>
          </div>
        )}
        <div className="tabel-scroll">
        <table
          className={`lines boekingsregels-tabel${projectVerplicht ? ' met-project' : ''}`}
          // Addendum 27-08 punt 4: minimumbreedte = som van de kolomminima (boekingsregelsKolommen.ts)
          // — te smal paneel = horizontale scroll bínnen .tabel-scroll, nooit kolom-implosie.
          style={{ minWidth: minimaleTabelbreedte(projectVerplicht) }}
          data-testid="boekingsregels-tabel"
        >
          <colgroup>
            {/* Absolute minima per kolom (één bron: boekingsregelsKolommen.ts). Bedragen ruim
                (geld altijd volledig leesbaar); de zoek-comboboxen tonen hun keuze desnoods
                afgekort en zijn in de listbox (≥ 280 px) alsnog volledig leesbaar. Omschrijving
                krijgt de rest boven haar eigen ondergrens en wrapt op woordgrenzen. */}
            <col style={{ width: KOLOM_PX.grootboek }} />
            <col style={{ width: KOLOM_PX.btw }} />
            {projectVerplicht && <col style={{ width: KOLOM_PX.project }} />}
            <col style={{ width: KOLOM_PX.netto }} />
            <col style={{ width: KOLOM_PX.btwBedrag }} />
            <col />
            <col style={{ width: KOLOM_PX.verwijder }} />
          </colgroup>
          <tbody>
            <tr>
              <th>Grootboek</th>
              <th>Btw-code</th>
              {projectVerplicht && <th>Project</th>}
              <th className="amount">Netto</th>
              <th className="amount">Btw-bedrag</th>
              <th>Omschrijving</th>
              <th />
            </tr>
            {regels.map((regel) => {
              const percentage = regel.taxrateId ? percentageMap[regel.taxrateId] : undefined
              const nettoAlsGetal = bedragAlsGetal(regel.netto)
              const verwachtBtw =
                percentage !== undefined && nettoAlsGetal !== null ? berekenBtwBedrag(nettoAlsGetal, percentage) : null
              const huidigBtw = bedragAlsGetal(regel.btw)
              // Regelrij-UI 25-08 (screenshot Peter, LUSSO): alleen een RELEVANTE afwijking is een
              // melding waard — een puur afrondingsverschil (≤ 1 cent tussen netto × tarief en de
              // factuur-btw) niet; de factuur-btw is leidend (bestaand beleid).
              const btwWijktAf =
                verwachtBtw !== null && (huidigBtw === null || Math.abs(huidigBtw - verwachtBtw) > BTW_AFRONDINGSMARGE)
              return (
              <tr key={regel.key}>
                <td>
                  {isReadOnly ? (
                    optieWeergave(grootboekOpties, regel.ledgerId)
                  ) : (
                    <>
                      <SearchableCombobox
                        label="Grootboek"
                        opties={grootboekOpties}
                        waarde={regel.ledgerId}
                        onWijzig={(id) => wijzigRegel(regel.key, 'ledgerId', id)}
                        vereist
                        toonLabel={false}
                      />
                      {(() => {
                        // Blok D 04-09 (mockup blok 2): regel-niveau grootboek-voorstel — groen "uit geheugen",
                        // oranje historie/conflict/"AI-voorstel — bevestig". Weg zodra de mens het veld aanraakt.
                        const gbChip = bepaalGbChip(regel.gbBron, regel.gbDetail, regel.ledgerId, regel.handmatigeVelden.ledgerId)
                        return gbChip ? (
                          <div style={{ marginTop: 4 }}>
                            <span className={`chip ${gbChip.klasse}`} title={gbChip.titel} data-testid="regel-gb-chip">
                              {gbChip.tekst}
                            </span>
                          </div>
                        ) : null
                      })()}
                      {regel.geheugen && !bepaalGbChip(regel.gbBron, regel.gbDetail, regel.ledgerId, regel.handmatigeVelden.ledgerId) && (
                        <GeheugenChipBlok
                          veld={regel.geheugen.gb}
                          huidig={regel.ledgerId}
                          handmatig={regel.handmatigeVelden.ledgerId}
                          opties={grootboekOpties}
                        />
                      )}
                      {regel.geheugenFout && (
                        <div
                          style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}
                          title="Het ophalen van het boekingsgeheugen-voorstel is mislukt — handmatig invullen werkt gewoon en de harde checks draaien onverminderd."
                        >
                          Geheugenvoorstel niet beschikbaar
                        </div>
                      )}
                    </>
                  )}
                </td>
                <td>
                  {isReadOnly ? (
                    optieWeergave(taxrateOpties, regel.taxrateId)
                  ) : (
                    <>
                      <SearchableCombobox
                        label="Btw-code"
                        opties={taxrateOpties}
                        waarde={regel.taxrateId}
                        onWijzig={(id) => wijzigRegel(regel.key, 'taxrateId', id)}
                        vereist
                        toonLabel={false}
                      />
                      {(() => {
                        // Blok E 04-09 (mockup blok 3): btw-default van de administratie — neutrale chip
                        // "standaard administratie", alleen zolang de mens het veld niet aanraakt.
                        const btwChip = bepaalBtwStandaardChip(regel.btwBron, regel.taxrateId, regel.handmatigeVelden.taxrateId)
                        return btwChip ? (
                          <div style={{ marginTop: 4 }}>
                            <span className={`chip ${btwChip.klasse}`} title={btwChip.titel} data-testid="regel-btw-standaard-chip">
                              {btwChip.tekst}
                            </span>
                          </div>
                        ) : null
                      })()}
                      {regel.btwBron === 'factuur' && regel.taxrateId && !regel.handmatigeVelden.taxrateId && (
                        <div style={{ marginTop: 4 }}>
                          <span
                            className="chip ok"
                            title="Door code afgeleid uit netto- en btw-bedrag van deze factuurregel (±1 cent) tegen de RLZ-tarieven van deze administratie — geen AI, geen geheugen. De harde checks blijven de poort."
                          >
                            uit factuur{percentageMap[regel.taxrateId] !== undefined ? ` (${Math.round(percentageMap[regel.taxrateId] * 100)}%)` : ''}
                          </span>
                        </div>
                      )}
                      {verlegdVermelding &&
                        regel.taxrateId === null &&
                        !regel.handmatigeVelden.taxrateId &&
                        (bedragAlsGetal(regel.btw) ?? 0) === 0 && (
                          <div style={{ marginTop: 4 }}>
                            <span
                              className="chip vraag"
                              title={`De factuur vermeldt: "${verlegdVermelding}". Dit is een hint — 0% kan verlegd, vrijgesteld of 0%-tarief zijn, dus de code wordt nooit automatisch ingevuld; kies zelf (of het boekingsgeheugen van deze leverancier vult 'm).`}
                            >
                              factuur vermeldt &ldquo;btw verlegd&rdquo; — kies de verlegd-code
                            </span>
                          </div>
                        )}
                      {regel.geheugen && (
                        <GeheugenChipBlok
                          veld={regel.geheugen.btw}
                          huidig={regel.taxrateId}
                          handmatig={regel.handmatigeVelden.taxrateId}
                          opties={taxrateOpties}
                        />
                      )}
                    </>
                  )}
                </td>
                {projectVerplicht && (
                  <td>
                    {isReadOnly ? (
                      optieWeergave(projectOpties, regel.projectId)
                    ) : (
                      <>
                        <SearchableCombobox
                          label="Project"
                          opties={projectOpties}
                          waarde={regel.projectId}
                          onWijzig={(id) => wijzigRegel(regel.key, 'projectId', id)}
                          vereist
                          toonLabel={false}
                          fout={checkRapport?.geblokkeerd && regel.projectId === null}
                        />
                        {regel.geheugen && (
                          <GeheugenChipBlok
                            veld={regel.geheugen.project}
                            huidig={regel.projectId}
                            handmatig={regel.handmatigeVelden.projectId}
                            opties={projectOpties}
                          />
                        )}
                      </>
                    )}
                  </td>
                )}
                <td className="amount">
                  {isReadOnly ? (
                    regel.netto || '—'
                  ) : (
                    <input
                      aria-label="Netto bedrag"
                      inputMode="decimal"
                      title="Bijvoorbeeld 1234,56 of 1234.56"
                      style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}
                      value={regel.netto}
                      onChange={(e) => wijzigRegel(regel.key, 'netto', e.target.value)}
                    />
                  )}
                </td>
                <td className="amount">
                  {isReadOnly ? (
                    regel.btw || '—'
                  ) : (
                    <>
                      <input
                        aria-label="Btw bedrag"
                        inputMode="decimal"
                        title="Bijvoorbeeld 1234,56 of 1234.56"
                        style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}
                        value={regel.btw}
                        onChange={(e) => wijzigRegel(regel.key, 'btw', e.target.value)}
                      />
                      {btwWijktAf && verwachtBtw !== null && (
                        <div className="regel-hint" style={{ textAlign: 'right' }}>
                          <span
                            className="chip afwijking"
                            title={`Netto × tarief geeft € ${formatEuro(verwachtBtw)}; het ingevulde bedrag wijkt meer dan 1 cent af. De btw van de factuur is leidend — controleer of het tarief klopt.`}
                          >
                            Berekend uit tarief: € {formatEuro(verwachtBtw)} · factuur-btw leidend
                          </span>
                        </div>
                      )}
                    </>
                  )}
                </td>
                <td className="omschrijving">
                  {isReadOnly ? (
                    regel.omschrijving || '—'
                  ) : (
                    <>
                      <RegelOmschrijvingVeld
                        ariaLabel="Omschrijving"
                        waarde={regel.omschrijving}
                        onWijzig={(waarde) => wijzigRegel(regel.key, 'omschrijving', waarde)}
                      />
                      {aiChipsActief && regel.aiZekerheid !== null && (
                        <div style={{ marginTop: 4 }}>
                          <AiChip score={regel.aiZekerheid} drempel={ai?.zekerheid_drempel ?? 0.8} bron={ai?.bron} />
                        </div>
                      )}
                    </>
                  )}
                </td>
                <td style={{ padding: '8px 4px' }}>
                  {!isReadOnly && (
                    <button
                      type="button"
                      className="icon-btn"
                      onClick={() => verwijderRegel(regel.key)}
                      aria-label="Regel verwijderen"
                    >
                      ×
                    </button>
                  )}
                </td>
              </tr>
              )
            })}
          </tbody>
        </table>
        </div>
        {!isReadOnly && (
          <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <button type="button" className="btn secondary" onClick={voegRegelToe}>
              + Regel toevoegen
            </button>
            {regelsomToets.basis !== null && regelsomToets.sluitAan !== null && (
              <span className={`chip ${regelsomToets.sluitAan ? 'ok' : 'afwijking'}`}>
                {regelsomToets.sluitAan
                  ? `Aansluitend — ${regelsomToets.basis === 'excl' ? 'netto' : 'netto + btw'} € ${formatEuro(regelsomToets.som ?? 0)} vs totaal ${regelsomToets.basis === 'excl' ? 'excl.' : 'incl.'}`
                  : `Afwijking € ${formatEuro(regelsomToets.verschil ?? 0)} (${regelsomToets.basis === 'excl' ? 'netto' : 'netto + btw'} € ${formatEuro(regelsomToets.som ?? 0)} vs totaal ${regelsomToets.basis === 'excl' ? 'excl.' : 'incl.'} € ${formatEuro(regelsomToets.vergelijk ?? 0)})`}
              </span>
            )}
            {regelsomToets.reden === 'btw_per_regel_ontbreekt' && (
              <span className="chip afwijking">
                Btw per regel ontbreekt (regel {regelsomToets.regelsZonderBtw.join(', ')}) en er is geen totaal excl. gelezen —
                netto € {formatEuro(regelsomToets.nettoSom ?? 0)} is niet tegen het totaal incl. te toetsen
              </span>
            )}
          </div>
        )}
        {/* B1 (04-09, UX-norm "lege stand = actie"): regels zonder project bieden de verdeling aan — één project blijft
            gewoon de kolom, het blok is voor de meerdere-projecten-gevallen. */}
        {!isReadOnly && projectVerplicht && onVerdelenGevraagd && regels.some((r) => r.projectId === null) && (
          <div className="hint" data-testid="project-leeg-actie" style={{ marginTop: 6 }}>
            {regels.filter((r) => r.projectId === null).length === 1
              ? '1 regel zonder project'
              : `${regels.filter((r) => r.projectId === null).length} regels zonder project`}{' '}
            {verdelingDektRegels ? (
              // B3-dekking: de opgeslagen verdeling geeft deze regels hun project(en) — geen actie meer nodig.
              <>— gedekt door de projectverdeling ✓</>
            ) : (
              <>
                — kies per regel een project óf{' '}
                <button type="button" className="linkbtn" onClick={onVerdelenGevraagd}>
                  Verdelen over projecten…
                </button>
              </>
            )}
          </div>
        )}
        {!isReadOnly && (
          <div className="hint">
            Grootboek- en btw-lijsten komen uit de sync-cache van deze administratie (koppelcontract §2c) — nooit
            rechtstreeks live van RLZ.
          </div>
        )}
      </div>

      {!isReadOnly &&
        (() => {
          // v2 ① "checks onzichtbaar-tot-relevant": groen/passief = één inklapregel onderaan
          // (mét de volledige lijst); afwijkingen verschijnen als banner boven de actiebalk.
          const groen = checkRapport ? checkRapport.resultaten.filter((r) => r.ok && !r.signaal).length : 0
          const totaal = checkRapport ? checkRapport.resultaten.length : 0
          const inklap = (
            <details className="inklap-controles" data-testid="controles-inklap">
              <summary>
                Controles{' '}
                {checksBezig ? (
                  <span className="chip vraag">worden uitgevoerd…</span>
                ) : checkRapport !== null && checksActueel ? (
                  <span className={`chip ${checkRapport.geblokkeerd ? 'blokkerend' : 'ok'}`}>
                    {checkRapport.geblokkeerd ? 'blokkerend' : `${groen}/${totaal} groen`}
                  </span>
                ) : (
                  <span className="chip">automatisch</span>
                )}
              </summary>
              <div className="inklap-inhoud">
                {controlerenFout && <div className="fout">{controlerenFout}</div>}
                {checkRapport === null && !checksBezig && (
                  <p className="hint">De harde checks draaien automatisch — bij het openen en na elke wijziging.</p>
                )}
                {checkRapport && (
                  <>
                    {!checksActueel && !checksBezig && (
                      <div className="hint" style={{ color: 'var(--orange)' }}>
                        Wijzigingen sinds de laatste controle — de checks draaien zo automatisch opnieuw.
                      </div>
                    )}
                    <table className="lines">
                      <tbody>
                        {checkRapport.resultaten.map((r) => (
                          <tr key={r.naam} style={!checksActueel ? { opacity: 0.55 } : undefined}>
                            <td>
                              {/* Punt 14 (28-08): oranje signaal = ok maar kijken (geen blokkade). */}
                              <span className={`chip ${!r.ok ? 'blokkerend' : r.signaal ? 'afwijking' : 'ok'}`}>
                                {!r.ok ? 'Blokkerend' : r.signaal ? 'Signaal' : 'OK'}
                              </span>
                            </td>
                            <td>
                              <b>{r.naam}</b>
                            </td>
                            <td>{r.melding}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </>
                )}
              </div>
            </details>
          )
          if (inklapDoel === undefined) return inklap
          return inklapDoel ? createPortal(inklap, inklapDoel) : null
        })()}

      {/* Alleen-lezen-uitkomsten (geboekt/verwijderd/boekfout) blijven hier; de actiebalk zelf
          verhuist via `actiebalkDoel` naar ónder het doorbelast-blok (27-08). */}
      {(isGeboekt || isVerwijderd || (isReadOnly && (boekenFout || boekResultaat))) && (
      <div className="panel">
        {isReadOnly && boekenFout && <div className="fout">{boekenFout}</div>}
        {isReadOnly && boekResultaat && (
          <div className="hint" style={{ color: 'var(--green)' }}>
            Geboekt in RLZ — boekstuknummer <b>{boekResultaat.rlz_boekstuknummer}</b>
          </div>
        )}
        {isGeboekt && (
          <>
            <p style={{ margin: 0, fontSize: 14 }}>
              Geboekt in RLZ — boekstuknummer <b>{boekstuknummer ?? '—'}</b>
            </p>
            <p className="hint">
              Wijzigen kan alleen via stornering in Reeleezee (actie 19); daarna komt het document hier terug als
              concept.
            </p>
          </>
        )}
        {isVerwijderd && (
          <>
            {herstellenFout && <div className="fout">{herstellenFout}</div>}
            <p className="hint" style={{ marginTop: 0 }}>
              Dit document is verwijderd — het bestand en de geschiedenis blijven bewaard. Herstellen zet het terug
              op de status van vóór de verwijdering.
            </p>
            <div className="actions">
              <button type="button" className="btn" disabled={herstellenBezig} onClick={() => void herstellen()}>
                {herstellenBezig ? 'Bezig…' : '↺ Herstellen'}
              </button>
            </div>
          </>
        )}
      </div>
      )}
      {!isReadOnly &&
        (() => {
          const afwijkingen = checkRapport && checksActueel ? checkRapport.resultaten.filter((r) => !r.ok || r.signaal) : []
          const ibanGeblokkeerd =
            Boolean(onIbanAangeboden) && checksActueel && (checkRapport?.resultaten.some((r) => r.naam === 'IBAN-wissel' && !r.ok) ?? false)
          const actiebalk = (
            <div className="panel actiebalk" data-testid="actiebalk">
              {/* v2 ①: élke rode/oranje uitkomst = één regel boven de knoppen (klik = detail). */}
              {afwijkingen.length > 0 && (
                <div className="controles-banner" data-testid="controles-banner">
                  {afwijkingen.map((r) => (
                    <button
                      key={r.naam}
                      type="button"
                      className={r.ok ? undefined : 'rood'}
                      onClick={() => setPopupChecks({ melding: null, checks: checkRapport! })}
                      title="Klik voor alle controles"
                    >
                      ⚠ {r.naam}: {r.melding}
                    </button>
                  ))}
                </div>
              )}
              {ibanGeblokkeerd && (
                <div style={{ marginBottom: 10 }}>
                  <div className="hint" style={{ marginTop: 0 }}>
                    Het rekeningnummer wijkt af van de vertrouwde set van deze crediteur. Bied het aan ter
                    <b> vier-ogen-accordering</b>: een ingestelde accordeur (nooit uzelf) beoordeelt en
                    deblokkeert — u kunt uw eigen aanvraag niet accorderen.
                  </div>
                  <IbanAanbiedenVorm
                    administratieId={administratieId}
                    documentId={documentId}
                    initieelIban={typeof veldvoorstel?.iban === 'string' ? veldvoorstel.iban : ''}
                    knopTekst="Rekening ter accordering aanbieden"
                    onAangeboden={onIbanAangeboden!}
                  />
                </div>
              )}
              {boekenFout && <div className="fout">{boekenFout}</div>}
              {boekResultaat && (
                <div className="hint" style={{ color: 'var(--green)', marginTop: 0 }}>
                  Geboekt in RLZ — boekstuknummer <b>{boekResultaat.rlz_boekstuknummer}</b>
                </div>
              )}
              <div className="actions">
                {onAfwijzen && (
                  <button type="button" className="btn secondary" onClick={onAfwijzen} title="Afwijzen — sneltoets A">
                    Afwijzen… <kbd className="kbd" aria-hidden>A</kbd>
                  </button>
                )}
                {onVraagStellen && (
                  <button type="button" className="btn warn" onClick={onVraagStellen}>
                    Vraag stellen…
                  </button>
                )}
                <button
                  type="button"
                  className="btn"
                  disabled={!kanBoeken || boekenBezig}
                  title={boekenTitel ? `${boekenTitel} — sneltoets B` : `${boekLabel} — sneltoets B`}
                  onClick={() => void boeken()}
                >
                  {boekenBezig ? 'Bezig…' : boekLabel}
                  {!boekenBezig && (
                    <kbd className="kbd" aria-hidden>
                      B
                    </kbd>
                  )}
                </button>
              </div>
            </div>
          )
          if (actiebalkDoel === undefined) return actiebalk
          return actiebalkDoel ? createPortal(actiebalk, actiebalkDoel) : null
        })()}
      {popupChecks && (
        <ChecksPopup
          melding={popupChecks.melding}
          checks={popupChecks.checks}
          onSluiten={() => setPopupChecks(null)}
        />
      )}
      {popupMatch && (
        <MatchAfwijkingPopup
          melding={popupMatch.melding}
          match={popupMatch.match}
          actieLabel={effectiefAccorderingAan ? 'Ter accordering ondanks afwijking' : 'Boeken ondanks afwijking'}
          bezig={boekenBezig}
          onBevestig={() => {
            setPopupMatch(null)
            void boeken(true)
          }}
          onSluiten={() => setPopupMatch(null)}
        />
      )}
      {popupMateriaal && (
        <MateriaalAfwijkingPopup
          melding={popupMateriaal.melding}
          match={popupMateriaal.match}
          actieLabel={effectiefAccorderingAan ? 'Ter accordering ondanks materiaal-afwijking' : 'Boeken ondanks materiaal-afwijking'}
          bezig={boekenBezig}
          onBevestig={() => {
            setPopupMateriaal(null)
            void boeken(false, true)
          }}
          onSluiten={() => setPopupMateriaal(null)}
        />
      )}
    </>
  )
}
