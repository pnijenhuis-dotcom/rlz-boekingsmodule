import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Button, SkeletonPaneel } from '../ui/basis'
import { FoutMelding } from '../ui/FoutMelding'
import { Breadcrumb } from '../werkvoorraad/Breadcrumb'
import { useAdministraties } from '../werkvoorraad/useAdministraties'
import {
  euro,
  euroPrecies,
  haalCijfersSyncStatus,
  haalProjectResultaat,
  startCijfersSync,
  type ProjectResultaatDto,
} from './projectenApi'

/* Resultaat per project (mockup projecten-invoer.html view 3, akkoord Peter 22-08): vier
 * tegels + weektabel met cumulatief. Analytische laag — volledig deterministisch uit de
 * backend-rekenlaag (project_regel_cache + weekstaten + meerwerk), wordt nooit in RLZ
 * geboekt, excl. AK-opslag. "Onderweg" zonder tarief = post "onbepaalbaar" (oranje), nooit
 * gokken. Besluit Peter 22-08: géén suppletie-signaal. */

function Tegel({ label, waarde, sub, kleur }: { label: string; waarde: string; sub?: string; kleur?: string }) {
  return (
    <div>
      <div style={{ color: 'var(--muted)', fontSize: 11.5 }}>{label}</div>
      <div style={{ color: kleur, fontSize: 22, fontWeight: 800 }}>{waarde}</div>
      {sub && <div style={{ color: 'var(--faint)', fontSize: 11.5 }}>{sub}</div>}
    </div>
  )
}

