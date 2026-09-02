import { useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, apiJson } from '../api/client'
import type {
  DoorbelastingMappingDto,
  DoorbelastingRunDto,
  DoorbelastingVerdeelRegelInputDto,
  VerdeelsleutelDoelInputDto,
  VerdeelsleutelDto,
} from '../api/types'
import { SearchableCombobox } from '../document/SearchableCombobox'
import { AnkerPopup, MultiSelect, Select } from '../ui/basis'
import { haalVerdeelsleutelsOp, pasVerdeelsleutelToe, slaDoorbelastingVerdelingOp, slaVerdeelsleutelOp } from './doorbelastingApi'
import {
  bedragNaarPercentage,
  formatPct,
  parsePercentage,
  percentageNaarBedrag,
  percentageVoorBackend,
  restPercentage,
  restantStand,
  somPercentages as somVanInvoer,
} from './percentage'
import { boekingStatusChip, formatEuroString, formatPercentage } from './status'
import { useDoelGrootboek } from './useDoelGrootboek'
import { useDoelProjecten } from './useDoelProjecten'

/** Eén bron-regel van het document (uit het bestaande boekvoorstel-endpoint). */
export interface BronRegel {
  id: string
  omschrijving: string
  netto: string | null
}

/** Eén verdeelregel in bewerking (mockup doorbelasten-blok-v2 ①): doelentiteit + % ÓF bedrag
 * (twee kanten van één waarde — `percentage` is de bron, `bedragInvoer` de getypte andere kant)
 * + doel-kosten-GB in een uitklap. `nettoDeel` is uitsluitend het server-berekende deel uit de
 * laatste opslag — de client rekent nooit bindend (grootste-rest leeft in de backend). */
interface VerdeelRij {
  key: string
  mappingId: string | null
  percentage: string
  bedragInvoer: string | null
  gbId: string | null
  gbOpen: boolean
  nettoDeel: string | null
  /** Doorbelasting × projecten (besluit Peter 25-08): projecten in de doel-administratie —
   * leeg = geen project, één = dat project, meerdere = multi-project-verdeling (server splitst
   * naar `verdeelbasis`). `alleActief` onthoudt de knop "alle actieve projecten" zodat een
   * opgeslagen verdeelsleutel dynamisch blijft ("alle_actief") i.p.v. een bevroren lijst. */
  projectIds: string[]
  verdeelbasis: 'm2' | 'gelijk' | null
  alleActief: boolean
  /** Server-berekende delen per project uit de laatste opslag (weergave). */
  projectDelen: { projectId: string; naam: string | null; nettoDeel: string; m2: string | null }[]
}

type Verdeling = Record<string, VerdeelRij[]>

/** Run-regels → werkstaat: de project-rijen van één (bron-regel, doelentiteit) vouwen samen tot
 * één verdeelrij met een projectenlijst (de server bewaart één rij per project). */
function verdelingUitRun(run: DoorbelastingRunDto): Verdeling {
  const verdeling: Verdeling = {}
  const perSleutel = new Map<string, VerdeelRij>()
  for (const regel of run.regels) {
    const lijst = verdeling[regel.bron_regel_id] ?? (verdeling[regel.bron_regel_id] = [])
    const sleutel = `${regel.bron_regel_id}|${regel.mapping_id}`
    let rij = perSleutel.get(sleutel)
    if (!rij) {
      rij = {
        key: regel.id,
        mappingId: regel.mapping_id,
        percentage: formatPercentage(regel.percentage),
        bedragInvoer: null,
        gbId: regel.doel_kosten_ledger_id,
        gbOpen: false,
        nettoDeel: '0.00',
        projectIds: [],
        verdeelbasis: regel.verdeelbasis ?? null,
        alleActief: false,
        projectDelen: [],
      }
      perSleutel.set(sleutel, rij)
      lijst.push(rij)
    }
    rij.nettoDeel = (Number(rij.nettoDeel) + Number(regel.netto_deel)).toFixed(2)
    if (regel.project_id) {
      rij.projectIds.push(regel.project_id)
      rij.projectDelen.push({
        projectId: regel.project_id,
        naam: regel.project_naam ?? null,
        nettoDeel: regel.netto_deel,
        m2: regel.m2 ?? null,
      })
    }
  }
  return verdeling
}

function nieuweRij(percentage: string): VerdeelRij {
  return {
    key: crypto.randomUUID(),
    mappingId: null,
    percentage,
    bedragInvoer: null,
    gbId: null,
    gbOpen: false,
    nettoDeel: null,
    projectIds: [],
    verdeelbasis: null,
    alleActief: false,
    projectDelen: [],
  }
}

function formatM2(m2: string | null): string {
  if (m2 === null) return 'geen m²'
  return `${Number(m2).toLocaleString('nl-NL', { maximumFractionDigits: 2 })} m²`
}

/** Percentagesom van de rijen van één bron-regel (2 decimalen, ongeldig = 0) — weergave/
 * poortwachter; de harde check leeft server-side. Parsen/afronden: `percentage.ts`. */
function somPercentages(rijen: VerdeelRij[]): number {
  return somVanInvoer(rijen.map((rij) => rij.percentage))
}

/** Server-staat van de run: sluit elke verdeelde bron-regel exact op 100%? Synchroon
 * afleidbaar uit de run (zonder editor-effect), zodat een boekknop nooit één render lang
 * ten onrechte actief staat vóór de editor zijn werkstaat gemeld heeft. */
