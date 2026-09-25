import { useEffect, useState } from 'react'
import { apiJson, ApiError } from '../api/client'

/** FV-01 (feedbackrun A 25-09): de leesbare UBL-kaart voor een XML-document zonder PDF-beeld — het antwoord van
 * `GET /administraties/{id}/documenten/{doc}/ubl-samenvatting` (backend `documenten/ubl_samenvatting.py`, dezelfde
 * deterministische parser als de intake; geen AI). `leesbaar=false` + `reden` = dezelfde tekst als de tijdlijn-detail
 * `ubl_parse_fout`. */
export interface UblSamenvattingDocumentDto {
  leesbaar: boolean
  reden?: string | null
  bestandsnaam?: string | null
  is_creditnota?: boolean
  leverancier?: string | null
  afnemer?: string | null
  factuurnummer?: string | null
  factuurdatum?: string | null
  vervaldatum?: string | null
  valuta?: string | null
  totaal_excl?: string | null
  totaal_btw?: string | null
  totaal_incl?: string | null
  kvk_nummer?: string | null
  btw_nummer?: string | null
  iban?: string | null
  leverancier_adres?: string | null
  betalingskenmerk?: string | null
  note?: string | null
  project_tekst?: string | null
  regelaantal?: number
  regels?: Array<{
    volgnummer: number
    omschrijving?: string | null
    aantal?: string | null
    eenheid?: string | null
    netto_bedrag?: string | null
    btw_percentage?: string | null
    btw_bedrag?: string | null
    soort?: string | null
  }>
  onvolledig?: string | null
}

