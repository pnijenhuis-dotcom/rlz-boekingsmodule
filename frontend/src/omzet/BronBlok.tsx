import type { OmzetBronControleDto, OmzetBronDetailDto, OmzetBronTegenrekeningDto, OmzetCombiVerdelingDto } from '../api/types'
import type { ComboboxOptie } from '../document/SearchableCombobox'

const BRON_NAMEN: Record<string, string> = {
  zonnestudio_dagstaat: 'dagstaat zonnestudio (POS-rapport + kascheck)',
  zonnestudio_kascheck: 'kascheck zonnestudio',
  pilates_betalingsexport: 'betalingsexport pilates (één uitbetaling)',
  profx_journaal: 'ProfX Journaal (coffeeshop-kassa, per artikelgroep)',
  profx_margerapport: 'ProfX Margerapport (inkoopwaarde per artikelgroep)',
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

const BETAALWIJZE_LABELS: Record<string, string> = {
  pin: 'PIN',
  cash: 'Contant',
  stripe: 'Stripe/PSP',
  kasverschil: 'Kasverschil',
  storting: 'Storting automaat',
}

const HERKOMST_LABELS: Record<string, { tekst: string; klasse: string }> = {
  instelling: { tekst: 'ingesteld', klasse: 'handmatig' },
  mens: { tekst: 'ingesteld', klasse: 'handmatig' },
  default: { tekst: 'standaard (op naam)', klasse: 'geheugen' },
  standaard: { tekst: 'standaard (op naam)', klasse: 'geheugen' },
  naam: { tekst: 'standaard (op naam)', klasse: 'geheugen' },
  geen: { tekst: 'geen rekening — instellen', klasse: 'blokkerend' },
}

const RICHTING_LABELS: Record<string, string> = {
  ontvangst: 'bank moet ontvangen',
  kas: 'blijft in kas',
  signaal: 'signaal — nooit automatisch',
}

const COMBI_BASIS_LABELS: Record<string, { tekst: string; klasse: string }> = {
  batch: { tekst: 'netto-omzet batch', klasse: 'ok' },
  historie_30d: { tekst: 'laatste 30 dagen', klasse: 'ok' },
  laatste_30_dagen: { tekst: 'laatste 30 dagen', klasse: 'ok' },
  '50_50': { tekst: '50/50 — geen basis', klasse: 'afwijking' },
}

interface TegenRij {
  betaalwijze: string
  bedrag?: string | null
  ledger_id?: string | null
  code?: string | null
  naam?: string | null
  herkomst?: string | null
  richting?: string | null
  datum?: string | null
  venster_dagen?: number[]
}

/** Gebouwde vorm (X): `bron_detail.tegenzijde.regels[]`; contract-terugval: `tegenrekeningen` record óf lijst. */
export function tegenrekeningRijen(d: OmzetBronDetailDto): TegenRij[] {
  const regels = d.tegenzijde?.regels
  if (regels && regels.length > 0) return regels.map((r) => ({ ...r }))
  const x = d.tegenrekeningen
  if (!x) return []
  if (Array.isArray(x)) return x.map((rij: OmzetBronTegenrekeningDto, i) => ({ ...rij, betaalwijze: rij.betaalwijze ?? String(i) }))
  return Object.entries(x).map(([betaalwijze, rij]) => ({ ...(rij ?? {}), betaalwijze }))
}

/** Tegenrekening per betaalwijze (blok A 16-09): waar de Receipt-tegenzijde landt, mét herkomst-chip. De regel draagt
 * alleen het ledger_id — code · naam komen uit de gesyncte grootboek-opties van het scherm (`rekeningen`). */
function TegenrekeningenTabel({ rijen, rekeningen }: { rijen: TegenRij[]; rekeningen: ComboboxOptie[] }) {
  if (rijen.length === 0) return null
  const naamVoor = (rij: TegenRij): string => {
    if (!rij.ledger_id) return '—'
    const eigen = [rij.code, rij.naam].filter(Boolean).join(' · ')
    if (eigen) return eigen
    const o = rekeningen.find((r) => r.id === rij.ledger_id)
    return o ? [o.code, o.label].filter(Boolean).join(' · ') : rij.ledger_id
  }
  return (
    <table className="tabel compact" aria-label="Tegenrekeningen">
      <thead>
        <tr>
          <th>Betaalwijze</th>
          <th>Tegenrekening</th>
          <th>Herkomst</th>
          <th style={{ textAlign: 'right' }}>Bedrag</th>
        </tr>
      </thead>
      <tbody>
        {rijen.map((rij) => {
          const herkomst = HERKOMST_LABELS[rij.herkomst ?? ''] ?? (rij.ledger_id ? HERKOMST_LABELS.default : HERKOMST_LABELS.geen)
          const venster = rij.venster_dagen && rij.venster_dagen.some((x) => x !== 0) ? ` · bank +${rij.venster_dagen[0]}…+${rij.venster_dagen[1]} d` : ''
          return (
            <tr key={rij.betaalwijze}>
              <td>
                {BETAALWIJZE_LABELS[rij.betaalwijze] ?? rij.betaalwijze}
                {rij.richting && (
                  <div className="hint" style={{ marginTop: 0 }}>
                    {RICHTING_LABELS[rij.richting] ?? rij.richting}
                    {venster}
                  </div>
                )}
              </td>
              <td>{naamVoor(rij)}</td>
              <td>
                <span className={`chip ${herkomst.klasse}`}>{herkomst.tekst}</span>
              </td>
              <td style={{ textAlign: 'right' }}>{euro(rij.bedrag)}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

/** Verdeling als lijst, uit de gebouwde record-vorm (categorie → bedrag, `aandeel` apart) óf de contract-lijst. */
function combiRijen(combi: OmzetCombiVerdelingDto): { categorie: string; bedrag: string; aandeel: string | number | null }[] {
  const v = combi.verdeling
  if (!v) return []
  if (Array.isArray(v)) return v.map((x) => ({ categorie: x.categorie, bedrag: x.bedrag, aandeel: x.aandeel ?? null }))
  return Object.entries(v).map(([categorie, bedrag]) => ({ categorie, bedrag, aandeel: combi.aandeel?.[categorie] ?? null }))
}

/** Combi-verdeling (blok C 16-09): "combi Abonnement" pro rato over Pilates/Yoga — bedragen uit code, basis als chip. */
function CombiVerdeling({ combi }: { combi: OmzetCombiVerdelingDto | null | undefined }) {
  if (!combi) return null
  const rijen = combiRijen(combi)
  if (rijen.length === 0 && !combi.bedrag) return null
  const signaal = combi.signaal ?? combi.basis === '50_50'
  const basis = COMBI_BASIS_LABELS[combi.basis ?? ''] ?? { tekst: combi.basis_tekst ?? combi.basis ?? 'basis onbekend', klasse: signaal ? 'afwijking' : 'ok' }
  return (
    <div data-testid="combi-verdeling">
      <p className="hint" style={{ marginBottom: 4 }}>
        <b>Combi-abonnement {euro(combi.bedrag)}</b> pro rato verdeeld
        {combi.transacties ? ` (${combi.transacties} transactie${combi.transacties === 1 ? '' : 's'})` : ''} · basis{' '}
        <span className={`chip ${signaal ? 'afwijking' : basis.klasse}`}>{basis.tekst}</span>
        {combi.basis_tekst && COMBI_BASIS_LABELS[combi.basis ?? ''] ? ` — ${combi.basis_tekst}` : null}
      </p>
      {rijen.length > 0 && (
        <table className="tabel compact" aria-label="Combi-verdeling">
          <tbody>
            {rijen.map((v) => (
              <tr key={v.categorie}>
                <td>{v.categorie}</td>
                <td style={{ textAlign: 'right' }}>
                  {v.aandeel !== null && v.aandeel !== undefined ? `${Math.round(Number(v.aandeel) * 100)} % · ` : null}
                  {euro(v.bedrag)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

/** Omzetbronnen (Peter 15-09): wat de parser uit de spreadsheet las en welke harde controles daarop staan. Puur
 * weergave — de bedragen komen uit code (parser), nooit uit AI; de controles reizen óók als check-rijen mee in de harde
 * checks, hier staan ze leesbaar bij elkaar. */
export function BronBlok({
  bron,
  detail,
  rekeningen = [],
}: {
  bron: string
  detail: OmzetBronDetailDto | null | undefined
  /** Gesyncte grootboek-opties van het scherm — om ledger_id's van de tegenzijde als code · naam te tonen. */
  rekeningen?: ComboboxOptie[]
}) {
  const d = detail ?? {}
  // Parser-controles + de live tegenzijde-controles ("Tegenrekening PIN" …) in één lijst, op naam ontdubbeld.
  const controles: OmzetBronControleDto[] = [...(d.controles ?? [])]
  for (const c of d.tegenzijde?.controles ?? []) if (!controles.some((x) => x.naam === c.naam)) controles.push(c)
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
      <TegenrekeningenTabel rijen={tegenrekeningRijen(d)} rekeningen={rekeningen} />
      <CombiVerdeling combi={d.combi_verdeling} />
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
