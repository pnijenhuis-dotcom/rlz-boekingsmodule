// Inzicht › Reconciliatie — blok "Automatiseringen (laatste 24 u)" (herstelrun 07-09 blok C, besluit Peter
// "geen stille no-op"). Per automatisering: stand (aan/uit/deels), verwacht / gedaan / overgeslagen mét reden,
// en de LET-OP-markering (ontbrekende harde voorwaarde of zeven dagen stil). De bevindingen zelf staan als
// gewone rijen in de lijst (blok Automatisering) mét handeling; dit blok is het compacte overzicht. Géén
// eigen endpoint: de tellers komen mee in `laatste_run.samenvatting.automatiseringen`. Uitgeschakeld = één
// regel "uit". Teal = actie, groen = status; de client formatteert alleen.
import { Badge } from '../ui/basis'
import { REDEN_LABEL, STAND_LABEL, type AutomatiseringenDto, type AutomatiseringTellerDto } from './reconciliatieApi'

function redenTekst(t: AutomatiseringTellerDto): string {
  const delen = Object.entries(t.dag.overgeslagen)
    .filter(([k, n]) => n > 0 || k === 'geen_eigenaar')
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([k, n]) => `${REDEN_LABEL[k] ?? k.replace(/_/g, ' ')}: ${n}`)
  return delen.join(', ')
}

function overgeslagenTotaal(t: AutomatiseringTellerDto): number {
  return Object.values(t.dag.overgeslagen).reduce((s, n) => s + n, 0)
}

export function AutomatiseringenBlok({ data }: { data: AutomatiseringenDto | null | undefined }) {
  if (!data || data.tellers.length === 0) return null
  const letOp = data.tellers.filter((t) => t.stil || t.harde_voorwaarden.length > 0).length
  return (
    <details
      data-testid="automatiseringen-blok"
      open={letOp > 0}
      style={{ margin: 0, padding: '8px 18px', borderBottom: '1px solid var(--border)' }}
    >
      <summary style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5 }}>
        <strong>Automatiseringen (laatste {data.venster_uren} u)</strong>
        <span className="hint" style={{ margin: 0 }}>
          verwacht / gedaan / overgeslagen mét reden — vangnet, geen poort
        </span>
        {letOp > 0 && (
          <Badge variant="warn" data-testid="automatiseringen-let-op">
            {letOp} let-op
          </Badge>
        )}
      </summary>
      <div className="tabel-scroll" style={{ marginTop: 6 }}>
        <table data-testid="automatiseringen-tabel" style={{ fontSize: 12 }}>
          <thead>
            <tr>
              <th>Automatisering</th>
              <th style={{ width: 110 }}>Stand</th>
              <th style={{ width: 80, textAlign: 'right' }}>Verwacht</th>
              <th style={{ width: 70, textAlign: 'right' }}>Gedaan</th>
              <th>Overgeslagen (reden)</th>
              <th style={{ width: 120, textAlign: 'right' }}>{data.stil_dagen} dagen</th>
            </tr>
          </thead>
          <tbody>
            {data.tellers.map((t) => {
              const uit = t.stand === 'uit'
              return (
                <tr key={t.sleutel} data-testid={`automatisering-${t.sleutel}`} className={uit ? 'hint' : undefined}>
                  <td>
                    {t.label}
                    {t.stil && (
                      <>
                        {' '}
                        <Badge variant="warn">stil</Badge>
                      </>
                    )}
                    {t.harde_voorwaarden.length > 0 && (
                      <>
                        {' '}
                        <Badge variant="warn" data-testid="chip-harde-voorwaarde">
                          wacht op voorwaarde
                        </Badge>
                      </>
                    )}
                  </td>
                  <td title={t.stand_detail ?? undefined}>
                    {STAND_LABEL[t.stand]}
                    {t.stand_detail && (t.stand === 'deels' || uit) ? (
                      <span className="hint" style={{ margin: 0 }}>
                        {' '}
                        ({t.stand_detail})
                      </span>
                    ) : null}
                  </td>
                  {uit ? (
                    <td colSpan={4} className="hint">
                      uitgeschakeld — geen bevinding
                    </td>
                  ) : (
                    <>
                      <td style={{ textAlign: 'right' }}>{t.dag.verwacht}</td>
                      <td style={{ textAlign: 'right' }}>{t.dag.gedaan}</td>
                      <td>
                        {overgeslagenTotaal(t)}
                        {redenTekst(t) ? <span className="hint" style={{ margin: 0 }}> ({redenTekst(t)})</span> : null}
                      </td>
                      <td style={{ textAlign: 'right' }} className="hint">
                        {t.week.gedaan} / {t.week.verwacht}
                      </td>
                    </>
                  )}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </details>
  )
}
