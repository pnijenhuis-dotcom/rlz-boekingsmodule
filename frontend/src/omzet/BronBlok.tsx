import type { OmzetBronDetailDto } from '../api/types'

const BRON_NAMEN: Record<string, string> = {
  zonnestudio_dagstaat: 'dagstaat zonnestudio (POS-rapport + kascheck)',
  zonnestudio_kascheck: 'kascheck zonnestudio',
  pilates_betalingsexport: 'betalingsexport pilates (één uitbetaling)',
}

export function bronNaam(bron: string): string {
  return BRON_NAMEN[bron] ?? bron
}

function euro(bedrag: string | null | undefined): string {
  if (bedrag === null || bedrag === undefined || bedrag === '') return '—'
  const n = Number(bedrag)
  if (Number.isNaN(n)) return bedrag
  return n.toLocaleString('nl-NL', { style: 'currency', currency: 'EUR' })
}

/** Omzetbronnen (Peter 15-09): wat de parser uit de spreadsheet las en welke harde controles daarop staan. Puur
 * weergave — de bedragen komen uit code (parser), nooit uit AI; de controles reizen óók als check-rijen mee in de harde
 * checks, hier staan ze leesbaar bij elkaar. */
export function BronBlok({ bron, detail }: { bron: string; detail: OmzetBronDetailDto | null | undefined }) {
  const d = detail ?? {}
  const controles = d.controles ?? []
  const rood = controles.filter((c) => !c.ok && c.blokkerend)
  const oranje = controles.filter((c) => !c.ok && !c.blokkerend)
  const betaalwijzen = Object.entries(d.betaalwijzen ?? {})
  return (
    <div className="panel bronblok" data-testid="bronblok">
      <h2>
        Bron: {bronNaam(bron)}{' '}
        {d.wacht_op ? (
          <span className="chip vraag">wacht op {d.wacht_op}</span>
        ) : rood.length > 0 ? (
          <span className="chip blokkerend">
            {rood.length} blokkerende controle{rood.length === 1 ? '' : 's'}
          </span>
        ) : oranje.length > 0 ? (
          <span className="chip afwijking">
            {oranje.length} signa{oranje.length === 1 ? 'al' : 'len'}
          </span>
        ) : (
          <span className="chip ok">sluit</span>
        )}
      </h2>
      {(d.store || d.datum || d.batch_id) && (
        <p className="hint">
          {d.store ? `Store ${d.store}` : null}
          {d.store && d.datum ? ' · ' : null}
          {d.datum ? `dag ${d.datum}` : null}
          {d.batch_id ? `Uitbetaling ${d.batch_id}` : null}
          {d.batch_id && d.uitbetaaldatum ? ` · uitbetaald ${d.uitbetaaldatum}` : null}
        </p>
      )}
      {betaalwijzen.length > 0 && (
        <table className="tabel compact" aria-label="Betaalwijzen">
          <tbody>
            {betaalwijzen.map(([naam, bedrag]) => (
              <tr key={naam}>
                <td>{naam}</td>
                <td style={{ textAlign: 'right' }}>{euro(bedrag)}</td>
              </tr>
            ))}
            {d.grand_total?.bruto && (
              <tr>
                <td>
                  <b>Grand Total (incl. btw)</b>
                </td>
                <td style={{ textAlign: 'right' }}>
                  <b>{euro(d.grand_total.bruto)}</b>
                </td>
              </tr>
            )}
            {d.points_redeemed && Number(d.points_redeemed) > 0 && (
              <tr>
                <td>Points Redeemed (punten, waarde onbekend)</td>
                <td style={{ textAlign: 'right' }}>{d.points_redeemed}</td>
              </tr>
            )}
          </tbody>
        </table>
      )}
      {d.kas && (
        <table className="tabel compact" aria-label="Kascheck">
          <tbody>
            <tr>
              <td>Beginsaldo kas</td>
              <td style={{ textAlign: 'right' }}>{euro(d.kas.beginsaldo)}</td>
            </tr>
            <tr>
              <td>Telling</td>
              <td style={{ textAlign: 'right' }}>{euro(d.kas.telling)}</td>
            </tr>
            <tr>
              <td>Storting</td>
              <td style={{ textAlign: 'right' }}>{euro(d.kas.storting)}</td>
            </tr>
            <tr>
              <td>Eindsaldo ná storting</td>
              <td style={{ textAlign: 'right' }}>{euro(d.kas.eindsaldo_na_storting)}</td>
            </tr>
            <tr>
              <td>
                <b>Contante omzet volgens kascheck</b>
              </td>
              <td style={{ textAlign: 'right' }}>
                <b>{euro(d.kas.contante_omzet)}</b>
              </td>
            </tr>
          </tbody>
        </table>
      )}
      {d.batch_id && (
        <table className="tabel compact" aria-label="Uitbetaling">
          <tbody>
            <tr>
              <td>Bruto ontvangen</td>
              <td style={{ textAlign: 'right' }}>{euro(d.bruto)}</td>
            </tr>
            <tr>
              <td>Transactiekosten PSP</td>
              <td style={{ textAlign: 'right' }}>− {euro(d.kosten)}</td>
            </tr>
            <tr>
              <td>
                <b>Netto uitbetaald</b>
              </td>
              <td style={{ textAlign: 'right' }}>
                <b>{euro(d.netto)}</b>
              </td>
            </tr>
          </tbody>
        </table>
      )}
      {(d.disputes?.length ?? 0) > 0 && (
        <p className="hint">
          Disputes/terugboekingen in deze uitbetaling:{' '}
          {d.disputes!.map((x) => `${x.factuurnummer} (${euro(x.bedrag)})`).join(', ')} — als negatieve omzet meegenomen.
        </p>
      )}
      {controles.length > 0 && (
        <ul className="controle-lijst">
          {controles.map((c) => (
            <li key={c.naam}>
              <span className={`chip ${c.ok ? 'ok' : c.blokkerend ? 'blokkerend' : 'afwijking'}`}>
                {c.ok ? 'ok' : c.blokkerend ? 'blokkeert' : 'signaal'}
              </span>{' '}
              <b>{c.naam}</b>
              {c.detail ? <span className="hint"> — {c.detail}</span> : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
