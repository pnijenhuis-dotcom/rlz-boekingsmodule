import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, apiJson, apiPostJson } from '../api/client'
import type {
  DocumentDetailDto,
  DocumentListItemDto,
  DuplicaatAfvoerResponseDto,
  DuplicaatAfvoerStandDto,
  DuplicaatOrigineelDto,
} from '../api/types'
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from '../ui/basis'
import { formatDatumKort } from '../werkvoorraad/format'

/** Duplicaat-afvoer (besluit Peter 04-09, migratie 0105). Eén-klik "Afvoeren als duplicaat" — altijd
 * beschikbaar, ook zonder de per-administratie opt-in voor het automatische pad — mét bevestigingsdialoog
 * waarin het gevonden origineel als voorstel-kaart-regel staat; geen vrije reden (de reden is
 * deterministisch: "Duplicaat van ‹referentie› (…)"). Plus de kruisverwijzing op het controlescherm:
 * afgevoerd-kant ("Duplicaat van … → open origineel") en origineel-kant ("N duplicaten afgevoerd").
 * Nooit verwijderen — terughalen via de bestaande Heropenen-knop. */

/** Spiegel van app/documenten/duplicaat_afvoer.py::AFVOERBARE_STATUSSEN. */
export const DUPLICAAT_AFVOERBARE_STATUSSEN = ['te_controleren', 'handmatig_afmaken', 'klaar_om_te_boeken']

/** Rijmenu-regel: alleen zichtbaar bij een harde-match-signaal (gecachete RLZ-/Odoo-treffer óf een
 * werkvoorraad-origineel) én een status die afvoeren toelaat. */
export function toonAfvoerenAlsDuplicaat(d: DocumentListItemDto): boolean {
  if (d.soort !== 'inkoopfactuur') return false
  if (!DUPLICAAT_AFVOERBARE_STATUSSEN.includes(d.status)) return false
  return d.duplicaatsignaal?.uitkomst === 'mogelijk_duplicaat' || Boolean(d.duplicaat_werkvoorraad_van)
}

export function origineelLabel(o: DuplicaatOrigineelDto): string {
  const delen: string[] = []
  if (o.bestandsnaam) delen.push(o.bestandsnaam)
  if (o.aangemaakt_op) delen.push(formatDatumKort(o.aangemaakt_op))
  if (o.boekstuknummer) delen.push(`boekstuk ${o.boekstuknummer}`)
  const staat = o.bron === 'geboekt' ? 'al geboekt' : 'in de werkvoorraad'
  return delen.length ? `${delen.join(' · ')} — ${staat}` : staat
}

/** Voorstel-kaart-achtige regel voor het origineel: referentie vet, herkomst eronder, link als er een
 * app-document is (een RLZ-/Odoo-origineel zonder app-document toont alleen referentie/boekstuk). */
export function OrigineelRegel({ administratieId, origineel }: { administratieId: string; origineel: DuplicaatOrigineelDto }) {
  return (
    <div className="q-item" style={{ marginBottom: 0 }} data-testid="duplicaat-origineel">
      <div>
        <b>{origineel.referentie}</b>{' '}
        <span className={`chip ${origineel.bron === 'geboekt' ? 'geheugen' : 'vraag'}`}>
          {origineel.bron === 'geboekt' ? 'geboekt' : 'werkvoorraad'}
        </span>
      </div>
      <div className="meta">
        {origineelLabel(origineel)}
        {origineel.document_id && (
          <>
            {' · '}
            <Link to={`/documenten/${administratieId}/${origineel.document_id}`} onClick={(e) => e.stopPropagation()}>
              open origineel
            </Link>
          </>
        )}
      </div>
    </div>
  )
}

interface DialogProps {
  administratieId: string
  documentId: string
  bestandsnaam: string
  /** Al bekend (controlescherm)? Dan geen extra detail-call; anders haalt de dialoog de stand zelf op. */
  kandidaat?: DuplicaatOrigineelDto | null
  onAfgevoerd: (resultaat: DuplicaatAfvoerResponseDto) => void
  onAnnuleren: () => void
}

