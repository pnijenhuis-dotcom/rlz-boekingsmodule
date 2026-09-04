// Instellingen v3 (mockup instellingen-v3.html = bouwnorm, akkoord Peter 01-09, iteratie 2 —
// HERZIET D2 25-08 "landing met sectiekaarten" én 30-08 "detail-dialoog per administratie"):
// twee-paneel op élke /instellingen-route (InstellingenLayout: vaste settings-nav + zoeker),
// /instellingen zonder sectie redirect naar het eerste zichtbare item van de rol, álle oude
// sectie-URL's/tegel-deep-links redirecten, administratie-detail = eigen PAGINA met tabs
// (AdministratieDetailPagina). Rol×sectie-matrix fail-closed (instellingenRegistry). Alle
// handlers/bevestigingsdialogen/bulkbediening zijn identiek aan v2 — alleen de IA is verbouwd.
import { useCallback, useEffect, useState } from 'react'
import { Link, Navigate, useLocation, useParams } from 'react-router-dom'
import { ApiError, apiJson } from '../api/client'
import { Button, Switch, SkeletonPaneel, SkeletonRegels } from '../ui/basis'
import type { AdministratieDto, AdministratieInstellingenDto } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { useMijnToegang } from '../auth/useMijnToegang'
import { zetIbanAccordeurs } from '../document/ibanAccorderingApi'
import { DoorbelastingInstellingen } from '../doorbelasting/DoorbelastingInstellingen'
import { DossierTypenModal } from './DossierTypenModal'
import { MateriaalCatalogusBeheer } from './MateriaalCatalogusBeheer'
import { AccorderingInstellingen } from './AccorderingInstellingen'
import { BevestigDialog } from './BevestigDialog'
import { BeveiligingInstellingen, WeekmailVoorkeur } from './BeveiligingInstellingen'
import { AdministratieWizard } from './AdministratieWizard'
import { AdministratiesV2, type PendingToggle } from './AdministratiesV2'
import { AdministratieDetailPagina } from './AdministratieDetailPagina'
import { ArchiveerDialog } from './ArchiveerDialog'
import { InstellingenLayout, type NavStanden } from './InstellingenLayout'
import { SchrijftestDialog, WebserviceGegevensDialog } from './KoppelingDialogen'
import { AutoboekKandidaten } from './AutoboekKandidaten'
import {
  eersteSectieVoor,
  type InstellingenSectie,
  NAV_ITEMS,
  OUDE_SECTIE_REDIRECTS,
  SECTIE_PADEN,
  zichtbareNavItems,
} from './instellingenRegistry'
import {
  haalAiKostenStatusOp,
  haalAutoboekStandOp,
  haalBoekenKillSwitchOp,
  haalDuplicaatAutoafvoerOp,
  haalInstellingenAdministratiesOp,
  haalIntakeAiInstellingOp,
  zetAiExtractieInstelling,
  zetAiKostenLimiet,
  zetBoekenInstelling,
  zetBoekenKillSwitch,
  zetDuplicaatAutoafvoer,
  zetEigenaar,
  zetIntakeAiInstelling,
  zetAfdelingenInstelling,
  zetProjectInstelling,
  zetVoorraadInstelling,
  zetOmzetAutoboekenInstelling,
  zetUrenDagmaxInstelling,
  zetUrenMeerwerkInstelling,
  zetIsVastgoed,
  zetVerkoopAutoboekenInstelling,
  type AiKostenStatusDto,
} from './instellingenApi'

type WijzigingType =
  | 'kill_switch'
  | 'intake_ai'
  | 'boeken'
  | 'project'
  | 'ai_extractie'
  | 'verkoop_autoboeken'
  | 'is_vastgoed'
  | 'uren_meerwerk'
  | 'afdelingen'
  | 'voorraad'
  | 'omzet_autoboeken'
  | 'duplicaat_noodrem'
  | 'eigenaar'
  | 'iban_accordeurs'
  | 'ai_kosten_limiet'

interface PendingWijziging {
  type: WijzigingType
  administratieId?: string
  naam: string
  nieuweWaarde: boolean
  /** Alleen voor type 'eigenaar' (mockup Instellingen "Eigenaar (krijgt vragen)"). */
  eigenaarId?: string | null
  eigenaarNaam?: string
  /** Alleen voor type 'iban_accordeurs': de volledige nieuwe accordeur-set + leesbare
   * omschrijving van de wijziging (vier-ogen-flow, docs/ontwerp/iban-wissel-accordering.md). */
  accordeurs?: string[]
  accordeursOmschrijving?: string
  /** Alleen voor type 'ai_kosten_limiet': de nieuwe maandlimiet in EUR (string, Decimal-precisie). */
  limietEur?: string
  /** Alleen voor type 'is_vastgoed' (UIT): staat verkoop-autoboeken nu aan? Dan gaat die mee uit. */
  verkoopAutoboekenAan?: boolean
}

