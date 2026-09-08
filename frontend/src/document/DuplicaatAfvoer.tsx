import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, apiJson, apiPostJson } from '../api/client'
import type {
  DocumentDetailDto,
  DocumentListItemDto,
  DuplicaatAfmeldingDto,
  DuplicaatAfvoerResponseDto,
  DuplicaatAfvoerStandDto,
  DuplicaatModuleTrefferDto,
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

/** Spiegel van app/documenten/duplicaat_afvoer.py::AFVOERBARE_STATUSSEN — sinds blok A2 04-09 óók ter_accordering en
 * vraag_open (ronde/vraag worden vóór de afvoer mét reden gesloten). */
export const DUPLICAAT_AFVOERBARE_STATUSSEN = ['te_controleren', 'handmatig_afmaken', 'klaar_om_te_boeken', 'ter_accordering', 'vraag_open']

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

/** Blok 1 07-09: leesbare categorie van een module-tegenhanger (harde check "Duplicaat (module)"). */
export const MODULE_CATEGORIE_LABEL: Record<string, string> = {
  bestand: 'zelfde bestand',
  referentie_bedrag: 'zelfde referentie + bedrag',
  crediteur_referentie: 'zelfde crediteur + referentie (ander bedrag)',
}

interface AfmeldDialogProps {
  administratieId: string
  documentId: string
  treffers: DuplicaatModuleTrefferDto[]
  onAfgemeld: (afmelding: DuplicaatAfmeldingDto) => void
  onAnnuleren: () => void
}

/** "Geen duplicaat — afmelden" (blok 1 07-09): de ENIGE mens-override op de harde check "Duplicaat (module)".
 * Reden verplicht; de afmelding geldt voor precies deze tegenhangers (beide kanten) — een nieuw exemplaar blokkeert
 * weer. Geen statuswissel: tijdlijnregel + audit. */
export function DuplicaatAfmeldenDialog({ administratieId, documentId, treffers, onAfgemeld, onAnnuleren }: AfmeldDialogProps) {
  const [reden, setReden] = useState('')
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  const bevestig = async () => {
    if (!reden.trim()) {
      setFout('Een reden is verplicht.')
      return
    }
    setBezig(true)
    setFout(null)
    try {
      const afmelding = await apiPostJson<DuplicaatAfmeldingDto>(
        `/administraties/${administratieId}/documenten/${documentId}/duplicaat-afmelden`,
        { reden: reden.trim() },
      )
      onAfgemeld(afmelding)
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Afmelden mislukt.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onAnnuleren()}>
      <DialogContent aria-describedby={undefined} data-testid="duplicaat-afmelden-dialoog">
        <DialogTitle>Geen duplicaat — afmelden</DialogTitle>
        <DialogDescription>
          Je verklaart dat dit document géén duplicaat is van {treffers.length === 1 ? 'het onderstaande document' : `de ${treffers.length} onderstaande documenten`}.
          De controle &ldquo;Duplicaat (module)&rdquo; wordt daarna groen voor precies deze tegenhanger(s); een nieuw
          exemplaar blokkeert opnieuw. Reden verplicht (audit).
        </DialogDescription>
        <ul style={{ margin: '4px 0 8px', paddingLeft: 18, fontSize: 12.5 }}>
          {treffers.map((t) => (
            <li key={t.document_id}>
              {t.bestandsnaam} — {MODULE_CATEGORIE_LABEL[t.categorie] ?? t.categorie} ({t.status.replace(/_/g, ' ')})
            </li>
          ))}
        </ul>
        <label style={{ display: 'grid', gap: 4, fontSize: 12 }}>
          Reden
          <textarea value={reden} onChange={(e) => setReden(e.target.value)} rows={3} required aria-label="Reden" />
        </label>
        {fout && <div className="fout">{fout}</div>}
        <DialogFooter>
          <Button type="button" variant="secundair" onClick={onAnnuleren} disabled={bezig}>
            Annuleren
          </Button>
          <Button type="button" onClick={() => void bevestig()} disabled={bezig || !reden.trim()}>
            {bezig ? 'Bezig…' : 'Afmelden als geen duplicaat'}
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
  const [afmeldenOpen, setAfmeldenOpen] = useState(false)
  if (!stand) return null
  const kandidaat = DUPLICAAT_AFVOERBARE_STATUSSEN.includes(status) ? stand.kandidaat : null
  // Blok 3 (fixrun 08-09): de eigen status; 'afgewezen' blijft ernaast geaccepteerd voor
  // niet-gebackfilde legacy-rijen (van vóór deze deploy, zie duplicaat-status-backfill).
  const is_afgevoerd_status = status === 'afgevoerd_duplicaat' || status === 'afgewezen'
  const afgevoerdVan = is_afgevoerd_status ? stand.afgevoerd_als_duplicaat_van : null
  const afgevoerde = stand.afgevoerde_duplicaten
  // Blok 1 07-09: module-tegenhangers (harde check rood) — alleen op een niet-afgevoerd document.
  const moduleTreffers = is_afgevoerd_status ? [] : (stand.module_treffers ?? [])
  const afmelding = stand.afmelding ?? null
  if (!kandidaat && !afgevoerdVan && afgevoerde.length === 0 && moduleTreffers.length === 0 && !afmelding) return null
  return (
    <>
      {(kandidaat || moduleTreffers.length > 0) && (
        <div className="panel" data-testid={kandidaat ? 'duplicaat-kandidaat' : 'duplicaat-module'}>
          <h2>
            Duplicaat gevonden <span className="chip vraag">{kandidaat ? 'harde match' : 'controle rood'}</span>
          </h2>
          {kandidaat ? (
            <p className="hint" style={{ marginTop: 0 }}>
              Zelfde bestand of zelfde referentie + totaalbedrag als een {kandidaat.bron === 'geboekt' ? 'al geboekte' : 'oudere'} factuur.
              Afvoeren zet dit document op Afgewezen mét kruisverwijzing; het origineel blijft staan.
            </p>
          ) : (
            <p className="hint" style={{ marginTop: 0 }}>
              De controle &ldquo;Duplicaat (module)&rdquo; blokkeert boeken: een ander document in deze administratie lijkt
              hetzelfde stuk. Is het géén duplicaat (deelfactuur, creditnota met hetzelfde nummer)? Meld het af mét reden.
            </p>
          )}
          {kandidaat && <OrigineelRegel administratieId={administratieId} origineel={kandidaat} />}
          {moduleTreffers.length > 0 && (
            <ul style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 12.5 }} data-testid="duplicaat-module-lijst">
              {moduleTreffers.map((t) => (
                <li key={t.document_id}>
                  <Link to={`/documenten/${administratieId}/${t.document_id}`} onClick={(e) => e.stopPropagation()}>
                    {t.bestandsnaam}
                  </Link>{' '}
                  — {MODULE_CATEGORIE_LABEL[t.categorie] ?? t.categorie}
                  {t.referentie ? ` · ${t.referentie}` : ''} <span className="chip">{t.status.replace(/_/g, ' ')}</span>
                </li>
              ))}
            </ul>
          )}
          <div className="actions">
            {kandidaat && (
              <button type="button" className="btn secondary" onClick={() => setDialoogOpen(true)}>
                Afvoeren als duplicaat…
              </button>
            )}
            {moduleTreffers.length > 0 && (
              <button type="button" className="linkbtn" onClick={() => setAfmeldenOpen(true)}>
                Geen duplicaat — afmelden…
              </button>
            )}
          </div>
        </div>
      )}
      {afmelding && moduleTreffers.length === 0 && !is_afgevoerd_status && (
        <p className="hint" data-testid="duplicaat-afgemeld">
          Afgemeld als geen duplicaat door {naamVoor(afmelding.actor_id)} op {formatDatumKort(afmelding.tijdstip)}:
          &ldquo;{afmelding.reden}&rdquo;
        </p>
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
      {afmeldenOpen && moduleTreffers.length > 0 && (
        <DuplicaatAfmeldenDialog
          administratieId={administratieId}
          documentId={documentId}
          treffers={moduleTreffers}
          onAfgemeld={() => {
            setAfmeldenOpen(false)
            onGewijzigd()
          }}
          onAnnuleren={() => setAfmeldenOpen(false)}
        />
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
