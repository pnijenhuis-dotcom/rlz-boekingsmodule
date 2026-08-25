import { useEffect, useMemo, useState } from 'react'
import { ApiError } from '../api/client'
import type {
  DoorbelastingMappingDto,
  DoorbelastingRunDto,
  DoorbelastingVerdeelRegelInputDto,
  VerdeelsleutelDoelInputDto,
  VerdeelsleutelDto,
} from '../api/types'
import { bedragAlsGetal, normaliseerBedrag } from '../document/bedrag'
import { SearchableCombobox } from '../document/SearchableCombobox'
import { MultiSelect, Select } from '../ui/basis'
import { haalVerdeelsleutelsOp, pasVerdeelsleutelToe, slaDoorbelastingVerdelingOp, slaVerdeelsleutelOp } from './doorbelastingApi'
import { boekingStatusChip, formatEuroString, formatPercentage } from './status'
import { useDoelGrootboek } from './useDoelGrootboek'
import { useDoelProjecten } from './useDoelProjecten'

/** Eén bron-regel van het document (uit het bestaande boekvoorstel-endpoint). */
export interface BronRegel {
  id: string
  omschrijving: string
  netto: string | null
}

/** Eén verdeelregel in bewerking (mockup #verdeelmodal): doelentiteit + % + doel-kosten-GB.
 * `nettoDeel` is uitsluitend het server-berekende deel uit de laatste opslag — de client
 * rekent nooit bindend (grootste-rest leeft in de backend). */
interface VerdeelRij {
  key: string
  mappingId: string | null
  percentage: string
  gbId: string | null
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
        gbId: regel.doel_kosten_ledger_id,
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
    gbId: null,
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

/** Percentagesom van de rijen van één bron-regel — afgerond op 2 decimalen tegen
 * floating-point-ruis (33,33+33,33+33,34). Puur weergave/poortwachter; de harde check leeft
 * server-side. */
function somPercentages(rijen: VerdeelRij[]): number {
  const som = rijen.reduce((acc, rij) => acc + (bedragAlsGetal(rij.percentage) ?? 0), 0)
  return Math.round(som * 100) / 100
}

/** Percentage-getal voor weergave: 2 decimalen tegen floating-point-ruis, NL-komma. */
function formatPct(x: number): string {
  return String(Math.round(x * 100) / 100).replace('.', ',')
}

/** Server-staat van de run: sluit elke verdeelde bron-regel exact op 100%? Synchroon
 * afleidbaar uit de run (zonder editor-effect), zodat een boekknop nooit één render lang
 * ten onrechte actief staat vóór de editor zijn werkstaat gemeld heeft. */
export function runVerdelingOnvolledig(run: DoorbelastingRunDto): boolean {
  return Object.values(verdelingUitRun(run)).some((rijen) => rijen.length > 0 && somPercentages(rijen) !== 100)
}

/** Werkstaat-signalen voor de aanroeper (boekknop-poort): onopgeslagen wijzigingen of een
 * verdeelde regel die niet op 100% sluit = niet groen. */
export interface VerdelingStaat {
  gewijzigd: boolean
  onvolledig: boolean
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
   * checks-paneel (de boekknop toont de gecombineerde poort), wél preview + opslaan. */
  compact?: boolean
}

/** Herbruikbare verdeel-UI (mockup #verdeelmodal, 1-op-1 uit het reviewscherm gelicht voor
 * besluit Peter 25-08 "doorbelasting in de boekflow"): per bron-regel een percentage-verdeling
 * over de whitelist-doelentiteiten, server-berekende netto-delen na "Verdeling opslaan",
 * provisie-preview per doelentiteit en (niet-compact) de harde checks. Zelfde component in het
 * reviewscherm (na boeken) én in het blok "Doorbelasten na boeken" (vóór boeken). */
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
  // boeken kan pas weer ná een verse "Verdeling opslaan" (server berekent bindend).
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
  const doelGrootboek = useDoelGrootboek(
    useMemo(
      () =>
        Object.values(verdeling)
          .flat()
          .map((rij) => (rij.mappingId ? (mappingPerId.get(rij.mappingId)?.doel_administratie_id ?? null) : null)),
      [verdeling, mappingPerId],
    ),
  )

  const doelProjecten = useDoelProjecten(
    administratieId,
    useMemo(() => Object.values(verdeling).flat().map((rij) => rij.mappingId), [verdeling]),
  )