export function runVerdelingOnvolledig(run: DoorbelastingRunDto): boolean {
  return Object.values(verdelingUitRun(run)).some((rijen) => rijen.length > 0 && somPercentages(rijen) !== 100)
}

/** Werkstaat-signalen voor de aanroeper (boekknop-poort): onopgeslagen wijzigingen of een
 * verdeelde regel die niet op 100% sluit = niet groen. `blokkade` = de ene zin waarom er (nog)
 * niet opgeslagen wordt — dezelfde tekst als onder de tabel. */
export interface VerdelingStaat {
  gewijzigd: boolean
  onvolledig: boolean
  blokkade?: string | null
}

interface Props {
  administratieId: string
  run: DoorbelastingRunDto
  bronRegels: BronRegel[]
  regelIdsOntbreken: boolean
  mappings: DoorbelastingMappingDto[]
  /** Server-side bevroren (geboekt / bij de klant) — de UI biedt bewerken dan niet aan. */
  bevroren: boolean
  onRunGewijzigd: (run: DoorbelastingRunDto) => void
  onStaat?: (staat: VerdelingStaat) => void
  /** Compacte variant voor het controlescherm-blok "Doorbelasten na boeken": geen eigen
   * checks-paneel (de boekknop toont de gecombineerde poort), wél preview. */
  compact?: boolean
}

/** Debounce van het automatisch opslaan: de server berekent de centen bindend, dus élke geldige
 * verdeling gaat kort ná de laatste toetsaanslag naar de server (één primaire actie = boeken;
 * geen aparte opslaanknop meer — mockup doorbelasten-blok-v2 ②). */
export const AUTO_OPSLAAN_MS = 600

/** Restant-balk (mockup doorbelasten-blok-v2 ②: de enige voortgangsindicator, drie standen). */
function RestantBalk({ netto, rijen }: { netto: string | null; rijen: VerdeelRij[] }) {
  const som = somPercentages(rijen)
  const stand = restantStand(som)
  const nettoGetal = netto === null ? null : Number(netto)
  const breedte = Math.min(100, Math.max(0, som))
  const nogPct = Math.max(0, 100 - som)
  return (
    <div className={`restant-balk ${stand === 'compleet' ? 'compleet' : stand === 'te_veel' ? 'te-veel' : ''}`} data-testid="restant-balk">
      {nettoGetal !== null && Number.isFinite(nettoGetal) && <b>€ {formatEuroString(netto!)} excl.</b>}
      <div className="balk" aria-hidden="true">
        <span style={{ width: `${breedte}%` }} />
      </div>
      {rijen.length === 0 ? (
        <span className="chip geheugen">niet doorbelast</span>
      ) : stand === 'compleet' ? (
        <b className="compleet-tekst">verdeeld 100% ✓</b>
      ) : stand === 'te_veel' ? (
        <span className="te-veel-tekst">
          {formatPct(som)}% — {formatPct(som - 100)}% te veel
        </span>
      ) : (
        <>
          <b>verdeeld {formatPct(som)}%</b>
          <span className="nog">
            nog {formatPct(nogPct)}%
            {nettoGetal !== null && Number.isFinite(nettoGetal) && nettoGetal !== 0
              ? ` · € ${formatEuroString(String(percentageNaarBedrag(nettoGetal, nogPct)))}`
              : ''}
          </span>
        </>
      )}
    </div>
  )
}

/** Herbruikbare verdeel-UI v2 (mockup `doorbelasten-blok-v2.html` = norm, akkoord Peter 02-09):
 * per bron-regel een restant-balk + verdeel-tabel (doelentiteit · % · bedrag · project) waarin
 * % en bedrag live gekoppeld zijn, één "Verdeelsleutel ▾"-menu, lege projectstand als actie
 * ("Nu synchroniseren"), GB in een uitklap per rij, compacte preview pas ná een geldige
 * verdeling. Opslaan gebeurt automatisch zodra de verdeling compleet is; de server berekent de
 * centen bindend (grootste-rest). Zelfde component in het reviewscherm (na boeken) én in het
 * blok "Doorbelasten na boeken" (vóór boeken). */
