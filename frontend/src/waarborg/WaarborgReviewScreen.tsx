import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError, apiFetch, apiJson } from '../api/client'
import type { CheckRapportDto, DocumentDetailDto, WaarborgBoekenResponseDto, WaarborgVoorstelDto } from '../api/types'
import { formatteerXml } from '../document/DocumentDetailScreen'
import { SearchableCombobox } from '../document/SearchableCombobox'
import { useAutoChecks } from '../document/useAutoChecks'
import { useGrootboekOpties } from '../document/useSyncOpties'
import { ChecksPopup } from '../ui/ChecksPopup'
import { haalWaarborgVoorstelOp, slaWaarborgTegenrekeningOp, voerWaarborgChecksUit } from './waarborgApi'

/** Waarborg-review (§2d-waarborgroute v1.11, blok E 2026-08-10): alle berichtvelden zijn
 * BRONGEGEVEN (read-only — het VASTLY-WAARBORG-bericht is de bron); de éne menselijke keuze is
 * de tegenrekening van het saldo-0-memoriaal. Checks draaien automatisch (blok B-patroon),
 * boeken herdraait ze server-side (pop-up bij blokkade). */

const BOEKBARE_STATUSSEN = new Set(['te_controleren', 'klaar_om_te_boeken', 'boeken_mislukt', 'handmatig_afmaken'])

