import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError, apiFetch, apiJson } from '../api/client'
import type {
  CheckRapportDto,
  DocumentDetailDto,
  VerkoopBoekenResponseDto,
  VerkoopRegelDto,
  VerkoopVoorstelDto,
  VerkoopVoorstelInputDto,
} from '../api/types'
import { bedragAlsGetal, normaliseerBedrag } from '../document/bedrag'
import { formatteerXml } from '../document/DocumentDetailScreen'
import { SearchableCombobox } from '../document/SearchableCombobox'
import { useGrootboekOpties, useTaxrateOpties } from '../document/useSyncOpties'
import { DatePicker } from '../ui/DatePicker'
import { haalVerkoopVoorstelOp, slaVerkoopVoorstelOp, voerVerkoopChecksUit } from './verkoopApi'

/** Bewerkbare regel-staat: bedragen als tekst (NL-invoer toegestaan), keuzes als id's.
 * `gbCode` + `gbCodeStatus` reizen readonly mee (deterministisch uit de UBL gelezen, BT-133) —
 * de mens kiest de RLZ-rekening via de combobox, de UBL-code zelf wordt nooit bewerkt. */
interface RegelStaat {
  volgnummer: number
  omschrijving: string
  nettoBedrag: string
  btwBedrag: string
  gbCode: string | null
  ledgerId: string | null
  taxrateId: string | null
  gbCodeStatus: string
  herkomst: string
}

function naarRegelStaat(regel: VerkoopRegelDto): RegelStaat {
  return {
    volgnummer: regel.volgnummer,
    omschrijving: regel.omschrijving ?? '',
    nettoBedrag: regel.netto_bedrag ?? '',
    btwBedrag: regel.btw_bedrag ?? '',
    gbCode: regel.gb_code,
    ledgerId: regel.ledger_id,
    taxrateId: regel.taxrate_id,
    gbCodeStatus: regel.gb_code_status,
    herkomst: regel.herkomst,
  }
}

