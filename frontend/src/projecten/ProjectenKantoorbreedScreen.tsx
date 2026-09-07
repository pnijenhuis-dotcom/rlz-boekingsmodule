// Inzicht › Projecten — KANTOORBREED (fixrun 07-09 blok C5; mockup inzicht-kantoorbreed.html ①②⑨ =
// bouwnorm, zelfde patroon als Inzicht › Reconciliatie/Verplichtingen). Alle actieve projecten over de
// administraties van de gebruiker (RLS blijft de waarheid), met per project vier status-chips die de
// server uit de bestaande caches berekent (resultaat-marge, offerte-verbruik, weekstaten-stand,
// m²-voortgang), urgentste bovenaan, facetten administratie/status (filter, nooit poort), zoekveld,
// server-side paginering 25 en tellers "N projecten over M administraties". Klik = het bestaande
// projectdetail (/projecten/:administratieId/:projectId). Teal = actie, groen = status, rood = signaal.
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { AdministratieCombobox } from '../ui/AdministratieCombobox'
import { FoutMelding } from '../ui/FoutMelding'
import { Badge, Button, SkeletonRegels } from '../ui/basis'
import { useAdministraties } from '../werkvoorraad/useAdministraties'
import {
  euro,
  haalProjectenKantoorbreed,
  PROJECT_STATUS_FACETTEN,
  PROJECT_STATUS_LABEL,
  type ProjectKantoorbreedRijDto,
  type ProjectenKantoorbreedDto,
  type ProjectStatusFacet,
} from './projectenApi'

const ALLE = '__alle'

function isStatusFacet(w: string | null): w is ProjectStatusFacet {
  return w !== null && (PROJECT_STATUS_FACETTEN as string[]).includes(w)
}

function pct(waarde: string | number | null): string {
  if (waarde === null) return '—'
  return `${Number(waarde).toLocaleString('nl-NL', { maximumFractionDigits: 1 })} %`
}

function m2(waarde: string): string {
  return Number(waarde).toLocaleString('nl-NL', { maximumFractionDigits: 0 })
}

/** Resultaat-chip: marge-% uit de analytische laag (zelfde rekenregel als het projectdetail). */
export function ResultaatChip({ rij }: { rij: ProjectKantoorbreedRijDto }) {
  const r = rij.resultaat
  if (!r.heeft_cijfers) return <span className="hint">geen cijfers</span>
  const negatief = Number(r.marge) < 0
  return (
    <span data-testid="chip-resultaat">
      {r.marge_pct === null ? (
        <Badge variant="warn" title={`Kosten ${euro(r.kosten)} zonder omzet`}>
          nog geen omzet
        </Badge>
      ) : (
        <Badge variant={negatief ? 'danger' : 'ok'} title={`Marge ${euro(r.marge)} op ${euro(r.baten)} baten`}>
          marge {pct(r.marge_pct)}
        </Badge>
      )}
      {Number(r.onbepaalbaar_uren) > 0 && (
        <span className="hint" style={{ display: 'block', margin: 0, fontSize: 11 }}>
          {Number(r.onbepaalbaar_uren).toLocaleString('nl-NL')} u zonder tarief
        </span>
      )}
    </span>
  )
}

/** Verplichtingen-chip: cumulatief verbruik van de lopende offertes van dit project (③, verbruik = geboekt). */
export function VerplichtingenChip({ rij }: { rij: ProjectKantoorbreedRijDto }) {
  const v = rij.verplichtingen
  if (v.aantal === 0) return <span className="hint">—</span>
  return (
    <span data-testid="chip-verplichtingen">
      {v.overschreden > 0 ? (
        <Badge variant="danger">
          {v.overschreden === 1 ? 'offerte overschreden' : `${v.overschreden} offertes overschreden`}
        </Badge>
      ) : (
        <Badge variant={v.percentage !== null && v.percentage >= 100 ? 'ok' : 'info'}>
          {v.percentage === null ? 'zonder bedrag' : `${v.percentage} % verbruikt`}
        </Badge>
      )}
      <span className="hint" style={{ display: 'block', margin: 0, fontSize: 11 }}>
        {euro(v.verbruikt_excl)} / {euro(v.goedgekeurd_excl)} · {v.aantal} {v.aantal === 1 ? 'offerte' : 'offertes'}
      </span>
    </span>
  )
}

