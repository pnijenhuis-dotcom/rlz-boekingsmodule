import { useEffect, useMemo, useState } from 'react'
import { ApiError, apiFetch, apiJson } from '../api/client'
import type { BoekenResponseDto, BoekvoorstelDto, BoekvoorstelMetChecksDto, CheckRapportDto } from '../api/types'
import { bedragAlsGetal, normaliseerBedrag } from './bedrag'
import { SearchableCombobox } from './SearchableCombobox'
import {
  synchroniseerAlleCaches,
  useGrootboekOpties,
  useProjectOpties,
  useProjectVerplicht,
  useTaxrateOpties,
  useVendorOpties,
} from './useSyncOpties'

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

function formatEuro(bedrag: number): string {
  return bedrag.toLocaleString('nl-NL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

interface LegeCacheBannerProps {
  naam: string
  bezig: boolean
  onSynchroniseren: () => void
}

/** Design-pass taak 3: duidelijke melding + herstelactie i.p.v. een blijkbaar-lege combobox
 * zonder verklaring. "Nu synchroniseren" verversen ALLE vier de caches (grootboek/btw/crediteuren/
 * projecten) tegelijk — een controleur die deze banner ziet, wil de hele administratie bijwerken. */
function LegeCacheBanner({ naam, bezig, onSynchroniseren }: LegeCacheBannerProps) {
  return (
    <div
      style={{
        background: 'var(--orange-bg)',
        color: 'var(--orange)',
        borderRadius: 8,
        padding: '9px 12px',
        fontSize: 12.5,
        marginBottom: 10,
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        flexWrap: 'wrap',
      }}
    >
      <span>Deze administratie is nog niet gesynchroniseerd voor {naam}.</span>
      <button type="button" className="btn secondary" disabled={bezig} onClick={onSynchroniseren}>
        {bezig ? 'Bezig…' : 'Nu synchroniseren'}
      </button>
    </div>
  )
}

interface Props {
  administratieId: string
  documentId: string
  status: string
  onGeboekt: () => void
}

/** Controlescherm-uitbreiding (CLAUDE.md-taak 2.1, design-pass): kopgegevens + boekingsregels met
 * zoekbare GB-/btw-/project-comboboxen, harde checks zichtbaar (groen/blokkerend), live
 * aansluit-indicator, en de echte boekactie. */
export function BoekvoorstelPanel({ administratieId, documentId, status, onGeboekt }: Props) {
  const [cacheVersie, setCacheVersie] = useState(0)
  const { opties: grootboekOpties, fout: grootboekFout, laden: grootboekLaden } = useGrootboekOpties(administratieId, cacheVersie)
  const { opties: taxrateOpties, fout: taxrateFout, laden: taxrateLaden } = useTaxrateOpties(administratieId, cacheVersie)
  const { opties: vendorOpties, fout: vendorFout, laden: vendorLaden } = useVendorOpties(administratieId, cacheVersie)
  const { opties: projectOpties, laden: projectLaden } = useProjectOpties(administratieId, cacheVersie)
  const projectVerplicht = useProjectVerplicht(administratieId)

  const [synchroniserenBezig, setSynchroniserenBezig] = useState(false)
  const [synchroniserenFout, setSynchroniserenFout] = useState<string | null>(null)

  const [laden, setLaden] = useState(true)
  const [ladenFout, setLadenFout] = useState<string | null>(null)
  const [vendorId, setVendorId] = useState<string | null>(null)
  const [referentie, setReferentie] = useState('')
  const [factuurdatum, setFactuurdatum] = useState('')
  const [totaalbedrag, setTotaalbedrag] = useState('')
  const [regels, setRegels] = useState<RegelState[]>([nieuweRegel()])
  const [boekstuknummer, setBoekstuknummer] = useState<string | null>(null)

  const [checkRapport, setCheckRapport] = useState<CheckRapportDto | null>(null)
  // Design-pass taak 7: elke veldwijziging maakt het laatste checkresultaat ongeldig voor de
  // ACTUELE invoer — de knop "Boeken" mag dan niet meer aan staan, ook al was het vorige resultaat
  // groen. De rijen blijven zichtbaar (context), maar duidelijk gemarkeerd als verouderd.
  const [checksActueel, setChecksActueel] = useState(false)
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

  const veranderInvoer = () => setChecksActueel(false)

  const wijzigVendorId = (id: string | null) => {
    setVendorId(id)
    veranderInvoer()
  }
  const wijzigReferentie = (waarde: string) => {
    setReferentie(waarde)
    veranderInvoer()
  }
  const wijzigFactuurdatum = (waarde: string) => {
    setFactuurdatum(waarde)
    veranderInvoer()
  }
  const wijzigTotaalbedrag = (waarde: string) => {
    setTotaalbedrag(waarde)
    veranderInvoer()
  }

  const wijzigRegel = (key: string, veld: keyof RegelState, waarde: string | null) => {
    setRegels((huidig) => huidig.map((r) => (r.key === key ? { ...r, [veld]: waarde } : r)))
    veranderInvoer()
  }

  const verwijderRegel = (key: string) => {
    setRegels((huidig) => (huidig.length > 1 ? huidig.filter((r) => r.key !== key) : huidig))
    veranderInvoer()
  }

  const voegRegelToe = () => {
    setRegels((r) => [...r, nieuweRegel()])
    veranderInvoer()
  }

  const nuSynchroniseren = async () => {
    setSynchroniserenBezig(true)
    setSynchroniserenFout(null)
    const fouten = await synchroniseerAlleCaches(administratieId)
    if (fouten.length > 0) setSynchroniserenFout(fouten.join('; '))
    setCacheVersie((v) => v + 1)
    setSynchroniserenBezig(false)
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
            totaalbedrag: totaalbedrag ? normaliseerBedrag(totaalbedrag) : null,
            regels: regels.map((r) => ({
              ledger_id: r.ledgerId,
              taxrate_id: r.taxrateId,
              project_id: projectVerplicht ? r.projectId : null,
              netto_bedrag: r.netto ? normaliseerBedrag(r.netto) : null,
              btw_bedrag: r.btw ? normaliseerBedrag(r.btw) : null,
              omschrijving: r.omschrijving || null,
            })),
          }),
        },
      )
      setCheckRapport(resultaat.checks)
      setChecksActueel(true)
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
        setChecksActueel(true)
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

  const totaalAlsGetal = useMemo(() => bedragAlsGetal(totaalbedrag), [totaalbedrag])
  const somRegels = useMemo(
    () => regels.reduce((acc, r) => acc + (bedragAlsGetal(r.netto) ?? 0) + (bedragAlsGetal(r.btw) ?? 0), 0),
    [regels],
  )
  const aansluitVerschil = totaalAlsGetal === null ? null : somRegels - totaalAlsGetal
  const aansluit = aansluitVerschil === null ? null : Math.abs(aansluitVerschil) <= 0.01

  if (laden) return <div className="panel">Boekvoorstel laden…</div>
  if (ladenFout) return <div className="fout">Kon boekvoorstel niet laden: {ladenFout}</div>

  const kanBoeken = checkRapport !== null && checksActueel && !checkRapport.geblokkeerd && !isBevroren
  const boekenTitel = isBevroren
    ? undefined
    : checkRapport === null
      ? 'Voer eerst de harde checks uit via "Controleren".'
      : !checksActueel
        ? 'Er zijn wijzigingen sinds de laatste controle — klik opnieuw op "Controleren".'
        : checkRapport.geblokkeerd
          ? 'Boeken geblokkeerd — een of meer harde checks zijn niet groen.'
          : undefined

  return (
    <>
      <div className="panel">
        <h2>Kopgegevens</h2>
        {synchroniserenFout && <div className="fout">Synchroniseren gaf fouten: {synchroniserenFout}</div>}
        {!vendorLaden && vendorOpties.length === 0 && !vendorFout && (
          <LegeCacheBanner naam="crediteuren" bezig={synchroniserenBezig} onSynchroniseren={() => void nuSynchroniseren()} />
        )}
        {vendorFout && <div className="fout">Kon crediteuren niet laden: {vendorFout}</div>}
        <div className="grid2">
          <SearchableCombobox
            label="Crediteur"
            opties={vendorOpties}
            waarde={vendorId}
            onWijzig={wijzigVendorId}
            vereist
            fout={checkRapport?.geblokkeerd && vendorId === null}
          />
          <div>
            <label htmlFor="boekvoorstel-referentie">Referentie / factuurnummer</label>
            <input
              id="boekvoorstel-referentie"
              value={referentie}
              onChange={(e) => wijzigReferentie(e.target.value)}
              disabled={isBevroren}
            />
          </div>
          <div>
            <label htmlFor="boekvoorstel-datum">Factuurdatum</label>
            <input
              id="boekvoorstel-datum"
              type="date"
              value={factuurdatum}
              onChange={(e) => wijzigFactuurdatum(e.target.value)}
              disabled={isBevroren}
            />
          </div>
          <div>
            <label htmlFor="boekvoorstel-totaal">Totaalbedrag (incl. btw)</label>
            <input
              id="boekvoorstel-totaal"
              inputMode="decimal"
              placeholder="1234,56"
              title="Bijvoorbeeld 1234,56 of 1234.56"
              value={totaalbedrag}
              onChange={(e) => wijzigTotaalbedrag(e.target.value)}
              disabled={isBevroren}
            />
          </div>
        </div>
      </div>

      <div className="panel">
        <h2>Boekingsregels</h2>
        {!grootboekLaden && grootboekOpties.length === 0 && !grootboekFout && (
          <LegeCacheBanner naam="het grootboekschema" bezig={synchroniserenBezig} onSynchroniseren={() => void nuSynchroniseren()} />
        )}
        {!taxrateLaden && taxrateOpties.length === 0 && !taxrateFout && (
          <LegeCacheBanner naam="btw-codes" bezig={synchroniserenBezig} onSynchroniseren={() => void nuSynchroniseren()} />
        )}
        {projectVerplicht && !projectLaden && projectOpties.length === 0 && (
          <LegeCacheBanner naam="projecten" bezig={synchroniserenBezig} onSynchroniseren={() => void nuSynchroniseren()} />
        )}
        {(grootboekFout || taxrateFout) && (
          <div className="fout">Kon grootboek- en/of btw-cache niet laden — controleer of deze administratie gesynchroniseerd is.</div>
        )}
        <table className="lines boekingsregels-tabel">
          <colgroup>
            <col style={{ width: '22%' }} />
            <col style={{ width: '16%' }} />
            {projectVerplicht && <col style={{ width: '14%' }} />}
            <col style={{ width: 84 }} />
            <col style={{ width: 84 }} />
            <col />
            <col style={{ width: 36 }} />
          </colgroup>
          <tbody>
            <tr>
              <th>Grootboek</th>
              <th>Btw-code</th>
              {projectVerplicht && <th>Project</th>}
              <th className="amount">Netto</th>
              <th className="amount">Btw</th>
              <th>Omschrijving</th>
              <th />
            </tr>
            {regels.map((regel) => (
              <tr key={regel.key}>
                <td>
                  <SearchableCombobox
                    label="Grootboek"
                    opties={grootboekOpties}
                    waarde={regel.ledgerId}
                    onWijzig={(id) => wijzigRegel(regel.key, 'ledgerId', id)}
                    vereist
                    toonLabel={false}
                  />
                </td>
                <td>
                  <SearchableCombobox
                    label="Btw-code"
                    opties={taxrateOpties}
                    waarde={regel.taxrateId}
                    onWijzig={(id) => wijzigRegel(regel.key, 'taxrateId', id)}
                    vereist
                    toonLabel={false}
                  />
                </td>
                {projectVerplicht && (
                  <td>
                    <SearchableCombobox
                      label="Project"
                      opties={projectOpties}
                      waarde={regel.projectId}
                      onWijzig={(id) => wijzigRegel(regel.key, 'projectId', id)}
                      vereist
                      toonLabel={false}
                      fout={checkRapport?.geblokkeerd && regel.projectId === null}
                    />
                  </td>
                )}
                <td className="amount">
                  <input
                    aria-label="Netto bedrag"
                    inputMode="decimal"
                    title="Bijvoorbeeld 1234,56 of 1234.56"
                    style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}
                    value={regel.netto}
                    onChange={(e) => wijzigRegel(regel.key, 'netto', e.target.value)}
                    disabled={isBevroren}
                  />
                </td>
                <td className="amount">
                  <input
                    aria-label="Btw bedrag"
                    inputMode="decimal"
                    title="Bijvoorbeeld 1234,56 of 1234.56"
                    style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}
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
          <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <button type="button" className="btn secondary" onClick={voegRegelToe}>
              + Regel toevoegen
            </button>
            {aansluit !== null && aansluitVerschil !== null && (
              <span className={`chip ${aansluit ? 'ok' : 'afwijking'}`}>
                {aansluit
                  ? `Aansluitend — € ${formatEuro(somRegels)}`
                  : `Afwijking € ${formatEuro(Math.abs(aansluitVerschil))} (som € ${formatEuro(somRegels)} vs totaal € ${formatEuro(totaalAlsGetal ?? 0)})`}
              </span>
            )}
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
            <>
              {!checksActueel && (
                <div className="hint" style={{ color: 'var(--orange)' }}>
                  Wijzigingen sinds de laatste controle — dit resultaat is verouderd. Klik opnieuw op "Controleren".
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
            <button
              type="button"
              className="btn green"
              disabled={!kanBoeken || boekenBezig}
              title={boekenTitel}
              onClick={() => void boeken()}
            >
              {boekenBezig ? 'Bezig…' : 'Boeken in RLZ ✓'}
            </button>
          </div>
        )}
      </div>
    </>
  )
}