export function VerdelingEditor({
  administratieId,
  run,
  bronRegels,
  regelIdsOntbreken,
  mappings,
  bevroren,
  onRunGewijzigd,
  onStaat,
  compact = false,
}: Props) {
  const [verdeling, setVerdeling] = useState<Verdeling>(() => verdelingUitRun(run))
  // Elke wijziging maakt het laatste server-resultaat (netto-delen + checks) verouderd —
  // boeken kan pas weer ná een verse opslag (server berekent bindend).
  const [gewijzigd, setGewijzigd] = useState(false)
  const [opslaanBezig, setOpslaanBezig] = useState(false)
  const [opslaanFout, setOpslaanFout] = useState<string | null>(null)

  // Verse run van de server (na opslaan/boeken/herkoppeling) → werkstaat opnieuw afleiden.
  useEffect(() => {
    setVerdeling(verdelingUitRun(run))
    setGewijzigd(false)
  }, [run])

  const actieveMappings = useMemo(() => mappings.filter((m) => m.actief), [mappings])
  const mappingPerId = useMemo(() => new Map(mappings.map((m) => [m.id, m])), [mappings])
  const bronPerId = useMemo(() => new Map(bronRegels.map((b) => [b.id, b])), [bronRegels])
  const doelGrootboek = useDoelGrootboek(
    useMemo(
      () =>
        Object.values(verdeling)
          .flat()
          .map((rij) => (rij.mappingId ? (mappingPerId.get(rij.mappingId)?.doel_administratie_id ?? null) : null)),
      [verdeling, mappingPerId],
    ),
  )

  const { kaart: doelProjecten, herlaad: herlaadProjecten } = useDoelProjecten(
    administratieId,
    useMemo(() => Object.values(verdeling).flat().map((rij) => rij.mappingId), [verdeling]),
  )

  // Lege stand als actie (mockup ④): "nog geen projecten gesynchroniseerd → Nu synchroniseren"
  // triggert de bestaande projecten-sync van de DOEL-administratie en haalt de lijst opnieuw op.
  const [syncStand, setSyncStand] = useState<Record<string, 'bezig' | string>>({})
  const synchroniseerProjecten = async (mappingId: string, doelId: string) => {
    setSyncStand((s) => ({ ...s, [mappingId]: 'bezig' }))
    try {
      await apiJson(`/administraties/${doelId}/sync/projects`, { method: 'POST' })
      herlaadProjecten(mappingId)
      setSyncStand((s) => {
        const kopie = { ...s }
        delete kopie[mappingId]
        return kopie
      })
    } catch (err) {
      const melding =
        err instanceof ApiError && err.status === 403
          ? 'Geen toegang tot de doel-administratie (geen scope) — vraag de Beheerder.'
          : `Synchroniseren mislukt: ${err instanceof Error ? err.message : 'onbekende fout'}`
      setSyncStand((s) => ({ ...s, [mappingId]: melding }))
    }
  }

  // Verdeelsleutels (25-08, punt 2c) achter één menu (mockup ③): toepassen per sleutel,
  // opslaan-als vanuit de huidige verdeling. Beheren (hernoemen/intrekken) heeft nog geen
  // endpoint — bewust niet als dode knop getoond.
  const [sleutels, setSleutels] = useState<VerdeelsleutelDto[]>([])
  const [sleutelMenuOpen, setSleutelMenuOpen] = useState(false)
  const [sleutelOpslaanOpen, setSleutelOpslaanOpen] = useState(false)
  const [sleutelNaam, setSleutelNaam] = useState('')
  const [sleutelBezig, setSleutelBezig] = useState(false)
  const [sleutelMelding, setSleutelMelding] = useState<string | null>(null)
  const sleutelKnop = useRef<HTMLButtonElement | null>(null)
  useEffect(() => {
    if (bevroren) return
    let actief = true
    haalVerdeelsleutelsOp(administratieId)
      .then((lijst) => {
        if (actief) setSleutels(lijst)
      })
      .catch(() => {
        // Geen sleutels beschikbaar (bv. oudere backend/test-mock) — de editor werkt gewoon door.
      })
    return () => {
      actief = false
    }
  }, [administratieId, bevroren])

  const sleutelToepassen = async (sleutelId: string) => {
    setSleutelMenuOpen(false)
    setSleutelBezig(true)
    setSleutelMelding(null)
    try {
      const vers = await pasVerdeelsleutelToe(administratieId, run.id, sleutelId)
      onRunGewijzigd(vers)
      setSleutelMelding('Verdeelsleutel toegepast — controleer en pas zo nodig aan.')
    } catch (err) {
      setSleutelMelding(err instanceof ApiError ? err.message : 'Verdeelsleutel toepassen mislukt.')
    } finally {
      setSleutelBezig(false)
    }
  }

  /** Sleutel-definitie uit de huidige verdeling: per doelentiteit (uit de eerste verdeelde
   * bron-regel — een sleutel geldt voor élke regel). "Alle actieve projecten" blijft dynamisch. */
  const sleutelDoelenUitVerdeling = (): VerdeelsleutelDoelInputDto[] | null => {
    const eerste = Object.values(verdeling).find((rijen) => rijen.length > 0)
    if (!eerste) return null
    const doelen: VerdeelsleutelDoelInputDto[] = []
    for (const rij of eerste) {
      const pct = percentageVoorBackend(rij.percentage)
      if (!rij.mappingId || pct === null) return null
      doelen.push({
        mapping_id: rij.mappingId,
        percentage: pct,
        doel_kosten_ledger_id: rij.gbId,
        projecten: rij.alleActief ? 'alle_actief' : rij.projectIds,
        verdeelbasis: rij.projectIds.length > 1 || rij.alleActief ? (rij.verdeelbasis ?? 'gelijk') : null,
      })
    }
    return doelen
  }

  const sleutelOpslaan = async () => {
    const doelen = sleutelDoelenUitVerdeling()
    if (!doelen) {
      setSleutelMelding('Maak eerst een volledige verdeling (doelentiteit + geldig percentage per rij) om als sleutel op te slaan.')
      return
    }
    setSleutelBezig(true)
    setSleutelMelding(null)
    try {
      const nieuw = await slaVerdeelsleutelOp(administratieId, { naam: sleutelNaam.trim(), doelen })
      setSleutels((huidig) => [...huidig.filter((s) => s.naam !== nieuw.naam), nieuw].sort((a, b) => a.naam.localeCompare(b.naam)))
      setSleutelNaam('')
      setSleutelOpslaanOpen(false)
      setSleutelMelding(`Verdeelsleutel "${nieuw.naam}" opgeslagen als versie ${nieuw.versie}.`)
    } catch (err) {
      setSleutelMelding(err instanceof ApiError ? err.message : 'Verdeelsleutel opslaan mislukt.')
    } finally {
      setSleutelBezig(false)
    }
  }

  const wijzig = (bronId: string, key: string, wijziging: Partial<VerdeelRij>) => {
    setVerdeling((huidig) => ({
      ...huidig,
      [bronId]: (huidig[bronId] ?? []).map((rij) => (rij.key === key ? { ...rij, ...wijziging, nettoDeel: null } : rij)),
    }))
    setGewijzigd(true)
  }

  /** Alleen-weergave-wijziging (uitklap open/dicht) — geen opslag-trigger. */
  const wijzigWeergave = (bronId: string, key: string, wijziging: Partial<VerdeelRij>) => {
    setVerdeling((huidig) => ({
      ...huidig,
      [bronId]: (huidig[bronId] ?? []).map((rij) => (rij.key === key ? { ...rij, ...wijziging } : rij)),
    }))
  }

  const voegRijToe = (bronId: string) => {
    setVerdeling((huidig) => {
      const rijen = huidig[bronId] ?? []
      // Bugfix 02-09: `100 - som` gaf floating-point-ruis ("11,099999999999994") die letterlijk
      // in het %-veld belandde — de rest komt nu afgerond uit één bron.
      const rest = restPercentage(rijen.map((rij) => rij.percentage))
      return { ...huidig, [bronId]: [...rijen, nieuweRij(formatPct(rest))] }
    })
    setGewijzigd(true)
  }

  const verwijderRij = (bronId: string, key: string) => {
    setVerdeling((huidig) => ({ ...huidig, [bronId]: (huidig[bronId] ?? []).filter((rij) => rij.key !== key) }))
    setGewijzigd(true)
  }

  // Eén zin waarom er (nog) niet opgeslagen/geboekt kan worden — de blokkeer-reden onder de
  // tabel (mockup ②) én de poort voor het automatisch opslaan.
  const blokkade = useMemo<string | null>(() => {
    if (regelIdsOntbreken) return 'Niet alle boekingsregels zijn al opgeslagen — pas het voorstel aan, dan verschijnen ze hier.'
    for (const [bronId, rijen] of Object.entries(verdeling)) {
      if (rijen.length === 0) continue
      for (const rij of rijen) {
        if (!rij.mappingId) return 'Kies voor elke rij een doelentiteit — of verwijder de rij.'
        const parse = parsePercentage(rij.percentage)
        if (parse.fout) return parse.fout
        if (parse.waarde === null || parse.waarde <= 0) return 'Elk percentage moet groter dan 0 zijn.'
        if (rij.projectIds.length > 1 && rij.verdeelbasis === null) {
          return 'Kies bij meerdere projecten een verdeelbasis: naar rato m² of gelijk per object.'
        }
        const info = doelProjecten[rij.mappingId]
        const naam = mappingPerId.get(rij.mappingId)?.doelentiteit_naam ?? 'de doel-administratie'
        if (info?.projectVerplicht && rij.projectIds.length === 0) return `Project verplicht in ${naam} — kies minimaal één project.`
        if (rij.verdeelbasis === 'm2' && rij.projectIds.length > 1) {
          const zonderM2 = (info?.projecten ?? []).filter((p) => rij.projectIds.includes(p.id) && p.contract_m2 === null)
          if (zonderM2.length > 0) return `Geen m² bekend voor ${zonderM2.map((p) => p.naam).join(', ')} — vul de projectspecificatie aan of kies "gelijk per object".`
        }
      }
      const som = somPercentages(rijen)
      const bron = bronPerId.get(bronId)
      const label = bronRegels.length > 1 && bron ? ` (${bron.omschrijving})` : ''
      if (som < 100) return `Nog ${formatPct(100 - som)}% te verdelen${label}.`
      if (som > 100) return `${formatPct(som - 100)}% te veel verdeeld${label}.`
    }
    return null
  }, [verdeling, regelIdsOntbreken, doelProjecten, mappingPerId, bronPerId, bronRegels.length])

  const verdelingOnvolledig = Object.values(verdeling).some(
    (rijen) => rijen.length > 0 && (somPercentages(rijen) !== 100 || rijen.some((rij) => parsePercentage(rij.percentage).fout !== null)),
  )
  useEffect(() => {
    onStaat?.({ gewijzigd, onvolledig: verdelingOnvolledig, blokkade })
  }, [gewijzigd, verdelingOnvolledig, blokkade, onStaat])

  const opslaan = async () => {
    setOpslaanBezig(true)
    setOpslaanFout(null)
    try {
      const regels: DoorbelastingVerdeelRegelInputDto[] = []
      for (const [bronId, rijen] of Object.entries(verdeling)) {
        for (const rij of rijen) {
          const pct = rij.mappingId ? percentageVoorBackend(rij.percentage) : null
          if (!rij.mappingId || pct === null) return // blokkade staat al onder de tabel
          regels.push({
            bron_regel_id: bronId,
            mapping_id: rij.mappingId,
            percentage: pct,
            doel_kosten_ledger_id: rij.gbId,
            project_ids: rij.projectIds,
            verdeelbasis: rij.projectIds.length > 1 ? rij.verdeelbasis : null,
          })
        }
      }
      const vers = await slaDoorbelastingVerdelingOp(administratieId, run.id, regels)
      onRunGewijzigd(vers)
    } catch (err) {
      setOpslaanFout(err instanceof ApiError ? err.message : 'Verdeling opslaan mislukt.')
    } finally {
      setOpslaanBezig(false)
    }
  }

  // Automatisch opslaan: kort ná de laatste wijziging, uitsluitend als de verdeling compleet is.
  const opslaanRef = useRef(opslaan)
  opslaanRef.current = opslaan
  useEffect(() => {
    if (bevroren || !gewijzigd || blokkade !== null || opslaanBezig) return
    const timer = window.setTimeout(() => void opslaanRef.current(), AUTO_OPSLAAN_MS)
    return () => window.clearTimeout(timer)
  }, [verdeling, gewijzigd, blokkade, bevroren, opslaanBezig])

  const heeftVerdeling = Object.values(verdeling).some((rijen) => rijen.length > 0)
  const previewZichtbaar = run.previews.length > 0 && !gewijzigd

  return (
    <>
      <div className={compact ? undefined : 'panel'}>
        {!compact && <h2>Verdeling per regel</h2>}
        {run.verdeelsleutel && (
          <p className="hint" style={{ marginTop: 0 }}>
            Verdeelsleutel <b>{run.verdeelsleutel.naam}</b> v{run.verdeelsleutel.versie} toegepast
            {run.verdeelsleutel.toegepast_op ? ` op ${new Date(run.verdeelsleutel.toegepast_op).toLocaleString('nl-NL')}` : ''}.
          </p>
        )}
        {bronRegels.length === 0 && !regelIdsOntbreken && (
          <p className="hint">Geen boekingsregels gevonden bij dit document.</p>
        )}
        {bronRegels.map((bron) => {
          const rijen = verdeling[bron.id] ?? []
          const nettoGetal = bron.netto === null ? null : Number(bron.netto)
          return (
            <div key={bron.id} style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 12.5, marginBottom: 4 }}>
                <b>{bron.omschrijving}</b>
              </div>
              <RestantBalk netto={bron.netto} rijen={rijen} />
              {rijen.length > 0 && (
                <div className="tabel-scroll">
                  <table className="lines vd-tabel">
                    <colgroup>
                      <col style={{ width: '34%' }} />
                      <col style={{ width: 82 }} />
                      <col style={{ width: 120 }} />
                      <col />
                      <col style={{ width: 30 }} />
                    </colgroup>
                    <tbody>
                      <tr>
                        <th>Doelentiteit</th>
                        <th>%</th>
                        <th className="amount">Bedrag excl.</th>
                        <th>Project in doel</th>
                        <th />
                      </tr>
                      {rijen.map((rij) => {
                        const mapping = rij.mappingId ? (mappingPerId.get(rij.mappingId) ?? null) : null
                        const doelId = mapping?.doel_administratie_id ?? null
                        const schema = doelId ? doelGrootboek[doelId] : undefined
                        const projectInfo = rij.mappingId ? doelProjecten[rij.mappingId] : undefined
                        const projectOpties = (projectInfo?.projecten ?? []).map((p) => ({
                          waarde: p.id,
                          label: p.naam,
                          sub: `${p.is_actief ? '' : 'inactief · '}${formatM2(p.contract_m2)}`,
                        }))
                        const zonderM2 = (projectInfo?.projecten ?? []).filter(
                          (p) => rij.projectIds.includes(p.id) && p.contract_m2 === null,
                        )
                        const pctParse = parsePercentage(rij.percentage)
                        const bedragWeergave =
                          rij.bedragInvoer !== null
                            ? rij.bedragInvoer
                            : rij.nettoDeel !== null && !gewijzigd
                              ? formatEuroString(rij.nettoDeel)
                              : nettoGetal !== null && Number.isFinite(nettoGetal) && pctParse.waarde !== null
                                ? formatEuroString(String(percentageNaarBedrag(nettoGetal, pctParse.waarde)))
                                : ''
                        const gbLabel = schema?.opties.find((o) => o.id === rij.gbId)?.label ?? rij.gbId ?? null
                        const projectenLeeg =
                          projectInfo !== undefined && !projectInfo.laden && !projectInfo.fout && projectInfo.projecten.length === 0
                        const sync = rij.mappingId ? syncStand[rij.mappingId] : undefined
                        return (
                          <tr key={rij.key}>
                            <td>
                              {bevroren ? (
                                (mapping?.doelentiteit_naam ?? '—')
                              ) : (
                                <Select
                                  aria-label={`Doelentiteit voor ${bron.omschrijving}`}
                                  value={rij.mappingId ?? ''}
                                  onChange={(e) => {
                                    // Entiteit gewisseld: de GB-keuze hoort bij het oude
                                    // rekeningschema en gaat mee weg; voorstel uit de
                                    // whitelist-rij (laatste kosten-GB) komt vooringevuld.
                                    const nieuweMapping = e.target.value ? mappingPerId.get(e.target.value) : undefined
                                    wijzig(bron.id, rij.key, {
                                      mappingId: e.target.value || null,
                                      gbId: nieuweMapping?.laatste_kosten_ledger_id ?? null,
                                      gbOpen: false,
                                      projectIds: [],
                                      verdeelbasis: null,
                                      alleActief: false,
                                      projectDelen: [],
                                    })
                                  }}
                                >
                                  <option value="">— doelentiteit kiezen —</option>
                                  {actieveMappings.map((m) => (
                                    <option key={m.id} value={m.id}>
                                      {m.doelentiteit_naam}
                                    </option>
                                  ))}
                                </Select>
                              )}
                              {/* GB in doeladministratie: uitklap per rij (mockup ⑤) — vooringevuld
                                  uit de whitelist-rij; alleen de combobox tonen bij ontbreken of uitklap. */}
                              {mapping !== null && doelId === null && (
                                <div className="vd-sub">GB volgt bij de spiegel-taak (doel niet onboarded)</div>
                              )}
                              {mapping !== null && doelId !== null && schema?.fout && (
                                <div className="vd-sub" style={{ color: 'var(--orange)' }}>
                                  {schema.fout}
                                </div>
                              )}
                              {mapping !== null && doelId !== null && !schema?.fout && (bevroren || (rij.gbId && !rij.gbOpen)) && (
                                <div className="vd-sub">
                                  GB {gbLabel ?? '—'}
                                  {!bevroren && (
                                    <button type="button" className="linkbtn" onClick={() => wijzigWeergave(bron.id, rij.key, { gbOpen: true })}>
                                      wijzigen
                                    </button>
                                  )}
                                </div>
                              )}
                              {mapping !== null && doelId !== null && !schema?.fout && !bevroren && (!rij.gbId || rij.gbOpen) && (
                                <div className="vd-sub" style={{ display: 'block' }}>
                                  <SearchableCombobox
                                    label={`Kosten-GB in ${mapping.doelentiteit_naam}`}
                                    toonLabel={false}
                                    opties={schema?.opties ?? []}
                                    waarde={rij.gbId}
                                    onWijzig={(id) => wijzig(bron.id, rij.key, { gbId: id, gbOpen: false })}
                                    placeholder="GB in doel: typ nummer of naam…"
                                    vereist
                                  />
                                </div>
                              )}
                            </td>
                            <td>
                              {bevroren ? (
                                `${rij.percentage}%`
                              ) : (
                                <>
                                  <input
                                    aria-label={`Percentage voor ${bron.omschrijving}`}
                                    inputMode="decimal"
                                    placeholder="%"
                                    aria-invalid={pctParse.fout !== null || undefined}
                                    style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}
                                    value={rij.percentage}
                                    onChange={(e) => wijzig(bron.id, rij.key, { percentage: e.target.value, bedragInvoer: null })}
                                  />
                                  {pctParse.fout && (
                                    <div className="fout" style={{ fontSize: 11.5, marginTop: 4 }}>
                                      {pctParse.fout}
                                    </div>
                                  )}
                                </>
                              )}
                            </td>
                            <td className="amount">
                              {bevroren ? (
                                rij.nettoDeel !== null ? `€ ${formatEuroString(rij.nettoDeel)}` : '—'
                              ) : (
                                <input
                                  aria-label={`Bedrag voor ${bron.omschrijving}`}
                                  inputMode="decimal"
                                  placeholder="€"
                                  disabled={nettoGetal === null || !Number.isFinite(nettoGetal) || nettoGetal === 0}
                                  title={
                                    rij.nettoDeel !== null && !gewijzigd
                                      ? 'Server-berekend deel (grootste-rest)'
                                      : 'Indicatief — de server rondt de centen bindend bij opslaan'
                                  }
                                  style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}
                                  value={bedragWeergave}
                                  onChange={(e) => {
                                    const pct = nettoGetal !== null ? bedragNaarPercentage(nettoGetal, e.target.value) : null
                                    wijzig(bron.id, rij.key, {
                                      bedragInvoer: e.target.value,
                                      percentage: pct === null ? rij.percentage : formatPct(pct),
                                    })
                                  }}
                                />
                              )}
                            </td>
                            <td>
                              {mapping === null ? (
                                <span className="hint" style={{ margin: 0 }}>
                                  —
                                </span>
                              ) : doelId === null ? (
                                <span className="hint" style={{ margin: 0 }}>
                                  niet onboarded — geen projecten
                                </span>
                              ) : projectInfo?.fout ? (
                                <span className="hint" style={{ margin: 0, color: 'var(--orange)' }}>
                                  {projectInfo.fout}
                                </span>
                              ) : projectInfo?.laden || sync === 'bezig' ? (
                                <span className="hint" style={{ margin: 0 }}>
                                  {sync === 'bezig' ? 'Projecten synchroniseren…' : 'Projecten laden…'}
                                </span>
                              ) : projectenLeeg ? (
                                <div className="vd-leeg" data-testid="projecten-leeg">
                                  <span>nog geen projecten gesynchroniseerd</span>
                                  {!bevroren && (
                                    <button type="button" className="knopje" onClick={() => void synchroniseerProjecten(rij.mappingId!, doelId)}>
                                      Nu synchroniseren
                                    </button>
                                  )}
                                  {sync && sync !== 'bezig' && <span className="fout" style={{ fontSize: 11.5 }}>{sync}</span>}
                                </div>
                              ) : bevroren || (rij.projectDelen.length > 0 && !gewijzigd) ? (
                                <div>
                                  {rij.projectDelen.length === 0 ? (
                                    <span className="hint" style={{ margin: 0 }}>
                                      geen project
                                    </span>
                                  ) : (
                                    rij.projectDelen.map((pd) => (
                                      <div key={pd.projectId} style={{ fontSize: 12 }}>
                                        {pd.naam ?? pd.projectId} · € {formatEuroString(pd.nettoDeel)}
                                        {rij.verdeelbasis === 'm2' && pd.m2 !== null && (
                                          <span style={{ color: 'var(--muted)' }}> ({formatM2(pd.m2)})</span>
                                        )}
                                      </div>
                                    ))
                                  )}
                                  {rij.projectDelen.length > 1 && (
                                    <span className="chip geheugen" style={{ marginTop: 4 }}>
                                      {rij.verdeelbasis === 'm2' ? 'naar rato m²' : 'gelijk per object'}
                                    </span>
                                  )}
                                  {!bevroren && (
                                    <button
                                      type="button"
                                      className="linkbtn"
                                      style={{ marginTop: 4, fontSize: 11.5 }}
                                      onClick={() => wijzig(bron.id, rij.key, { projectDelen: [] })}
                                    >
                                      projecten wijzigen
                                    </button>
                                  )}
                                </div>
                              ) : (
                                <div>
                                  <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginBottom: 4 }}>
                                    {projectInfo?.projectVerplicht && (
                                      <span className="chip blokkerend" title="De doel-administratie heeft projectplicht: elke verdeelregel moet een project dragen">
                                        project verplicht
                                      </span>
                                    )}
                                    <button
                                      type="button"
                                      className="btn secondary"
                                      style={{ padding: '2px 8px', fontSize: 11.5 }}
                                      title="Alle actieve projecten van de doel-administratie selecteren (blijft dynamisch in een verdeelsleutel)"
                                      onClick={() =>
                                        wijzig(bron.id, rij.key, {
                                          projectIds: (projectInfo?.projecten ?? []).filter((p) => p.is_actief).map((p) => p.id),
                                          alleActief: true,
                                          verdeelbasis: rij.verdeelbasis ?? 'm2',
                                        })
                                      }
                                    >
                                      alle actieve projecten
                                    </button>
                                    {rij.projectIds.length > 0 && (
                                      <span style={{ fontSize: 11.5, color: 'var(--muted)' }}>
                                        {rij.projectIds.length} gekozen
                                      </span>
                                    )}
                                  </div>
                                  <MultiSelect
                                    opties={projectOpties}
                                    waarden={rij.projectIds}
                                    onChange={(ids) =>
                                      wijzig(bron.id, rij.key, {
                                        projectIds: ids,
                                        alleActief: false,
                                        verdeelbasis: ids.length > 1 ? (rij.verdeelbasis ?? 'm2') : null,
                                      })
                                    }
                                    zoekPlaceholder={`Zoek project in ${mapping.doelentiteit_naam}…`}
                                  />
                                  {rij.projectIds.length > 1 && (
                                    <div role="radiogroup" aria-label={`Verdeelbasis voor ${mapping.doelentiteit_naam}`} style={{ display: 'flex', gap: 10, marginTop: 4, fontSize: 12 }}>
                                      <label style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                                        <input
                                          type="radio"
                                          name={`basis-${rij.key}`}
                                          checked={rij.verdeelbasis === 'm2'}
                                          onChange={() => wijzig(bron.id, rij.key, { verdeelbasis: 'm2' })}
                                        />
                                        naar rato m²
                                      </label>
                                      <label style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                                        <input
                                          type="radio"
                                          name={`basis-${rij.key}`}
                                          checked={rij.verdeelbasis === 'gelijk'}
                                          onChange={() => wijzig(bron.id, rij.key, { verdeelbasis: 'gelijk' })}
                                        />
                                        gelijk per object
                                      </label>
                                    </div>
                                  )}
                                  {rij.verdeelbasis === 'm2' && rij.projectIds.length > 1 && zonderM2.length > 0 && (
                                    <span className="chip blokkerend" style={{ marginTop: 4 }} title="Ontbrekende contract-m² — vul de projectspecificatie aan of kies 'gelijk per object'; er wordt nooit gegokt">
                                      geen m² bekend: {zonderM2.map((p) => p.naam).join(', ')}
                                    </span>
                                  )}
                                </div>
                              )}
                            </td>
                            <td style={{ padding: '8px 4px' }}>
                              {!bevroren && (
                                <button
                                  type="button"
                                  className="icon-btn"
                                  aria-label={`Verdeelregel verwijderen (${bron.omschrijving})`}
                                  onClick={() => verwijderRij(bron.id, rij.key)}
                                >
                                  ✕
                                </button>
                              )}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}
              {!bevroren && (
                <button type="button" className="linkbtn" style={{ marginTop: 6, fontWeight: 600 }} onClick={() => voegRijToe(bron.id)}>
                  + Doelentiteit
                </button>
              )}
            </div>
          )
        })}

        {!bevroren && bronRegels.length > 0 && (
          <div className="vd-voet">
            <button
              ref={sleutelKnop}
              type="button"
              className="btn secondary"
              aria-label="Verdeelsleutel"
              aria-haspopup="menu"
              aria-expanded={sleutelMenuOpen}
              disabled={sleutelBezig}
              onClick={() => setSleutelMenuOpen((o) => !o)}
            >
              Verdeelsleutel ▾
            </button>
            <AnkerPopup
              open={sleutelMenuOpen}
              anker={sleutelKnop}
              kant="onder"
              uitlijning="start"
              className="rijmenu"
              role="menu"
              onAnkerUitBeeld={() => setSleutelMenuOpen(false)}
            >
              {sleutels.length === 0 && (
                <span className="hint" style={{ display: 'block', padding: '6px 8px', margin: 0 }}>
                  Nog geen verdeelsleutels voor deze administratie.
                </span>
              )}
              {sleutels.map((s) => (
                <button key={s.id} type="button" className="linkbtn" role="menuitem" onClick={() => void sleutelToepassen(s.id)}>
                  Toepassen: {s.naam} (v{s.versie})
                </button>
              ))}
              <button
                type="button"
                className="linkbtn"
                role="menuitem"
                disabled={!heeftVerdeling}
                title={heeftVerdeling ? 'Bewaart doelen + projecten + verdeelbasis van de huidige verdeling als herbruikbare sleutel' : 'Maak eerst een verdeling'}
                onClick={() => {
                  setSleutelMenuOpen(false)
                  setSleutelOpslaanOpen(true)
                }}
              >
                Opslaan als sleutel…
              </button>
            </AnkerPopup>
            {sleutelOpslaanOpen && (
              <>
                <input
                  aria-label="Naam nieuwe verdeelsleutel"
                  placeholder="Naam van de sleutel…"
                  value={sleutelNaam}
                  onChange={(e) => setSleutelNaam(e.target.value)}
                  style={{ maxWidth: 220 }}
                />
                <button type="button" className="btn secondary" disabled={!sleutelNaam.trim() || sleutelBezig} onClick={() => void sleutelOpslaan()}>
                  Opslaan als sleutel
                </button>
                <button type="button" className="linkbtn" onClick={() => setSleutelOpslaanOpen(false)}>
                  annuleren
                </button>
              </>
            )}
            <span className="vd-status" role="status">
              {opslaanBezig
                ? 'Verdeling opslaan…'
                : opslaanFout
                  ? null
                  : gewijzigd
                    ? blokkade
                      ? null
                      : 'Wordt opgeslagen…'
                    : heeftVerdeling
                      ? 'Verdeling opgeslagen ✓'
                      : null}
            </span>
          </div>
        )}
        {sleutelMelding && (
          <p className="hint" style={{ marginBottom: 0 }}>
            {sleutelMelding}
          </p>
        )}
        {opslaanFout && <div className="fout">{opslaanFout}</div>}
        {!bevroren && blokkade && (
          <p className="vd-blokkade" data-testid="verdeling-blokkade">
            {heeftVerdeling || regelIdsOntbreken
              ? `Nog niet compleet: ${blokkade}`
              : blokkade}
          </p>
        )}
        {!bevroren && !blokkade && !heeftVerdeling && bronRegels.length > 0 && (
          <p className="vd-blokkade">
            De boekknop wordt actief zodra de verdeling exact 100% is en elke rij een doelentiteit (en waar verplicht een
            project) heeft.
          </p>
        )}
      </div>

      {previewZichtbaar && (
        <div className={compact ? undefined : 'panel'} style={compact ? { marginTop: 10 } : undefined}>
          <h2 style={compact ? { fontSize: 12.5 } : undefined}>Per doelentiteit</h2>
          <div className="tabel-scroll">
            <table className="lines">
              <tbody>
                <tr>
                  <th>Doelentiteit</th>
                  <th>Onboarded</th>
                  <th className="amount">Doorbelast (excl.)</th>
                  <th className="amount">Provisie</th>
                  <th className="amount">Btw</th>
                  <th>Status</th>
                </tr>
                {run.previews.map((p) => {
                  const chip = p.boeking_status ? boekingStatusChip(p.boeking_status) : null
                  return (
                    <tr key={p.mapping_id}>
                      <td>
                        <b>{p.doelentiteit_naam}</b>
                      </td>
                      <td>
                        {p.onboarded ? (
                          <span className="chip ok">onboarded</span>
                        ) : (
                          <span
                            className="chip vraag"
                            title="Geen eigen administratie in het platform — de bron-kant boekt gewoon; de spiegel wordt een zichtbare open taak"
                          >
                            niet onboarded — spiegel wordt open taak
                          </span>
                        )}
                      </td>
                      <td className="amount">
                        € {formatEuroString(p.netto_totaal)}
                        {(p.projecten ?? []).length > 0 && (
                          <div style={{ fontSize: 11.5, color: 'var(--muted)', fontWeight: 400, textAlign: 'right' }}>
                            {(p.projecten ?? []).map((pp) => (
                              <div key={pp.project_id}>
                                {pp.naam}: € {formatEuroString(pp.netto_totaal)}
                              </div>
                            ))}
                          </div>
                        )}
                      </td>
                      <td className="amount">€ {formatEuroString(p.provisie_bedrag)}</td>
                      <td className="amount">€ {formatEuroString(p.btw_bedrag)}</td>
                      <td>{chip ? <span className={`chip ${chip.klasse}`}>{chip.label}</span> : '—'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          {!compact && (
            <p className="hint" style={{ marginBottom: 0 }}>
              De provisie (vast percentage uit Instellingen → Doorbelasting) boekt als losse regel op de
              verkoopfactuur; de btw is het vlakke doorbelastings-tarief uit dezelfde instellingen. In de
              doel-administratie boekt de provisie altijd apart, op de vaste provisie-GB van de mapping.
            </p>
          )}
        </div>
      )}

      {!compact && (
        <div className="panel">
          <h2>
            Harde checks{' '}
            {gewijzigd ? (
              <span className="chip vraag">verouderd — wordt opgeslagen</span>
            ) : (
              <span className={`chip ${run.checks.geblokkeerd ? 'blokkerend' : 'ok'}`}>
                {run.checks.geblokkeerd ? 'blokkerend' : 'alle checks groen'}
              </span>
            )}
          </h2>
          <table className="lines">
            <tbody>
              {run.checks.resultaten.map((r) => (
                <tr key={r.naam} style={gewijzigd ? { opacity: 0.55 } : undefined}>
                  <td>
                    <span className={`chip ${r.ok ? 'ok' : 'blokkerend'}`}>{r.ok ? 'OK' : 'Blokkerend'}</span>
                  </td>
                  <td>
                    <b>{r.naam}</b>
                  </td>
                  <td>{r.melding}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
