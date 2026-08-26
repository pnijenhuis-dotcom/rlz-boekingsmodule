import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError, apiJson } from '../api/client'
import type {
  BoekvoorstelDto,
  CheckRapportDto,
  DocumentDetailDto,
  DoorbelastingMappingDto,
  DoorbelastingRunDto,
} from '../api/types'
import { ChecksPopup } from '../ui/ChecksPopup'
import { FoutMelding } from '../ui/FoutMelding'
import {
  boekDoorbelastingRun,
  haalDoorbelastingMappingsOp,
  haalDoorbelastingRunOp,
  startDoorbelastingRun,
} from './doorbelastingApi'
import { boekingStatusChip } from './status'
import { runVerdelingOnvolledig, VerdelingEditor, type BronRegel, type VerdelingStaat } from './VerdelingEditor'
import { SkeletonPaneel } from '../ui/basis'

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

  // Werkstaat van de verdeel-editor (onopgeslagen wijzigingen / regel niet op 100%) — boeken kan
  // pas ná een verse "Verdeling opslaan" (server berekent bindend).
  const [staat, setStaat] = useState<VerdelingStaat>({ gewijzigd: false, onvolledig: false })
  const onStaat = useCallback((s: VerdelingStaat) => setStaat(s), [])
  const gewijzigd = staat.gewijzigd

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
        setMappings(mappingLijst)
      })
      .catch((err: unknown) => {
        if (actief) setLaadFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
    return () => {
      actief = false
    }
  }, [administratieId, documentId])

  const mappingPerId = new Map(mappings.map((m) => [m.id, m]))

  if (laadFout) return <div className="fout">Kon de doorbelasting niet laden: {laadFout}</div>
  if (!administratieId || !documentId || !detail || !run || bronRegels === null) {
    return <SkeletonPaneel />
  }

  // Synchroon uit de run + de editor-werkstaat: nooit één render lang ten onrechte "aan".
  const verdelingOnvolledig = staat.onvolledig || runVerdelingOnvolledig(run)
  const boekingen = run.previews.filter((p) => p.boeking_status !== null)
  // Zodra er een niet-gestorneerde boeking is, is de verdeling server-side bevroren (de
  // geboekte werkelijkheid mag nooit stil verschuiven) — de UI biedt bewerken dan niet aan.
  const bevroren = run.status !== 'concept' || boekingen.length > 0
  const volledigGeboekt = run.status === 'geboekt'
  const checksGroen = !gewijzigd && !run.checks.geblokkeerd

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

      <VerdelingEditor
        administratieId={administratieId}
        run={run}
        bronRegels={bronRegels}
        regelIdsOntbreken={regelIdsOntbreken}
        mappings={mappings}
        bevroren={bevroren}
        onRunGewijzigd={(vers) => {
          setRun(vers)
          setBoekResultaat(null)
        }}
        onStaat={onStaat}
      />

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
              className="btn"
              disabled={!checksGroen || boekenBezig || verdelingOnvolledig}
              title={
                verdelingOnvolledig
                  ? 'Elke verdeelde regel moet exact op 100% sluiten — zie de teller per regel'
                  : gewijzigd
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
