// Blok "Automatiseringen" (herstelrun 07-09 blok C, "geen stille no-op"; VERHUISD 08-09 blok 5 — feedback Peter
// "wat moet ik hiermee"): dit blok stond op Inzicht › Reconciliatie (werkscherm) en staat sinds 08-09 op
// Instellingen › Boeken platformbreed (Beheerder). Per automatisering: stand (aan/deels), verwacht / gedaan /
// overgeslagen mét reden, en de LET-OP-markering (ontbrekende harde voorwaarde of zeven dagen stil) mét de
// handeling "Naar de instelling →" op de rij. Standaard ingeklapt tot één regel ("9 aan · 1 let-op"); automatisch
// open alleen bij een LET-OP. Uitgeschakelde automatiseringen worden NIET getoond (besluit Peter 08-09) en tellen
// niet mee in de één-regel-samenvatting. Géén eigen endpoint: de tellers komen mee in
// `laatste_run.samenvatting.automatiseringen` (GET /reconciliatie/run/laatste, kantoorrol). Sleutel-agnostisch:
// een onbekende automatisering/reden/stand toont de sleutel als label — nooit een crash (blok 1 voegt `bank_sync` toe).
// Teal = actie, groen = status; de client formatteert alleen.
import { useEffect, useState, type ReactElement } from 'react'
import { Link } from 'react-router-dom'
import { Badge } from '../ui/basis'
import {
  doelPadVoorVoorwaarde,
  haalLaatsteRun,
  REDEN_LABEL,
  STAND_LABEL,
  type AutomatiseringenDto,
  type AutomatiseringTellerDto,
  type ReconciliatieRunDto,
} from './reconciliatieApi'

function redenLabel(sleutel: string): string {
  return REDEN_LABEL[sleutel] ?? sleutel.replace(/_/g, ' ')
}

function standLabel(stand: string): string {
  return (STAND_LABEL as Record<string, string>)[stand] ?? stand.replace(/_/g, ' ')
}

function redenTekst(t: AutomatiseringTellerDto): string {
  const delen = Object.entries(t.dag.overgeslagen)
    .filter(([k, n]) => n > 0 || k === 'geen_eigenaar')
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([k, n]) => `${redenLabel(k)}: ${n}`)
  return delen.join(', ')
}

/** Blok A bundel 10-09: extra standen uit `detail` (additief, sleutel-agnostisch) — alleen getallen mét een bekend label
 * worden getoond ("lerend 4 · actief 2 · uitgezonderd 1 · vandaag geactiveerd 1"); onbekende sleutels en niet-getallen
 * worden overgeslagen, nooit een crash. */
const DETAIL_LABEL: Record<string, string> = {
  lerend: 'lerend',
  actief: 'actief',
  uitgezonderd: 'uitgezonderd',
  geactiveerd_24u: 'vandaag geactiveerd',
  automatisch_geboekt_24u: 'vandaag automatisch geboekt',
}

export function detailTekst(detail: Record<string, unknown> | null | undefined): string | null {
  if (!detail) return null
  const delen = Object.entries(DETAIL_LABEL)
    .filter(([k]) => typeof detail[k] === 'number')
    .map(([k, label]) => `${label} ${String(detail[k])}`)
  return delen.length > 0 ? delen.join(' · ') : null
}

function overgeslagenTotaal(t: AutomatiseringTellerDto): number {
  return Object.values(t.dag.overgeslagen).reduce((s, n) => s + n, 0)
}

/** LET-OP = een ontbrekende harde voorwaarde in het etmaal óf zeven dagen stil — precies de gevallen waarvoor
 * de run ook een bevinding (blok Automatisering) mét deeplink aanmaakt. */
export function isLetOp(t: AutomatiseringTellerDto): boolean {
  return t.stil || t.harde_voorwaarden.length > 0
}

/** Getoond = niet uit, óf uit mét LET-OP (07-09-uitzondering: noodrem UIT + gesignaleerde duplicaten in het etmaal) —
 * een signaal mét handeling verdwijnt nooit achter "uit-regels niet tonen". */
export function isZichtbaar(t: AutomatiseringTellerDto): boolean {
  return t.stand !== 'uit' || isLetOp(t)
}

/** Eén-regel-samenvatting ("9 aan · 1 let-op"): aan = niet uit; let-op over álle tellers (ook een uit-teller mét LET-OP). */
export function samenvattingTekst(tellers: readonly AutomatiseringTellerDto[]): string {
  const aan = tellers.filter((t) => t.stand !== 'uit').length
  const letOp = tellers.filter(isLetOp).length
  return `${aan} aan · ${letOp} let-op`
}

