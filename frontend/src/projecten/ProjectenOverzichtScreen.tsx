import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Badge } from '../ui/basis'
import { FoutMelding } from '../ui/FoutMelding'
import { Breadcrumb } from '../werkvoorraad/Breadcrumb'
import { useAdministraties } from '../werkvoorraad/useAdministraties'
import { euro, haalProjectenOverzicht, type ProjectenOverzichtDto } from './projectenApi'

/* Resultaat alle projecten (mockup projecten-invoer.html view 4, akkoord Peter 22-08):
 * totaal-tegels + tabel per project (baten/kosten/marge/marge-%/4-weken-trend/signalen),
 * gesorteerd op laagste marge eerst — aandachtswerk bovenaan; rij klikt door naar de
 * week-uitsplitsing. Zelfde rekenlaag als het projectdetail: cijfers sluiten per definitie. */

const TREND: Record<string, { tekst: string; kleur: string }> = {
  stijgend: { tekst: '▲ stijgend', kleur: 'var(--ok)' },
  stabiel: { tekst: '▲ stabiel', kleur: 'var(--ok)' },
  dalend: { tekst: '▼ dalend', kleur: 'var(--danger)' },
}

export function ProjectenOverzichtScreen() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const administratieId = searchParams.get('administratie')
  const { administraties } = useAdministraties()
  const [data, setData] = useState<ProjectenOverzichtDto | null>(null)
  const [fout, setFout] = useState<string | null>(null)

  const administratieNaam = useMemo(
    () => (administraties ?? []).find((a) => a.id === administratieId)?.naam ?? 'Administratie',
    [administraties, administratieId],
  )

  const laad = useCallback(() => {
    if (!administratieId) return
    setFout(null)
    haalProjectenOverzicht(administratieId)
      .then(setData)
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Onbekende fout'))
  }, [administratieId])

  useEffect(() => {
    setData(null)
    laad()
  }, [laad])

  if (!administratieId) {
    return <p className="hint">Geen administratie gekozen — open het resultaat vanaf de projectenlijst.</p>
  }
  if (fout) return <FoutMelding melding="Het overzicht kon niet geladen worden." detail={fout} onOpnieuw={laad} />
  if (data === null) return <p className="hint" aria-busy="true">Laden…</p>

  return (
    <div>
      <div className="topbar">
        <div>
          <Breadcrumb
            stappen={[
              { label: 'Werkvoorraad', naar: '/' },
              { label: administratieNaam, naar: `/?administratie=${administratieId}` },
              { label: 'Projecten', naar: `/projecten?administratie=${administratieId}` },
            ]}
            huidige="Resultaat (alle projecten)"
          />
          <h1>Resultaat — alle actieve projecten</h1>
          <div style={{ color: 'var(--muted)', fontSize: 12.5, marginTop: 3 }}>
            Cumulatief · gefactureerd + onderweg · analytisch, nooit geboekt in RLZ · excl. AK-opslag
          </div>
        </div>
      </div>

      <div className="panel">
        <div style={{ display: 'grid', gap: '12px 16px', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
          <div>
            <div style={{ color: 'var(--muted)', fontSize: 11.5 }}>Baten totaal</div>
            <div style={{ fontSize: 22, fontWeight: 800 }}>{euro(data.baten_totaal)}</div>
            <div style={{ color: 'var(--faint)', fontSize: 11.5 }}>
              {data.rijen.length} actieve projecten met activiteit
            </div>
          </div>
          <div>
            <div style={{ color: 'var(--muted)', fontSize: 11.5 }}>Kosten totaal (incl. onderweg)</div>
            <div style={{ fontSize: 22, fontWeight: 800 }}>{euro(data.kosten_totaal_incl_onderweg)}</div>
            <div style={{ color: 'var(--faint)', fontSize: 11.5 }}>waarvan {euro(data.uren_onderweg_totaal)} uren-onderweg</div>
          </div>
          <div>
            <div style={{ color: 'var(--muted)', fontSize: 11.5 }}>Marge totaal</div>
            <div style={{ color: Number(data.marge_totaal) >= 0 ? 'var(--ok)' : 'var(--danger)', fontSize: 22, fontWeight: 800 }}>
              {euro(data.marge_totaal)}
              {data.marge_pct !== null
                ? ` · ${Number(data.marge_pct).toLocaleString('nl-NL', { maximumFractionDigits: 1 })}%`
                : ''}
            </div>
            <div style={{ color: 'var(--faint)', fontSize: 11.5 }}>excl. AK-opslag</div>
          </div>
          <div>
            <div style={{ color: 'var(--muted)', fontSize: 11.5 }}>Aandacht</div>
            <div style={{ color: data.aandacht > 0 ? 'var(--danger)' : 'var(--ok)', fontSize: 22, fontWeight: 800 }}>
              {data.aandacht} project{data.aandacht === 1 ? '' : 'en'}
            </div>
            <div style={{ color: 'var(--faint)', fontSize: 11.5 }}>negatieve of dalende marge</div>
          </div>
        </div>
        {Number(data.onbepaalbaar_uren_totaal) > 0 && (
          <p style={{ background: 'var(--warn-bg)', borderRadius: 8, color: 'var(--warn)', fontSize: 12.5, marginTop: 12, padding: '9px 13px' }}>
            ⚠️ {Number(data.onbepaalbaar_uren_totaal).toLocaleString('nl-NL')} getekende uren zónder tarief tellen niet
            mee (post &quot;onbepaalbaar&quot; — nooit gokken).
          </p>
        )}
      </div>

      <div className="panel">
        <h2>Per project</h2>
        <p className="hint" style={{ marginTop: 0 }}>
          Gesorteerd op marge, laagste eerst — zo staat het aandachtswerk bovenaan. Klik een rij voor de
          week-uitsplitsing.
        </p>
        {data.rijen.length === 0 && <p className="hint">Nog geen projecten met activiteit — ververs eerst de cijfers uit RLZ op een projectdetail.</p>}
        {data.rijen.length > 0 && (
          <div className="tabel-scroll">
            <table>
              <thead>
                <tr>
                  <th>Project</th>
                  <th className="amount">Baten</th>
                  <th className="amount">Kosten (incl. onderweg)</th>
                  <th className="amount">Marge</th>
                  <th className="amount">Marge %</th>
                  <th>Trend 4 wkn</th>
                  <th>Signalen</th>
                </tr>
              </thead>
              <tbody>
                {data.rijen.map((rij) => {
                  const margePositief = Number(rij.marge) >= 0
                  const trend = TREND[rij.trend] ?? { tekst: rij.trend, kleur: 'var(--muted)' }
                  return (
                    <tr
                      key={rij.project_id}
                      className="clickable"
                      onClick={() => navigate(`/projecten/${administratieId}/${rij.project_id}/resultaat`)}
                    >
                      <td>
                        <b>{rij.project_naam ?? rij.project_id}</b>
                        {rij.opdrachtgever && (
                          <div style={{ color: 'var(--muted)', fontSize: 11.5 }}>{rij.opdrachtgever}</div>
                        )}
                      </td>
                      <td className="amount">{euro(rij.baten)}</td>
                      <td className="amount">{euro(rij.kosten_incl_onderweg)}</td>
                      <td className="amount" style={{ color: margePositief ? 'var(--ok)' : 'var(--danger)', fontWeight: 700 }}>
                        {margePositief ? '+ ' : '− '}
                        {euro(Math.abs(Number(rij.marge)))}
                      </td>
                      <td className="amount" style={{ color: margePositief ? 'var(--ok)' : 'var(--danger)', fontWeight: 700 }}>
                        {rij.marge_pct !== null
                          ? `${Number(rij.marge_pct).toLocaleString('nl-NL', { maximumFractionDigits: 1 })}%`
                          : '—'}
                      </td>
                      <td style={{ color: trend.kleur }}>{trend.tekst}</td>
                      <td>
                        <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 4 }}>
                          {rij.kosten_zonder_omzet_weken >= 2 && (
                            <Badge variant="danger">kosten zonder omzet {rij.kosten_zonder_omzet_weken} wkn</Badge>
                          )}
                          {rij.meerwerk_te_lang_niet_doorbelast > 0 && (
                            <Badge variant="warn">meerwerk &gt; 2 wkn niet doorbelast</Badge>
                          )}
                          {rij.doorlopende_huur && <Badge variant="info">doorlopende huur loopt</Badge>}
                          {Number(rij.onbepaalbaar_uren) > 0 && (
                            <Badge variant="warn">{Number(rij.onbepaalbaar_uren).toLocaleString('nl-NL')} u onbepaalbaar</Badge>
                          )}
                          {rij.kosten_zonder_omzet_weken < 2 &&
                            rij.meerwerk_te_lang_niet_doorbelast === 0 &&
                            !rij.doorlopende_huur &&
                            Number(rij.onbepaalbaar_uren) === 0 &&
                            '—'}
                        </span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        <p className="hint" style={{ marginTop: 10 }}>
          ℹ️ Zelfde rekenregels als het project-resultaat: baten en kosten uit RLZ per project, verrijkt met
          getekende-uren-onderweg en goedgekeurd-meerwerk-nog-te-factureren. De signalen hergebruiken de bestaande
          projectsignalen (kosten-zonder-omzet, meerwerk-niet-doorbelast, doorlopende huur).
        </p>
      </div>
    </div>
  )
}
