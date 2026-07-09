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

function formatDatumKort(iso: string): string {
  return new Date(iso).toLocaleDateString('nl-NL', { dateStyle: 'medium' })
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

/** Puur cosmetisch: legt de XML in nette, ingesprongen regels voor de bron-weergave (geen
 * DOM-parsing/uitvoering — React rendert dit altijd als platte tekst in een <pre>, dus geen
 * XSS-risico). Werkt op basis van eenvoudige tag-grenzen; bedoeld voor leesbaarheid, geen
 * volwaardige XML-formatter. */
function formatteerXml(xml: string): string {
  const zonderWhitespaceTussenTags = xml.replace(/>\s*</g, '><').trim()
  const tokens = zonderWhitespaceTussenTags.split(/(?=<)/g).filter(Boolean)
  let diepte = 0
  const regels: string[] = []
  for (const token of tokens) {
    const isSluitend = token.startsWith('</')
    const isZelfsluitendOfDeclaratie = /\/>\s*$/.test(token) || token.startsWith('<?')
    if (isSluitend) diepte = Math.max(0, diepte - 1)
    regels.push('  '.repeat(diepte) + token)
    if (!isSluitend && !isZelfsluitendOfDeclaratie) diepte += 1
  }
  return regels.join('\n')
}

interface Bijlage {
  url: string
  contentType: string
  xmlTekst: string | null
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
      const contentType = resp.headers.get('content-type') ?? 'application/octet-stream'
      objectUrl = URL.createObjectURL(blob)
      const xmlTekst = contentType.includes('xml') ? formatteerXml(await blob.text()) : null
      if (actief) setBijlage({ url: objectUrl, contentType, xmlTekst })
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

      <div className="review">
        <div className="docpane">
          <div className="panel">
            <h2>Bijlage</h2>
            <div className="bijlage-inhoud">
              {!bijlage && <p className="hint">Bijlage laden…</p>}
              {bijlage?.contentType.includes('pdf') && (
                <object data={bijlage.url} type="application/pdf">
                  <p className="hint">
                    Geen inline PDF-weergave in deze browser —{' '}
                    <a href={bijlage.url} download={detail.bestandsnaam}>
                      open het bestand direct
                    </a>
                    .
                  </p>
                </object>
              )}
              {bijlage?.xmlTekst !== null && bijlage?.xmlTekst !== undefined && (
                <pre className="xml-bron">{bijlage.xmlTekst}</pre>
              )}
              {bijlage && !bijlage.contentType.includes('pdf') && bijlage.xmlTekst === null && (
                <p className="hint">Geen inline weergave voor dit bestandstype.</p>
              )}
            </div>
            {bijlage && (
              <p style={{ marginTop: 10 }}>
                <a className="btn secondary" href={bijlage.url} download={detail.bestandsnaam}>
                  Downloaden
                </a>
              </p>
            )}
          </div>
        </div>

        <div className="formpane">
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
            onHersteld={laadDetail}
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
                          Document binnengekomen — status <b>{statusLabel(g.naar_status)}</b>
                          {detail.mogelijk_duplicaat_van && (
                            <div className="hint" style={{ marginTop: 2 }}>
                              Mogelijk duplicaat van{' '}
                              <Link to={`/documenten/${administratieId}/${detail.mogelijk_duplicaat_van.document_id}`}>
                                {detail.mogelijk_duplicaat_van.bestandsnaam} (
                                {formatDatumKort(detail.mogelijk_duplicaat_van.aangemaakt_op)})
                              </Link>
                              — beoordelen
                            </div>
                          )}
                        </>
                      )}
                      {g.detail && 'ubl_parse_fout' in g.detail && (
                        <div className="hint" style={{ marginTop: 2 }}>
                          UBL-parsefout: {String(g.detail.ubl_parse_fout)}
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