function naarInstelling(t: AutomatiseringTellerDto) {
  // Handeling op de rij: de instelling waar de harde voorwaarde hersteld wordt (spiegel van DOEL_PAD in de
  // backend); bij "stil" de autoboek-instellingen of, voor een onbekend pad, de bevinding op Inzicht › Reconciliatie.
  const hv = t.harde_voorwaarden[0]
  const pad = hv
    ? doelPadVoorVoorwaarde(hv.categorie, hv.administratie_id)
    : t.sleutel.startsWith('autoboek')
      ? '/instellingen/autoboeken'
      : '/reconciliatie?soort=let_op'
  return (
    <Link to={pad} className="linkbtn" aria-label={`Naar de instelling van ${t.label}`} data-testid="automatisering-actie">
      Naar de instelling →
    </Link>
  )
}

export function AutomatiseringenBlok({ data }: { data: AutomatiseringenDto | null | undefined }) {
  if (!data || data.tellers.length === 0) return null
  const zichtbaar = data.tellers.filter(isZichtbaar)
  const letOp = data.tellers.filter(isLetOp).length
  return (
    <details data-testid="automatiseringen-blok" open={letOp > 0} style={{ margin: 0 }}>
      <summary style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0, display: 'inline' }}>Automatiseringen</h2>
        <span data-testid="automatiseringen-samenvatting" style={{ fontSize: 12.5 }}>
          {samenvattingTekst(data.tellers)}
        </span>
        {letOp > 0 && (
          <Badge variant="warn" data-testid="automatiseringen-let-op">
            {letOp} let-op
          </Badge>
        )}
        <span className="hint" style={{ margin: 0 }}>
          laatste {data.venster_uren} u · verwacht / gedaan / overgeslagen mét reden — vangnet, geen poort
        </span>
      </summary>
      {zichtbaar.length === 0 ? (
        <p className="hint" style={{ marginTop: 6, marginBottom: 0 }} data-testid="automatiseringen-leeg">
          Alle automatiseringen staan uit.
        </p>
      ) : (
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
                <th style={{ width: 150 }} />
              </tr>
            </thead>
            <tbody>
              {zichtbaar.map((t) => (
                <tr key={t.sleutel} data-testid={`automatisering-${t.sleutel}`}>
                  <td>
                    {t.label || t.sleutel}
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
                    {standLabel(t.stand)}
                    {t.stand_detail && (t.stand === 'deels' || t.stand === 'uit') ? (
                      <span className="hint" style={{ margin: 0 }}>
                        {' '}
                        ({t.stand_detail})
                      </span>
                    ) : null}
                    {detailTekst(t.detail) ? (
                      <div className="hint" style={{ margin: 0 }} data-testid={`automatisering-detail-${t.sleutel}`}>
                        {detailTekst(t.detail)}
                      </div>
                    ) : null}
                  </td>
                  <td style={{ textAlign: 'right' }}>{t.dag.verwacht}</td>
                  <td style={{ textAlign: 'right' }}>{t.dag.gedaan}</td>
                  <td>
                    {overgeslagenTotaal(t)}
                    {redenTekst(t) ? <span className="hint" style={{ margin: 0 }}> ({redenTekst(t)})</span> : null}
                  </td>
                  <td style={{ textAlign: 'right' }} className="hint">
                    {t.week.gedaan} / {t.week.verwacht}
                  </td>
                  <td className="acties" style={{ whiteSpace: 'nowrap', textAlign: 'right' }}>
                    {isLetOp(t) ? naarInstelling(t) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </details>
  )
}

/** Instellingen › Boeken platformbreed: het blok laadt zelf de laatste run (kantoorrol-endpoint; de pagina is
 * Beheerder-only). Best-effort: een fout hier blokkeert de noodstop-schakelaars niet — dan één hint-regel. */
export function AutomatiseringenInstellingenBlok() {
  const [run, setRun] = useState<ReconciliatieRunDto | null | undefined>(undefined)
  const [fout, setFout] = useState<string | null>(null)
  useEffect(() => {
    let actueel = true
    haalLaatsteRun()
      .then((r) => {
        if (actueel) setRun(r)
      })
      .catch((err: unknown) => {
        if (actueel) setFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
    return () => {
      actueel = false
    }
  }, [])

  const data = run?.samenvatting?.automatiseringen
  let inhoud: ReactElement | null
  if (fout) {
    inhoud = (
      <p className="hint" style={{ margin: 0 }} data-testid="automatiseringen-fout">
        Automatiseringen: stand niet geladen ({fout}).
      </p>
    )
  } else if (run === undefined) {
    inhoud = null
  } else if (!data || data.tellers.length === 0) {
    inhoud = (
      <p className="hint" style={{ margin: 0 }} data-testid="automatiseringen-geen-run">
        Automatiseringen: {run && (run.status === 'bezig' || run.status === 'wachtend') ? 'reconciliatie bezig — tellers volgen.' : 'nog geen afgeronde reconciliatie-run met tellers.'}{' '}
        <Link to="/reconciliatie" className="linkbtn">
          Inzicht › Reconciliatie
        </Link>
      </p>
    )
  } else {
    inhoud = <AutomatiseringenBlok data={data} />
  }
  return (
    <div
      data-testid="automatiseringen-instellingen"
      style={{ marginTop: 18, paddingTop: 16, borderTop: '1px solid var(--border)' }}
    >
      {inhoud}
    </div>
  )
}
