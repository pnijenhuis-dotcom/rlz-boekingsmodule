import { useEffect, useState } from 'react'
import { ApiError, apiFetch, apiJson } from '../api/client'
import type { BoekenResponseDto, BoekvoorstelDto, BoekvoorstelMetChecksDto, CheckRapportDto } from '../api/types'
import { SearchableCombobox } from './SearchableCombobox'
import { useGrootboekOpties, useProjectOpties, useTaxrateOpties, useVendorOpties } from './useSyncOpties'

interface RegelState {
  key: string
  ledgerId: string | null
  taxrateId: string | null
  projectId: string | null
  netto: string
  btw: string
  omschrijving: string
}

function nieuweRegel(): RegelState {
  return { key: crypto.randomUUID(), ledgerId: null, taxrateId: null, projectId: null, netto: '', btw: '', omschrijving: '' }
}

function regelsUitDto(dto: BoekvoorstelDto): RegelState[] {
  if (dto.regels.length === 0) return [nieuweRegel()]
  return dto.regels.map((r) => ({
    key: crypto.randomUUID(),
    ledgerId: r.ledger_id,
    taxrateId: r.taxrate_id,
    projectId: r.project_id,
    netto: r.netto_bedrag ?? '',
    btw: r.btw_bedrag ?? '',
    omschrijving: r.omschrijving ?? '',
  }))
}

interface Props {
  administratieId: string
  documentId: string
  status: string
  onGeboekt: () => void
}

/** Controlescherm-uitbreiding (CLAUDE.md-taak 2.1): kopgegevens + boekingsregels met zoekbare
 * GB-/btw-/project-comboboxen, harde checks zichtbaar (groen/blokkerend), en de echte boekactie. */
