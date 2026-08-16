import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError, apiJson } from '../api/client'
import type {
  BoekvoorstelDto,
  CheckRapportDto,
  DocumentDetailDto,
  DoorbelastingMappingDto,
  DoorbelastingRunDto,
  DoorbelastingVerdeelRegelInputDto,
} from '../api/types'
import { bedragAlsGetal, normaliseerBedrag } from '../document/bedrag'
import { SearchableCombobox } from '../document/SearchableCombobox'
import { Select } from '../ui/basis'
import { ChecksPopup } from '../ui/ChecksPopup'
import { FoutMelding } from '../ui/FoutMelding'
import {
  boekDoorbelastingRun,
  haalDoorbelastingMappingsOp,
  haalDoorbelastingRunOp,
  slaDoorbelastingVerdelingOp,
  startDoorbelastingRun,
} from './doorbelastingApi'
import { boekingStatusChip, formatEuroString, formatPercentage } from './status'
import { useDoelGrootboek } from './useDoelGrootboek'

/** Eén bron-regel van het geboekte document (uit het bestaande boekvoorstel-endpoint). */
interface BronRegel {
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

/** Reviewscherm Kempen-doorbelasting (blok 3, route /doorbelasting/:administratieId/:documentId):
 * per bron-regel een percentage-verdeling over de whitelist-doelentiteiten (verdeelmodal-
 * mechanica uit de mockup, 1-op-1 leidend), server-berekende netto-delen na "Verdeling
 * opslaan", provisie-preview + harde checks per doelentiteit, en de boekactie met zichtbaar
 * per-doelentiteit-resultaat (ook gedeeltelijke fouten). */
export function DoorbelastingReviewScreen() {
  const { administratieId, documentId } = useParams<{ administratieId: string; documentId: string }>()

  const [detail, setDetail] = useState<DocumentDetailDto | null>(null)
  const [bronRegels, setBronRegels] = useState<BronRegel[] | null>(null)
  const [regelIdsOntbreken, setRegelIdsOntbreken] = useState(false)
  const [run, setRun] = useState<DoorbelastingRunDto | null>(null)
  const [mappings, setMappings] = useState<DoorbelastingMappingDto[]>([])
  const [laadFout, setLaadFout] = useState<string | null>(null)

  const [verdeling, setVerdeling] = useState<Verdeling>({})
  // Elke wijziging maakt het laatste server-resultaat (netto-delen + checks) verouderd —
  // boeken kan pas weer ná een verse "Verdeling opslaan" (server berekent bindend).
  const [gewijzigd, setGewijzigd] = useState(false)

  const [opslaanBezig, setOpslaanBezig] = useState(false)
  const [opslaanFout, setOpslaanFout] = useState<string | null>(null)
  const [boekenBezig, setBoekenBezig] = useState(false)
  const [boekenFout, setBoekenFout] = useState<string | null>(null)
  const [boekResultaat, setBoekResultaat] = useState<Record<string, string> | null>(null)
  const [popupChecks, setPopupChecks] = useState<{ melding: string | null; checks: CheckRapportDto } | null>(null)

  useEffect(() => {
    if (!administratieId || !documentId) return
    let actief = true
    Promise.all([
      apiJson<DocumentDetailDto>(`/administraties/${administratieId}/documenten/${documentId}`),
      apiJson<BoekvoorstelDto>(`/administraties/${administratieId}/documenten/${documentId}/boekvoorstel`),
      startDoorbelastingRun(administratieId, documentId),
      haalDoorbelastingMappingsOp(administratieId),
    ])
      .then(([documentDetail, boekvoorstel, runData, mappingLijst]) => {
        if (!actief) return
        setDetail(documentDetail)
        const metId = boekvoorstel.regels.filter((r): r is typeof r & { id: string } => Boolean(r.id))
        setRegelIdsOntbreken(metId.length !== boekvoorstel.regels.length)
        setBronRegels(
          metId.map((r, i) => ({
            id: r.id,
            omschrijving: r.omschrijving?.trim() || `Regel ${i + 1}`,
            netto: r.netto_bedrag,
          })),
        )
        setRun(runData)
        setVerdeling(verdelingUitRun(runData))
        setMappings(mappingLijst)
      })
      .catch((err: unknown) => {
        if (actief) setLaadFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
    return () => {
      actief = false
    }
  }, [administratieId, documentId])

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

  if (laadFout) return <div className="fout">Kon de doorbelasting niet laden: {laadFout}</div>
  if (!administratieId || !documentId || !detail || !run || bronRegels === null) {
    return <p className="hint">Laden…</p>
  }

  const boekingen = run.previews.filter((p) => p.boeking_status !== null)
  // Zodra er een niet-gestorneerde boeking is, is de verdeling server-side bevroren (de
  // geboekte werkelijkheid mag nooit stil verschuiven) — de UI biedt bewerken dan niet aan.
  const bevroren = run.status !== 'concept' || boekingen.length > 0
  const volledigGeboekt = run.status === 'geboekt'
  const checksGroen = !gewijzigd && !run.checks.geblokkeerd

  const wijzig = (bronId: string, key: string, wijziging: Partial<VerdeelRij>) => {
    setVerdeling((huidig) => ({
      ...huidig,
      [bronId]: (huidig[bronId] ?? []).map((rij) =>
        rij.key === key ? { ...rij, ...wijziging, nettoDeel: null } : rij,
      ),
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
    setBoekResultaat(null)
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
      setRun(vers)
      setVerdeling(verdelingUitRun(vers))
      setGewijzigd(false)
    } catch (err) {
      setOpslaanFout(err instanceof ApiError ? err.message : 'Verdeling opslaan mislukt.')
    } finally {
      setOpslaanBezig(false)
    }
  }

  const boeken = async () => {
    setBoekenBezig(true)
    setBoekenFout(null)
    setBoekResultaat(null)
    try {
      const resp = await boekDoorbelastingRun(administratieId, run.id)
      const body: unknown = await resp.json().catch(() => null)
      if (resp.ok) {
        const resultaat = (body as { per_doelentiteit: Record<string, string> }).per_doelentiteit
        setBoekResultaat(resultaat)
        // Verse run-staat (previews met boeking_status, run-status, checks) ná het boeken.
        const vers = await haalDoorbelastingRunOp(administratieId, run.id)
        setRun(vers)
        setVerdeling(verdelingUitRun(vers))
        setGewijzigd(false)
        return
      }
      const detailBody = body && typeof body === 'object' ? (body as { detail?: unknown }).detail : null
      if (resp.status === 409 && detailBody && typeof detailBody === 'object' && 'checks' in detailBody) {
        const { melding, checks } = detailBody as { melding?: string; checks: CheckRapportDto }
        setRun((huidig) => (huidig ? { ...huidig, checks } : huidig))
        setPopupChecks({ melding: melding ?? null, checks })
      } else {
        setBoekenFout(typeof detailBody === 'string' ? detailBody : resp.statusText || `Fout (${resp.status})`)
      }
    } catch (err) {
      setBoekenFout(err instanceof ApiError ? err.message : 'Doorbelasten mislukt.')
    } finally {
      setBoekenBezig(false)
    }
  }

  return (
    <div>
      <div className="topbar">
        <h1>
          <Link to={`/documenten/${administratieId}/${documentId}`}>← Document</Link>{' '}
          <span style={{ color: 'var(--muted)', fontWeight: 400 }}>/</span> {detail.bestandsnaam}
        </h1>
        <div className="adm-select">
          <span className="chip klaar">doorbelasten · Kempen</span>{' '}
          {volledigGeboekt && <span className="chip ok">doorbelast ✓</span>}
        </div>
      </div>

      <div className="membanner">
        <div className="icon">↔</div>
        <div>
          <b>Doorbelasting per regel:</b> verdeel elke door te belasten regel procentueel (exact 100%)
          over de doelentiteiten op de whitelist. De centen worden server-side kloppend verdeeld
          (grootste-rest — er raakt nooit een cent kwijt); per doelentiteit ontstaat bij het boeken een
          verkoopfactuur in deze administratie (kosten + provisie) en een spiegel-inkoopfactuur in de
          doel-administratie. Een regel zonder verdeling wordt niet doorbelast.
        </div>
      </div>

      {regelIdsOntbreken && (
        <FoutMelding
          melding={
            'De boekingsregels van dit document dragen geen regel-id — zonder id kan er geen verdeling ' +
            'opgeslagen worden. Neem contact op met de beheerder (het boekvoorstel-endpoint moet het ' +
            'regel-id meegeven).'
          }
        />
      )}
      {bevroren && !volledigGeboekt && (
        <div className="alertbanner">
          <div className="icon">🔒</div>
          <div>
            Deze doorbelasting is (deels) geboekt — de verdeling is bevroren (de geboekte werkelijkheid
            mag nooit verschuiven). Ontbrekende doelentiteiten kunnen hieronder alsnog geboekt worden;
            terugdraaien = storneren per deelboeking op het documentdetail.
          </div>
        </div>
      )}

      <div className="panel">
        <h2>Verdeling per regel</h2>
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
                ) : (
                  <span className="chip afwijking">{String(som).replace('.', ',')}% — moet exact 100% zijn</span>
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
                disabled={opslaanBezig || boekenBezig || regelIdsOntbreken}
                onClick={() => void opslaan()}
              >
                {opslaanBezig ? 'Bezig…' : 'Verdeling opslaan'}
              </button>
              {rijenZonderEntiteit > 0 && (
                <span className="chip afwijking">
                  {rijenZonderEntiteit} verdeelregel{rijenZonderEntiteit === 1 ? '' : 's'} zonder doelentiteit
                </span>
              )}
            </div>
            <p className="hint" style={{ marginBottom: 0 }}>
              De server berekent de netto-delen bindend (grootste-rest-methode): de som van de delen is
              altijd exact het regelbedrag. Percentages die niet op 100% sluiten mogen opgeslagen worden
              (werkstaat), maar blokkeren het boeken als harde check.
            </p>
          </>
        )}
      </div>

      <div className="panel">
        <h2>Per doelentiteit (preview)</h2>
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
        <p className="hint" style={{ marginBottom: 0 }}>
          De provisie (vast percentage uit Instellingen → Doorbelasting) boekt als losse regel op de
          verkoopfactuur; de btw is het vlakke doorbelastings-tarief uit dezelfde instellingen. In de
          doel-administratie boekt de provisie altijd apart, op de vaste provisie-GB van de mapping.
        </p>
      </div>

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

      <div className="panel">
        {boekenFout && <div className="fout">{boekenFout}</div>}
        {run.laatste_fout && !boekResultaat && (
          <div className="fout">
            De laatste boekpoging gaf een fout.
            <details style={{ marginTop: 6 }}>
              <summary style={{ cursor: 'pointer', fontSize: 12 }}>Technische details</summary>
              <code style={{ fontSize: 12, wordBreak: 'break-word' }}>{JSON.stringify(run.laatste_fout)}</code>
            </details>
          </div>
        )}
        {boekResultaat && (
          <div style={{ marginBottom: 10 }}>
            <b>Resultaat per doelentiteit:</b>
            <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
              {Object.entries(boekResultaat).map(([mappingId, statusWaarde]) => {
                const chip = boekingStatusChip(statusWaarde)
                return (
                  <li key={mappingId} style={{ marginBottom: 4 }}>
                    {mappingPerId.get(mappingId)?.doelentiteit_naam ?? mappingId}:{' '}
                    <span className={`chip ${chip.klasse}`}>{chip.label}</span>
                  </li>
                )
              })}
            </ul>
          </div>
        )}
        {volledigGeboekt ? (
          <p className="hint" style={{ marginTop: 0 }}>
            Alle doelentiteiten zijn doorbelast. Terugdraaien kan per deelboeking (storno, verplichte
            reden) op het documentdetail.
          </p>
        ) : (
          <div className="actions">
            <button
              type="button"
              className="btn green"
              disabled={!checksGroen || boekenBezig || opslaanBezig}
              title={
                gewijzigd
                  ? 'Sla de verdeling eerst op — de server herberekent de delen en de checks'
                  : run.checks.geblokkeerd
                    ? 'Doorbelasten geblokkeerd — een of meer harde checks zijn niet groen'
                    : 'Boekt per doelentiteit de verkoopfactuur (bron) + spiegel-inkoopfactuur (doel)'
              }
              onClick={() => void boeken()}
            >
              {boekenBezig ? 'Bezig…' : 'Doorbelasten in RLZ ✓'}
            </button>
          </div>
        )}
      </div>

      {popupChecks && (
        <ChecksPopup melding={popupChecks.melding} checks={popupChecks.checks} onSluiten={() => setPopupChecks(null)} />
      )}
    </div>
  )
}