function berichtVoor(pending: PendingWijziging): string {
  switch (pending.type) {
    case 'kill_switch':
      // D4 (kliktest-les 25-08): "aan" = boeken kan, "uit" = boeken staat plat — nooit meer
      // "kill switch: uit", dat werd gelezen als "noodstop niet actief".
      return pending.nieuweWaarde
        ? 'Boeken platformbreed gaat AAN: boeken kan weer, voor elke administratie waarvan de eigen boeken-toggle ook aan staat.'
        : 'Boeken platformbreed gaat UIT: boeken staat per direct plat voor ALLE administraties, ongeacht de toggle per administratie (noodstop).'
    case 'intake_ai':
      return pending.nieuweWaarde
        ? 'Nog-niet-toegewezen intake-PDF\'s (verzamelbak) gaan voortaan voor tenaamstelling en splitsingsdetectie naar de Claude API (platform-brede AVG-gate). Echte klantdocumenten pas ná DPA + EU-verwerking + verwerkersregister — zie docs/BOUWPLAN.md.'
        : 'Intake-AI wordt uitgeschakeld — élke niet-eenduidige PDF valt weer zichtbaar in de verzamelbak en wordt handmatig toegewezen.'
    case 'boeken':
      return pending.nieuweWaarde
        ? `Boeken wordt ingeschakeld voor "${pending.naam}".`
        : `Boeken wordt uitgeschakeld voor "${pending.naam}".`
    case 'project':
      return pending.nieuweWaarde
        ? `Project wordt verplicht bij boeken voor "${pending.naam}" — regels zonder project blokkeren dan het boeken.`
        : `Project is niet langer verplicht bij boeken voor "${pending.naam}".`
    case 'ai_extractie':
      return pending.nieuweWaarde
        ? `PDF's van "${pending.naam}" gaan voortaan voor extractie naar de Claude API (AVG-gate). Echte klantfacturen pas ná DPA + EU-verwerking + verwerkersregister — zie docs/BOUWPLAN.md.`
        : `AI-extractie wordt uitgeschakeld voor "${pending.naam}" — PDF's worden weer volledig handmatig ingevuld.`
    case 'afdelingen':
      return pending.nieuweWaarde
        ? `Afdelingen gaan AAN voor "${pending.naam}": op élk inkoopdocument wordt een afdeling verplicht (blokkerende check bij boeken en ter accordering) en de accorderingsroute loopt per afdeling. De terugval-afdeling "Algemeen" ontstaat automatisch en volgt de bestaande accorderingsconfig — alleen nieuwe/nog niet geboekte documenten vergen een afdeling.`
        : `Afdelingen gaan UIT voor "${pending.naam}": het veld verdwijnt en de check zwijgt; afdelingen en gemaakte keuzes blijven bewaard.`
    case 'voorraad':
      return pending.nieuweWaarde
        ? `Voorraad bijhouden gaat AAN voor "${pending.naam}": regel-niveau feiten uit gescande inkoopfacturen en verkoopfactuurregels worden bijgehouden in de controle-laag (mi-schema), artikelteksten worden volautomatisch genormaliseerd (AI achter de bestaande gates, onzeker telt mee mét vlag) en het aansluitscherm vergelijkt de theoretische stand met tellingen. Niets wordt geboekt; er gaat nooit iets naar Reeleezee.`
        : `Voorraad bijhouden gaat UIT voor "${pending.naam}" — de feitenlaag en tellingen blijven bewaard, er komen geen nieuwe regels bij.`
    case 'omzet_autoboeken':
      return pending.nieuweWaarde
        ? `Omzet-autoboeken gaat AAN voor "${pending.naam}": een kassarapport boekt ná extractie automatisch (verkoopfactuur + kostprijsmemoriaal als één transactie) uitsluitend als álles groen is — harde checks incl. memoriaal-saldo-0 en marge-plausibiliteit, categorie-mapping volledig door een mens bevestigd, geen duplicaat per periode, geen open vraag of afwijzing. Elk ander geval blijft gewoon in de werkvoorraad; volumerem 20/dag; elke automatische boeking is gemarkeerd en geauditeerd en een half-geboekt-geval geeft een alert.`
        : `Omzet-autoboeken gaat UIT voor "${pending.naam}" — elk kassarapport wacht weer op de boek-klik van een medewerker.`
    case 'duplicaat_noodrem':
      return pending.nieuweWaarde
        ? 'Duplicaten automatisch afvoeren gaat platformbreed AAN (de standaard): bij een harde match — zelfde crediteur (btw-nummer), zelfde referentie én zelfde totaalbedrag, origineel al geboekt óf ouder in de werkvoorraad — zet het systeem het duplicaat direct op Afgewezen met reden "Duplicaat van …" en een kruisverwijzing naar het origineel; ligt het duplicaat bij de klant of draagt het een open vraag, dan worden ronde en vraag met dezelfde reden gesloten. Niets wordt verwijderd; terughalen kan via Heropenen. Volumerem 20 per dag per administratie; alles in audit en tijdlijn.'
        : 'NOODREM: duplicaten automatisch afvoeren gaat platformbreed UIT — voor álle administraties blijven duplicaten als signaal staan; de knop "Afvoeren als duplicaat" blijft beschikbaar.'
    case 'uren_meerwerk':
      return pending.nieuweWaarde
        ? `Uren & meerwerk (steigerbouw-tak) wordt ingeschakeld voor "${pending.naam}": ZZP'ers/uitvoerders/detacheerders kunnen er weekstaten en meerwerk op werken en het kantoor ziet de standen (module-recht vereist).`
        : `Uren & meerwerk wordt uitgeschakeld voor "${pending.naam}" — de app en de kantoor-schermen weigeren dan; bestaande weekstaten en meerwerk blijven bewaard.`
    case 'verkoop_autoboeken':
      return pending.nieuweWaarde
        ? `Vastly-verkoopfacturen van "${pending.naam}" boeken voortaan automatisch zodra álles groen is (harde checks, ondubbelzinnige GB-codes en btw uit de UBL, geen vraag of duplicaatsignaal). Elk ander geval blijft gewoon in de werkvoorraad; elke automatische boeking is gemarkeerd en geauditeerd.`
        : `Verkoop-autoboeken wordt uitgeschakeld voor "${pending.naam}" — elke Vastly-verkoopfactuur wacht weer op een menselijke boek-klik.`
    case 'is_vastgoed':
      // Avondrun 26-08 (S2-draaiboek R1): de consequenties benoemen — dit is de schakelaar die
      // het koppelvlak met Vastly voor deze administratie aan- of uitzet.
      return pending.nieuweWaarde
        ? `Vastgoed-koppeling gaat AAN voor "${pending.naam}": factuur_geboekt- en factuur_gestorneerd-events naar Vastly gaan per direct lopen voor deze administratie (ook voor doorbelasting-spiegels die hier landen), Vastly-verkoopfacturen (VASTLY-VERKOOP) worden hier geboekt mét webhook — en automatisch zodra álles groen is (autoboeken volgt de koppeling, besluit 29-08) — en projectaanvragen vanuit Vastly worden geaccepteerd. Alleen aanzetten ná Vastly's omschakeling voor deze administratie (draaiboek R1).`
        : `Vastgoed-koppeling gaat UIT voor "${pending.naam}": de events naar Vastly stoppen per direct, projectaanvragen worden geweigerd en het automatisch boeken van Vastly-verkoopfacturen stopt (volgt de koppeling, geauditeerd). Niets wordt verwijderd; al verstuurde events blijven staan.`
    case 'eigenaar':
      return pending.eigenaarId
        ? `${pending.eigenaarNaam ?? 'Deze medewerker'} wordt eigenaar van "${pending.naam}" en krijgt nieuwe vragen standaard toegewezen.`
        : `"${pending.naam}" krijgt geen eigenaar — een vraag stellen vereist dan een expliciete toewijzing.`
    case 'iban_accordeurs':
      return `${pending.accordeursOmschrijving ?? 'De IBAN-accordeurs worden gewijzigd'} voor "${pending.naam}".${
        (pending.accordeurs?.length ?? 0) === 0
          ? ' Zonder ingestelde accordeurs vallen IBAN-wissels terug op de beheerder(s).'
          : ''
      }`
    case 'ai_kosten_limiet':
      return `De AI-kosten-maandlimiet wordt € ${pending.limietEur ?? '?'} per kalendermaand. Boven de limiet wordt AI-verwerking geblokkeerd en volgen documenten het handmatige pad.`
  }
}