  // Verdeelsleutels (25-08, punt 2c): herbruikbare verdeling per bron-administratie — één klik
  // toepassen, daarna nog aanpasbaar; opslaan als sleutel vanuit de huidige verdeling.
  const [sleutels, setSleutels] = useState<VerdeelsleutelDto[]>([])
  const [gekozenSleutel, setGekozenSleutel] = useState('')
  const [sleutelNaam, setSleutelNaam] = useState('')
  const [sleutelBezig, setSleutelBezig] = useState(false)
  const [sleutelMelding, setSleutelMelding] = useState<string | null>(null)
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

  const sleutelToepassen = async () => {
    if (!gekozenSleutel) return
    setSleutelBezig(true)
    setSleutelMelding(null)
    try {
      const vers = await pasVerdeelsleutelToe(administratieId, run.id, gekozenSleutel)
      onRunGewijzigd(vers)
      setSleutelMelding('Verdeelsleutel toegepast — controleer en pas zo nodig aan vóór opslaan.')
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
      if (!rij.mappingId) return null
      doelen.push({
        mapping_id: rij.mappingId,
        percentage: normaliseerBedrag(rij.percentage),
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
      setSleutelMelding('Maak eerst een volledige verdeling (doelentiteit per regel) om als sleutel op te slaan.')
      return
    }
    setSleutelBezig(true)
    setSleutelMelding(null)
    try {
      const nieuw = await slaVerdeelsleutelOp(administratieId, { naam: sleutelNaam.trim(), doelen })
      setSleutels((huidig) => [...huidig.filter((s) => s.naam !== nieuw.naam), nieuw].sort((a, b) => a.naam.localeCompare(b.naam)))
      setGekozenSleutel(nieuw.id)
      setSleutelNaam('')
      setSleutelMelding(`Verdeelsleutel "${nieuw.naam}" opgeslagen als versie ${nieuw.versie}.`)
    } catch (err) {
      setSleutelMelding(err instanceof ApiError ? err.message : 'Verdeelsleutel opslaan mislukt.')
    } finally {
      setSleutelBezig(false)
    }
  }

  // Kliktest-bevinding Peter 2026-08-16: opslaan/boeken pas aanbieden als elke verdeelde
  // regel exact op 100% sluit — de teller per regel laat live zien wat er nog open staat.
  // Een regel zónder verdeelrijen blijft gewoon "niet doorbelast" (geen blokkade).
  const verdelingOnvolledig = Object.values(verdeling).some(
    (rijen) => rijen.length > 0 && somPercentages(rijen) !== 100,
  )
  useEffect(() => {
    onStaat?.({ gewijzigd, onvolledig: verdelingOnvolledig })
  }, [gewijzigd, verdelingOnvolledig, onStaat])

  const wijzig = (bronId: string, key: string, wijziging: Partial<VerdeelRij>) => {
    setVerdeling((huidig) => ({
      ...huidig,
      [bronId]: (huidig[bronId] ?? []).map((rij) => (rij.key === key ? { ...rij, ...wijziging, nettoDeel: null } : rij)),
    }))
    setGewijzigd(true)
  }

  const voegRijToe = (bronId: string) => {
    setVerdeling((huidig) => {
      const rijen = huidig[bronId] ?? []
      const rest = Math.max(0, 100 - somPercentages(rijen))
      return { ...huidig, [bronId]: [...rijen, nieuweRij(String(rest).replace('.', ','))] }
    })
    setGewijzigd(true)
  }

  const verwijderRij = (bronId: string, key: string) => {
    setVerdeling((huidig) => ({ ...huidig, [bronId]: (huidig[bronId] ?? []).filter((rij) => rij.key !== key) }))
    setGewijzigd(true)
  }

  const rijenZonderEntiteit = Object.values(verdeling)
    .flat()
    .filter((rij) => rij.mappingId === null).length

  const opslaan = async () => {
    setOpslaanBezig(true)
    setOpslaanFout(null)
    try {
      const regels: DoorbelastingVerdeelRegelInputDto[] = []
      for (const [bronId, rijen] of Object.entries(verdeling)) {
        for (const rij of rijen) {
          if (!rij.mappingId) {
            setOpslaanFout('Kies voor elke verdeelregel een doelentiteit — of verwijder de regel.')
            return
          }
          const pct = bedragAlsGetal(rij.percentage)
          if (pct === null || pct <= 0 || pct > 100) {
            setOpslaanFout('Elk percentage moet groter dan 0 en hoogstens 100 zijn.')
            return
          }
          if (rij.projectIds.length > 1 && rij.verdeelbasis === null) {
            setOpslaanFout('Kies bij meerdere projecten een verdeelbasis: naar rato m² of gelijk per object.')
            return
          }
          const info = rij.mappingId ? doelProjecten[rij.mappingId] : undefined
          if (info?.projectVerplicht && rij.projectIds.length === 0) {
            setOpslaanFout(
              `Project verplicht in ${mappingPerId.get(rij.mappingId)?.doelentiteit_naam ?? 'de doel-administratie'} — kies minimaal één project.`,
            )
            return
          }
          regels.push({
            bron_regel_id: bronId,
            mapping_id: rij.mappingId,
            percentage: normaliseerBedrag(rij.percentage),
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
        {!bevroren && bronRegels.length > 0 && (
          <div className="verdeelsleutel-balk" style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 12 }}>
            <Select
              aria-label="Verdeelsleutel"
              value={gekozenSleutel}
              onChange={(e) => setGekozenSleutel(e.target.value)}
              style={{ maxWidth: 260 }}
            >
              <option value="">— verdeelsleutel kiezen —</option>
              {sleutels.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.naam} (v{s.versie})
                </option>
              ))}
            </Select>
            <button type="button" className="btn secondary" disabled={!gekozenSleutel || sleutelBezig} onClick={() => void sleutelToepassen()}>
              Sleutel toepassen
            </button>
            <input
              aria-label="Naam nieuwe verdeelsleutel"
              placeholder="Opslaan als sleutel… (naam)"
              value={sleutelNaam}
              onChange={(e) => setSleutelNaam(e.target.value)}
              style={{ maxWidth: 220 }}
            />
            <button
              type="button"
              className="btn secondary"
              disabled={!sleutelNaam.trim() || sleutelBezig}
              title="Bewaart doelen + projecten + verdeelbasis van de huidige verdeling als herbruikbare sleutel (nieuwe versie bij een bestaande naam)"
              onClick={() => void sleutelOpslaan()}
            >
              Opslaan als sleutel
            </button>
            {sleutelMelding && <span style={{ fontSize: 12, color: 'var(--muted)' }}>{sleutelMelding}</span>}
          </div>
        )}
        {bronRegels.length === 0 && !regelIdsOntbreken && (
          <p className="hint">Geen boekingsregels gevonden bij dit document.</p>
        )}
        {bronRegels.map((bron) => {
          const rijen = verdeling[bron.id] ?? []
          const som = somPercentages(rijen)
          return (
            <div key={bron.id} style={{ marginBottom: 18 }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap', marginBottom: 6 }}>
                <b>{bron.omschrijving}</b>
                {bron.netto !== null && (
                  <span style={{ color: 'var(--muted)', fontSize: 13 }}>€ {formatEuroString(bron.netto)} excl.</span>
                )}
                {rijen.length === 0 ? (
                  <span className="chip geheugen">niet doorbelast</span>
                ) : som === 100 ? (
                  <span className="chip ok">100% ✓</span>
                ) : som < 100 ? (
                  <span className="chip afwijking">
                    {formatPct(som)}% — nog {formatPct(100 - som)}% te verdelen
                  </span>
                ) : (
                  <span className="chip afwijking">
                    {formatPct(som)}% — {formatPct(som - 100)}% te veel
                  </span>
                )}
              </div>
              {rijen.length > 0 && (
                <div className="tabel-scroll">
                  <table className="lines">
                    <colgroup>
                      <col style={{ width: '22%' }} />
                      <col style={{ width: 70 }} />
                      <col style={{ width: 110 }} />
                      <col style={{ width: '28%' }} />
                      <col />
                      <col style={{ width: 30 }} />
                    </colgroup>
                    <tbody>
                      <tr>
                        <th>Doelentiteit</th>
                        <th>%</th>
                        <th className="amount">Bedrag excl.</th>
                        <th>Project(en) in doel</th>
                        <th>GB in doeladministratie</th>
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
                                    // rekeningschema en gaat bewust mee weg.
                                    wijzig(bron.id, rij.key, {
                                      mappingId: e.target.value || null,
                                      gbId: null,
                                      projectIds: [],
                                      verdeelbasis: null,
                                      alleActief: false,
                                      projectDelen: [],
                                    })
                                  }}
                                >
                                  <option value="">— kies doelentiteit —</option>
                                  {actieveMappings.map((m) => (
                                    <option key={m.id} value={m.id}>
                                      {m.doelentiteit_naam}
                                    </option>
                                  ))}
                                </Select>
                              )}
                            </td>
                            <td>
                              {bevroren ? (
                                `${rij.percentage}%`
                              ) : (
                                <input
                                  aria-label={`Percentage voor ${bron.omschrijving}`}
                                  inputMode="decimal"
                                  style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}
                                  value={rij.percentage}
                                  onChange={(e) => wijzig(bron.id, rij.key, { percentage: e.target.value })}
                                />
                              )}
                            </td>
                            <td className="amount">
                              {rij.nettoDeel !== null && !gewijzigd ? (
                                `€ ${formatEuroString(rij.nettoDeel)}`
                              ) : (
                                <span
                                  className="hint"
                                  style={{ margin: 0, display: 'inline' }}
                                  title="De server berekent de centen bindend (grootste-rest) bij Verdeling opslaan"
                                >
                                  na opslaan
                                </span>
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
                              ) : bevroren || rij.projectDelen.length > 0 && !gewijzigd ? (
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
                                      className="btn secondary"
                                      style={{ marginTop: 4, padding: '2px 8px', fontSize: 11.5 }}
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
                                    leegTekst={projectInfo?.laden ? 'Projecten laden…' : 'Geen projecten in de cache van deze administratie.'}
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
                            <td>
                              {mapping === null ? (
                                <span className="hint" style={{ margin: 0 }}>
                                  kies eerst een doelentiteit
                                </span>
                              ) : doelId === null ? (
                                <span className="hint" style={{ margin: 0 }}>
                                  nog niet onboarded — GB-keuze volgt bij de spiegel-taak
                                </span>
                              ) : schema?.fout ? (
                                <span className="hint" style={{ margin: 0, color: 'var(--orange)' }}>
                                  {schema.fout}
                                </span>
                              ) : bevroren ? (
                                (schema?.opties.find((o) => o.id === rij.gbId)?.label ?? rij.gbId ?? '—')
                              ) : (
                                <SearchableCombobox
                                  label={`Kosten-GB in ${mapping.doelentiteit_naam}`}
                                  toonLabel={false}
                                  opties={schema?.opties ?? []}
                                  waarde={rij.gbId}
                                  onWijzig={(id) => wijzig(bron.id, rij.key, { gbId: id })}
                                  placeholder="typ nummer of naam…"
                                  vereist
                                />
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
              )}
              {!bevroren && (
                <div style={{ marginTop: 6 }}>
                  <button type="button" className="btn secondary" onClick={() => voegRijToe(bron.id)}>
                    + Doelentiteit toevoegen
                  </button>
                </div>
              )}
            </div>
          )
        })}
        {!bevroren && (
          <>
            {opslaanFout && <div className="fout">{opslaanFout}</div>}
            <div className="actions">
              <button
                type="button"
                className="btn secondary"
                disabled={opslaanBezig || regelIdsOntbreken || verdelingOnvolledig}
                title={
                  verdelingOnvolledig
                    ? 'Elke verdeelde regel moet exact op 100% sluiten — zie de teller per regel'
                    : undefined
                }
                onClick={() => void opslaan()}
              >
                {opslaanBezig ? 'Bezig…' : 'Verdeling opslaan'}
              </button>
              {rijenZonderEntiteit > 0 && (
                <span className="chip afwijking">
                  {rijenZonderEntiteit} verdeelregel{rijenZonderEntiteit === 1 ? '' : 's'} zonder doelentiteit
                </span>
              )}
              {gewijzigd && !verdelingOnvolledig && (
                <span className="chip vraag" title="De server herberekent de delen en de checks bij opslaan">
                  nog niet opgeslagen
                </span>
              )}
            </div>
            {!compact && (
              <p className="hint" style={{ marginBottom: 0 }}>
                De server berekent de netto-delen bindend (grootste-rest-methode): de som van de delen is
                altijd exact het regelbedrag. Opslaan kan zodra elke verdeelde regel exact op 100% sluit
                (de teller per regel telt live mee); de harde check server-side blijft daarbovenop staan.
              </p>
            )}
          </>
        )}
      </div>

      <div className={compact ? undefined : 'panel'} style={compact ? { marginTop: 12 } : undefined}>
        <h2 style={compact ? { fontSize: 13.5 } : undefined}>Per doelentiteit (preview)</h2>
        {run.previews.length === 0 && <p className="hint">Nog geen verdeling opgeslagen.</p>}
        {run.previews.length > 0 && (
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
        )}
        {!compact && (
          <p className="hint" style={{ marginBottom: 0 }}>
            De provisie (vast percentage uit Instellingen → Doorbelasting) boekt als losse regel op de
            verkoopfactuur; de btw is het vlakke doorbelastings-tarief uit dezelfde instellingen. In de
            doel-administratie boekt de provisie altijd apart, op de vaste provisie-GB van de mapping.
          </p>
        )}
      </div>

      {!compact && (
        <div className="panel">
          <h2>
            Harde checks{' '}
            {gewijzigd ? (
              <span className="chip vraag">verouderd — sla de verdeling eerst op</span>
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
