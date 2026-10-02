/**
 * Bijlagen bij de factuur (Peter 02-10 "één mail = één document", migratie 0174): de niet-factuur-bijlagen uit dezelfde
 * mail (specificatie, huurstaat, werkbon, foto, xlsx/csv) hangen aan de factuur en zijn hier als tabbladen in het
 * bijlage-paneel te bekijken — "Factuur" + één tab per bijlage (chip "niet eenduidig" als de bijlage bij meerdere
 * facturen uit die mail hangt). De bytes komen van `GET …/documenten/{factuur}/bijlagen/{id}/bestand`; PDF inline,
 * afbeelding als <img>, elk ander type = downloadknop (geen inline weergave). Geen bijlagen = geen tabbalk.
 */
import { useEffect, useState } from 'react'

import { apiFetch } from '../api/client'
import type { DocumentBijlageDto } from '../api/types'
import { metViewerOpties } from './pdfWeergaveUrl'

export const FACTUUR_TAB = 'factuur'

export function BijlageTabs({
  bijlagen,
  keuze,
  onKeuze,
  factuurLabel = 'Factuur',
}: {
  bijlagen: DocumentBijlageDto[]
  keuze: string
  onKeuze: (keuze: string) => void
  factuurLabel?: string
}) {
  if (bijlagen.length === 0) return null
  return (
    <div className="segment compact" role="tablist" aria-label="Factuur en bijlagen" style={{ marginBottom: 10, flexWrap: 'wrap' }}>
      <button
        type="button"
        role="tab"
        aria-selected={keuze === FACTUUR_TAB}
        className={keuze === FACTUUR_TAB ? 'actief' : undefined}
        onClick={() => onKeuze(FACTUUR_TAB)}
      >
        {factuurLabel}
      </button>
      {bijlagen.map((b) => (
        <button
          key={b.id}
          type="button"
          role="tab"
          aria-selected={keuze === b.id}
          className={keuze === b.id ? 'actief' : undefined}
          onClick={() => onKeuze(b.id)}
          title={
            b.niet_eenduidig
              ? 'Deze bijlage kwam uit een e-mail met meerdere facturen zonder eenduidige verwijzing — hij hangt aan álle facturen uit die mail'
              : 'Bijlage uit dezelfde e-mail als de factuur'
          }
          data-testid={`bijlage-tab-${b.id}`}
        >
          {b.bestandsnaam}
          {b.niet_eenduidig && (
            <span className="chip warn" style={{ marginLeft: 6 }}>
              niet eenduidig
            </span>
          )}
        </button>
      ))}
    </div>
  )
}

interface BijlageInhoud {
  url: string
  contentType: string
}

/** De weergave van één bijlage (laadt de bytes zelf; blob-URL wordt bij wissel/unmount vrijgegeven). */
export function BijlageWeergave({
  administratieId,
  documentId,
  bijlage,
}: {
  administratieId: string
  documentId: string
  bijlage: DocumentBijlageDto
}) {
  const [inhoud, setInhoud] = useState<BijlageInhoud | null>(null)
  const [fout, setFout] = useState<string | null>(null)

  useEffect(() => {
    let actief = true
    let objectUrl: string | null = null
    setInhoud(null)
    setFout(null)
    void apiFetch(`/administraties/${administratieId}/documenten/${documentId}/bijlagen/${bijlage.id}/bestand`).then(
      async (resp) => {
        if (!actief) return
        if (!resp.ok) {
          setFout(resp.status === 404 ? 'Deze bijlage hangt niet (meer) aan dit document.' : `Bijlage niet te laden (${resp.status}).`)
          return
        }
        const blob = await resp.blob()
        const contentType = resp.headers.get('content-type') ?? bijlage.content_type
        objectUrl = URL.createObjectURL(blob)
        if (actief) setInhoud({ url: objectUrl, contentType })
      },
      () => {
        if (actief) setFout('Bijlage niet te laden.')
      },
    )
    return () => {
      actief = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [administratieId, documentId, bijlage.id, bijlage.content_type])

  if (fout) return <p className="fout">{fout}</p>
  if (!inhoud) return <p className="hint">Bijlage wordt geladen…</p>
  const isPdf = inhoud.contentType.includes('pdf')
  const isAfbeelding = inhoud.contentType.startsWith('image/')
  return (
    <>
      {isPdf && (
        <object key={inhoud.url} data={metViewerOpties(inhoud.url)} type="application/pdf" data-testid="bijlage-tab-pdf">
          <p className="hint">
            Geen inline PDF-weergave in deze browser —{' '}
            <a href={inhoud.url} download={bijlage.bestandsnaam}>
              open het bestand direct
            </a>
            .
          </p>
        </object>
      )}
      {isAfbeelding && (
        <img
          src={inhoud.url}
          alt={bijlage.bestandsnaam}
          style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }}
          data-testid="bijlage-tab-afbeelding"
        />
      )}
      {!isPdf && !isAfbeelding && (
        <p className="hint" data-testid="bijlage-tab-download">
          Geen inline weergave voor dit bestandstype —{' '}
          <a className="btn secondary" href={inhoud.url} download={bijlage.bestandsnaam}>
            Downloaden ({bijlage.bestandsnaam})
          </a>
        </p>
      )}
    </>
  )
}