async function voerWijzigingUit(pending: PendingWijziging): Promise<void> {
  // Alle paden via instellingenApi.ts/ibanAccorderingApi.ts — nooit losse fetch-paden in het
  // scherm (guard-test: instellingenApi.test.ts).
  if (pending.type === 'kill_switch') {
    await zetBoekenKillSwitch(pending.nieuweWaarde)
    return
  }
  if (pending.type === 'intake_ai') {
    await zetIntakeAiInstelling(pending.nieuweWaarde)
    return
  }
  if (pending.type === 'boeken') {
    await zetBoekenInstelling(pending.administratieId ?? '', pending.nieuweWaarde)
    return
  }
  if (pending.type === 'ai_extractie') {
    await zetAiExtractieInstelling(pending.administratieId ?? '', pending.nieuweWaarde)
    return
  }
  if (pending.type === 'verkoop_autoboeken') {
    await zetVerkoopAutoboekenInstelling(pending.administratieId ?? '', pending.nieuweWaarde)
    return
  }
  if (pending.type === 'is_vastgoed') {
    await zetIsVastgoed(pending.administratieId ?? '', pending.nieuweWaarde)
    return
  }
  if (pending.type === 'uren_meerwerk') {
    await zetUrenMeerwerkInstelling(pending.administratieId ?? '', pending.nieuweWaarde)
    return
  }
  if (pending.type === 'afdelingen') {
    await zetAfdelingenInstelling(pending.administratieId ?? '', pending.nieuweWaarde)
    return
  }
  if (pending.type === 'voorraad') {
    await zetVoorraadInstelling(pending.administratieId ?? '', pending.nieuweWaarde)
    return
  }
  if (pending.type === 'omzet_autoboeken') {
    await zetOmzetAutoboekenInstelling(pending.administratieId ?? '', pending.nieuweWaarde)
    return
  }
  if (pending.type === 'duplicaat_noodrem') {
    await zetDuplicaatAutoafvoer(pending.nieuweWaarde)
    return
  }
  if (pending.type === 'eigenaar') {
    await zetEigenaar(pending.administratieId ?? '', pending.eigenaarId ?? null)
    return
  }
  if (pending.type === 'iban_accordeurs') {
    await zetIbanAccordeurs(pending.administratieId ?? '', pending.accordeurs ?? [])
    return
  }
  if (pending.type === 'ai_kosten_limiet') {
    await zetAiKostenLimiet(pending.limietEur ?? '')
    return
  }
  await zetProjectInstelling(pending.administratieId ?? '', pending.nieuweWaarde)
}

