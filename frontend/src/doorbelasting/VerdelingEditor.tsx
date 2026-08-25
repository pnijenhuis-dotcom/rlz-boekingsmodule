import { useEffect, useMemo, useState } from 'react'
import { ApiError } from '../api/client'
import type { DoorbelastingMappingDto, DoorbelastingRunDto, DoorbelastingVerdeelRegelInputDto } from '../api/types'
import { bedragAlsGetal, normaliseerBedrag } from '../document/bedrag'
import { SearchableCombobox } from '../document/SearchableCombobox'
import { Select } from '../ui/basis'
import { slaDoorbelastingVerdelingOp } from './doorbelastingApi'
import { boekingStatusChip, formatEuroString, formatPercentage } from './status'
import { useDoelGrootboek } from './useDoelGrootboek'

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
}

type Verdeling = Record<string, VerdeelRij[]>

function verdelingUitRun(run: DoorbelastingRunDto): Verdeling {
  const verdeling: Verdeling = {}
  for (const regel of run.regels) {
    const lijst = verdeling[regel.bron_regel_id] ?? (verdeling[regel.bron_regel_id] = [])
    lijst.push({
      key: regel.id,
      mappingId: regel.mapping_id,
      percentage: formatPercentage(regel.percentage),
      gbId: regel.doel_kosten_ledger_id,
      nettoDeel: regel.netto_deel,
    })
  }
  return verdeling
}

function nieuweRij(percentage: string): VerdeelRij {
  return { key: crypto.randomUUID(), mappingId: null, percentage, gbId: null, nettoDeel: null }
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
          regels.push({
            bron_regel_id: bronId,
            mapping_id: rij.mappingId,
            percentage: normaliseerBedrag(rij.percentage),
            doel_kosten_ledger_id: rij.gbId,
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
                      <col style={{ width: '30%' }} />
                      <col style={{ width: 80 }} />
                      <col style={{ width: 110 }} />
                      <col />
                      <col style={{ width: 30 }} />
                    </colgroup>
                    <tbody>
                      <tr>
                        <th>Doelentiteit</th>
                        <th>%</th>
                        <th className="amount">Bedrag excl.</th>
                        <th>GB in doeladministratie</th>
                        <th />
                      </tr>
                      {rijen.map((rij) => {
                        const mapping = rij.mappingId ? (mappingPerId.get(rij.mappingId) ?? null) : null
                        const doelId = mapping?.doel_administratie_id ?? null
                        const schema = doelId ? doelGrootboek[doelId] : undefined
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
                                    wijzig(bron.id, rij.key, { mappingId: e.target.value || null, gbId: null })
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
                      <td className="amount">€ {formatEuroString(p.netto_totaal)}</td>
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