export function BoekvoorstelPanel({ administratieId, documentId, status, onGeboekt }: Props) {
  const { opties: grootboekOpties, fout: grootboekFout } = useGrootboekOpties(administratieId)
  const { opties: taxrateOpties, fout: taxrateFout } = useTaxrateOpties(administratieId)
  const { opties: vendorOpties, fout: vendorFout } = useVendorOpties(administratieId)
  const { opties: projectOpties } = useProjectOpties(administratieId)

  const [laden, setLaden] = useState(true)
  const [ladenFout, setLadenFout] = useState<string | null>(null)
  const [vendorId, setVendorId] = useState<string | null>(null)
  const [referentie, setReferentie] = useState('')
  const [factuurdatum, setFactuurdatum] = useState('')
  const [totaalbedrag, setTotaalbedrag] = useState('')
  const [regels, setRegels] = useState<RegelState[]>([nieuweRegel()])
  const [boekstuknummer, setBoekstuknummer] = useState<string | null>(null)

  const [checkRapport, setCheckRapport] = useState<CheckRapportDto | null>(null)
  const [controlerenBezig, setControlerenBezig] = useState(false)
  const [controlerenFout, setControlerenFout] = useState<string | null>(null)
  const [boekenBezig, setBoekenBezig] = useState(false)
  const [boekenFout, setBoekenFout] = useState<string | null>(null)
  const [boekResultaat, setBoekResultaat] = useState<BoekenResponseDto | null>(null)

  useEffect(() => {
    let actief = true
    setLaden(true)
    setLadenFout(null)
    apiJson<BoekvoorstelDto>(`/administraties/${administratieId}/documenten/${documentId}/boekvoorstel`)
      .then((dto) => {
        if (!actief) return
        setVendorId(dto.vendor_id)
        setReferentie(dto.referentie ?? '')
        setFactuurdatum(dto.factuurdatum ?? '')
        setTotaalbedrag(dto.totaalbedrag ?? '')
        setBoekstuknummer(dto.rlz_boekstuknummer)
        setRegels(regelsUitDto(dto))
      })
      .catch((err: unknown) => {
        if (actief) setLadenFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
      .finally(() => {
        if (actief) setLaden(false)
      })
    return () => {
      actief = false
    }
  }, [administratieId, documentId])

  const isBevroren = status === 'geboekt'

  const wijzigRegel = (key: string, veld: keyof RegelState, waarde: string | null) => {
    setRegels((huidig) => huidig.map((r) => (r.key === key ? { ...r, [veld]: waarde } : r)))
  }

  const verwijderRegel = (key: string) => {
    setRegels((huidig) => (huidig.length > 1 ? huidig.filter((r) => r.key !== key) : huidig))
  }

  const controleren = async () => {
    setControlerenBezig(true)
    setControlerenFout(null)
    setBoekenFout(null)
    setBoekResultaat(null)
    try {
      const resultaat = await apiJson<BoekvoorstelMetChecksDto>(
        `/administraties/${administratieId}/documenten/${documentId}/boekvoorstel`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            vendor_id: vendorId,
            referentie: referentie || null,
            factuurdatum: factuurdatum || null,
            totaalbedrag: totaalbedrag || null,
            regels: regels.map((r) => ({
              ledger_id: r.ledgerId,
              taxrate_id: r.taxrateId,
              project_id: r.projectId,
              netto_bedrag: r.netto || null,
              btw_bedrag: r.btw || null,
              omschrijving: r.omschrijving || null,
            })),
          }),
        },
      )
      setCheckRapport(resultaat.checks)
    } catch (err) {
      setControlerenFout(err instanceof ApiError ? err.message : 'Controleren mislukt.')
    } finally {
      setControlerenBezig(false)
    }
  }

  const boeken = async () => {
    setBoekenBezig(true)
    setBoekenFout(null)
    try {
      const resp = await apiFetch(`/administraties/${administratieId}/documenten/${documentId}/boeken`, {
        method: 'POST',
      })
      const body: unknown = await resp.json().catch(() => null)

      if (resp.ok) {
        const resultaat = body as BoekenResponseDto
        setBoekResultaat(resultaat)
        setBoekstuknummer(resultaat.rlz_boekstuknummer)
        onGeboekt()
        return
      }

      // Bij BoekenGeblokkeerdDoorChecks (409) stuurt de router het CheckRapport mee in
      // detail.checks (een object, geen platte string) — dat kan de generieke apiJson/ApiError-
      // afhandeling niet uitpakken, dus hier rechtstreeks de rauwe Response gebruiken.
      const detail = body && typeof body === 'object' ? (body as { detail?: unknown }).detail : null
      if (resp.status === 409 && detail && typeof detail === 'object' && 'checks' in detail) {
        const { message, checks } = detail as { message?: string; checks: unknown }
        setCheckRapport(checks as BoekvoorstelMetChecksDto['checks'])
        setBoekenFout(message ?? 'Boeken geblokkeerd door harde checks — zie de checks hierboven.')
      } else {
        setBoekenFout(typeof detail === 'string' ? detail : resp.statusText || `Fout (${resp.status})`)
      }
    } catch (err) {
      setBoekenFout(err instanceof ApiError ? err.message : 'Boeken mislukt.')
    } finally {
      setBoekenBezig(false)
    }
  }

  if (laden) return <div className="panel">Boekvoorstel laden…</div>
  if (ladenFout) return <div className="fout">Kon boekvoorstel niet laden: {ladenFout}</div>

  const kanBoeken = checkRapport !== null && !checkRapport.geblokkeerd && !isBevroren

  return (
    <>
      <div className="panel">
        <h2>Kopgegevens</h2>
        {(grootboekFout || taxrateFout || vendorFout) && (
          <div className="fout">Kon sync-caches niet volledig laden — controleer of deze administratie gesynchroniseerd is.</div>
        )}
        <div className="grid2">
          <SearchableCombobox
            label="Crediteur"
            opties={vendorOpties}
            waarde={vendorId}
            onWijzig={setVendorId}
            vereist
            fout={checkRapport?.geblokkeerd && vendorId === null}
          />
          <div>
            <label htmlFor="boekvoorstel-referentie">Referentie / factuurnummer</label>
            <input
              id="boekvoorstel-referentie"
              value={referentie}
              onChange={(e) => setReferentie(e.target.value)}
              disabled={isBevroren}
            />
          </div>
          <div>
            <label htmlFor="boekvoorstel-datum">Factuurdatum</label>
            <input
              id="boekvoorstel-datum"
              type="date"
              value={factuurdatum}
              onChange={(e) => setFactuurdatum(e.target.value)}
              disabled={isBevroren}
            />
          </div>
          <div>
            <label htmlFor="boekvoorstel-totaal">Totaalbedrag (incl. btw)</label>
            <input
              id="boekvoorstel-totaal"
              inputMode="decimal"
              value={totaalbedrag}
              onChange={(e) => setTotaalbedrag(e.target.value)}
              disabled={isBevroren}
            />
          </div>
        </div>
      </div>

      <div className="panel">
        <h2>Boekingsregels</h2>
        <table className="lines">
          <tbody>
            <tr>
              <th>Grootboek</th>
              <th>Btw-code</th>
              <th>Project</th>
              <th>Netto</th>
              <th>Btw</th>
              <th>Omschrijving</th>
              <th />
            </tr>
            {regels.map((regel) => (
              <tr key={regel.key}>
                <td style={{ minWidth: 200 }}>
                  <SearchableCombobox
                    label="Grootboek"
                    opties={grootboekOpties}
                    waarde={regel.ledgerId}
                    onWijzig={(id) => wijzigRegel(regel.key, 'ledgerId', id)}
                    vereist
                  />
                </td>
                <td style={{ minWidth: 180 }}>
                  <SearchableCombobox
                    label="Btw-code"
                    opties={taxrateOpties}
                    waarde={regel.taxrateId}
                    onWijzig={(id) => wijzigRegel(regel.key, 'taxrateId', id)}
                    vereist
                  />
                </td>
                <td style={{ minWidth: 160 }}>
                  <SearchableCombobox
                    label="Project"
                    opties={projectOpties}
                    waarde={regel.projectId}
                    onWijzig={(id) => wijzigRegel(regel.key, 'projectId', id)}
                  />
                </td>
                <td className="amount" style={{ minWidth: 90 }}>
                  <input
                    aria-label="Netto bedrag"
                    inputMode="decimal"
                    value={regel.netto}
                    onChange={(e) => wijzigRegel(regel.key, 'netto', e.target.value)}
                    disabled={isBevroren}
                  />
                </td>
                <td className="amount" style={{ minWidth: 90 }}>
                  <input
                    aria-label="Btw bedrag"
                    inputMode="decimal"
                    value={regel.btw}
                    onChange={(e) => wijzigRegel(regel.key, 'btw', e.target.value)}
                    disabled={isBevroren}
                  />
                </td>
                <td>
                  <input
                    aria-label="Omschrijving"
                    value={regel.omschrijving}
                    onChange={(e) => wijzigRegel(regel.key, 'omschrijving', e.target.value)}
                    disabled={isBevroren}
                  />
                </td>
                <td>
                  {!isBevroren && (
                    <button
                      type="button"
                      className="btn secondary"
                      onClick={() => verwijderRegel(regel.key)}
                      aria-label="Regel verwijderen"
                    >
                      ×
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!isBevroren && (
          <div style={{ marginTop: 10 }}>
            <button type="button" className="btn secondary" onClick={() => setRegels((r) => [...r, nieuweRegel()])}>
              + Regel toevoegen
            </button>
          </div>
        )}
        <div className="hint">
          Grootboek- en btw-lijsten komen uit de sync-cache van deze administratie (koppelcontract §2c) — nooit
          rechtstreeks live van RLZ.
        </div>
      </div>

      {!isBevroren && (
        <div className="panel">
          <h2>Harde checks</h2>
          {controlerenFout && <div className="fout">{controlerenFout}</div>}
          {checkRapport === null && <p className="hint">Klik op "Controleren" om de harde checks uit te voeren.</p>}
          {checkRapport && (
            <table className="lines">
              <tbody>
                {checkRapport.resultaten.map((r) => (
                  <tr key={r.naam}>
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
          <div className="actions">
            <button type="button" className="btn secondary" disabled={controlerenBezig} onClick={() => void controleren()}>
              {controlerenBezig ? 'Bezig…' : 'Controleren'}
            </button>
          </div>
        </div>
      )}

      <div className="panel">
        {boekenFout && <div className="fout">{boekenFout}</div>}
        {boekResultaat && (
          <div className="hint" style={{ color: 'var(--green)' }}>
            Geboekt in RLZ — boekstuknummer <b>{boekResultaat.rlz_boekstuknummer}</b>
          </div>
        )}
        {isBevroren && boekstuknummer && (
          <div className="hint">
            Al geboekt — RLZ-boekstuknummer <b>{boekstuknummer}</b>
          </div>
        )}
        {!isBevroren && (
          <div className="actions">
            <button type="button" className="btn green" disabled={!kanBoeken || boekenBezig} onClick={() => void boeken()}>
              {boekenBezig ? 'Bezig…' : 'Boeken in RLZ ✓'}
            </button>
          </div>
        )}
      </div>
    </>
  )
}