export function DuplicaatAfvoerDialog({ administratieId, documentId, bestandsnaam, kandidaat, onAfgevoerd, onAnnuleren }: DialogProps) {
  const [origineel, setOrigineel] = useState<DuplicaatOrigineelDto | null | undefined>(kandidaat)
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  useEffect(() => {
    if (kandidaat !== undefined) return
    let actueel = true
    apiJson<DocumentDetailDto>(`/administraties/${administratieId}/documenten/${documentId}`)
      .then((detail) => {
        if (!actueel) return
        setOrigineel(detail.duplicaat_afvoer?.kandidaat ?? null)
      })
      .catch((err: unknown) => {
        if (actueel) setLaadFout(err instanceof Error ? err.message : 'Origineel niet te bepalen.')
      })
    return () => {
      actueel = false
    }
  }, [administratieId, documentId, kandidaat])

  const bevestig = async () => {
    setBezig(true)
    setFout(null)
    try {
      const resultaat = await apiPostJson<DuplicaatAfvoerResponseDto>(
        `/administraties/${administratieId}/documenten/${documentId}/afvoeren-als-duplicaat`,
        {},
      )
      onAfgevoerd(resultaat)
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Afvoeren mislukt.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onAnnuleren()}>
      <DialogContent aria-describedby={undefined} data-testid="duplicaat-afvoer-dialoog">
        <DialogTitle>Afvoeren als duplicaat</DialogTitle>
        <DialogDescription>
          <b>{bestandsnaam}</b> gaat naar <b>Afgewezen</b> met de reden &ldquo;Duplicaat van …&rdquo; en een
          kruisverwijzing naar het origineel. Er wordt niets verwijderd — terughalen kan via Heropenen.
        </DialogDescription>
        {origineel === undefined && !laadFout && <p className="hint">Origineel bepalen…</p>}
        {laadFout && <div className="fout">{laadFout}</div>}
        {origineel === null && !laadFout && (
          <div className="fout">
            Geen harde duplicaat-match (meer): crediteur, referentie en totaalbedrag komen niet alle drie overeen met een
            geboekte of oudere factuur.
          </div>
        )}
        {origineel && <OrigineelRegel administratieId={administratieId} origineel={origineel} />}
        {fout && <div className="fout">{fout}</div>}
        <DialogFooter>
          <Button type="button" variant="secundair" onClick={onAnnuleren} disabled={bezig}>
            Annuleren
          </Button>
          <Button type="button" onClick={() => void bevestig()} disabled={bezig || !origineel}>
            {bezig ? 'Bezig…' : 'Afvoeren als duplicaat'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

interface SectieProps {
  administratieId: string
  documentId: string
  bestandsnaam: string
  status: string
  stand: DuplicaatAfvoerStandDto | null | undefined
  naamVoor: (id: string) => string
  onGewijzigd: () => void
}

/** Controlescherm: (1) kandidaat → paneel mét één knop "Afvoeren als duplicaat" (btn secondary — het is een
 * afvoer-actie, niet dé besluitknop); (2) afgevoerd → regel "Duplicaat van … → open origineel" (de
 * afgewezen-banner mét Heropenen staat er los onder); (3) origineel-kant → "N duplicaten afgevoerd". */
export function DuplicaatAfvoerSectie({ administratieId, documentId, bestandsnaam, status, stand, naamVoor, onGewijzigd }: SectieProps) {
  const [dialoogOpen, setDialoogOpen] = useState(false)
  if (!stand) return null
  const kandidaat = DUPLICAAT_AFVOERBARE_STATUSSEN.includes(status) ? stand.kandidaat : null
  const afgevoerdVan = status === 'afgewezen' ? stand.afgevoerd_als_duplicaat_van : null
  const afgevoerde = stand.afgevoerde_duplicaten
  if (!kandidaat && !afgevoerdVan && afgevoerde.length === 0) return null
  return (
    <>
      {kandidaat && (
        <div className="panel" data-testid="duplicaat-kandidaat">
          <h2>
            Duplicaat gevonden <span className="chip vraag">harde match</span>
          </h2>
          <p className="hint" style={{ marginTop: 0 }}>
            Zelfde crediteur, referentie en totaalbedrag als een {kandidaat.bron === 'geboekt' ? 'al geboekte' : 'oudere'} factuur.
            Afvoeren zet dit document op Afgewezen mét kruisverwijzing; het origineel blijft staan.
          </p>
          <OrigineelRegel administratieId={administratieId} origineel={kandidaat} />
          <div className="actions">
            <button type="button" className="btn secondary" onClick={() => setDialoogOpen(true)}>
              Afvoeren als duplicaat…
            </button>
          </div>
        </div>
      )}
      {afgevoerdVan && (
        <div className="panel" data-testid="duplicaat-afgevoerd">
          <h2>
            Afgevoerd als duplicaat <span className="chip geheugen">duplicaat</span>
          </h2>
          <OrigineelRegel administratieId={administratieId} origineel={afgevoerdVan} />
        </div>
      )}
      {afgevoerde.length > 0 && (
        <div className="panel" data-testid="duplicaat-afgevoerde-lijst">
          <h2>
            {afgevoerde.length === 1 ? '1 duplicaat afgevoerd' : `${afgevoerde.length} duplicaten afgevoerd`}
          </h2>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {afgevoerde.map((d) => (
              <li key={d.afwijzing_id} style={{ fontSize: 12.5 }}>
                <Link to={`/documenten/${administratieId}/${d.document_id}`}>{d.bestandsnaam}</Link> ({formatDatumKort(d.aangemaakt_op)}) —
                afgevoerd {formatDatumKort(d.afgewezen_op)} door {d.automatisch ? '⚙ systeem' : naamVoor(d.afgewezen_door)}
              </li>
            ))}
          </ul>
        </div>
      )}
      {dialoogOpen && kandidaat && (
        <DuplicaatAfvoerDialog
          administratieId={administratieId}
          documentId={documentId}
          bestandsnaam={bestandsnaam}
          kandidaat={kandidaat}
          onAfgevoerd={() => {
            setDialoogOpen(false)
            onGewijzigd()
          }}
          onAnnuleren={() => setDialoogOpen(false)}
        />
      )}
    </>
  )
}
