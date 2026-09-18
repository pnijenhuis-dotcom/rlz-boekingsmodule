import { useState } from 'react'
import { dagKort, perProjectRijen, type DagKolom } from './dagEerst'
import { UREN_STATUS_KLEUR, UREN_STATUS_LABEL, weekUrenTekst, type PlanningWeekDto } from './planningApi'

/* Toggle "Per project" (mockup v3 ④): dezelfde weekrespons gedraaid — rij per project, cel = aantal + status-stip +
 * conflict-chip, weekkolom "N mandagen · uren x/y · conflicten". Alleen projecten mét planning deze week + de regel
 * "N actieve projecten zonder planning · tonen". GEEN bewerkacties: klik op een cel = terug naar "Per dag" mét die kaart
 * geselecteerd — één bewerkroute, geen twee waarheden. */
export function PerProjectWeergave({
  kolommen,
  data,
  vandaagIso,
  administratieId,
  weekParam,
  onNaarKaart,
  onNaarPerDag,
}: {
  kolommen: DagKolom[]
  data: PlanningWeekDto
  vandaagIso: string
  administratieId: string
  weekParam: string
  onNaarKaart: (sleutel: string) => void
  onNaarPerDag: () => void
}) {
  const { rijen, zonder_planning } = perProjectRijen(kolommen, data)
  const [toonZonder, setToonZonder] = useState(false)
  const zonder = data.projecten.filter((p) => p.is_actief && !rijen.some((r) => r.project_id === p.project_id))
  return (
    <div className="tabel-scroll sticky-koppen plan-scroll" data-testid="per-project">
      <table className="plan-grid plan-pp" style={{ tableLayout: 'fixed', minWidth: 760 }}>
        <thead>
          <tr>
            <th style={{ width: 220 }}>Project</th>
            {kolommen.map((k) => (
              <th key={k.datum} className={k.datum === vandaagIso ? 'plan-vandaag' : undefined} style={{ textAlign: 'center' }}>
                {dagKort(k.datum)}
              </th>
            ))}
            <th style={{ width: 260 }}>Week</th>
          </tr>
        </thead>
        <tbody>
          {rijen.length === 0 && (
            <tr>
              <td colSpan={kolommen.length + 2}>
                <p className="hint" style={{ margin: 0 }}>
                  Nog niemand gepland deze week —{' '}
                  <button type="button" className="linkbtn" onClick={onNaarPerDag}>
                    plan in &quot;Per dag&quot;
                  </button>
                  .
                </p>
              </td>
            </tr>
          )}
          {rijen.map((r) => (
            <tr key={r.project_id} data-testid={`pp-rij-${r.project_id}`}>
              <th style={{ textAlign: 'left', verticalAlign: 'top' }}>
                {r.project_naam ?? r.project_id}
                <div style={{ fontWeight: 400, fontSize: 10.5, color: 'var(--muted)' }}>{r.opdrachtgever ?? ''}</div>
              </th>
              {r.cellen.map((c) => (
                <td key={c.datum} className={`plan-cel${c.datum === vandaagIso ? ' plan-vandaag' : ''}`} style={{ textAlign: 'center' }}>
                  {c.aantal === 0 && !c.gereserveerd ? (
                    <span style={{ color: 'var(--faint)' }}>—</span>
                  ) : (
                    <button
                      type="button"
                      className="linkbtn"
                      title={`Naar de kaart in "Per dag" · ${UREN_STATUS_LABEL[c.status]}${c.conflicten ? ` · ${c.conflicten} conflict` : ''}`}
                      aria-label={`${r.project_naam ?? ''} ${dagKort(c.datum)}: ${c.gereserveerd ? 'gereserveerd' : `${c.aantal} man`}`}
                      onClick={() => onNaarKaart(`${r.project_id}|${c.datum}`)}
                      style={{ fontWeight: 700, display: 'inline-flex', alignItems: 'center', gap: 5 }}
                    >
                      <span aria-hidden style={{ width: 7, height: 7, borderRadius: 99, background: UREN_STATUS_KLEUR[c.status] }} />
                      {c.gereserveerd ? <em className="plan-chip grijs">gereserveerd</em> : c.aantal}
                      {c.conflicten > 0 && <span className="plan-chip warn">{c.conflicten}</span>}
                    </button>
                  )}
                </td>
              ))}
              <td style={{ fontSize: 12, color: 'var(--muted)' }}>
                {r.week_tekst}
                {/* 15-09: weektotaal-link naar de weekstaten van dit project (bestaande route) — de leesweergave is dé plek. */}
                {weekUrenTekst(data.projecten.find((p) => p.project_id === r.project_id)?.week_uren) && (
                  <a
                    className="linkbtn"
                    data-testid="week-uren-chip"
                    href={`/meerwerk?administratie=${administratieId}&project=${r.project_id}&week=${weekParam}`}
                    style={{ display: 'block', fontSize: 11, marginTop: 2 }}
                    title="Weekstaten en keuring van dit project openen"
                  >
                    {weekUrenTekst(data.projecten.find((p) => p.project_id === r.project_id)?.week_uren)} →
                  </a>
                )}
              </td>
            </tr>
          ))}
          {zonder_planning > 0 && (
            <tr className="plan-scheider">
              <th colSpan={kolommen.length + 2}>
                {zonder_planning} actieve projecten zonder planning deze week ·{' '}
                <button type="button" className="linkbtn" style={{ fontSize: 10.5, textTransform: 'none', letterSpacing: 0 }} onClick={() => setToonZonder((t) => !t)}>
                  {toonZonder ? 'verbergen' : 'tonen'}
                </button>
              </th>
            </tr>
          )}
          {toonZonder &&
            zonder.map((p) => (
              <tr key={p.project_id} className="plan-compact">
                <th style={{ textAlign: 'left' }}>
                  {p.project_naam ?? p.project_id}
                  <div style={{ fontWeight: 400, fontSize: 10.5, color: 'var(--muted)' }}>{p.opdrachtgever ?? ''}</div>
                </th>
                <td colSpan={kolommen.length + 1} style={{ color: 'var(--faint)', fontSize: 11.5 }}>
                  niet gepland — plan in &quot;Per dag&quot; (sleep het project naar een dag)
                </td>
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  )
}