/** Weekstaten-chip: geplande weken zonder ingediende staat + staten die op keuring wachten. */
export function WeekstatenChip({ rij }: { rij: ProjectKantoorbreedRijDto }) {
  const w = rij.weekstaten
  if (!w.van_toepassing) return <span className="hint">n.v.t.</span>
  if (w.ontbrekend === 0 && w.te_keuren === 0) {
    return (
      <Badge variant="ok" data-testid="chip-weekstaten">
        bij
      </Badge>
    )
  }
  return (
    <span data-testid="chip-weekstaten" style={{ display: 'inline-flex', gap: 4, flexWrap: 'wrap' }}>
      {w.ontbrekend > 0 && (
        <Badge variant="danger">
          wk {w.oudste_ontbrekende_week} ontbreekt{w.ontbrekend > 1 ? ` (+${w.ontbrekend - 1})` : ''}
        </Badge>
      )}
      {w.te_keuren > 0 && <Badge variant="warn">{w.te_keuren} te keuren</Badge>}
    </span>
  )
}

/** m²-chip: gebouwd (goedgekeurde weekstaten) t.o.v. contract. */
export function M2Chip({ rij }: { rij: ProjectKantoorbreedRijDto }) {
  const m = rij.m2
  if (m.doorlopende_huur) return <Badge variant="info">doorlopende huur</Badge>
  if (m.contract_m2 === null) return <span className="hint">geen contract-m²</span>
  return (
    <span data-testid="chip-m2">
      {m2(m.gebouwd_m2)} / {m2(m.contract_m2)} m²
      <span className="hint" style={{ display: 'block', margin: 0, fontSize: 11 }}>
        {m.percentage ?? 0} % · uit weekstaten
      </span>
    </span>
  )
}

