import { useCallback, useEffect, useState } from 'react'
import { Link, Navigate, useLocation, useParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { Badge, Button, Checkbox, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle, Select, Switch } from '../ui/basis'
import type {
  AdministratieDto, AdministratieInstellingenDto } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { haalIbanAccordeursOp, zetIbanAccordeurs } from '../document/ibanAccorderingApi'
import { DoorbelastingInstellingen } from '../doorbelasting/DoorbelastingInstellingen'
import { useMedewerkers } from '../vragen/useMedewerkers'
import { DossierTypenModal } from './DossierTypenModal'
import { MateriaalCatalogusBeheer } from './MateriaalCatalogusBeheer'
import { AccorderingInstellingen } from './AccorderingInstellingen'
import { BevestigDialog } from './BevestigDialog'
import { BulkBediening } from './BulkBediening'
import { BeveiligingInstellingen } from './BeveiligingInstellingen'
import { LeverancierAutoboeken } from './LeverancierAutoboeken'
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
  zetProjectInstelling,
  zetUrenDagmaxInstelling,
  zetUrenMeerwerkInstelling,
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
  | 'uren_meerwerk'
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
    case 'uren_meerwerk':
      return pending.nieuweWaarde
        ? `Uren & meerwerk (steigerbouw-tak) wordt ingeschakeld voor "${pending.naam}": ZZP'ers/uitvoerders/detacheerders kunnen er weekstaten en meerwerk op werken en het kantoor ziet de standen (module-recht vereist).`
        : `Uren & meerwerk wordt uitgeschakeld voor "${pending.naam}" — de app en de kantoor-schermen weigeren dan; bestaande weekstaten en meerwerk blijven bewaard.`
    case 'verkoop_autoboeken':
      return pending.nieuweWaarde
        ? `Vastly-verkoopfacturen van "${pending.naam}" boeken voortaan automatisch zodra álles groen is (harde checks, ondubbelzinnige GB-codes en btw uit de UBL, geen vraag of duplicaatsignaal). Elk ander geval blijft gewoon in de werkvoorraad; elke automatische boeking is gemarkeerd en geauditeerd.`
        : `Verkoop-autoboeken wordt uitgeschakeld voor "${pending.naam}" — elke Vastly-verkoopfactuur wacht weer op een menselijke boek-klik.`
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
  if (pending.type === 'uren_meerwerk') {
    await zetUrenMeerwerkInstelling(pending.administratieId ?? '', pending.nieuweWaarde)
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

interface EigenaarCellProps {
  administratie: AdministratieInstellingenDto
  onKies: (eigenaarId: string | null, eigenaarNaam: string | undefined) => void
}

/** Eigenaar-select per administratie (mockup Instellingen "Eigenaar (krijgt vragen)"): de
 * toewijsbare medewerkers komen per rij uit het scope-gecontroleerde medewerkers-endpoint. */
function EigenaarCell({ administratie, onKies }: EigenaarCellProps) {
  const { medewerkers, fout } = useMedewerkers(administratie.id)
  if (fout) return <span className="hint" style={{ margin: 0 }}>medewerkers niet te laden</span>
  return (
    <Select
      aria-label={`Eigenaar van ${administratie.naam}`}
      value={administratie.eigenaar_gebruiker_id ?? ''}
      disabled={!medewerkers}
      onChange={(e) => {
        const id = e.target.value || null
        onKies(id, medewerkers?.find((m) => m.id === id)?.naam)
      }}
    >
      <option value="">— geen eigenaar —</option>
      {(medewerkers ?? []).map((m) => (
        <option key={m.id} value={m.id}>
          {m.naam}
        </option>
      ))}
    </Select>
  )
}

interface IbanAccordeursCellProps {
  administratie: AdministratieInstellingenDto
  /** Bump na een geslaagde wijziging: de cel herlaadt dan zijn set van de backend. */
  versie: number
  onWijzig: (nieuweSet: string[], omschrijving: string) => void
}

/** Instelling "IBAN-wissel accorderen door" (vier-ogen-flow, docs/ontwerp/
 * iban-wissel-accordering.md): één of meer medewerkers binnen de scope. Compact in de rij
 * (feedbackronde 25-08 deel 3 punt 4a — de open checkbox-lijst maakte elke rij 4-6 regels hoog):
 * de gekozen namen als chips, of "beheerders (terugval)" zonder set, plus "wijzig" dat de
 * checkbox-lijst in een dialoog opent (patroon ScopeModal). Opslaan in de dialoog = één
 * bevestigde wijziging (PUT met de volledige nieuwe set), zoals voorheen per vinkje. */
function IbanAccordeursCell({ administratie, versie, onWijzig }: IbanAccordeursCellProps) {
  const { medewerkers, fout: medewerkersFout } = useMedewerkers(administratie.id)
  const [accordeurs, setAccordeurs] = useState<string[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const [concept, setConcept] = useState<string[]>([])

  useEffect(() => {
    haalIbanAccordeursOp(administratie.id)
      .then((dto) => setAccordeurs(dto.accordeurs))
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Onbekende fout'))
  }, [administratie.id, versie])

  if (fout || medewerkersFout) {
    return (
      <span className="hint" style={{ margin: 0 }}>
        accordeurs niet te laden
      </span>
    )
  }
  if (accordeurs === null || !medewerkers) {
    return (
      <span className="hint" style={{ margin: 0 }}>
        Laden…
      </span>
    )
  }
  const naamVan = (id: string) => medewerkers.find((m) => m.id === id)?.naam ?? 'onbekend'
  const gekozen = accordeurs.filter((id) => medewerkers.some((m) => m.id === id))
  const opslaan = () => {
    const erbij = concept.filter((id) => !accordeurs.includes(id)).map(naamVan)
    const eraf = accordeurs.filter((id) => !concept.includes(id)).map(naamVan)
    setOpen(false)
    if (erbij.length === 0 && eraf.length === 0) return
    const delen = [
      erbij.length ? `${erbij.join(', ')} ${erbij.length === 1 ? 'wordt' : 'worden'} IBAN-accordeur` : null,
      eraf.length ? `${eraf.join(', ')} ${eraf.length === 1 ? 'is' : 'zijn'} niet langer IBAN-accordeur` : null,
    ].filter(Boolean)
    onWijzig(concept, delen.join('; '))
  }
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
      {gekozen.length === 0 ? (
        <Badge variant="stil" title="Geen accordeurs ingesteld — een IBAN-wissel valt terug op de beheerder(s)">
          beheerders (terugval)
        </Badge>
      ) : (
        gekozen.map((id) => (
          <Badge key={id} variant="info">
            {naamVan(id)}
          </Badge>
        ))
      )}
      <Button
        variant="ghost"
        maat="klein"
        aria-label={`IBAN-accordeurs van ${administratie.naam} wijzigen`}
        onClick={() => {
          setConcept(gekozen)
          setOpen(true)
        }}
      >
        wijzig
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogTitle>IBAN-wissel accorderen door — {administratie.naam}</DialogTitle>
          <DialogDescription>
            Wie mag een IBAN-wissel accorderen (vier ogen — nooit de aanvrager zelf)? Zonder keuze valt de
            accordering terug op de beheerder(s). Opslaan vraagt één bevestiging en wordt geauditeerd.
          </DialogDescription>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, margin: '10px 0' }}>
            {medewerkers.map((m) => (
              <label key={m.id} style={{ display: 'flex', alignItems: 'center', gap: 8, margin: 0, fontSize: 13 }}>
                <Checkbox
                  checked={concept.includes(m.id)}
                  onChange={(e) =>
                    setConcept((huidig) => (e.target.checked ? [...huidig, m.id] : huidig.filter((id) => id !== m.id)))
                  }
                />
                {m.naam}
              </label>
            ))}
            {medewerkers.length === 0 && (
              <span className="hint" style={{ margin: 0 }}>
                Geen medewerkers met scope op deze administratie.
              </span>
            )}
          </div>
          <DialogFooter>
            <Button variant="secundair" onClick={() => setOpen(false)}>
              Annuleren
            </Button>
            <Button onClick={opslaan}>Opslaan</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

/** Sectiekaarten van de Instellingen-landing (besluit Peter 25-08, D2 — patroon Vastly's
 * configuratie-landing): elke kaart leidt naar een eigen subpagina `/instellingen/<sectie>`.
 * Geen functionaliteit gewijzigd, alleen herindeeld; deep-links naar de oude secties (hash of
 * ?sectie=) redirecten. */
export const INSTELLINGEN_SECTIES = [
  { pad: 'beveiliging', titel: 'Beveiliging', uitleg: 'Passkeys van jezelf en van medewerkers (apparaat-kill-switch).', beheerder: false },
  { pad: 'boeken', titel: 'Boeken & platform', uitleg: 'Boeken platformbreed aan/uit (noodstop) — de poort boven alle administraties.', beheerder: true },
  { pad: 'intake-ai', titel: 'Intake-AI & kosten', uitleg: 'AVG-gate voor de verzamelbak-AI en de maandelijkse AI-kostengrens.', beheerder: true },
  { pad: 'administraties', titel: 'Administraties', uitleg: 'Per administratie: eigenaar, IBAN-accordeurs, projectplicht, boeken, AI-extractie, autoboeken, uren & meerwerk — mét bulkbediening.', beheerder: true },
  { pad: 'accordering', titel: 'Klant-accordering', uitleg: 'Goedkeuring door klanten: lagen, apparaten, staande goedkeuringen.', beheerder: true },
  { pad: 'autoboeken', titel: 'Autoboeken', uitleg: 'Automatisch boeken per leverancier (opt-in, harde checks blijven blokkerend).', beheerder: true },
  { pad: 'doorbelasting', titel: 'Doorbelasting', uitleg: 'Kempen-doorbelasting: toggle, provisie, whitelist doelentiteiten, opruimlijst.', beheerder: true },
  { pad: 'materiaal', titel: 'Materiaalcatalogus', uitleg: 'Steigerbouw: leveranciers, catalogus (verpakking, m²-lengte), bestel-mailadres, crediteur-koppeling — bron voor bestellingen en transport.', beheerder: true },
  { pad: 'gebruikers', titel: 'Gebruikers & toegang', uitleg: 'Medewerkers, accordeurs en veldwerkers uitnodigen, rollen en scope, blokkeren.', beheerder: true, extern: '/gebruikers' },
] as const

export type InstellingenSectie = (typeof INSTELLINGEN_SECTIES)[number]['pad']

const SECTIE_PADEN = new Set<string>(INSTELLINGEN_SECTIES.map((s) => s.pad))

export function InstellingenScreen() {
  const { rol, status } = useAuth()
  const { sectie: sectieParam } = useParams<{ sectie?: string }>()
  const location = useLocation()

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

  const laadAlles = useCallback(() => {
    setLaadFout(null)
    Promise.all([
      haalInstellingenAdministratiesOp(),
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

  // Backend dwingt dit al af op elk endpoint hieronder — dit is de UI-kant. Sinds de
  // kantoor-passkeys (besluit 0020) is Instellingen voor élke kantoor-rol bereikbaar, maar een
  // niet-Beheerder ziet uitsluitend de Beveiliging-sectie (eigen passkeys) — de beheer-secties
  // renderen niet eens (design-pass taak 3: geen kale 403 of lege tabel). Wacht op `status`
  // (niet alleen `rol`) zodat dit ook correct is los van App.tsx's status==='laden'-gate.
  if (status === 'laden') {
    return <p className="hint">Laden…</p>
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
    // Niet-Beheerder: alleen Beveiliging (eigen passkeys) — landing én subpagina zijn hetzelfde.
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
                          : pending.type === 'eigenaar'
                            ? { eigenaar_gebruiker_id: pending.eigenaarId ?? null }
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
        <h2 style={{ marginTop: 0 }}>Administraties</h2>
        <p className="hint" style={{ marginTop: 4 }}>
          Selecteer rijen voor bulk-bediening. Elke wijziging vraagt één bevestiging en wordt geauditeerd.
        </p>
        {administraties === null && !laadFout && <p className="hint">Laden…</p>}
        {administraties !== null && administraties.length === 0 && (
          <p className="hint">Nog geen administraties gekoppeld.</p>
        )}
        {administraties !== null && administraties.length > 0 && (
          <>
          <BulkBediening
            administraties={administraties}
            geselecteerd={selectie}
            onWisSelectie={() => setSelectie([])}
            onGereed={laadAlles}
          />
          {/* .tabel-scroll (kliktest 2026-08-16, ~1170px): acht kolommen clipten rechts buiten
              het paneel zonder scroll — brede inhoud scrolt intern, nooit paginabreed.
              sticky-koppen (kliktest 2026-08-21): bij 11+ administraties blijven de kolomkoppen
              in beeld tijdens het scrollen. */}
          <div className="tabel-scroll sticky-koppen">
          <table>
            <tbody>
              <tr>
                <th style={{ width: 36 }}>
                  <Checkbox
                    aria-label="Alle administraties selecteren"
                    checked={selectie.length === administraties.length}
                    indeterminate={selectie.length > 0 && selectie.length < administraties.length}
                    onChange={(e) => setSelectie(e.target.checked ? administraties.map((a) => a.id) : [])}
                  />
                </th>
                <th>Administratie</th>
                <th>Eigenaar (krijgt vragen)</th>
                <th>IBAN-wissel accorderen door</th>
                <th>Project verplicht bij boeken</th>
                <th>Boeken ingeschakeld</th>
                <th>AI-extractie (AVG-gate)</th>
                <th>Autoboeken Vastly-verkoop</th>
                <th>Uren &amp; meerwerk</th>
              </tr>
              {administraties.map((a) => (
                <tr key={a.id} className={selectie.includes(a.id) ? 'geselecteerd' : undefined}>
                  <td>
                    <Checkbox
                      aria-label={`Selecteer ${a.naam}`}
                      checked={selectie.includes(a.id)}
                      onChange={(e) =>
                        setSelectie((huidig) =>
                          e.target.checked ? [...huidig, a.id] : huidig.filter((id) => id !== a.id),
                        )
                      }
                    />
                  </td>
                  <td>{a.naam}</td>
                  <td>
                    <EigenaarCell
                      administratie={a}
                      onKies={(eigenaarId, eigenaarNaam) =>
                        setPending({
                          type: 'eigenaar',
                          administratieId: a.id,
                          naam: a.naam,
                          nieuweWaarde: eigenaarId !== null,
                          eigenaarId,
                          eigenaarNaam,
                        })
                      }
                    />
                  </td>
                  <td>
                    <IbanAccordeursCell
                      administratie={a}
                      versie={accordeursVersie}
                      onWijzig={(nieuweSet, omschrijving) =>
                        setPending({
                          type: 'iban_accordeurs',
                          administratieId: a.id,
                          naam: a.naam,
                          nieuweWaarde: nieuweSet.length > 0,
                          accordeurs: nieuweSet,
                          accordeursOmschrijving: omschrijving,
                        })
                      }
                    />
                  </td>
                  <td>
                    <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0, whiteSpace: 'nowrap' }}>
                      <Switch
                        aria-label={`Project verplicht voor ${a.naam}`}
                        checked={a.project_verplicht}
                        onChange={(e) =>
                          setPending({
                            type: 'project',
                            administratieId: a.id,
                            naam: a.naam,
                            nieuweWaarde: e.target.checked,
                          })
                        }
                      />
                      {a.project_verplicht ? 'aan' : 'uit'}
                    </label>
                  </td>
                  <td>
                    <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0, whiteSpace: 'nowrap' }}>
                      <Switch
                        aria-label={`Boeken ingeschakeld voor ${a.naam}`}
                        checked={a.boeken_ingeschakeld}
                        onChange={(e) =>
                          setPending({
                            type: 'boeken',
                            administratieId: a.id,
                            naam: a.naam,
                            nieuweWaarde: e.target.checked,
                          })
                        }
                      />
                      {a.boeken_ingeschakeld ? 'aan' : 'uit'}
                    </label>
                  </td>
                  <td>
                    <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0, whiteSpace: 'nowrap' }}>
                      <Switch
                        aria-label={`AI-extractie voor ${a.naam}`}
                        checked={a.ai_extractie_ingeschakeld}
                        onChange={(e) =>
                          setPending({
                            type: 'ai_extractie',
                            administratieId: a.id,
                            naam: a.naam,
                            nieuweWaarde: e.target.checked,
                          })
                        }
                      />
                      {a.ai_extractie_ingeschakeld ? 'aan' : 'uit'}
                    </label>
                  </td>
                  <td>
                    {a.is_vastgoed ? (
                      <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0, whiteSpace: 'nowrap' }}>
                        <Switch
                          aria-label={`Autoboeken Vastly-verkoop voor ${a.naam}`}
                          checked={a.verkoop_autoboeken_ingeschakeld}
                          onChange={(e) =>
                            setPending({
                              type: 'verkoop_autoboeken',
                              administratieId: a.id,
                              naam: a.naam,
                              nieuweWaarde: e.target.checked,
                            })
                          }
                        />
                        {a.verkoop_autoboeken_ingeschakeld ? 'aan' : 'uit'}
                      </label>
                    ) : (
                      <span className="hint" title="Alleen voor vastgoed-administraties (Vastly-verkoopfacturen)">
                        —
                      </span>
                    )}
                  </td>
                  <td>
                    <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0, whiteSpace: 'nowrap' }}>
                      <Switch
                        aria-label={`Uren & meerwerk voor ${a.naam}`}
                        checked={a.uren_meerwerk_ingeschakeld}
                        onChange={(e) =>
                          setPending({
                            type: 'uren_meerwerk',
                            administratieId: a.id,
                            naam: a.naam,
                            nieuweWaarde: e.target.checked,
                          })
                        }
                      />
                      {a.uren_meerwerk_ingeschakeld ? 'aan' : 'uit'}
                    </label>
                    {a.uren_meerwerk_ingeschakeld && (
                      <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 6, flexWrap: 'wrap' }}>
                        {/* A6 (25-08): drempel >N uur per dag — signaal bij de keuring, geen blokkade. */}
                        <label style={{ display: 'flex', gap: 4, alignItems: 'center', fontSize: 11, margin: 0 }} title="Signaal >N uur per dag (som over alle weekstaten per kalenderdag)">
                          max/dag
                          <input
                            type="number"
                            inputMode="decimal"
                            min={0.5}
                            max={24}
                            step={0.5}
                            aria-label={`Dagdrempel uren voor ${a.naam}`}
                            defaultValue={a.uren_dagmax_uren}
                            style={{ width: 62, padding: '2px 6px' }}
                            onBlur={(e) => {
                              const waarde = e.target.value.replace(',', '.')
                              if (waarde !== '' && Number(waarde) !== Number(a.uren_dagmax_uren)) void slaDagmaxOp(a.id, a.naam, waarde)
                            }}
                          />
                          u
                        </label>
                        <Button variant="ghost" maat="klein" onClick={() => setDossierTypenVoor({ id: a.id, naam: a.naam })}>
                          📁 Dossier-documenttypen…
                        </Button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
          </>
        )}
      </div>
      )}

      {dossierTypenVoor && (
        <DossierTypenModal administratieId={dossierTypenVoor.id} naam={dossierTypenVoor.naam} onSluiten={() => setDossierTypenVoor(null)} />
      )}

      {sectie === 'materiaal' && administraties !== null && (
        <MateriaalCatalogusBeheer administraties={administraties.filter((a) => a.uren_meerwerk_ingeschakeld).map((a) => ({ id: a.id, naam: a.naam }) as AdministratieDto)} />
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
      {sectie !== 'administraties' && sectie !== 'boeken' && sectie !== 'intake-ai' && administraties === null && !laadFout && (
        <p className="hint">Laden…</p>
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
