import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { apiFetch, apiJson } from '../api/client'
import type { DocumentDetailDto } from '../api/types'
import { StatusChip } from '../werkvoorraad/StatusChip'
import { statusLabel } from '../werkvoorraad/status'
import { BoekvoorstelPanel } from './BoekvoorstelPanel'

function formatDatum(iso: string): string {
  return new Date(iso).toLocaleString('nl-NL', { dateStyle: 'medium', timeStyle: 'short' })
}

function veldnaam(sleutel: string): string {
  const namen: Record<string, string> = {
    factuurnummer: 'Factuurnummer',
    factuurdatum: 'Factuurdatum',
    valuta: 'Valuta',
    totaal_excl: 'Totaal excl. btw',
    totaal_incl: 'Totaal incl. btw',
    leverancier_naam: 'Leverancier',
    regelaantal: 'Aantal regels',
  }
  return namen[sleutel] ?? sleutel
}

interface Bijlage {
  url: string
  contentType: string
}

export function DocumentDetailScreen() {
  const { administratieId, documentId } = useParams<{ administratieId: string; documentId: string }>()
  const [detail, setDetail] = useState<DocumentDetailDto | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [bijlage, setBijlage] = useState<Bijlage | null>(null)

  const laadDetail = useCallback(() => {
    if (!administratieId || !documentId) return
    setFout(null)
    apiJson<DocumentDetailDto>(`/administraties/${administratieId}/documenten/${documentId}`)
      .then(setDetail)
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Onbekende fout'))
  }, [administratieId, documentId])

  useEffect(() => {
    setDetail(null)
    laadDetail()
  }, [laadDetail])

  useEffect(() => {
    if (!administratieId || !documentId) return
    let objectUrl: string | null = null
    let actief = true

    void apiFetch(`/administraties/${administratieId}/documenten/${documentId}/bestand`).then(async (resp) => {
      if (!resp.ok || !actief) return
      const blob = await resp.blob()
      objectUrl = URL.createObjectURL(blob)
      setBijlage({ url: objectUrl, contentType: resp.headers.get('content-type') ?? 'application/octet-stream' })
    })

    return () => {
      actief = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [administratieId, documentId])

  if (fout) return <div className="fout">Kon document niet laden: {fout}</div>
  if (!administratieId || !documentId || !detail) return <p className="hint">Laden…</p>

  return (
    <div>
      <div className="topbar">
        <h1>
          <Link to="/">← Werkvoorraad</Link> <span style={{ color: 'var(--muted)', fontWeight: 400 }}>/</span>{' '}
          {detail.bestandsnaam}
        </h1>
        <div className="adm-select">
          <StatusChip status={detail.status} />
        </div>
      </div>

      <div style={{ display: 'flex', gap: 20, alignItems: 'flex-start', flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 380px', minWidth: 320 }}>
          <div className="panel">
            <h2>Bijlage</h2>
            {!bijlage && <p className="hint">Bijlage laden…</p>}
            {bijlage?.contentType.includes('pdf') && (
              <embed src={bijlage.url} type="application/pdf" width="100%" height="500" />
            )}
            {bijlage && !bijlage.contentType.includes('pdf') && (
              <p className="hint">Geen inline weergave voor dit bestandstype.</p>
            )}
            {bijlage && (
              <p style={{ marginTop: 10 }}>
                <a className="btn secondary" href={bijlage.url} download={detail.bestandsnaam}>
                  Downloaden
                </a>
              </p>
            )}
          </div>
        </div>

        <div style={{ flex: '1.2 1 420px', minWidth: 320 }}>
          {detail.veldvoorstel && (
            <div className="panel">
              <h2>
                Veldvoorstel (UBL) <span className="chip geheugen">deterministisch geparst</span>
              </h2>
              <table className="lines">
                <tbody>
                  {Object.entries(detail.veldvoorstel).map(([sleutel, waarde]) => (
                    <tr key={sleutel}>
                      <td style={{ color: 'var(--muted)' }}>{veldnaam(sleutel)}</td>
                      <td>{waarde === null || waarde === undefined ? '—' : String(waarde)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <BoekvoorstelPanel
            administratieId={administratieId}
            documentId={documentId}
            status={detail.status}
            onGeboekt={laadDetail}
          />

          <div className="panel">
            <h2>Tijdlijn</h2>
            <table className="lines">
              <tbody>
                {detail.tijdlijn.map((g, i) => (
                  <tr key={i}>
                    <td style={{ whiteSpace: 'nowrap', color: 'var(--muted)' }}>{formatDatum(g.tijdstip)}</td>
                    <td>
                      {g.van_status ? (
                        <>
                          {statusLabel(g.van_status)} → <b>{statusLabel(g.naar_status)}</b>
                        </>
                      ) : (
                        <>
                          Ontvangen (status <b>{statusLabel(g.naar_status)}</b>)
                        </>
                      )}
                      {g.detail && 'ubl_parse_fout' in g.detail && (
                        <div className="hint" style={{ marginTop: 2 }}>
                          UBL-parsefout: {String(g.detail.ubl_parse_fout)}
                        </div>
                      )}
                      {g.detail && 'mogelijk_duplicaat_van' in g.detail && (
                        <div className="hint" style={{ marginTop: 2 }}>
                          Mogelijk duplicaat van document {String(g.detail.mogelijk_duplicaat_van)}
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}
