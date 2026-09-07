// Projectdetail-verrijking (fixrun 07-09 blok C5): twee additieve panelen op het bestaande projectdetail.
// - "Verplichtingen": de goedgekeurde offertes/opdrachtbevestigingen van dit project mét de verbruiksbalk
//   (VerbruiksBalk = restant-balk-patroon, UX-PATRONEN; verbruik = uitsluitend GEBOEKTE facturen, ③) en de
//   deep-link naar het reviewscherm van de verplichting.
// - "Weekstaten & planning": stand per ISO-week (gepland / ingediend / gekeurd / ontbrekend) over de laatste
//   weken, mét de link naar de planning-agenda op die week. Signalering zonder handeling is niet af
//   (kernprincipe 7): een ontbrekende week linkt naar Inzicht › Weekstaten ontbreken, te keuren staten naar
//   het keuringsscherm. Presentatie only — alle cijfers komen kant-en-klaar van de server.
import { Link } from 'react-router-dom'
import { Badge } from '../ui/basis'
import { VerbruiksBalk } from '../verplichting/VerbruiksBalk'
import type { ProjectVerplichtingDto, WeekstatenStandDto } from './projectenApi'

const SOORT_LABEL: Record<string, string> = {
  offerte: 'offerte',
  prijsopgave: 'prijsopgave',
  opdrachtbevestiging: 'opdrachtbevestiging',
}

function ddmmyyyy(iso: string | null): string {
  if (!iso) return '—'
  return new Date(`${iso.slice(0, 10)}T12:00:00Z`).toLocaleDateString('nl-NL', { day: '2-digit', month: '2-digit', year: 'numeric' })
}

function statusBadge(status: string) {
  if (status === 'overschreden') return <Badge variant="danger">overschreden</Badge>
  if (status === 'vervallen') return <Badge variant="stil">vervallen</Badge>
  return <Badge variant="info">lopend</Badge>
}

