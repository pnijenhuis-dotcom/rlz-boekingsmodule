import { useCallback, useEffect, useState } from 'react'
import { Link, Navigate, useLocation, useParams } from 'react-router-dom'
import { ApiError, apiJson } from '../api/client'
import { Button, Switch, SkeletonPaneel, SkeletonRegels } from '../ui/basis'
import type {
  AdministratieDto, AdministratieInstellingenDto } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { useMijnToegang } from '../auth/useMijnToegang'
import { zetIbanAccordeurs } from '../document/ibanAccorderingApi'
import { DoorbelastingInstellingen } from '../doorbelasting/DoorbelastingInstellingen'
import { DossierTypenModal } from './DossierTypenModal'
import { MateriaalCatalogusBeheer } from './MateriaalCatalogusBeheer'
import { AccorderingInstellingen } from './AccorderingInstellingen'
import { BevestigDialog } from './BevestigDialog'
import { BeveiligingInstellingen } from './BeveiligingInstellingen'
import { AdministratieWizard } from './AdministratieWizard'
import { AdministratiesV2 } from './AdministratiesV2'
import { SchrijftestDialog, WebserviceGegevensDialog } from './KoppelingDialogen'
import { LeverancierAutoboeken } from './LeverancierAutoboeken'
import { CrediteurDubbelen } from './CrediteurDubbelen'
import {
  haalAiKostenStatusOp,
  haalBoekenKillSwitchOp,
  haalInstellingenAdministratiesOp,
  haalIntakeAiInstellingOp,
  zetAiExtractieInstelling,
  zetAiKostenLimiet,
  zetBoekenInstelling,
  zetBoekenKillSwitch,
  zetEigenaar,
  zetIntakeAiInstelling,
  zetAfdelingenInstelling,
  zetProjectInstelling,
  zetVoorraadInstelling,
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

/** Sectiekaarten van de Instellingen-landing (besluit Peter 25-08, D2 — patroon Vastly's
 * configuratie-landing): elke kaart leidt naar een eigen subpagina `/instellingen/<sectie>`.
 * Geen functionaliteit gewijzigd, alleen herindeeld; deep-links naar de oude secties (hash of
 * ?sectie=) redirecten. */
export const INSTELLINGEN_SECTIES = [
  { pad: 'beveiliging', titel: 'Beveiliging', uitleg: 'Passkeys van jezelf en van medewerkers (apparaat-kill-switch).', beheerder: false },
  { pad: 'boeken', titel: 'Boeken & platform', uitleg: 'Boeken platformbreed aan/uit (noodstop) — de poort boven alle administraties.', beheerder: true },
  { pad: 'intake-ai', titel: 'Intake-AI & kosten', uitleg: 'AVG-gate voor de verzamelbak-AI en de maandelijkse AI-kostengrens.', beheerder: true },
  { pad: 'administraties', titel: 'Administraties', uitleg: 'Per administratie: eigenaar, IBAN-accordeurs, projectplicht, boeken, AI-extractie, autoboeken, uren & meerwerk, afdelingen, voorraad — mét bulkbediening.', beheerder: true },
  { pad: 'accordering', titel: 'Klant-accordering', uitleg: 'Goedkeuring door klanten: lagen, apparaten, staande goedkeuringen.', beheerder: true },
  { pad: 'autoboeken', titel: 'Autoboeken', uitleg: 'Automatisch boeken per leverancier (opt-in, harde checks blijven blokkerend).', beheerder: true },
  { pad: 'doorbelasting', titel: 'Doorbelasting', uitleg: 'Kempen-doorbelasting: toggle, provisie, whitelist doelentiteiten, opruimlijst.', beheerder: true },
  { pad: 'crediteuren', titel: 'Crediteuren', uitleg: 'Dubbel-signalering per administratie (btw-/KvK-nummer, IBAN, naam) — samenvoegen blijft RLZ-werk.', beheerder: true },
  { pad: 'materiaal', titel: 'Materiaalcatalogus', uitleg: 'Steigerbouw: leveranciers, catalogus (verpakking, m²-lengte), bestel-mailadres, crediteur-koppeling — bron voor bestellingen en transport.', beheerder: true },
  { pad: 'gebruikers', titel: 'Gebruikers & toegang', uitleg: 'Medewerkers, accordeurs en veldwerkers uitnodigen, rollen en scope, blokkeren.', beheerder: true, extern: '/gebruikers' },
] as const

export type InstellingenSectie = (typeof INSTELLINGEN_SECTIES)[number]['pad']

const SECTIE_PADEN = new Set<string>(INSTELLINGEN_SECTIES.map((s) => s.pad))

/** Rol×sectie-matrix, fail-closed (verzamelrun 31-08 blok B): een beheer-kaart is Beheerder-only
 * tenzij hier een expliciete uitzondering staat — élke nieuwe kaart of onbekende rol valt dus
 * automatisch dicht. Enige uitzondering (besluit Peter 31-08, spiegel van backend
 * `require_beheerder_of_bp`): Boekhouding+Projecten mag de Materiaalcatalogus (leveranciers,
 * contactpersonen, catalogus) bereiken. */
export function zichtbareSecties(rol: string | null) {
  return INSTELLINGEN_SECTIES.filter((k) => {
    if (!k.beheerder) return true // Beveiliging: eigen passkeys, elke kantoorrol
    if (rol === 'beheerder') return true
    return k.pad === 'materiaal' && rol === 'boekhouding_projecten'
  })
}

export function InstellingenScreen() {
  const { rol, status } = useAuth()
  const { sectie: sectieParam } = useParams<{ sectie?: string }>()
  const location = useLocation()
  // Blok B 31-08: B+P bereikt de Materiaalcatalogus — de administratie-namen komen dan uit de
  // scope-gefilterde /auth/administraties (het Beheerder-instellingen-endpoint is niet van hen),
  // de uren-&-meerwerk-opt-in-filter uit mijn-toegang (zelfde filter als de Beheerder-tak).
  const toegang = useMijnToegang()
  const [scopeAdministraties, setScopeAdministraties] = useState<AdministratieDto[] | null>(null)

  const [administraties, setAdministraties] = useState<AdministratieInstellingenDto[] | null>(null)
  const [accordeursVersie, setAccordeursVersie] = useState(0)
  const [killSwitch, setKillSwitch] = useState<boolean | null>(null)
  const [intakeAi, setIntakeAi] = useState<boolean | null>(null)
  const [aiKosten, setAiKosten] = useState<AiKostenStatusDto | null>(null)
  const [limietInvoer, setLimietInvoer] = useState('')
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [pending, setPending] = useState<PendingWijziging | null>(null)
  const [dossierTypenVoor, setDossierTypenVoor] = useState<{ id: string; naam: string } | null>(null)

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

  const laadAlles = useCallback(() => {
    setLaadFout(null)
    Promise.all([
      haalInstellingenAdministratiesOp(true),
      haalBoekenKillSwitchOp(),
      haalIntakeAiInstellingOp(),
      haalAiKostenStatusOp(),
    ])
      .then(([lijst, switchDto, intakeAiDto, aiKostenDto]) => {
        setAdministraties(lijst.administraties)
        setKillSwitch(switchDto.ingeschakeld)
        setIntakeAi(intakeAiDto.ingeschakeld)
        setAiKosten(aiKostenDto)
        setLimietInvoer(aiKostenDto.limiet_eur)
      })
      .catch((err: unknown) => setLaadFout(err instanceof Error ? err.message : 'Onbekende fout'))
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

  // Backend dwingt dit al af op elk endpoint hieronder — dit is de UI-kant. Sinds de
  // kantoor-passkeys (besluit 0020) is Instellingen voor élke kantoor-rol bereikbaar, maar een
  // niet-Beheerder ziet uitsluitend de Beveiliging-sectie (eigen passkeys) — de beheer-secties
  // renderen niet eens (design-pass taak 3: geen kale 403 of lege tabel). Wacht op `status`
  // (niet alleen `rol`) zodat dit ook correct is los van App.tsx's status==='laden'-gate.
  if (status === 'laden') {
    return <SkeletonPaneel />
  }
  const isBeheerder = rol === 'beheerder'

  // Deep-link-redirects (D2): oude vormen `#doorbelasting` / `?sectie=doorbelasting` → subpagina.
  const hashSectie = location.hash.replace(/^#/, '')
  const querySectie = new URLSearchParams(location.search).get('sectie')
  const doelSectie = [hashSectie, querySectie].find((x) => x && SECTIE_PADEN.has(x))
  if (!sectieParam && doelSectie) {
    return <Navigate to={`/instellingen/${doelSectie}`} replace />
  }
  if (sectieParam && !SECTIE_PADEN.has(sectieParam)) {
    return <Navigate to="/instellingen" replace />
  }
  const sectie = (sectieParam ?? null) as InstellingenSectie | null
  const sectieInfo = INSTELLINGEN_SECTIES.find((x) => x.pad === sectie) ?? null
  if (sectieInfo && 'extern' in sectieInfo && sectieInfo.extern) {
    return <Navigate to={sectieInfo.extern} replace />
  }

  if (!isBeheerder) {
    // Niet-Beheerder: fail-closed via de rol×sectie-matrix (zichtbareSecties). Boekhouding ziet
    // alleen Beveiliging (eigen passkeys, landing = subpagina); B+P daarnaast de
    // Materiaalcatalogus (blok B 31-08) — élke andere sectie valt terug op Beveiliging.
    const eigenSecties = zichtbareSecties(rol)
    const magMateriaal = eigenSecties.some((k) => k.pad === 'materiaal')
    if (magMateriaal && sectie === 'materiaal') {
      const materiaalAdministraties =
        toegang && scopeAdministraties
          ? scopeAdministraties.filter((a) => toegang.administraties_met_opt_in.includes(a.id))
          : null
      return (
        <div>
          <div className="topbar">
            <div>
              <div className="mb-1 text-[12.5px] text-muted">
                <Link to="/instellingen" className="text-primary no-underline hover:underline">
                  Instellingen
                </Link>{' '}
                <span className="text-faint">›</span> Materiaalcatalogus
              </div>
              <h1>Materiaalcatalogus</h1>
            </div>
          </div>
          {materiaalAdministraties === null ? (
            <SkeletonRegels />
          ) : (
            <MateriaalCatalogusBeheer administraties={materiaalAdministraties} />
          )}
        </div>
      )
    }
    if (magMateriaal && sectie === null) {
      return (
        <div>
          <div className="topbar">
            <div>
              <h1>Instellingen</h1>
              <p className="hint" style={{ margin: 0 }}>
                Kies een onderdeel.
              </p>
            </div>
          </div>
          <div className="instellingen-kaarten">
            {eigenSecties.map((k) => (
              <Link key={k.pad} to={`/instellingen/${k.pad}`} className="panel instellingen-kaart">
                <h2>{k.titel}</h2>
                <p className="hint">{k.uitleg}</p>
                <span className="rijlink text-primary" style={{ fontWeight: 600 }}>
                  Openen →
                </span>
              </Link>
            ))}
          </div>
        </div>
      )
    }
    return (
      <div>
        <div className="topbar">
          <h1>Instellingen</h1>
        </div>
        <BeveiligingInstellingen isBeheerder={false} />
      </div>
    )
  }
  if (sectie && sectieInfo && !sectieInfo.beheerder) {
    return (
      <div>
        <div className="topbar">
          <div>
            <div className="mb-1 text-[12.5px] text-muted">
              <Link to="/instellingen" className="text-primary no-underline hover:underline">
                Instellingen
              </Link>{' '}
              <span className="text-faint">›</span> {sectieInfo.titel}
            </div>
            <h1>{sectieInfo.titel}</h1>
          </div>
        </div>
        <BeveiligingInstellingen isBeheerder />
      </div>
    )
  }
  if (sectie === null) {
    return (
      <div>
        <div className="topbar">
          <div>
            <h1>Instellingen</h1>
            <p className="hint" style={{ margin: 0 }}>
              Platform-instellingen en bediening per administratie — kies een onderdeel.
            </p>
          </div>
        </div>
        {laadFout && <div className="fout">Kon instellingen niet laden: {laadFout}</div>}
        <div className="instellingen-kaarten">
          {INSTELLINGEN_SECTIES.map((k) => (
            <Link
              key={k.pad}
              to={'extern' in k && k.extern ? k.extern : `/instellingen/${k.pad}`}
              className="panel instellingen-kaart"
            >
              <h2>{k.titel}</h2>
              <p className="hint">{k.uitleg}</p>
              <span className="instellingen-kaart-stand">
                {k.pad === 'boeken' && killSwitch !== null && (
                  <span className={`chip ${killSwitch ? 'ok' : 'blokkerend'}`}>
                    {killSwitch ? 'boeken kan' : 'boeken staat plat'}
                  </span>
                )}
                {k.pad === 'intake-ai' && intakeAi !== null && (
                  <span className={`chip ${intakeAi ? 'ok' : 'geheugen'}`}>intake-AI {intakeAi ? 'aan' : 'uit'}</span>
                )}
                {k.pad === 'intake-ai' && aiKosten && (
                  <span className="chip geheugen">
                    € {aiKosten.verbruik_eur} / € {aiKosten.limiet_eur}
                  </span>
                )}
                {k.pad === 'administraties' && administraties && (
                  <span className="chip geheugen">{administraties.length} administraties</span>
                )}
              </span>
              <span className="rijlink text-primary" style={{ fontWeight: 600 }}>
                Openen →
              </span>
            </Link>
          ))}
        </div>
      </div>
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
                            ? { eigenaar_gebruiker_id: pending.eigenaarId ?? null }
                            : pending.type === 'afdelingen'
                              ? { afdelingen_ingeschakeld: pending.nieuweWaarde }
                              : pending.type === 'voorraad'
                                ? { voorraad_ingeschakeld: pending.nieuweWaarde }
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

  return (
    <div>
      <div className="topbar">
        <div>
          <div className="mb-1 text-[12.5px] text-muted">
            <Link to="/instellingen" className="text-primary no-underline hover:underline">
              Instellingen
            </Link>{' '}
            <span className="text-faint">›</span> {sectieInfo?.titel}
          </div>
          <h1>{sectieInfo?.titel}</h1>
        </div>
      </div>

      {laadFout && <div className="fout">Kon instellingen niet laden: {laadFout}</div>}

      {sectie === 'boeken' && (
      <div className="panel">
        {/* D4 (kliktest-les Peter 25-08): het label "Globale kill switch: uit" werd gelezen als
            "noodstop niet actief" terwijl het "boeken staat plat" betekent. Nu eenduidig:
            "Boeken platformbreed" aan = boeken kan, uit = boeken kan niet. Alleen presentatie —
            backend-endpoint/audit ongewijzigd.
            flexWrap + nowrap-label (kliktest 2026-08-16, ~1170px): de switch mét aan/uit-label
            wikkelt onder de tekst i.p.v. rechts uit het paneel te clippen. */}
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

      <div className="panel" style={{ marginTop: 16 }}>
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
              {/* Button-component i.p.v. kale <button> (kliktest 2026-08-16): de ongestylede
                  browser-default oogde in dark als disabled terwijl de knop actief was. */}
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
        {/* Kopregel-layout (UI-fix 01-09, screenshot Peter): de knop kromp eerder als flex-item
            onder de introtekst en viel daar half over de filterregel "N actief · gearchiveerd".
            Nu: tekstblok mét flex-basis (knop blijft rechtsboven naast de titel, v2-mockup-norm)
            + eigen marge onder de kopregel — knop en filterregel elk hun eigen ruimte, ook op de
            smalle sweep-breekpunten (het scherm zit in scripts/overflow_sweep.sh). */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap', marginBottom: 10 }}>
          <div style={{ flex: '1 1 320px', minWidth: 0 }}>
            <h2 style={{ marginTop: 0 }}>Administraties</h2>
            <p className="hint" style={{ marginTop: 4, marginBottom: 0 }}>
              Chips tonen alleen ingeschakelde modules en afwijkingen van de defaults (Boeken en AI-extractie staan standaard aan).
              Klik op een rij of ⚙ voor alle instellingen; selecteer rijen voor bulk-bediening. Elke wijziging vraagt één bevestiging en wordt geauditeerd.
            </p>
          </div>
          {/* Wizard (besluit Peter 26-08, punt 5): webservice-gegevens → probe groen → keuze uit
              GET Administrations → opslaan met defaults → eerste sync op de achtergrond. */}
          <Button style={{ flexShrink: 0 }} onClick={() => setWizardOpen(true)}>+ Administratie toevoegen</Button>
        </div>
        {administraties === null && !laadFout && <SkeletonRegels />}
        {administraties !== null && administraties.length === 0 && (
          <p className="hint">Nog geen administraties gekoppeld — begin met &ldquo;+ Administratie toevoegen&rdquo;.</p>
        )}
        {administraties !== null && administraties.length > 0 && (
          <AdministratiesV2
            administraties={administraties}
            selectie={selectie}
            setSelectie={setSelectie}
            accordeursVersie={accordeursVersie}
            onHerlaad={laadAlles}
            onPending={setPending}
            onWebservice={setWebserviceVoor}
            onSchrijftest={setSchrijftestVoor}
            onDossierTypen={(a) => setDossierTypenVoor({ id: a.id, naam: a.naam })}
            onDagmax={slaDagmaxOp}
          />
        )}
      </div>
      )}

      <AdministratieWizard open={wizardOpen} onSluiten={() => setWizardOpen(false)} onAangemaakt={laadAlles} />
      {webserviceVoor && (
        <WebserviceGegevensDialog administratie={webserviceVoor} onSluiten={() => setWebserviceVoor(null)} onGewijzigd={laadAlles} />
      )}
      {schrijftestVoor && <SchrijftestDialog administratie={schrijftestVoor} onSluiten={() => setSchrijftestVoor(null)} />}
      {dossierTypenVoor && (
        <DossierTypenModal administratieId={dossierTypenVoor.id} naam={dossierTypenVoor.naam} onSluiten={() => setDossierTypenVoor(null)} />
      )}

      {sectie === 'materiaal' && administraties !== null && (
        <MateriaalCatalogusBeheer administraties={administraties.filter((a) => a.uren_meerwerk_ingeschakeld && !a.gearchiveerd_op).map((a) => ({ id: a.id, naam: a.naam }) as AdministratieDto)} />
      )}

      {sectie === 'accordering' && administraties !== null && (
        <AccorderingInstellingen administraties={administraties.map((a) => ({ id: a.id, naam: a.naam }))} />
      )}

      {sectie === 'autoboeken' && administraties !== null && (
        <LeverancierAutoboeken administraties={administraties.map((a) => ({ id: a.id, naam: a.naam }))} />
      )}

      {sectie === 'doorbelasting' && administraties !== null && (
        <DoorbelastingInstellingen administraties={administraties.map((a) => ({ id: a.id, naam: a.naam }))} />
      )}
      {sectie === 'crediteuren' && administraties !== null && (
        <CrediteurDubbelen administraties={administraties.map((a) => ({ id: a.id, naam: a.naam }))} />
      )}
      {sectie !== 'administraties' && sectie !== 'boeken' && sectie !== 'intake-ai' && administraties === null && !laadFout && (
        <SkeletonRegels />
      )}

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
    </div>
  )
}