function formatBedrag(waarde: number): string {
  return waarde.toLocaleString('nl-NL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** Statussen waaruit de backend een boekpoging accepteert (documenten.boeken-poort) —
 * zelfde set als het omzetreview-scherm. */
const BOEKBARE_STATUSSEN = new Set(['te_controleren', 'klaar_om_te_boeken', 'boeken_mislukt', 'handmatig_afmaken'])

export function VerkoopReviewScreen() {
  const { administratieId, documentId } = useParams<{ administratieId: string; documentId: string }>()

  const [detail, setDetail] = useState<DocumentDetailDto | null>(null)
  const [voorstel, setVoorstel] = useState<VerkoopVoorstelDto | null>(null)
  const [laadFout, setLaadFout] = useState<string | null>(null)
  // Brondocument is UBL-XML — we tonen de geformatteerde brontekst (zelfde patroon als
  // DocumentDetailScreen); een niet-XML-bijlage valt terug op een downloadlink.
  const [xmlTekst, setXmlTekst] = useState<string | null>(null)
  const [bijlageUrl, setBijlageUrl] = useState<string | null>(null)

  const [debiteurNaam, setDebiteurNaam] = useState('')
  const [factuurnummer, setFactuurnummer] = useState('')
  const [factuurdatum, setFactuurdatum] = useState('')
  const [totaalIncl, setTotaalIncl] = useState('')
  const [regels, setRegels] = useState<RegelStaat[]>([])

  const [opslaanBezig, setOpslaanBezig] = useState(false)
  const [opslaanFout, setOpslaanFout] = useState<string | null>(null)
  const [checkRapport, setCheckRapport] = useState<CheckRapportDto | null>(null)
  const [controlerenBezig, setControlerenBezig] = useState(false)
  const [boekenBezig, setBoekenBezig] = useState(false)
  const [boekenFout, setBoekenFout] = useState<string | null>(null)
  const [boekResultaat, setBoekResultaat] = useState<VerkoopBoekenResponseDto | null>(null)
  // Elke wijziging maakt een eerder checkresultaat verouderd — zelfde patroon als het
  // controlescherm: het rapport blijft zichtbaar maar telt niet meer als groen licht.
  const [checksActueel, setChecksActueel] = useState(false)

  const grootboek = useGrootboekOpties(administratieId ?? '')
  const btwCodes = useTaxrateOpties(administratieId ?? '')

  const neemVoorstelOver = useCallback((data: VerkoopVoorstelDto) => {
    setVoorstel(data)
    setDebiteurNaam(data.debiteur_naam ?? '')
    setFactuurnummer(data.factuurnummer ?? '')
    setFactuurdatum(data.factuurdatum ?? '')
    setTotaalIncl(data.totaalbedrag_incl ?? '')
    setRegels(data.regels.map(naarRegelStaat))
  }, [])

  useEffect(() => {
    if (!administratieId || !documentId) return
    let actief = true
    Promise.all([
      apiJson<DocumentDetailDto>(`/administraties/${administratieId}/documenten/${documentId}`),
      haalVerkoopVoorstelOp(administratieId, documentId),
    ])
      .then(([documentDetail, voorstelData]) => {
        if (!actief) return
        setDetail(documentDetail)
        neemVoorstelOver(voorstelData)
      })
      .catch((err: unknown) => {
        if (actief) setLaadFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
    return () => {
      actief = false
    }
  }, [administratieId, documentId, neemVoorstelOver])

  useEffect(() => {
    if (!administratieId || !documentId) return
    let objectUrl: string | null = null
    let actief = true
    void apiFetch(`/administraties/${administratieId}/documenten/${documentId}/bestand`).then(async (resp) => {
      if (!resp.ok || !actief) return
      const blob = await resp.blob()
      const contentType = resp.headers.get('content-type') ?? 'application/octet-stream'
      objectUrl = URL.createObjectURL(blob)
      const tekst = contentType.includes('xml') ? formatteerXml(await blob.text()) : null
      if (actief) {
        setBijlageUrl(objectUrl)
        setXmlTekst(tekst)
      }
    })
    return () => {
      actief = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [administratieId, documentId])

  const nettoTotaal = useMemo(
    () => regels.reduce((som, regel) => som + (bedragAlsGetal(regel.nettoBedrag) ?? 0), 0),
    [regels],
  )
  const btwTotaal = useMemo(
    () => regels.reduce((som, regel) => som + (bedragAlsGetal(regel.btwBedrag) ?? 0), 0),
    [regels],
  )

  const wijzigRegel = (index: number, wijziging: Partial<RegelStaat>) => {
    setRegels((huidig) => huidig.map((regel, i) => (i === index ? { ...regel, ...wijziging } : regel)))
    setChecksActueel(false)
  }

  const bouwInvoer = (): VerkoopVoorstelInputDto => ({
    debiteur_naam: debiteurNaam || null,
    factuurnummer: factuurnummer || null,
    factuurdatum: factuurdatum || null,
    totaalbedrag_incl: totaalIncl ? normaliseerBedrag(totaalIncl) : null,
    regels: regels.map((regel) => ({
      omschrijving: regel.omschrijving || null,
      netto_bedrag: regel.nettoBedrag ? normaliseerBedrag(regel.nettoBedrag) : null,
      btw_bedrag: regel.btwBedrag ? normaliseerBedrag(regel.btwBedrag) : null,
      gb_code: regel.gbCode,
      ledger_id: regel.ledgerId,
      taxrate_id: regel.taxrateId,
    })),
  })

  const opslaan = async (): Promise<boolean> => {
    if (!administratieId || !documentId) return false
    setOpslaanBezig(true)
    setOpslaanFout(null)
    try {
      const data = await slaVerkoopVoorstelOp(administratieId, documentId, bouwInvoer())
      neemVoorstelOver(data)
      return true
    } catch (err) {
      setOpslaanFout(err instanceof ApiError ? err.message : 'Opslaan mislukt.')
      return false
    } finally {
      setOpslaanBezig(false)
    }
  }

  const controleren = async () => {
    if (!administratieId || !documentId) return
    setControlerenBezig(true)
    setOpslaanFout(null)
    try {
      // Checks gelden over wat er opgeslagen is — eerst opslaan, dan toetsen.
      if (!(await opslaan())) return
      const resultaat = await voerVerkoopChecksUit(administratieId, documentId)
      setCheckRapport(resultaat.checks)
      setChecksActueel(true)
    } catch (err) {
      setOpslaanFout(err instanceof ApiError ? err.message : 'Controleren mislukt.')
    } finally {
      setControlerenBezig(false)
    }
  }

  const boeken = async () => {
    if (!administratieId || !documentId) return
    setBoekenBezig(true)
    setBoekenFout(null)
    try {
      if (!(await opslaan())) return
      // Rauwe apiFetch (zelfde patroon als omzet/controlescherm): BoekenGeblokkeerdDoorChecks (409)
      // stuurt het verse CheckRapport mee in detail.checks — een object dat de generieke
      // apiJson/ApiError-afhandeling niet kan uitpakken.
      const resp = await apiFetch(`/administraties/${administratieId}/verkoop/documenten/${documentId}/boeken`, {
        method: 'POST',
      })
      const body: unknown = await resp.json().catch(() => null)
      if (resp.ok) {
        const resultaat = body as VerkoopBoekenResponseDto
        setBoekResultaat(resultaat)
        setDetail((huidig) => (huidig ? { ...huidig, status: resultaat.status } : huidig))
        return
      }
      const detailBody = body && typeof body === 'object' ? (body as { detail?: unknown }).detail : null
      if (resp.status === 409 && detailBody && typeof detailBody === 'object' && 'checks' in detailBody) {
        const { melding, checks } = detailBody as { melding?: string; checks: CheckRapportDto }
        setCheckRapport(checks)
        setChecksActueel(true)
        setBoekenFout(melding ?? 'Boeken geblokkeerd door harde checks — zie de checks hierboven.')
      } else {
        setBoekenFout(typeof detailBody === 'string' ? detailBody : resp.statusText || `Fout (${resp.status})`)
      }
    } catch (err) {
      setBoekenFout(err instanceof ApiError ? err.message : 'Boeken mislukt.')
    } finally {
      setBoekenBezig(false)
    }
  }

  if (laadFout) return <div className="fout">Kon verkoopfactuur niet laden: {laadFout}</div>
  if (!detail || !voorstel || !administratieId || !documentId) return <p className="hint">Laden…</p>

  const isGeboekt = detail.status === 'geboekt'
  const isVraagOpen = detail.status === 'vraag_open'
  const isBoekbaar = BOEKBARE_STATUSSEN.has(detail.status)
  const regelsZonderGb = regels.filter((r) => r.gbCodeStatus !== 'bekend')
  const checksGroen = checksActueel && checkRapport !== null && !checkRapport.geblokkeerd

  return (
    <div>
      <div className="topbar">
        <h1>
          <Link to={`/?administratie=${administratieId}`}>← Werkvoorraad</Link>{' '}
          <span style={{ color: 'var(--muted)', fontWeight: 400 }}>/</span> {detail.bestandsnaam}
        </h1>
        <div className="adm-select">
          <span className="chip klaar">verkoopfactuur · Vastly</span>{' '}
          {voorstel.is_creditnota && (
            <span className="chip vraag">
              Creditnota — crediteert {voorstel.gecrediteerd_factuurnummer ?? 'onbekend factuurnummer'}
            </span>
          )}
        </div>
      </div>

      <div className="membanner">
        <div className="icon">📄</div>
        <div>
          <b>UBL-verkoopfactuur (VASTLY-VERKOOP):</b> de kopgegevens en regels zijn deterministisch uit de
          UBL gelezen (geen AI) — de grootboekcode per regel komt als <code>cbc:AccountingCost</code> mee.
          De debiteur wordt bij boeken de échte huurder in RLZ (idempotente debiteur-aanmaak, besluit
          2026-08-08).
        </div>
      </div>
      {regelsZonderGb.length > 0 && (
        <div className="alertbanner">
          <div className="icon">⚠️</div>
          <div>
            <b>
              {regelsZonderGb.length === 1 ? 'Regel' : `${regelsZonderGb.length} regels`} zonder bekende
              grootboekrekening:
            </b>{' '}
            kies per gemarkeerde regel zelf de RLZ-rekening — een onbekende UBL-code is een blokkerende
            check, boeken kan pas als elke regel compleet is.
          </div>
        </div>
      )}
      {isVraagOpen && (
        <div className="alertbanner">
          <div className="icon">❓</div>
          <div>
            Er staat een open vraag op deze factuur — boeken is geblokkeerd tot de vraag beantwoord of
            ingetrokken is (zie <Link to={`/vragen?administratie=${administratieId}&document=${documentId}`}>Vragen</Link>).
          </div>
        </div>
      )}

      <div className="review">
        <div className="docpane">
          <div className="panel">
            <div className="bijlage-inhoud">
              {!bijlageUrl && <p className="hint">Bijlage laden…</p>}
              {xmlTekst !== null && <pre className="xml-bron">{xmlTekst}</pre>}
              {bijlageUrl && xmlTekst === null && (
                <p className="hint">
                  Geen XML-weergave beschikbaar —{' '}
                  <a href={bijlageUrl} download={detail.bestandsnaam}>
                    download het brondocument
                  </a>
                  .
                </p>
              )}
            </div>
          </div>
        </div>

        <div className="formpane">
          <div className="panel">
            <h2>
              Factuurgegevens <span className="chip ok">deterministisch uit de UBL gelezen</span>
            </h2>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
              <div>
                <label htmlFor="debiteur-naam">Debiteur (huurder)</label>
                <input
                  id="debiteur-naam"
                  value={debiteurNaam}
                  onChange={(e) => {
                    setDebiteurNaam(e.target.value)
                    setChecksActueel(false)
                  }}
                  disabled={isGeboekt}
                />
              </div>
              <div>
                <label htmlFor="factuurnummer">Factuurnummer</label>
                <input
                  id="factuurnummer"
                  value={factuurnummer}
                  onChange={(e) => {
                    setFactuurnummer(e.target.value)
                    setChecksActueel(false)
                  }}
                  disabled={isGeboekt}
                />
              </div>
              <div>
                <label htmlFor="factuurdatum">Factuurdatum</label>
                <DatePicker
                  id="factuurdatum"
                  value={factuurdatum || null}
                  onChange={(v) => {
                    setFactuurdatum(v ?? '')
                    setChecksActueel(false)
                  }}
                  disabled={isGeboekt}
                />
              </div>
              <div>
                <label htmlFor="totaal-incl">Totaalbedrag (incl. btw)</label>
                <input
                  id="totaal-incl"
                  style={{ textAlign: 'right' }}
                  value={totaalIncl}
                  onChange={(e) => {
                    setTotaalIncl(e.target.value)
                    setChecksActueel(false)
                  }}
                  disabled={isGeboekt}
                />
              </div>
            </div>
          </div>

          <div className="panel">
            <h2>Factuurregels</h2>
            <table className="lines">
              <tbody>
                <tr>
                  <th>Omschrijving</th>
                  <th>GB-code (UBL)</th>
                  <th>Grootboek (RLZ)</th>
                  <th>Btw</th>
                  <th className="amount">Netto</th>
                  <th className="amount">Btw-bedrag</th>
                </tr>
                {regels.map((regel, index) => (
                  <tr key={regel.volgnummer}>
                    <td>
                      <input
                        aria-label={`Omschrijving regel ${regel.volgnummer}`}
                        value={regel.omschrijving}
                        onChange={(e) => wijzigRegel(index, { omschrijving: e.target.value })}
                        disabled={isGeboekt}
                      />
                      {regel.herkomst === 'ubl' && (
                        <div>
                          <span className="chip ok">uit UBL</span>
                        </div>
                      )}
                    </td>
                    <td>
                      {regel.gbCode ?? '—'}
                      {regel.gbCodeStatus === 'onbekend' && (
                        <div>
                          <span className="chip blokkerend">onbekende code {regel.gbCode}</span>
                        </div>
                      )}
                      {regel.gbCodeStatus === 'ontbreekt' && (
                        <div>
                          <span className="chip vraag">geen GB-code — kies zelf</span>
                        </div>
                      )}
                    </td>
                    <td>
                      <SearchableCombobox
                        label={`Grootboek regel ${regel.volgnummer}`}
                        toonLabel={false}
                        opties={grootboek.opties}
                        waarde={regel.ledgerId}
                        onWijzig={(id) => wijzigRegel(index, { ledgerId: id })}
                        placeholder="Kies grootboekrekening…"
                      />
                    </td>
                    <td>
                      <SearchableCombobox
                        label={`Btw-code regel ${regel.volgnummer}`}
                        toonLabel={false}
                        opties={btwCodes.opties}
                        waarde={regel.taxrateId}
                        onWijzig={(id) => wijzigRegel(index, { taxrateId: id })}
                        placeholder="Kies btw-code…"
                      />
                    </td>
                    <td className="amount">
                      <input
                        aria-label={`Nettobedrag regel ${regel.volgnummer}`}
                        style={{ textAlign: 'right' }}
                        value={regel.nettoBedrag}
                        onChange={(e) => wijzigRegel(index, { nettoBedrag: e.target.value })}
                        disabled={isGeboekt}
                      />
                    </td>
                    <td className="amount">
                      <input
                        aria-label={`Btw-bedrag regel ${regel.volgnummer}`}
                        style={{ textAlign: 'right' }}
                        value={regel.btwBedrag}
                        onChange={(e) => wijzigRegel(index, { btwBedrag: e.target.value })}
                        disabled={isGeboekt}
                      />
                    </td>
                  </tr>
                ))}
                <tr>
                  <td colSpan={4}>
                    <b>Totaal regels</b>{' '}
                    <span className="hint" style={{ display: 'inline' }}>
                      — netto + btw = € {formatBedrag(nettoTotaal + btwTotaal)}; moet aansluiten op het
                      totaalbedrag incl. btw hierboven (harde check)
                    </span>
                  </td>
                  <td className="amount">
                    <b>€ {formatBedrag(nettoTotaal)}</b>
                  </td>
                  <td className="amount">
                    <b>€ {formatBedrag(btwTotaal)}</b>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <div className="panel">
            <h2>Harde checks</h2>
            {checkRapport === null && (
              <p className="hint">Klik op &quot;Checks uitvoeren&quot; om de harde checks uit te voeren.</p>
            )}
            {checkRapport && (
              <>
                {!checksActueel && (
                  <div className="hint" style={{ color: 'var(--orange)' }}>
                    Wijzigingen sinds de laatste controle — dit resultaat is verouderd. Klik opnieuw op
                    &quot;Checks uitvoeren&quot;.
                  </div>
                )}
                <table className="lines">
                  <tbody>
                    {checkRapport.resultaten.map((r) => (
                      <tr key={r.naam} style={!checksActueel ? { opacity: 0.55 } : undefined}>
                        <td>
                          <span className={`chip ${r.ok ? 'ok' : 'blokkerend'}`}>{r.ok ? 'OK' : 'Blokkerend'}</span>
                        </td>
                        <td>
                          <b>{r.naam}</b>
                        </td>
                        <td>{r.melding}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>

          <div className="panel">
            {opslaanFout && <div className="fout">{opslaanFout}</div>}
            {boekenFout && <div className="fout">{boekenFout}</div>}
            {boekResultaat && (
              <div className="hint" style={{ color: 'var(--green)' }}>
                Geboekt in RLZ — verkoopfactuur <b>{boekResultaat.verkoop_boekstuknummer ?? '—'}</b>
                {boekResultaat.verkoop_referentie && (
                  <>
                    {' '}
                    (referentie <b>{boekResultaat.verkoop_referentie}</b>)
                  </>
                )}
                .
              </div>
            )}
            {isGeboekt && !boekResultaat && (
              <p className="hint" style={{ marginTop: 0 }}>
                Deze verkoopfactuur is geboekt in RLZ
                {voorstel.rlz_boekstuknummer ? (
                  <>
                    {' '}
                    als <b>{voorstel.rlz_boekstuknummer}</b>
                  </>
                ) : null}
                . Wijzigen kan alleen via stornering in Reeleezee (actie 19).
              </p>
            )}
            {!isGeboekt && (
              <div className="actions">
                <button
                  type="button"
                  className="btn secondary"
                  disabled={opslaanBezig || boekenBezig}
                  onClick={() => void opslaan()}
                >
                  {opslaanBezig ? 'Bezig…' : 'Opslaan'}
                </button>
                <button
                  type="button"
                  className="btn secondary"
                  disabled={controlerenBezig || boekenBezig}
                  onClick={() => void controleren()}
                >
                  {controlerenBezig ? 'Bezig…' : 'Checks uitvoeren'}
                </button>
                <button
                  type="button"
                  className="btn green"
                  disabled={!isBoekbaar || !checksGroen || boekenBezig}
                  title={
                    !isBoekbaar
                      ? `Boeken kan niet vanuit status ${detail.status}`
                      : !checksGroen
                        ? 'Voer eerst de harde checks uit (alle checks moeten OK zijn)'
                        : 'Boekt de verkoopfactuur in RLZ op de échte huurder als debiteur'
                  }
                  onClick={() => void boeken()}
                >
                  {boekenBezig ? 'Bezig…' : 'Boeken in RLZ ✓'}
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