export function VerplichtingenPaneel({
  administratieId,
  verplichtingen,
}: {
  administratieId: string
  verplichtingen: ProjectVerplichtingDto[]
}) {
  const lopend = verplichtingen.filter((v) => v.status !== 'vervallen')
  const overschreden = lopend.filter((v) => v.status === 'overschreden').length
  return (
    <div className="panel" data-testid="verplichtingen-paneel">
      <h2 style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        Verplichtingen
        {lopend.length > 0 && (
          <Badge variant={overschreden > 0 ? 'danger' : 'info'}>
            {overschreden > 0
              ? `${overschreden} overschreden`
              : `${lopend.length} ${lopend.length === 1 ? 'lopende offerte' : 'lopende offertes'}`}
          </Badge>
        )}
      </h2>
      {verplichtingen.length === 0 ? (
        <p className="hint" style={{ margin: 0 }} data-testid="verplichtingen-leeg">
          Geen goedgekeurde offerte of opdrachtbevestiging op dit project. Een offerte die de klant accordeert,
          verschijnt hier automatisch mét het verbruik van de geboekte facturen.{' '}
          <Link to="/verplichtingen" className="text-primary">
            Alle verplichtingen →
          </Link>
        </p>
      ) : (
        <div className="tabel-scroll">
          <table>
            <thead>
              <tr>
                <th>Offerte</th>
                <th>Leverancier</th>
                <th style={{ minWidth: 260 }}>Verbruik (geboekt)</th>
                <th>Geldig tot</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {verplichtingen.map((v) => (
                <tr key={v.document_id} data-testid="verplichting-rij" style={v.status === 'vervallen' ? { opacity: 0.65 } : undefined}>
                  <td>
                    <b>{v.offertenummer ?? 'zonder nummer'}</b>
                    <div className="hint" style={{ margin: '2px 0 0', fontSize: 11.5 }}>
                      {SOORT_LABEL[v.soort_label ?? ''] ?? 'verplichting'}
                      {v.omschrijving ? ` · ${v.omschrijving}` : ''}
                    </div>
                  </td>
                  <td>{v.leverancier_naam ?? '—'}</td>
                  <td>
                    {v.goedgekeurd_excl === null ? (
                      <span className="hint">zonder goedgekeurd bedrag</span>
                    ) : (
                      <VerbruiksBalk
                        verbruikt={v.verbruikt_excl}
                        totaal={v.goedgekeurd_excl}
                        percentage={v.percentage}
                        over={v.over_excl}
                        openFacturen={{ aantal: v.open_facturen_aantal, bedrag: v.open_facturen_excl }}
                        testId={`verbruiks-balk-${v.document_id}`}
                      />
                    )}
                  </td>
                  <td>{ddmmyyyy(v.geldig_tot)}</td>
                  <td>{statusBadge(v.status)}</td>
                  <td className="acties" style={{ whiteSpace: 'nowrap', textAlign: 'right' }}>
                    <Link
                      to={`/verplichting/${administratieId}/${v.document_id}`}
                      className="btn secondary"
                      aria-label={`Open verplichting ${v.offertenummer ?? v.document_id}`}
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
    </div>
  )
}

export function WeekstatenPaneel({
  administratieId,
  stand,
}: {
  administratieId: string
  stand: WeekstatenStandDto | null | undefined
}) {
  if (!stand || !stand.van_toepassing) {
    return null // administratie zonder uren-&-meerwerk-opt-in: het paneel is niet van toepassing
  }
  const planningLink = (jaar: number, week: number) => `/planning?administratie=${administratieId}&week=${jaar}-W${week}`
  return (
    <div className="panel" data-testid="weekstaten-paneel">
      <h2 style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        Weekstaten &amp; planning
        {stand.ontbrekend_totaal > 0 ? (
          <Badge variant="danger" data-testid="weekstaten-ontbrekend">
            wk {stand.oudste_ontbrekende_week} ontbreekt{stand.ontbrekend_totaal > 1 ? ` (+${stand.ontbrekend_totaal - 1})` : ''}
          </Badge>
        ) : (
          <Badge variant="ok">bij</Badge>
        )}
        {stand.te_keuren_totaal > 0 && (
          <Badge variant="warn" data-testid="weekstaten-te-keuren">
            {stand.te_keuren_totaal} te keuren
          </Badge>
        )}
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 8, fontSize: 12.5, fontWeight: 400 }}>
          {stand.ontbrekend_totaal > 0 && (
            <Link to={`/meerwerk/planning-signalen?administratie_id=${administratieId}`} className="text-primary">
              Herinneren of afmelden →
            </Link>
          )}
          {stand.te_keuren_totaal > 0 && (
            <Link to={`/meerwerk?administratie=${administratieId}`} className="text-primary">
              Keuren →
            </Link>
          )}
          <Link to={`/planning?administratie=${administratieId}`} className="text-primary">
            Planning →
          </Link>
        </span>
      </h2>
      <div className="tabel-scroll">
        <table data-testid="weekstaten-tabel">
          <thead>
            <tr>
              <th>Week</th>
              <th>Gepland</th>
              <th>Ingediend</th>
              <th>Gekeurd</th>
              <th>Ontbreekt</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {stand.weken.map((w) => {
              const leeg = w.gepland_personen === 0 && w.concept + w.ingediend + w.goedgekeurd + w.corrigeren === 0
              return (
                <tr key={`${w.jaar}-${w.weeknummer}`} data-testid="weekstand-rij" style={leeg ? { opacity: 0.65 } : undefined}>
                  <td>
                    <b>wk {w.weeknummer}</b>
                    <span className="hint" style={{ marginLeft: 6, fontSize: 11.5 }}>
                      {ddmmyyyy(w.maandag)}
                    </span>
                  </td>
                  <td>
                    {w.gepland_personen === 0
                      ? '—'
                      : `${w.gepland_personen} ${w.gepland_personen === 1 ? 'persoon' : 'personen'} · ${Number(w.gepland_dagen).toLocaleString('nl-NL')} ${Number(w.gepland_dagen) === 1 ? 'dag' : 'dagen'}`}
                  </td>
                  <td>
                    {w.ingediend > 0 ? <Badge variant="warn">{w.ingediend} te keuren</Badge> : w.concept > 0 || w.corrigeren > 0 ? (
                      <span className="hint">
                        {w.concept > 0 ? `${w.concept} concept` : ''}
                        {w.concept > 0 && w.corrigeren > 0 ? ' · ' : ''}
                        {w.corrigeren > 0 ? `${w.corrigeren} corrigeren` : ''}
                      </span>
                    ) : (
                      '—'
                    )}
                  </td>
                  <td>{w.goedgekeurd > 0 ? <Badge variant="ok">{w.goedgekeurd} gekeurd</Badge> : '—'}</td>
                  <td>
                    {w.ontbrekend > 0 ? (
                      <Badge variant="danger">{w.ontbrekend} ontbreekt</Badge>
                    ) : w.afgemeld > 0 ? (
                      <span className="hint">{w.afgemeld} afgemeld</span>
                    ) : (
                      '—'
                    )}
                  </td>
                  <td className="acties" style={{ whiteSpace: 'nowrap', textAlign: 'right' }}>
                    <Link to={planningLink(w.jaar, w.weeknummer)} className="linkbtn" aria-label={`Planning week ${w.weeknummer}`}>
                      Planning wk {w.weeknummer} →
                    </Link>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