/** Backwards-compat voor bestaande aanroepers/tests: de sectie-lijst en de rol×sectie-matrix leven
 * sinds v3 in instellingenRegistry.ts (één bron voor nav, tabs én zoeker). */
export const INSTELLINGEN_SECTIES = NAV_ITEMS
export type { InstellingenSectie }
export const zichtbareSecties = zichtbareNavItems

function Sectiekop({ titel }: { titel: string }) {
  return (
    <div className="topbar">
      <div>
        <div className="mb-1 text-[12.5px] text-muted">
          <Link to="/instellingen" className="text-primary no-underline hover:underline">
            Instellingen
          </Link>{' '}
          <span className="text-faint">›</span> {titel}
        </div>
        <h1>{titel}</h1>
      </div>
    </div>
  )
}

export function InstellingenScreen() {
  const { rol, status } = useAuth()
  const { sectie: sectieParam, administratieId: detailParam } = useParams<{ sectie?: string; administratieId?: string }>()
  const location = useLocation()
  // Blok B 31-08: B+P bereikt de Materiaalcatalogus — de administratie-namen komen dan uit de
  // scope-gefilterde /auth/administraties (het Beheerder-instellingen-endpoint is niet van hen),
  // de uren-&-meerwerk-opt-in-filter uit mijn-toegang (zelfde filter als de Beheerder-tak).
  const toegang = useMijnToegang()
  const [scopeAdministraties, setScopeAdministraties] = useState<AdministratieDto[] | null>(null)

  const [administraties, setAdministraties] = useState<AdministratieInstellingenDto[] | null>(null)
  const [accordeursVersie, setAccordeursVersie] = useState(0)
  const [killSwitch, setKillSwitch] = useState<boolean | null>(null)
  // Blok A1 04-09: platformbrede noodrem duplicaat-auto-afvoer (standaard AAN).
  const [duplicaatNoodrem, setDuplicaatNoodrem] = useState<boolean | null>(null)
  const [intakeAi, setIntakeAi] = useState<boolean | null>(null)
  const [aiKosten, setAiKosten] = useState<AiKostenStatusDto | null>(null)
  // Blok B (01-09): autoboek-kandidaten-teller voor de nav-stand-chip (oranje zolang > 0).
  const [autoboekKandidaten, setAutoboekKandidaten] = useState<number | undefined>(undefined)
  const [limietInvoer, setLimietInvoer] = useState('')
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [pending, setPending] = useState<PendingWijziging | null>(null)
  const [dossierTypenVoor, setDossierTypenVoor] = useState<{ id: string; naam: string } | null>(null)
  const [melding, setMelding] = useState<string | null>(null)

  /** A6 (25-08): dagdrempel opslaan — server valideert 0 < N ≤ 24, geaudit oud→nieuw. */
  async function slaDagmaxOp(administratieId: string, naam: string, waarde: string) {
    try {
      const r = await zetUrenDagmaxInstelling(administratieId, waarde)
      setAdministraties((huidig) =>
        huidig ? huidig.map((x) => (x.id === administratieId ? { ...x, uren_dagmax_uren: r.dagmax_uren } : x)) : huidig,
      )
      setWijzigenFout(null)
    } catch (err) {
      setWijzigenFout(err instanceof ApiError ? `Dagdrempel voor ${naam}: ${err.message}` : 'Dagdrempel opslaan mislukt.')
    }
  }
  const [bezig, setBezig] = useState(false)
  const [wijzigenFout, setWijzigenFout] = useState<string | null>(null)
  // Bulk-rijselectie (fase 3 modernisering 15-08): ids van geselecteerde administraties.
  const [selectie, setSelectie] = useState<string[]>([])
  // Administratie toevoegen / koppeling (feedbackronde 26-08 punt 5).
  const [wizardOpen, setWizardOpen] = useState(false)
  const [webserviceVoor, setWebserviceVoor] = useState<AdministratieInstellingenDto | null>(null)
  const [schrijftestVoor, setSchrijftestVoor] = useState<AdministratieInstellingenDto | null>(null)
  const [archiveerVoor, setArchiveerVoor] = useState<AdministratieInstellingenDto | null>(null)

  const laadAlles = useCallback(() => {
    setLaadFout(null)
    Promise.all([
      haalInstellingenAdministratiesOp(true),
      haalBoekenKillSwitchOp(),
      haalIntakeAiInstellingOp(),
      haalAiKostenStatusOp(),
      haalDuplicaatAutoafvoerOp(),
    ])
      .then(([lijst, switchDto, intakeAiDto, aiKostenDto, duplicaatDto]) => {
        setAdministraties(lijst.administraties)
        setKillSwitch(switchDto.ingeschakeld)
        setDuplicaatNoodrem(duplicaatDto.ingeschakeld)
        setIntakeAi(intakeAiDto.ingeschakeld)
        setAiKosten(aiKostenDto)
        setLimietInvoer(aiKostenDto.limiet_eur)
      })
      .catch((err: unknown) => setLaadFout(err instanceof Error ? err.message : 'Onbekende fout'))
    // De kandidaten-stand is een los, licht endpoint: een fout hier mag de rest niet blokkeren.
    haalAutoboekStandOp()
      .then((t) => setAutoboekKandidaten(t.kandidaten))
      .catch(() => setAutoboekKandidaten(undefined))
  }, [])

  useEffect(() => {
    if (rol === 'beheerder') laadAlles()
  }, [rol, laadAlles])

  useEffect(() => {
    if (rol !== 'boekhouding_projecten') return
    let actief = true
    apiJson<{ administraties: AdministratieDto[] }>('/auth/administraties')
      .then((r) => {
        if (actief) setScopeAdministraties(r.administraties)
      })
      .catch(() => {
        if (actief) setScopeAdministraties([]) // fail-closed: lege lijst, nooit een crash
      })
    return () => {
      actief = false
    }
  }, [rol])

  // Backend dwingt dit al af op elk endpoint hieronder — dit is de UI-kant. Wacht op `status`
  // (niet alleen `rol`) zodat dit ook correct is los van App.tsx's status==='laden'-gate.
  if (status === 'laden') {
    return <SkeletonPaneel />
  }
  const isBeheerder = rol === 'beheerder'
  const eigenSecties = zichtbareNavItems(rol)
  const magSectie = (pad: string) => eigenSecties.some((k) => k.pad === pad)
  const landing = `/instellingen/${eersteSectieVoor(rol)}`

  // --- Routing/redirects (ontwerpnotities ①, ③, ⑤) — niets 404't, alles landt op een zichtbare plek.
  const hashSectie = location.hash.replace(/^#/, '')
  const querySectie = new URLSearchParams(location.search).get('sectie')
  const queryAdministratie = new URLSearchParams(location.search).get('administratie')
  if (detailParam) {
    // Detailpagina: Beheerder-only (de lijst-endpoint is dat ook) — anders naar de eigen landing.
    if (!isBeheerder) return <Navigate to={landing} replace />
  } else if (!sectieParam) {
    // Oude deep-links: `?administratie=<id>` (v2-dialoog) → detailpagina; `#x`/`?sectie=x` → sectie.
    if (queryAdministratie && isBeheerder) return <Navigate to={`/instellingen/administraties/${queryAdministratie}`} replace />
    const oud = [hashSectie, querySectie].find((x) => x && (SECTIE_PADEN.has(x) || x in OUDE_SECTIE_REDIRECTS))
    if (oud) {
      const doel = OUDE_SECTIE_REDIRECTS[oud] ?? (magSectie(oud) ? `/instellingen/${oud}` : landing)
      return <Navigate to={doel} replace />
    }
    // Geen landing meer (①): direct naar het eerste zichtbare item van de rol.
    return <Navigate to={landing} replace />
  } else {
    if (sectieParam in OUDE_SECTIE_REDIRECTS) return <Navigate to={OUDE_SECTIE_REDIRECTS[sectieParam]} replace />
    if (!SECTIE_PADEN.has(sectieParam)) return <Navigate to={landing} replace />
    const item = NAV_ITEMS.find((i) => i.pad === sectieParam)
    if (item?.extern) return <Navigate to={item.extern} replace />
    // Rol×sectie-matrix fail-closed: een niet-zichtbare sectie valt terug op de eigen landing.
    if (!magSectie(sectieParam)) return <Navigate to={landing} replace />
  }

  const sectie: InstellingenSectie = detailParam ? 'administraties' : (sectieParam as InstellingenSectie)
  const sectieInfo = NAV_ITEMS.find((x) => x.pad === sectie)!
  const standen: NavStanden = {
    administraties: administraties ? administraties.filter((a) => !a.gearchiveerd_op).length : undefined,
    boekenPlatformbreed: killSwitch ?? undefined,
    intakeAiPercentage: aiKosten ? aiKosten.percentage : undefined,
    autoboekKandidaten,
  }
  const zoekAdministraties = (administraties ?? []).filter((a) => !a.gearchiveerd_op).map((a) => ({ id: a.id, naam: a.naam }))

  const laag = (inhoud: React.ReactNode) => (
    <InstellingenLayout actief={sectie} standen={standen} administraties={zoekAdministraties}>
      {inhoud}
    </InstellingenLayout>
  )

  if (!isBeheerder) {
    // Niet-Beheerder: alleen Beveiliging (eigen passkeys, élke kantoorrol) en — B+P (blok B 31-08)
    // — de Materiaalcatalogus mét scope-administraties.
    if (sectie === 'materiaal') {
      const materiaalAdministraties =
        toegang && scopeAdministraties
          ? scopeAdministraties.filter((a) => toegang.administraties_met_opt_in.includes(a.id))
          : null
      return laag(
        <div>
          <Sectiekop titel="Materiaalcatalogus" />
          {materiaalAdministraties === null ? <SkeletonRegels /> : <MateriaalCatalogusBeheer administraties={materiaalAdministraties} />}
        </div>,
      )
    }
    return laag(
      <div>
        <Sectiekop titel="Beveiliging" />
        <BeveiligingInstellingen isBeheerder={false} />
        <WeekmailVoorkeur />
      </div>,
    )
  }
  if (sectie === 'beveiliging') {
    return laag(
      <div>
        <Sectiekop titel={sectieInfo.titel} />
        <BeveiligingInstellingen isBeheerder />
        <WeekmailVoorkeur />
      </div>,
    )
  }

  const bevestigen = async () => {
    if (!pending) return
    setBezig(true)
    setWijzigenFout(null)
    try {
      await voerWijzigingUit(pending)
      if (pending.type === 'kill_switch') {
        setKillSwitch(pending.nieuweWaarde)
      } else if (pending.type === 'duplicaat_noodrem') {
        setDuplicaatNoodrem(pending.nieuweWaarde)
      } else if (pending.type === 'intake_ai') {
        setIntakeAi(pending.nieuweWaarde)
      } else if (pending.type === 'ai_kosten_limiet') {
        // Verse status ophalen: percentage/blokkade hangen van de nieuwe limiet af.
        haalAiKostenStatusOp()
          .then((dto) => {
            setAiKosten(dto)
            setLimietInvoer(dto.limiet_eur)
          })
          .catch(() => undefined)
      } else if (pending.type === 'iban_accordeurs') {
        setAccordeursVersie((v) => v + 1)
      } else {
        setAdministraties(
          (huidig) =>
            huidig?.map((a) =>
              a.id === pending.administratieId
                ? {
                    ...a,
                    ...(pending.type === 'boeken'
                      ? { boeken_ingeschakeld: pending.nieuweWaarde }
                      : pending.type === 'ai_extractie'
                        ? { ai_extractie_ingeschakeld: pending.nieuweWaarde }
                        : pending.type === 'verkoop_autoboeken'
                          ? { verkoop_autoboeken_ingeschakeld: pending.nieuweWaarde }
                          : pending.type === 'is_vastgoed'
                            ? {
                                is_vastgoed: pending.nieuweWaarde,
                                // UIT neemt verkoop-autoboeken server-side mee uit (409-regel).
                                ...(pending.nieuweWaarde ? {} : { verkoop_autoboeken_ingeschakeld: false }),
                              }
                            : pending.type === 'eigenaar'
                              ? { eigenaar_gebruiker_id: pending.eigenaarId ?? null, eigenaar_naam: pending.eigenaarNaam ?? null }
                              : pending.type === 'afdelingen'
                                ? { afdelingen_ingeschakeld: pending.nieuweWaarde }
                                : pending.type === 'voorraad'
                                  ? { voorraad_ingeschakeld: pending.nieuweWaarde }
                                  : pending.type === 'uren_meerwerk'
                                    ? { uren_meerwerk_ingeschakeld: pending.nieuweWaarde }
                                    : pending.type === 'omzet_autoboeken'
                                      ? { omzet_autoboeken_ingeschakeld: pending.nieuweWaarde }
                                    : { project_verplicht: pending.nieuweWaarde }),
                  }
                : a,
            ) ?? null,
        )
      }
      setPending(null)
    } catch (err) {
      setWijzigenFout(err instanceof ApiError ? err.message : 'Wijzigen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  const onPendingToggle = (p: PendingToggle) => setPending(p as PendingWijziging)

  // Detailpagina (mockup scherm 2): laadstand → skeleton; onbekende id → terug naar de lijst.
  let inhoud: React.ReactNode
  if (detailParam) {
    const detail = administraties?.find((a) => a.id === detailParam) ?? null
    if (administraties !== null && detail === null && !laadFout) {
      return <Navigate to="/instellingen/administraties" replace />
    }
    inhoud = detail ? (
      <AdministratieDetailPagina
        administratie={detail}
        accordeursVersie={accordeursVersie}
        onPending={onPendingToggle}
        onWebservice={setWebserviceVoor}
        onSchrijftest={setSchrijftestVoor}
        onArchiveren={setArchiveerVoor}
        onDossierTypen={(a) => setDossierTypenVoor({ id: a.id, naam: a.naam })}
        onDagmax={slaDagmaxOp}
        onHerlaad={laadAlles}
      />
    ) : (
      <SkeletonPaneel />
    )
  } else {
    inhoud = (
      <>
        <Sectiekop titel={sectieInfo.titel} />

        {sectie === 'boeken' && (
          <div className="panel">
            {/* D4 (kliktest-les Peter 25-08): "Boeken platformbreed" aan = boeken kan, uit = boeken
                staat plat. Alleen presentatie — backend-endpoint/audit ongewijzigd. */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
              <div style={{ minWidth: 0, flex: '1 1 320px' }}>
                <h2 style={{ margin: 0 }}>Boeken platformbreed</h2>
                <p className="hint" style={{ marginTop: 4, marginBottom: 0 }}>
                  De poort boven alle administraties. <b>Aan</b> = boeken kan (per administratie nog afhankelijk van
                  de eigen boeken-toggle onder Administraties). <b>Uit</b> = boeken staat per direct plat voor álle
                  administraties — de noodstop.
                </p>
              </div>
              {killSwitch !== null && (
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0, whiteSpace: 'nowrap' }}>
                  <Switch
                    aria-label="Boeken platformbreed"
                    checked={killSwitch}
                    onChange={(e) =>
                      setPending({ type: 'kill_switch', naam: 'boeken platformbreed', nieuweWaarde: e.target.checked })
                    }
                  />
                  {killSwitch ? 'aan — boeken kan' : 'uit — boeken staat plat'}
                </label>
              )}
            </div>
            {/* Blok A1 04-09 (besluit Peter): duplicaat-auto-afvoer is STANDAARD AAN voor de hele module; dit is
                de enige schakelaar — een platformbrede noodrem, geen toggle per administratie meer. */}
            <div
              data-testid="duplicaat-noodrem"
              style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginTop: 18, paddingTop: 16, borderTop: '1px solid var(--border)' }}
            >
              <div style={{ minWidth: 0, flex: '1 1 320px' }}>
                <h2 style={{ margin: 0 }}>Duplicaten automatisch afvoeren</h2>
                <p className="hint" style={{ marginTop: 4, marginBottom: 0 }}>
                  Standaard <b>aan</b> voor álle administraties: een harde duplicaat (zelfde leverancier, factuurnummer én
                  bedrag) gaat vanzelf naar Afgewezen met een link naar het origineel — ook als het bij de klant ligt of
                  een open vraag draagt (ronde en vraag worden met die reden gesloten). Niets verdwijnt; Heropenen haalt
                  terug. <b>Uit</b> = de noodrem: nergens meer automatisch, alleen de knop &quot;Afvoeren als duplicaat&quot;.
                </p>
              </div>
              {duplicaatNoodrem !== null && (
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0, whiteSpace: 'nowrap' }}>
                  <Switch
                    aria-label="Duplicaten automatisch afvoeren"
                    checked={duplicaatNoodrem}
                    onChange={(e) =>
                      setPending({ type: 'duplicaat_noodrem', naam: 'duplicaten automatisch afvoeren', nieuweWaarde: e.target.checked })
                    }
                  />
                  {duplicaatNoodrem ? 'aan — duplicaten worden afgevoerd' : 'uit — noodrem actief'}
                </label>
              )}
            </div>
          </div>
        )}

        {sectie === 'intake-ai' && (
          <>
            <div className="panel">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
                <div style={{ minWidth: 0, flex: '1 1 320px' }}>
                  <h2 style={{ margin: 0 }}>Intake-AI (AVG-gate, platform-breed)</h2>
                  <p className="hint" style={{ marginTop: 4, marginBottom: 0 }}>
                    Bepaalt of nog-niet-toegewezen intake-PDF&apos;s (verzamelbak) voor tenaamstelling en
                    multi-factuur-splitsingsdetectie naar de Claude API mogen. Staat los van de AI-extractie
                    per administratie (Instellingen → Administraties), die pas ná toewijzing geldt.
                  </p>
                </div>
                {intakeAi !== null && (
                  <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0, whiteSpace: 'nowrap' }}>
                    <Switch
                      aria-label="Intake-AI ingeschakeld"
                      checked={intakeAi}
                      onChange={(e) =>
                        setPending({ type: 'intake_ai', naam: 'intake-AI', nieuweWaarde: e.target.checked })
                      }
                    />
                    {intakeAi ? 'aan' : 'uit'}
                  </label>
                )}
              </div>
            </div>

            <div className="panel" style={{ marginTop: 16 }} id="kosten">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16, flexWrap: 'wrap' }}>
                <div style={{ minWidth: 0, flex: '1 1 320px' }}>
                  <h2 style={{ margin: 0 }}>AI-kosten (maandlimiet)</h2>
                  <p className="hint" style={{ marginTop: 4, marginBottom: 0 }}>
                    Wérkelijke Anthropic-API-kosten van intake-AI deze kalendermaand, deterministisch berekend uit de
                    token-usage per aanroep. Boven de limiet wordt AI-verwerking geblokkeerd en volgen documenten het
                    handmatige pad (&quot;AI-limiet bereikt — handmatig verwerken&quot;).
                  </p>
                  {aiKosten && (
                    <p style={{ marginTop: 8, marginBottom: 0 }} data-testid="ai-kosten-verbruik">
                      <strong>
                        {aiKosten.maand}: € {aiKosten.verbruik_eur} van € {aiKosten.limiet_eur} ({aiKosten.percentage}%)
                      </strong>
                      {aiKosten.limiet_bereikt ? (
                        <span style={{ color: 'var(--red)', marginLeft: 8 }}>
                          Limiet bereikt — AI-verwerking geblokkeerd tot de nieuwe maand of een hogere limiet.
                        </span>
                      ) : aiKosten.waarschuwing_80 ? (
                        <span style={{ color: 'var(--orange, #b45309)', marginLeft: 8 }}>
                          Waarschuwing: 80% van de maandlimiet bereikt.
                        </span>
                      ) : null}
                    </p>
                  )}
                  {aiKosten && (
                    <p className="hint" style={{ marginTop: 8, marginBottom: 0 }} data-testid="extractie-template-teller">
                      <strong>Extracties {aiKosten.maand}:</strong> {aiKosten.extracties_template_maand ?? 0} via template ·{' '}
                      {aiKosten.extracties_ai_maand ?? 0} via AI · {aiKosten.templates_actief ?? 0} actieve{' '}
                      {(aiKosten.templates_actief ?? 0) === 1 ? 'template' : 'templates'}. Een template wordt automatisch
                      geleerd uit de laatste drie door u bevestigde facturen van een leverancier en leest volgende facturen
                      deterministisch (lokale code, geen AI-aanroep, geen data naar buiten) — daarom werkt het óók voor
                      administraties met AI-extractie uit en als de AI-limiet bereikt is. Eén afwijking = volledig verworpen
                      en het AI-pad; geen beheer nodig.
                    </p>
                  )}
                </div>
                {aiKosten && (
                  <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0, whiteSpace: 'nowrap' }}>
                    €
                    <input
                      type="number"
                      aria-label="AI-kosten maandlimiet in euro"
                      min="1"
                      step="1"
                      style={{ width: 90 }}
                      value={limietInvoer}
                      onChange={(e) => setLimietInvoer(e.target.value)}
                    />
                    <Button
                      variant="secundair"
                      disabled={!limietInvoer || Number(limietInvoer) <= 0 || limietInvoer === aiKosten.limiet_eur}
                      onClick={() =>
                        setPending({ type: 'ai_kosten_limiet', naam: 'AI-kosten-maandlimiet', nieuweWaarde: true, limietEur: limietInvoer })
                      }
                    >
                      Limiet wijzigen
                    </Button>
                  </label>
                )}
              </div>
            </div>
          </>
        )}

        {sectie === 'administraties' && (
          <div className="panel">
            {/* Kopregel-layout (UI-fix 01-09): tekstblok mét flex-basis + eigen marge onder de kopregel. */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap', marginBottom: 10 }}>
              <div style={{ flex: '1 1 320px', minWidth: 0 }}>
                <h2 style={{ marginTop: 0 }}>Administraties</h2>
                <p className="hint" style={{ marginTop: 4, marginBottom: 0 }}>
                  Chips tonen alleen ingeschakelde modules en afwijkingen van de defaults (Boeken en AI-extractie staan standaard aan).
                  Klik op een rij of ⚙ voor de instellingenpagina van de administratie; selecteer rijen voor bulk-bediening. Elke wijziging vraagt één bevestiging en wordt geauditeerd.
                </p>
              </div>
              {/* Wizard (besluit Peter 26-08, punt 5). */}
              <Button id="toevoegen" style={{ flexShrink: 0 }} onClick={() => setWizardOpen(true)}>+ Administratie toevoegen</Button>
            </div>
            {melding && (
              <div className="hint" role="status" style={{ marginBottom: 10 }}>
                {melding}
              </div>
            )}
            {administraties === null && !laadFout && <SkeletonRegels />}
            {administraties !== null && administraties.length === 0 && (
              <p className="hint">Nog geen administraties gekoppeld — begin met &ldquo;+ Administratie toevoegen&rdquo;.</p>
            )}
            {administraties !== null && administraties.length > 0 && (
              <div id="bulk">
                <AdministratiesV2
                  administraties={administraties}
                  selectie={selectie}
                  setSelectie={setSelectie}
                  onHerlaad={laadAlles}
                  onSchrijftest={setSchrijftestVoor}
                />
              </div>
            )}
          </div>
        )}

        {sectie === 'materiaal' && administraties !== null && (
          <MateriaalCatalogusBeheer administraties={administraties.filter((a) => a.uren_meerwerk_ingeschakeld && !a.gearchiveerd_op).map((a) => ({ id: a.id, naam: a.naam }) as AdministratieDto)} />
        )}

        {sectie === 'accordering' && administraties !== null && (
          <AccorderingInstellingen administraties={administraties.filter((a) => !a.gearchiveerd_op).map((a) => ({ id: a.id, naam: a.naam }))} />
        )}

        {/* Blok B (01-09): de kandidaten-motor vervangt hier de kale leverancierslijst; de
            per-leverancier-switch blijft op de detailpagina (tab Boeken & AI). */}
        {sectie === 'autoboeken' && <AutoboekKandidaten onStand={(t) => setAutoboekKandidaten(t.kandidaten)} />}

        {sectie === 'doorbelasting' && administraties !== null && (
          <DoorbelastingInstellingen administraties={administraties.filter((a) => !a.gearchiveerd_op).map((a) => ({ id: a.id, naam: a.naam }))} />
        )}
        {sectie !== 'administraties' && sectie !== 'boeken' && sectie !== 'intake-ai' && administraties === null && !laadFout && (
          <SkeletonRegels />
        )}
      </>
    )
  }

  return laag(
    <div>
      {laadFout && <div className="fout">Kon instellingen niet laden: {laadFout}</div>}
      {inhoud}

      <AdministratieWizard open={wizardOpen} onSluiten={() => setWizardOpen(false)} onAangemaakt={laadAlles} />
      {webserviceVoor && (
        <WebserviceGegevensDialog administratie={webserviceVoor} onSluiten={() => setWebserviceVoor(null)} onGewijzigd={laadAlles} />
      )}
      {schrijftestVoor && <SchrijftestDialog administratie={schrijftestVoor} onSluiten={() => setSchrijftestVoor(null)} />}
      {dossierTypenVoor && (
        <DossierTypenModal administratieId={dossierTypenVoor.id} naam={dossierTypenVoor.naam} onSluiten={() => setDossierTypenVoor(null)} />
      )}
      <ArchiveerDialog
        administratie={archiveerVoor}
        onSluiten={() => setArchiveerVoor(null)}
        onGearchiveerd={(m) => {
          setMelding(m)
          setArchiveerVoor(null)
          laadAlles()
        }}
      />

      {pending && (
        <BevestigDialog
          titel="Instelling wijzigen?"
          bericht={berichtVoor(pending)}
          bezig={bezig}
          fout={wijzigenFout}
          onBevestigen={() => void bevestigen()}
          onAnnuleren={() => {
            setWijzigenFout(null)
            setPending(null)
          }}
        />
      )}
    </div>,
  )
}