export function ProjectResultaatScreen() {
  const { administratieId = '', projectId = '' } = useParams()
  const { administraties } = useAdministraties()
  const [data, setData] = useState<ProjectResultaatDto | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [syncBezig, setSyncBezig] = useState(false)
  const [syncMelding, setSyncMelding] = useState<string | null>(null)
  const gestopt = useRef(false)
  useEffect(() => () => { gestopt.current = true }, [])

  const administratieNaam = useMemo(
    () => (administraties ?? []).find((a) => a.id === administratieId)?.naam ?? 'Administratie',
    [administraties, administratieId],
  )

  const laad = useCallback(() => {
    setFout(null)
    haalProjectResultaat(administratieId, projectId)
      .then(setData)
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Onbekende fout'))
  }, [administratieId, projectId])

  useEffect(() => {
    setData(null)
    laad()
  }, [laad])

  /* Achtergrondrun (fix 23-08): start = 202, daarna de status pollen tot klaar/fout —
   * de RLZ-ronde duurt tegen echte datamassa minuten en hoort niet in één request. */
  const ververs = async () => {
    setSyncBezig(true)
    setSyncMelding(null)
    try {
      await startCijfersSync(administratieId)
      // Poll ruim (2,5 s); de run zelf meldt fouten expliciet via de statusroute — nooit stil.
      for (;;) {
        await new Promise((klaar) => setTimeout(klaar, 2500))
        if (gestopt.current) return
        const status = await haalCijfersSyncStatus(administratieId)
        if (status.status === 'klaar') {
          if ((status.leesfouten ?? 0) > 0) {
            setSyncMelding(
              `Verversing klaar, maar ${status.leesfouten} document(en) bleven onleesbaar in RLZ — ` +
                'cijfers mogelijk onvolledig; probeer later opnieuw.',
            )
          }
          laad()
          return
        }
        if (status.status === 'fout' || status.status === 'geen') {
          setSyncMelding(`Verversen mislukt: ${status.fout_reden ?? 'onbekende fout'}`)
          return
        }
      }
    } catch (err) {
      setSyncMelding(err instanceof Error ? `Verversen mislukt: ${err.message}` : 'Verversen mislukt')
    } finally {
      if (!gestopt.current) setSyncBezig(false)
    }
  }

  if (fout) return <FoutMelding melding="Het resultaat kon niet geladen worden." detail={fout} onOpnieuw={laad} />
  if (data === null) return <SkeletonPaneel />

  const onderwegNegatief = Number(data.onderweg_saldo) < 0
  const margePositief = Number(data.verwachte_marge) >= 0

  return (
    <div>
      <div className="topbar">
        <div>
          <Breadcrumb
            stappen={[
              { label: 'Werkvoorraad', naar: '/' },
              { label: administratieNaam, naar: `/?administratie=${administratieId}` },
              { label: 'Projecten', naar: `/projecten?administratie=${administratieId}` },
              { label: data.project_naam ?? 'Project', naar: `/projecten/${administratieId}/${projectId}` },
            ]}
            huidige="Resultaat"
          />
          <h1>Resultaat — {data.project_naam ?? 'Project'}</h1>
          <div style={{ color: 'var(--muted)', fontSize: 12.5, marginTop: 3 }}>
            Kosten/baten per week · analytische laag, wordt nooit in RLZ geboekt · excl. AK-opslag
          </div>
        </div>
        <div style={{ marginLeft: 'auto' }}>
          <Button variant="secundair" maat="klein" disabled={syncBezig} onClick={() => void ververs()}>
            {syncBezig ? 'Verversen… (loopt op de achtergrond)' : '⟳ Cijfers verversen uit RLZ'}
          </Button>
        </div>
      </div>

      {syncMelding && (
        <p style={{ background: 'var(--warn-bg)', borderRadius: 8, color: 'var(--warn)', fontSize: 12.5, padding: '9px 13px' }}>
          ⚠️ {syncMelding}
        </p>
      )}

      <div className="panel">
        <h2>Stand</h2>
        <div style={{ display: 'grid', gap: '12px 16px', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
          <Tegel label="Baten gefactureerd (RLZ)" waarde={euro(data.baten_geboekt)} sub="verkoopfacturen op dit project" />
          <Tegel label="Kosten geboekt (RLZ)" waarde={euro(data.kosten_geboekt)} sub="inkoop + ZZP-facturen op dit project" />
          <Tegel
            label="Onderweg (verrijking)"
            waarde={euro(data.onderweg_saldo)}
            kleur={onderwegNegatief ? 'var(--warn)' : 'var(--ok)'}
            sub={`getekende uren nog niet gefactureerd (${euro(data.uren_onderweg_bedrag)}) − goedgekeurd meerwerk nog te factureren (${euro(data.meerwerk_onderweg_bedrag)})`}
          />
          <Tegel
            label="Verwachte marge"
            waarde={`${euro(data.verwachte_marge)}${data.marge_pct !== null ? ` · ${Number(data.marge_pct).toLocaleString('nl-NL', { maximumFractionDigits: 1 })}%` : ''}`}
            kleur={margePositief ? 'var(--ok)' : 'var(--danger)'}
            sub="gefactureerd + onderweg, excl. AK-opslag"
          />
        </div>
        {Number(data.onbepaalbaar_uren) > 0 && (
          <p style={{ background: 'var(--warn-bg)', borderRadius: 8, color: 'var(--warn)', fontSize: 12.5, marginTop: 12, padding: '9px 13px' }}>
            ⚠️ {Number(data.onbepaalbaar_uren).toLocaleString('nl-NL')} getekende uren zónder tarief — post
            &quot;onbepaalbaar&quot;: telt niet mee in het onderweg-bedrag (nooit gokken). Zet het ZZP-/bureau-tarief op
            de veldwerker-koppeling.
          </p>
        )}
      </div>

      <div className="panel">
        <h2>Per week</h2>
        <p className="hint" style={{ marginTop: 0 }}>
          Baten = verkoopfacturen (RLZ) op dit project · Kosten = inkoop/ZZP-facturen (RLZ) + getekende-uren-verrijking
          uit de weekstaten (uren × tarief, zolang de factuur er nog niet is — telt nooit dubbel: zodra de factuur
          geboekt en verrekend is vervangt die de verrijking).
        </p>
        {data.weken.length === 0 && <p className="hint">Nog geen activiteit op dit project.</p>}
        {data.weken.length > 0 && (
          <div className="tabel-scroll">
            <table>
              <thead>
                <tr>
                  <th>Week</th>
                  <th className="amount">Baten</th>
                  <th className="amount">Kosten (geboekt)</th>
                  <th className="amount">Kosten onderweg (uren)</th>
                  <th className="amount">Saldo week</th>
                  <th className="amount">Cumulatief</th>
                </tr>
              </thead>
              <tbody>
                {data.weken.map((week) => {
                  const saldoPositief = Number(week.saldo) >= 0
                  return (
                    <tr key={`${week.jaar}-${week.weeknummer}`}>
                      <td>
                        <b>
                          wk {week.weeknummer}
                          {week.jaar !== new Date().getFullYear() ? ` '${String(week.jaar).slice(2)}` : ''}
                        </b>
                      </td>
                      <td className="amount">
                        {Number(week.baten) !== 0 ? euroPrecies(week.baten) : '—'}
                        {week.baten_detail.length > 0 && (
                          <div style={{ color: 'var(--muted)', fontSize: 11 }}>{week.baten_detail.join(', ')}</div>
                        )}
                      </td>
                      <td className="amount">
                        {Number(week.kosten_geboekt) !== 0 ? euroPrecies(week.kosten_geboekt) : '—'}
                        {week.kosten_detail.length > 0 && (
                          <div style={{ color: 'var(--muted)', fontSize: 11 }}>{week.kosten_detail.join(', ')}</div>
                        )}
                      </td>
                      <td className="amount">
                        {Number(week.kosten_onderweg) !== 0 ? euroPrecies(week.kosten_onderweg) : '—'}
                        {Number(week.onderweg_onbepaalbaar_uren) > 0 && (
                          <div style={{ color: 'var(--warn)', fontSize: 11 }}>
                            + {Number(week.onderweg_onbepaalbaar_uren).toLocaleString('nl-NL')} u onbepaalbaar
                          </div>
                        )}
                      </td>
                      <td className="amount" style={{ color: saldoPositief ? 'var(--ok)' : 'var(--danger)', fontWeight: 700 }}>
                        {Number(week.saldo) >= 0 ? '+ ' : '− '}
                        {euroPrecies(Math.abs(Number(week.saldo)))}
                      </td>
                      <td className="amount" style={{ fontWeight: 700 }}>
                        {Number(week.cumulatief) >= 0 ? '+ ' : '− '}
                        {euroPrecies(Math.abs(Number(week.cumulatief)))}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        <p className="hint" style={{ marginTop: 10 }}>
          ℹ️ Week-toewijzing: kosten op <b>werkweek</b> (uit verrekende weekstaten) waar herleidbaar, anders
          factuurdatum · een week met kosten maar zonder baten voedt het &quot;kosten zonder omzet&quot;-signaal in het
          overzicht.
        </p>
      </div>
    </div>
  )
}