export function ProjectenKantoorbreedScreen() {
  const navigate = useNavigate()
  const { administraties } = useAdministraties()
  const [zoekParams, setZoekParams] = useSearchParams()
  const administratieId = zoekParams.get('administratie_id') ?? ''
  const statusParam = zoekParams.get('status')
  const status: ProjectStatusFacet = isStatusFacet(statusParam) ? statusParam : 'alle'
  const [zoek, setZoek] = useState('')
  const [pagina, setPagina] = useState(1)
  const [data, setData] = useState<ProjectenKantoorbreedDto | null>(null)
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [versie, setVersie] = useState(0)

  useEffect(() => {
    let actueel = true
    setLaadFout(null)
    const timer = window.setTimeout(
      () => {
        haalProjectenKantoorbreed({ pagina, q: zoek.trim(), administratieId: administratieId || null, status })
          .then((d) => {
            if (actueel) setData(d)
          })
          .catch((err: unknown) => {
            if (actueel) setLaadFout(err instanceof Error ? err.message : 'Onbekende fout')
          })
      },
      zoek ? 250 : 0,
    )
    return () => {
      actueel = false
      window.clearTimeout(timer)
    }
  }, [pagina, zoek, administratieId, status, versie])

  const zetParam = (naam: string, waarde: string | null) => {
    const p = new URLSearchParams(zoekParams)
    if (waarde) p.set(naam, waarde)
    else p.delete(naam)
    setZoekParams(p, { replace: true })
    setPagina(1)
  }

  const comboboxOpties = useMemo(
    () => [{ id: ALLE, naam: 'Alle administraties' }, ...(administraties ?? [])],
    [administraties],
  )
  const rijen = data?.rijen ?? []
  const paginas = Math.max(1, Math.ceil((data?.totaal ?? 0) / (data?.per_pagina ?? 25)))

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 style={{ margin: 0 }}>Inzicht › Projecten</h1>
          <div className="hint" style={{ marginTop: 2 }}>
            Alle actieve projecten over al je administraties, met per project de stand van resultaat, offertes,
            weekstaten en m². Klik een project voor specificaties, documenten, staffels en het resultaat.
          </div>
        </div>
      </div>

      <div className="panel" data-testid="projecten-paneel" style={{ padding: 0, overflow: 'hidden' }}>
        <div
          className="p-kop"
          style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 18px', borderBottom: '1px solid var(--border)', flexWrap: 'wrap' }}
        >
          <h2 style={{ margin: 0, fontSize: 14.5 }}>Projecten</h2>
          {data && (
            <>
              <Badge variant={data.tellers.met_signaal > 0 ? 'warn' : 'ok'} data-testid="chip-signaal">
                {data.tellers.met_signaal} met signaal
              </Badge>
              <Badge variant={data.tellers.verplichting_overschreden > 0 ? 'danger' : 'stil'} data-testid="chip-overschreden">
                {data.tellers.verplichting_overschreden} offerte overschreden
              </Badge>
              <Badge variant={data.tellers.weekstaat_ontbreekt > 0 ? 'danger' : 'stil'} data-testid="chip-ontbreekt">
                {data.tellers.weekstaat_ontbreekt} weekstaat ontbreekt
              </Badge>
            </>
          )}
          <span style={{ marginLeft: 'auto' }} />
          <div style={{ minWidth: 220 }}>
            <AdministratieCombobox
              label="Administratie"
              toonLabel={false}
              administraties={comboboxOpties}
              waarde={administratieId || ALLE}
              onWijzig={(id) => zetParam('administratie_id', id === ALLE ? null : id)}
              placeholder="Administratie: alle"
            />
          </div>
          <select
            aria-label="Status"
            value={status}
            onChange={(e) => zetParam('status', e.target.value === 'alle' ? null : e.target.value)}
            style={{ width: 'auto' }}
          >
            {PROJECT_STATUS_FACETTEN.map((s) => (
              <option key={s} value={s}>
                Status: {PROJECT_STATUS_LABEL[s]}
                {data ? ` (${data.facetten.status[s] ?? 0})` : ''}
              </option>
            ))}
          </select>
          <input
            type="search"
            aria-label="Zoek project"
            placeholder="🔍 project, opdrachtgever, werknummer…"
            value={zoek}
            onChange={(e) => {
              setZoek(e.target.value)
              setPagina(1)
            }}
            style={{ width: 220, maxWidth: '100%' }}
          />
        </div>

        {laadFout && (
          <FoutMelding melding="De projecten konden niet geladen worden." detail={laadFout} onOpnieuw={() => setVersie((v) => v + 1)} />
        )}
        {data === null && !laadFout && <SkeletonRegels />}
        {data !== null && rijen.length === 0 && (
          <div className="hint" style={{ padding: '14px 18px' }} data-testid="projecten-leeg">
            {status !== 'alle'
              ? `Geen projecten met status "${PROJECT_STATUS_LABEL[status]}".`
              : zoek.trim()
                ? `Geen projecten gevonden voor "${zoek.trim()}".`
                : 'Nog geen actieve projecten in je administraties — projecten komen uit de RLZ-sync; een nieuw project maak je aan vanaf de klantpagina.'}
          </div>
        )}
        {rijen.length > 0 && (
          <div className="tabel-scroll">
            <table data-testid="projecten-tabel">
              <thead>
                <tr>
                  <th style={{ width: '16%' }}>Administratie</th>
                  <th>Project</th>
                  <th style={{ width: 130 }}>Resultaat</th>
                  <th style={{ width: 170 }}>Offertes</th>
                  <th style={{ width: 150 }}>Weekstaten</th>
                  <th style={{ width: 130 }}>m²</th>
                  <th style={{ width: 110 }} />
                </tr>
              </thead>
              <tbody>
                {rijen.map((r) => (
                  <tr
                    key={`${r.administratie_id}-${r.project_id}`}
                    data-testid="projecten-rij"
                    className="clickable"
                    onClick={() => navigate(`/projecten/${r.administratie_id}/${r.project_id}`)}
                  >
                    <td onClick={(e) => e.stopPropagation()}>
                      <Link to={`/projecten?administratie=${r.administratie_id}`} className="text-primary no-underline hover:underline">
                        {r.administratie_naam}
                      </Link>
                    </td>
                    <td>
                      <b>{r.naam ?? r.project_id}</b>
                      <div className="hint" style={{ margin: '2px 0 0', fontSize: 11.5 }}>
                        {r.opdrachtgever ?? 'opdrachtgever onbekend'}
                        {r.werknummer_opdrachtgever ? ` · werknr ${r.werknummer_opdrachtgever}` : ''}
                      </div>
                    </td>
                    <td>
                      <ResultaatChip rij={r} />
                    </td>
                    <td>
                      <VerplichtingenChip rij={r} />
                    </td>
                    <td>
                      <WeekstatenChip rij={r} />
                    </td>
                    <td>
                      <M2Chip rij={r} />
                    </td>
                    <td className="acties" style={{ whiteSpace: 'nowrap', textAlign: 'right' }} onClick={(e) => e.stopPropagation()}>
                      <Link
                        to={`/projecten/${r.administratie_id}/${r.project_id}`}
                        className="btn secondary"
                        aria-label={`Open project ${r.naam ?? r.project_id}`}
                      >
                        Openen →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && (
          <div
            className="voet hint"
            data-testid="projecten-voet"
            style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 8, padding: '10px 18px', borderTop: '1px solid var(--border)', flexWrap: 'wrap' }}
          >
            <Button variant="ghost" maat="klein" aria-label="Vorige pagina" disabled={pagina <= 1} onClick={() => setPagina((p) => p - 1)}>
              ‹
            </Button>
            <span>
              {pagina} van {paginas}
            </span>
            <Button variant="ghost" maat="klein" aria-label="Volgende pagina" disabled={pagina >= paginas} onClick={() => setPagina((p) => p + 1)}>
              ›
            </Button>
            <span>
              · {data.totaal} {data.totaal === 1 ? 'project' : 'projecten'} over {data.administraties_in_selectie}{' '}
              {data.administraties_in_selectie === 1 ? 'administratie' : 'administraties'}
            </span>
          </div>
        )}
      </div>
    </div>
  )
}