function formatBedrag(waarde: string): string {
  const getal = Number(waarde)
  return Number.isFinite(getal)
    ? getal.toLocaleString('nl-NL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : waarde
}

export function WaarborgReviewScreen() {
  const { administratieId, documentId } = useParams<{ administratieId: string; documentId: string }>()

  const [detail, setDetail] = useState<DocumentDetailDto | null>(null)
  const [voorstel, setVoorstel] = useState<WaarborgVoorstelDto | null>(null)
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [xmlTekst, setXmlTekst] = useState<string | null>(null)
  const [tegenrekeningId, setTegenrekeningId] = useState<string | null>(null)

  const [opslaanFout, setOpslaanFout] = useState<string | null>(null)
  const [checkRapport, setCheckRapport] = useState<CheckRapportDto | null>(null)
  const [checksActueel, setChecksActueel] = useState(false)
  const [boekenBezig, setBoekenBezig] = useState(false)
  const [boekenFout, setBoekenFout] = useState<string | null>(null)
  const [boekResultaat, setBoekResultaat] = useState<WaarborgBoekenResponseDto | null>(null)
  const [wijzigingsVersie, setWijzigingsVersie] = useState(0)
  const wijzigingsVersieRef = useRef(0)
  const [popupChecks, setPopupChecks] = useState<{ melding: string | null; checks: CheckRapportDto } | null>(null)

  const grootboek = useGrootboekOpties(administratieId ?? '')

  useEffect(() => {
    if (!administratieId || !documentId) return
    let actief = true
    Promise.all([
      apiJson<DocumentDetailDto>(`/administraties/${administratieId}/documenten/${documentId}`),
      haalWaarborgVoorstelOp(administratieId, documentId),
    ])
      .then(([documentDetail, voorstelData]) => {
        if (!actief) return
        setDetail(documentDetail)
        setVoorstel(voorstelData)
        setTegenrekeningId(voorstelData.tegenrekening_ledger_id)
      })
      .catch((err: unknown) => {
        if (actief) setLaadFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
    return () => {
      actief = false
    }
  }, [administratieId, documentId])

  useEffect(() => {
    if (!administratieId || !documentId) return
    let actief = true
    void apiFetch(`/administraties/${administratieId}/documenten/${documentId}/bestand`).then(async (resp) => {
      if (!resp.ok || !actief) return
      const tekst = formatteerXml(await resp.text())
      if (actief) setXmlTekst(tekst)
    })
    return () => {
      actief = false
    }
  }, [administratieId, documentId])

  const kiesTegenrekening = (id: string | null) => {
    setTegenrekeningId(id)
    setChecksActueel(false)
    wijzigingsVersieRef.current += 1
    setWijzigingsVersie(wijzigingsVersieRef.current)
  }

  const checksBijOpenen = useCallback(async () => {
    if (!administratieId || !documentId) return
    const versieBijStart = wijzigingsVersieRef.current
    const rapport = await voerWaarborgChecksUit(administratieId, documentId)
    if (wijzigingsVersieRef.current === versieBijStart) {
      setCheckRapport(rapport)
      setChecksActueel(true)
    }
  }, [administratieId, documentId])

  const checksBijWijziging = async () => {
    if (!administratieId || !documentId) return
    const versieBijStart = wijzigingsVersieRef.current
    setOpslaanFout(null)
    try {
      const data = await slaWaarborgTegenrekeningOp(administratieId, documentId, tegenrekeningId)
      if (wijzigingsVersieRef.current === versieBijStart) setVoorstel(data)
      const rapport = await voerWaarborgChecksUit(administratieId, documentId)
      if (wijzigingsVersieRef.current === versieBijStart) {
        setCheckRapport(rapport)
        setChecksActueel(true)
      }
    } catch (err) {
      setOpslaanFout(err instanceof ApiError ? err.message : 'Opslaan/checks mislukt.')
    }
  }

  const boeken = async () => {
    if (!administratieId || !documentId) return
    setBoekenBezig(true)
    setBoekenFout(null)
    try {
      await slaWaarborgTegenrekeningOp(administratieId, documentId, tegenrekeningId)
      const resp = await apiFetch(`/administraties/${administratieId}/waarborg/documenten/${documentId}/boeken`, {
        method: 'POST',
      })
      const body: unknown = await resp.json().catch(() => null)
      if (resp.ok) {
        const resultaat = body as WaarborgBoekenResponseDto
        setBoekResultaat(resultaat)
        setDetail((huidig) => (huidig ? { ...huidig, status: resultaat.status } : huidig))
        return
      }
      const detailBody = body && typeof body === 'object' ? (body as { detail?: unknown }).detail : null
      if (resp.status === 409 && detailBody && typeof detailBody === 'object' && 'checks' in detailBody) {
        const { melding, checks } = detailBody as { melding?: string; checks: CheckRapportDto }
        setCheckRapport(checks)
        setChecksActueel(true)
        setPopupChecks({ melding: melding ?? null, checks })
      } else {
        setBoekenFout(typeof detailBody === 'string' ? detailBody : resp.statusText || `Fout (${resp.status})`)
      }
    } catch (err) {
      setBoekenFout(err instanceof ApiError ? err.message : 'Boeken mislukt.')
    } finally {
      setBoekenBezig(false)
    }
  }

  const { checksBezig } = useAutoChecks({
    actief:
      detail !== null && voorstel !== null && detail.status !== 'geboekt' && detail.status !== 'verwijderd',
    wijzigingsVersie,
    bijOpenen: checksBijOpenen,
    bijWijziging: checksBijWijziging,
  })

  if (laadFout) return <div className="fout">Kon waarborg-bericht niet laden: {laadFout}</div>
  if (!detail || !voorstel || !administratieId || !documentId) return <p className="hint">Laden…</p>

  const isGeboekt = detail.status === 'geboekt' || voorstel.status === 'geboekt'
  const isBoekbaar = BOEKBARE_STATUSSEN.has(detail.status)
  const checksGroen = checksActueel && checkRapport !== null && !checkRapport.geblokkeerd

  return (
    <div>
      <div className="topbar">
        <h1>
          <Link to={`/?administratie=${administratieId}`}>← Werkvoorraad</Link>{' '}
          <span style={{ color: 'var(--muted)', fontWeight: 400 }}>/</span> {detail.bestandsnaam}
        </h1>
        <div className="adm-select">
          <span className="chip klaar">waarborg · Vastly</span>{' '}
          <span className={`chip ${voorstel.richting === 'ontvangst' ? 'ok' : 'vraag'}`}>
            {voorstel.richting}
          </span>
        </div>
      </div>

      <div className="membanner">
        <div className="icon">🔐</div>
        <div>
          <b>VASTLY-WAARBORG-bericht (§2d-waarborgroute):</b> de velden hieronder komen deterministisch uit
          het bericht en zijn niet te wijzigen — het bericht is de bron. U kiest alleen de{' '}
          <b>tegenrekening</b> waartegen het saldo-0-memoriaal sluit; de waarborg zelf boekt op
          balansrekening {voorstel.balans_gb_code}
          {voorstel.richting === 'ontvangst' ? ' (creditzijde — verplichting)' : ' (debetzijde — terugbetaling)'}.
        </div>
      </div>

      <div className="review">
        <div className="docpane">
          <div className="panel">
            <div className="bijlage-inhoud">
              {xmlTekst === null ? <p className="hint">Bericht laden…</p> : <pre className="xml-bron">{xmlTekst}</pre>}
            </div>
          </div>
        </div>

        <div className="formpane">
          <div className="panel">
            <h2>
              Waarborg-bericht <span className="chip ok">brongegeven — niet muteerbaar</span>
            </h2>
            <table className="lines">
              <tbody>
                <tr>
                  <td>Verhuurder (administratie)</td>
                  <td>{voorstel.verhuurder_entiteit}</td>
                </tr>
                <tr>
                  <td>Contract</td>
                  <td>{voorstel.contract_referentie}</td>
                </tr>
                <tr>
                  <td>Huurder</td>
                  <td>{voorstel.huurder}</td>
                </tr>
                <tr>
                  <td>Bedrag</td>
                  <td>
                    <b>€ {formatBedrag(voorstel.bedrag)}</b> ({voorstel.richting}, {voorstel.datum})
                  </td>
                </tr>
                <tr>
                  <td>Balansrekening (uit het bericht)</td>
                  <td>
                    {voorstel.balans_gb_code}{' '}
                    {voorstel.balans_gb_status === 'bekend' ? (
                      <span className="chip ok">bekend in het rekeningschema</span>
                    ) : (
                      <span className="chip blokkerend">onbekend in deze administratie — blokkerend</span>
                    )}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <div className="panel">
            <h2>Memoriaal</h2>
            <div style={{ maxWidth: 420 }}>
              <SearchableCombobox
                label="Tegenrekening (waartegen het memoriaal sluit)"
                opties={grootboek.opties}
                waarde={tegenrekeningId}
                onWijzig={kiesTegenrekening}
                placeholder="Kies tegenrekening…"
              />
            </div>
            <p className="hint">
              {voorstel.richting === 'ontvangst'
                ? `Debet tegenrekening / credit ${voorstel.balans_gb_code} Waarborgsommen — saldo 0 per constructie.`
                : `Debet ${voorstel.balans_gb_code} Waarborgsommen / credit tegenrekening — saldo 0 per constructie.`}
            </p>
          </div>

          <div className="panel">
            <h2>
              Harde checks{' '}
              {checksBezig ? (
                <span className="chip vraag">checks worden uitgevoerd…</span>
              ) : checkRapport !== null && checksActueel ? (
                <span className={`chip ${checkRapport.geblokkeerd ? 'blokkerend' : 'ok'}`}>
                  {checkRapport.geblokkeerd ? 'blokkerend' : 'alle checks groen'}
                </span>
              ) : (
                <span className="chip">automatisch</span>
              )}
            </h2>
            {checkRapport === null && !checksBezig && (
              <p className="hint">De harde checks draaien automatisch — bij het openen en na elke wijziging.</p>
            )}
            {checkRapport && (
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
            )}
          </div>

          <div className="panel">
            {opslaanFout && <div className="fout">{opslaanFout}</div>}
            {boekenFout && <div className="fout">{boekenFout}</div>}
            {(boekResultaat || isGeboekt) && (
              <p className="hint" style={{ color: 'var(--green)', marginTop: 0 }}>
                Geboekt in RLZ als memoriaal{' '}
                <b>{boekResultaat?.rlz_boekstuknummer ?? voorstel.rlz_boekstuknummer ?? '—'}</b>. Terugdraaien kan
                alleen via stornering in Reeleezee (actie 19).
              </p>
            )}
            {!isGeboekt && (
              <div className="actions">
                <button
                  type="button"
                  className="btn green"
                  disabled={!isBoekbaar || !checksGroen || boekenBezig}
                  title={
                    !isBoekbaar
                      ? `Boeken kan niet vanuit status ${detail.status}`
                      : !checksGroen
                        ? 'De harde checks draaien automatisch — boeken kan zodra alle checks groen zijn'
                        : 'Boekt het saldo-0-memoriaal in RLZ'
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
      {popupChecks && (
        <ChecksPopup melding={popupChecks.melding} checks={popupChecks.checks} onSluiten={() => setPopupChecks(null)} />
      )}
    </div>
  )
}