function euro(waarde: string | null | undefined, valuta?: string | null): string {
  if (waarde === null || waarde === undefined || waarde === '') return '—'
  const getal = Number(waarde)
  if (!Number.isFinite(getal)) return waarde
  const bedrag = new Intl.NumberFormat('nl-NL', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(getal)
  return `${valuta && valuta !== 'EUR' ? `${valuta} ` : '€ '}${bedrag}`
}

function datum(waarde: string | null | undefined): string {
  if (!waarde) return '—'
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(waarde)
  return m ? `${m[3]}-${m[2]}-${m[1]}` : waarde
}

function percentage(waarde: string | null | undefined): string {
  if (waarde === null || waarde === undefined || waarde === '') return '—'
  const getal = Number(waarde)
  return Number.isFinite(getal) ? `${getal.toLocaleString('nl-NL', { maximumFractionDigits: 2 })} %` : waarde
}

/**
 * Bijlage-paneel voor een UBL-document ZONDER beeld (FV-01, 25-09): tot 25-09 stond hier de ruwe XML als `<pre>` —
 * "een blok code" voor de controleur (casus Universal Nederland RLZ-2080142898 → Universal Steigerbouw). Nu: de
 * leesbare kaart (kop, crediteur-identiteit, totalen, regels); de XML-bron staat alleen nog achter de tekstknop
 * "XML-bron tonen" (`linkbtn`, nooit standaard open). Een niet-leesbare XML = de reden als chip, nooit een kale fout;
 * het bijlage-paneel spreekt dan hetzelfde als de tijdlijn (`ubl_parse_fout`).
 */
export function UblSamenvattingKaart({
  administratieId,
  documentId,
  xmlTekst,
  bestandsnaam,
}: {
  administratieId: string
  documentId: string
  /** De geformatteerde XML-bron (uit `/bestand`), alleen zichtbaar ná "XML-bron tonen". */
  xmlTekst: string | null
  bestandsnaam: string
}) {
  const [kaart, setKaart] = useState<UblSamenvattingDocumentDto | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [toonBron, setToonBron] = useState(false)

  useEffect(() => {
    let actief = true
    setKaart(null)
    setFout(null)
    apiJson<UblSamenvattingDocumentDto>(`/administraties/${administratieId}/documenten/${documentId}/ubl-samenvatting`)
      .then((dto) => {
        if (actief) setKaart(dto)
      })
      .catch((err: unknown) => {
        if (actief) setFout(err instanceof ApiError ? err.message : 'UBL-samenvatting kon niet worden geladen.')
      })
    return () => {
      actief = false
    }
  }, [administratieId, documentId])

  const bronKnop = xmlTekst !== null && (
    <p style={{ marginTop: 10 }}>
      <button type="button" className="linkbtn" onClick={() => setToonBron((v) => !v)} data-testid="xml-bron-toggle">
        {toonBron ? 'XML-bron verbergen' : 'XML-bron tonen'}
      </button>
    </p>
  )
  const bron = toonBron && xmlTekst !== null && (
    <pre className="xml-bron" data-testid="xml-bron">
      {xmlTekst}
    </pre>
  )

  if (fout) {
    return (
      <div className="ubl-kaart" data-testid="ubl-kaart">
        <div className="fout">{fout}</div>
        {bronKnop}
        {bron}
      </div>
    )
  }
  if (!kaart) {
    return (
      <div className="ubl-kaart" data-testid="ubl-kaart">
        <p className="hint">UBL wordt gelezen…</p>
      </div>
    )
  }
  if (!kaart.leesbaar) {
    return (
      <div className="ubl-kaart" data-testid="ubl-kaart">
        <p>
          <span className="chip blokkerend" data-testid="xml-niet-leesbaar-chip">
            XML niet leesbaar: {kaart.reden ?? 'onbekende reden'}
          </span>
        </p>
        <p className="hint" style={{ marginTop: 6 }}>
          Dit bestand ({bestandsnaam}) is geen leesbare UBL-factuur. Vul het boekingsvoorstel handmatig in, of vraag de
          leverancier om een geldige UBL of de factuur-PDF.
        </p>
        {bronKnop}
        {bron}
      </div>
    )
  }

  const regels = kaart.regels ?? []
  return (
    <div className="ubl-kaart" data-testid="ubl-kaart">
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
        <span className="chip ok">uit UBL — deterministisch gelezen</span>
        {kaart.is_creditnota && <span className="chip afwijking">creditnota</span>}
        {kaart.onvolledig && (
          <span className="chip blokkerend" data-testid="xml-niet-leesbaar-chip">
            XML niet leesbaar: {kaart.onvolledig}
          </span>
        )}
      </div>
      <dl className="ubl-kaart-velden">
        <dt>Leverancier</dt>
        <dd>
          {kaart.leverancier ?? '—'}
          {kaart.leverancier_adres ? <span className="hint"> · {kaart.leverancier_adres}</span> : null}
        </dd>
        <dt>Afnemer</dt>
        <dd>{kaart.afnemer ?? '—'}</dd>
        <dt>Factuurnummer</dt>
        <dd>{kaart.factuurnummer ?? '—'}</dd>
        <dt>Factuurdatum</dt>
        <dd>
          {datum(kaart.factuurdatum)}
          {kaart.vervaldatum ? <span className="hint"> · vervalt {datum(kaart.vervaldatum)}</span> : null}
        </dd>
        <dt>Totaal</dt>
        <dd>
          {euro(kaart.totaal_excl, kaart.valuta)} excl. · {euro(kaart.totaal_btw, kaart.valuta)} btw ·{' '}
          <b>{euro(kaart.totaal_incl, kaart.valuta)} incl.</b>
        </dd>
        {(kaart.kvk_nummer || kaart.btw_nummer || kaart.iban) && (
          <>
            <dt>Identiteit</dt>
            <dd>
              {[
                kaart.kvk_nummer ? `KvK ${kaart.kvk_nummer}` : null,
                kaart.btw_nummer ? `btw ${kaart.btw_nummer}` : null,
                kaart.iban ? `IBAN ${kaart.iban}` : null,
              ]
                .filter(Boolean)
                .join(' · ')}
            </dd>
          </>
        )}
        {kaart.betalingskenmerk && (
          <>
            <dt>Betalingskenmerk</dt>
            <dd>{kaart.betalingskenmerk}</dd>
          </>
        )}
        {kaart.note && (
          <>
            <dt>Opmerking</dt>
            <dd>
              {kaart.note}
              {kaart.project_tekst ? <span className="chip ok" style={{ marginLeft: 6 }}>project uit factuur</span> : null}
            </dd>
          </>
        )}
      </dl>
      <div className="tabel-scroll">
        <table className="ubl-kaart-regels" data-testid="ubl-kaart-regels">
          <thead>
            <tr>
              <th>#</th>
              <th>Omschrijving</th>
              <th style={{ textAlign: 'right' }}>Aantal</th>
              <th style={{ textAlign: 'right' }}>Netto</th>
              <th style={{ textAlign: 'right' }}>Btw</th>
            </tr>
          </thead>
          <tbody>
            {regels.length === 0 && (
              <tr>
                <td colSpan={5} className="hint">
                  Geen factuurregels in de UBL.
                </td>
              </tr>
            )}
            {regels.map((r) => (
              <tr key={r.volgnummer}>
                <td>{r.volgnummer}</td>
                <td>
                  {r.omschrijving ?? '—'}
                  {r.soort ? <span className="chip" style={{ marginLeft: 6 }}>{r.soort}</span> : null}
                </td>
                <td style={{ textAlign: 'right' }}>
                  {r.aantal ?? '—'}
                  {r.eenheid ? ` ${r.eenheid}` : ''}
                </td>
                <td style={{ textAlign: 'right' }}>{euro(r.netto_bedrag, kaart.valuta)}</td>
                <td style={{ textAlign: 'right' }}>
                  {percentage(r.btw_percentage)}
                  {r.btw_bedrag ? <span className="hint"> ({euro(r.btw_bedrag, kaart.valuta)})</span> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {bronKnop}
      {bron}
    </div>
  )
}
