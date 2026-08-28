import { useCallback, useEffect, useState } from 'react'
import { ApiError, apiFetch } from '../api/client'
import type { AdministratieDto } from '../api/types'
import {
  beoordeelDossierDocument,
  bevestigBedrijfsgegevens,
  dossierBestandPad,
  haalDossier,
  herinnerDossier,
  uploadDossierDocument,
  zoekKvk,
  type DossierDocumentDto,
  type DossierDto,
  type KvkLookupDto,
  type VeldgebruikerDto,
} from '../meerwerk/meerwerkApi'
import { Badge, Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle, FormField, useToastOptioneel, SkeletonRegels, SkeletonBlok } from '../ui/basis'
import { AdministratieCombobox } from '../ui/AdministratieCombobox'

/* ZZP-dossier per veldwerker (steigerbouw-run A1–A3, mockup meerwerk-kantoor.html "📁 Dossier"
 * = norm): KvK-/btw-blok (lookup → mens bevestigt), documententabel per type met status/geldig-
 * tot, upload (→ ter controle), ✓ Goedkeuren / Afwijzen… (reden verplicht), herinner-knop "N van
 * 3" + blokkade-badge. Kopie ID = BSN-regel: nooit extraheren/indexeren, weergave standaard
 * gemaskeerd (blur, klik-en-houd om te lezen), elke inzage server-side geauditeerd. */

export function dossierBadge(info: VeldgebruikerDto | undefined): { variant: 'ok' | 'warn' | 'danger'; label: string } | null {
  const dossiers = info?.dossiers ?? []
  if (!info || dossiers.length === 0) return null
  const geblokkeerd = dossiers.some((d) => d.geblokkeerd)
  const ontbrekend = dossiers.reduce((som, d) => som + d.aantal_ontbrekend + d.aantal_verlopen, 0)
  const binnenkort = dossiers.reduce((som, d) => som + d.aantal_verloopt_binnenkort, 0)
  const terControle = dossiers.reduce((som, d) => som + d.aantal_ter_controle, 0)
  const aanwezig = dossiers.reduce((som, d) => som + d.aantal_aanwezig, 0)
  const verplicht = dossiers.reduce((som, d) => som + d.aantal_verplicht, 0)
  if (geblokkeerd) return { variant: 'danger', label: `📁 dossier ${aanwezig}/${verplicht} · geblokkeerd` }
  if (ontbrekend > 0) return { variant: 'danger', label: `📁 dossier ${aanwezig}/${verplicht}` }
  if (terControle > 0) return { variant: 'warn', label: `📁 dossier ${aanwezig}/${verplicht} · ${terControle} ter controle` }
  if (binnenkort > 0) return { variant: 'warn', label: `📁 dossier compleet · verloopt binnenkort` }
  return { variant: 'ok', label: '📁 dossier compleet' }
}

function statusBadge(d: DossierDocumentDto) {
  switch (d.status) {
    case 'ontbreekt':
      return d.verplicht ? <Badge variant="danger">ontbreekt</Badge> : <Badge variant="stil">niet verplicht — ontbreekt</Badge>
    case 'ter_controle':
      return (
        <Badge variant="info">
          ter controle — geüpload door {d.geupload_door_naam ?? '?'} ({d.bron === 'app' ? 'app' : 'kantoor'}), {datumKort(d.geupload_op)}
        </Badge>
      )
    case 'afgewezen':
      return (
        <Badge variant="danger" title={d.afwijs_reden ?? undefined}>
          afgewezen{d.afwijs_reden ? `: ${d.afwijs_reden}` : ''}
        </Badge>
      )
    case 'goedgekeurd':
      return <Badge variant="ok">aanwezig</Badge>
    case 'verloopt_binnenkort':
      return <Badge variant="warn">verloopt over {d.verloopt_over_dagen} dagen</Badge>
    case 'verlopen':
      return <Badge variant="danger">verlopen {datumKort(d.geldig_tot)}</Badge>
  }
}

function datumKort(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('nl-NL', { day: '2-digit', month: '2-digit', year: 'numeric' })
}

export function DossierModal({
  veldwerker,
  administraties,
  onSluiten,
  onGewijzigd,
}: {
  veldwerker: VeldgebruikerDto
  administraties: AdministratieDto[]
  onSluiten: () => void
  onGewijzigd: () => void
}) {
  const { meld } = useToastOptioneel()
  const keuzes = (veldwerker.dossiers ?? []).length > 0
    ? veldwerker.dossiers.map((d) => ({ id: d.administratie_id, naam: d.administratie_naam ?? d.administratie_id }))
    : administraties.map((a) => ({ id: a.id, naam: a.naam }))
  const [administratieId, setAdministratieId] = useState(keuzes[0]?.id ?? '')
  const [dossier, setDossier] = useState<DossierDto | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const [uploadVoor, setUploadVoor] = useState<DossierDocumentDto | null>(null)
  const [afwijsVoor, setAfwijsVoor] = useState<DossierDocumentDto | null>(null)
  const [bekijk, setBekijk] = useState<DossierDocumentDto | null>(null)

  const laad = useCallback(() => {
    if (!administratieId) return
    setFout(null)
    haalDossier(administratieId, veldwerker.gebruiker_id)
      .then(setDossier)
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Dossier laden mislukt'))
  }, [administratieId, veldwerker.gebruiker_id])
  useEffect(() => {
    laad()
  }, [laad])

  async function actie(f: () => Promise<DossierDto>, melding: string) {
    setBezig(true)
    setFout(null)
    try {
      setDossier(await f())
      meld(melding)
      onGewijzigd()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Actie mislukt.')
    } finally {
      setBezig(false)
    }
  }

  async function herinner() {
    if (!dossier) return
    setBezig(true)
    setFout(null)
    try {
      const r = await herinnerDossier(administratieId, veldwerker.gebruiker_id)
      meld(
        `Herinnering ${r.volgnummer} van ${dossier.herinneringen_max} verstuurd via ${r.kanaal}${r.geblokkeerd ? ' — weekstaat-indienen is nu geblokkeerd' : ''}.`,
      )
      laad()
      onGewijzigd()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Herinneren mislukt.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onSluiten()}>
      <DialogContent className="max-w-[860px]">
        <DialogTitle>
          📁 Dossier — {veldwerker.naam} ({veldwerker.rol === 'zzper' ? "ZZP'er" : 'uitvoerder'})
        </DialogTitle>
        <DialogDescription>
          Verplichte documenten voor het inleners-/WKA-dossier, per type met geldig-tot en signalering. Een upload staat
          eerst <b>ter controle</b>; pas ná goedkeuring telt het document als aanwezig. Kopie ID: BSN wordt nooit
          geëxtraheerd of geïndexeerd; weergave gemaskeerd, elke inzage geauditeerd.
        </DialogDescription>
        {keuzes.length > 1 && (
          <AdministratieCombobox
            label="Administratie"
            administraties={keuzes}
            waarde={administratieId}
            onWijzig={setAdministratieId}
          />
        )}
        {fout && <div className="fout">{fout}</div>}
        {dossier === null && !fout && <SkeletonRegels />}
        {dossier !== null && (
          <>
            <BedrijfsgegevensBlok
              dossier={dossier}
              bezig={bezig}
              onBevestig={(payload) =>
                actie(() => bevestigBedrijfsgegevens(administratieId, veldwerker.gebruiker_id, payload), 'Bedrijfsgegevens bevestigd — geauditeerd.')
              }
            />
            <div className="tabel-scroll">
              <table>
                <tbody>
                  <tr>
                    <th>Document</th>
                    <th>Status</th>
                    <th>Geldig tot</th>
                    <th className="acties" />
                  </tr>
                  {dossier.documenten.map((d) => (
                    <tr key={d.code}>
                      <td>
                        <b>{d.naam}</b>
                        {!d.verplicht && <div style={{ fontSize: 11, color: 'var(--muted)' }}>optioneel</div>}
                        {d.bsn_gevoelig && <div style={{ fontSize: 11, color: 'var(--muted)' }}>BSN-gevoelig — gemaskeerde weergave</div>}
                      </td>
                      <td>{statusBadge(d)}</td>
                      <td>{d.geldig_tot ? datumKort(d.geldig_tot) : '—'}</td>
                      <td className="acties" style={{ whiteSpace: 'nowrap', textAlign: 'right' }}>
                        {d.status === 'ter_controle' && (
                          <>
                            <Button
                              maat="klein"
                              disabled={bezig}
                              onClick={() =>
                                actie(
                                  () => beoordeelDossierDocument(administratieId, d.document_id!, { goedgekeurd: true }),
                                  `${d.naam} goedgekeurd.`,
                                )
                              }
                            >
                              ✓ Goedkeuren
                            </Button>{' '}
                            <Button variant="secundair" maat="klein" disabled={bezig} onClick={() => setAfwijsVoor(d)}>
                              Afwijzen…
                            </Button>{' '}
                          </>
                        )}
                        {d.document_id && (
                          <Button variant="ghost" maat="klein" onClick={() => setBekijk(d)}>
                            {d.bsn_gevoelig ? 'bekijk (gemaskeerd)' : 'bekijk'}
                          </Button>
                        )}{' '}
                        <Button variant="ghost" maat="klein" disabled={bezig} onClick={() => setUploadVoor(d)}>
                          {d.document_id ? 'vervang' : 'uploaden…'}
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginTop: 12, flexWrap: 'wrap' }}>
              <Button
                variant="secundair"
                maat="klein"
                disabled={bezig || !dossier.kan_herinneren_vandaag}
                title={
                  dossier.compleet_incl_ter_controle
                    ? 'Alle verplichte documenten zijn aanwezig of ter controle'
                    : dossier.kan_herinneren_vandaag
                      ? 'Push (anders mail) via de app — max. 1 per dag'
                      : 'Vandaag al herinnerd — max. 1 per dag'
                }
                onClick={() => void herinner()}
              >
                🔔 Herinner {veldwerker.naam} ({dossier.herinneringen_teller} van {dossier.herinneringen_max} verstuurd
                {dossier.laatste_herinnering_op ? ` — laatst ${datumKort(dossier.laatste_herinnering_op)}` : ''})
              </Button>
              {dossier.geblokkeerd ? (
                <Badge variant="danger">weekstaat-indienen geblokkeerd tot het dossier compleet is</Badge>
              ) : (
                <Badge variant="warn">na de 3e herinnering: weekstaat-invoer geblokkeerd tot het dossier compleet is</Badge>
              )}
            </div>
            {dossier.signalen.length > 0 && (
              <p className="hint" style={{ marginTop: 8 }}>
                Signalen: {dossier.signalen.join(' · ')}
              </p>
            )}
          </>
        )}
        <DialogFooter>
          <Button variant="secundair" onClick={onSluiten} disabled={bezig}>
            Sluiten
          </Button>
        </DialogFooter>
      </DialogContent>
      {uploadVoor && dossier && (
        <UploadDialog
          type={uploadVoor}
          onSluiten={() => setUploadVoor(null)}
          onUpload={(bestand, geldigTot) =>
            actie(
              () => uploadDossierDocument(administratieId, veldwerker.gebruiker_id, { type_code: uploadVoor.code, geldig_tot: geldigTot, bestand }),
              `${uploadVoor.naam} geüpload — ter controle.`,
            ).then(() => setUploadVoor(null))
          }
        />
      )}
      {afwijsVoor && (
        <AfwijsDialog
          type={afwijsVoor}
          onSluiten={() => setAfwijsVoor(null)}
          onAfwijzen={(reden) =>
            actie(
              () => beoordeelDossierDocument(administratieId, afwijsVoor.document_id!, { goedgekeurd: false, reden }),
              `${afwijsVoor.naam} afgewezen — de veldwerker ziet de reden in de app.`,
            ).then(() => setAfwijsVoor(null))
          }
        />
      )}
      {bekijk && bekijk.document_id && (
        <BekijkDialog administratieId={administratieId} document={bekijk} onSluiten={() => setBekijk(null)} />
      )}
    </Dialog>
  )
}

function BedrijfsgegevensBlok({
  dossier,
  bezig,
  onBevestig,
}: {
  dossier: DossierDto
  bezig: boolean
  onBevestig: (payload: { kvk_nummer: string | null; btw_nummer: string | null; naam: string | null; plaats: string | null; rechtsvorm: string | null }) => Promise<void>
}) {
  const [kvk, setKvk] = useState(dossier.kvk_nummer ?? '')
  const [btw, setBtw] = useState(dossier.btw_nummer ?? '')
  const [lookup, setLookup] = useState<KvkLookupDto | null>(null)
  const [lookupFout, setLookupFout] = useState<string | null>(null)
  const [zoekBezig, setZoekBezig] = useState(false)

  useEffect(() => {
    setKvk(dossier.kvk_nummer ?? '')
    setBtw(dossier.btw_nummer ?? '')
    setLookup(null)
  }, [dossier.kvk_nummer, dossier.btw_nummer, dossier.gebruiker_id, dossier.administratie_id])

  async function zoek() {
    setZoekBezig(true)
    setLookupFout(null)
    setLookup(null)
    try {
      setLookup(await zoekKvk(kvk.trim()))
    } catch (err) {
      setLookupFout(err instanceof ApiError ? err.message : 'KvK-lookup mislukt.')
    } finally {
      setZoekBezig(false)
    }
  }

  const gewijzigd = kvk.trim() !== (dossier.kvk_nummer ?? '') || btw.trim() !== (dossier.btw_nummer ?? '')

  return (
    <div style={{ display: 'flex', gap: 10, marginBottom: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
      <FormField label="KvK-nummer" htmlFor="dossier-kvk" className="!mb-0">
        <div style={{ display: 'flex', gap: 6, width: 220 }}>
          <input id="dossier-kvk" type="text" inputMode="numeric" maxLength={8} value={kvk} onChange={(e) => setKvk(e.target.value.replace(/\D/g, ''))} placeholder="12345678" />
          <Button variant="secundair" maat="klein" disabled={zoekBezig || kvk.trim().length !== 8} onClick={() => void zoek()}>
            {zoekBezig ? '…' : 'Opzoeken'}
          </Button>
        </div>
      </FormField>
      <div style={{ flex: 1, minWidth: 220, fontSize: 12 }}>
        <div style={{ fontWeight: 600, marginBottom: 4 }}>
          Opgehaald via KvK-API{' '}
          {dossier.kvk_bevestigd_op && (
            <Badge variant="ok" title={`Bevestigd door ${dossier.kvk_bevestigd_door_naam ?? '?'} op ${datumKort(dossier.kvk_bevestigd_op)}`}>
              geverifieerd
            </Badge>
          )}
        </div>
        {lookupFout && <div className="fout" style={{ margin: 0 }}>{lookupFout}</div>}
        {lookup && !lookup.gevonden && <span className="hint">KvK-nummer niet gevonden.</span>}
        {lookup && lookup.gevonden && (
          <span>
            {lookup.naam ?? '?'}
            {lookup.rechtsvorm ? ` · ${lookup.rechtsvorm.toLowerCase()}` : ''}
            {lookup.plaats ? ` · ${lookup.plaats}` : ''}
            {lookup.uitgeschreven && <Badge variant="danger">uitgeschreven {lookup.datum_einde}</Badge>}
            {lookup.testomgeving && <Badge variant="stil" title="KVK_API_KEY niet gezet — KvK-testomgeving met fictieve data">testomgeving</Badge>}{' '}
            —{' '}
            <Button
              variant="ghost"
              maat="klein"
              disabled={bezig}
              onClick={() =>
                void onBevestig({
                  kvk_nummer: kvk.trim() || null,
                  btw_nummer: btw.trim() || null,
                  naam: lookup.naam,
                  plaats: lookup.plaats,
                  rechtsvorm: lookup.rechtsvorm,
                })
              }
            >
              bevestigen
            </Button>
          </span>
        )}
        {!lookup && dossier.kvk_naam && (
          <span className="hint">
            {dossier.kvk_naam}
            {dossier.kvk_rechtsvorm ? ` · ${dossier.kvk_rechtsvorm.toLowerCase()}` : ''}
            {dossier.kvk_plaats ? ` · ${dossier.kvk_plaats}` : ''}
          </span>
        )}
        {!lookup && !dossier.kvk_naam && <span className="hint">Vul het KvK-nummer in en klik Opzoeken — een mens bevestigt.</span>}
      </div>
      <FormField label="Btw-nummer" htmlFor="dossier-btw" className="!mb-0">
        <div style={{ display: 'flex', gap: 6 }}>
          <input id="dossier-btw" type="text" value={btw} onChange={(e) => setBtw(e.target.value)} placeholder="NL001234567B01" style={{ width: 170 }} />
          {gewijzigd && !lookup && (
            <Button
              variant="secundair"
              maat="klein"
              disabled={bezig}
              onClick={() =>
                void onBevestig({
                  kvk_nummer: kvk.trim() || null,
                  btw_nummer: btw.trim() || null,
                  naam: dossier.kvk_naam,
                  plaats: dossier.kvk_plaats,
                  rechtsvorm: dossier.kvk_rechtsvorm,
                })
              }
            >
              Opslaan
            </Button>
          )}
        </div>
      </FormField>
    </div>
  )
}

function UploadDialog({
  type,
  onSluiten,
  onUpload,
}: {
  type: DossierDocumentDto
  onSluiten: () => void
  onUpload: (bestand: File, geldigTot: string | null) => Promise<void>
}) {
  const [bestand, setBestand] = useState<File | null>(null)
  const [geldigTot, setGeldigTot] = useState('')
  const [bezig, setBezig] = useState(false)
  const kan = bestand !== null && (!type.geldig_tot_vereist || geldigTot !== '')
  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onSluiten()}>
      <DialogContent>
        <DialogTitle>{type.document_id ? 'Vervang' : 'Upload'} — {type.naam}</DialogTitle>
        <DialogDescription>
          PDF, JPEG of PNG (max. 15 MB). Het document komt <b>ter controle</b> te staan; goedkeuren is een aparte klik.
        </DialogDescription>
        <FormField label="Bestand" htmlFor="dossier-bestand">
          <input id="dossier-bestand" type="file" accept="application/pdf,image/jpeg,image/png" onChange={(e) => setBestand(e.target.files?.[0] ?? null)} />
        </FormField>
        <FormField label={type.geldig_tot_vereist ? 'Geldig tot (verplicht)' : 'Geldig tot (optioneel)'} htmlFor="dossier-geldig">
          <input id="dossier-geldig" type="date" value={geldigTot} onChange={(e) => setGeldigTot(e.target.value)} />
        </FormField>
        <DialogFooter>
          <Button variant="secundair" onClick={onSluiten} disabled={bezig}>
            Annuleren
          </Button>
          <Button
            disabled={!kan || bezig}
            onClick={() => {
              if (!bestand) return
              setBezig(true)
              void onUpload(bestand, geldigTot || null).finally(() => setBezig(false))
            }}
          >
            {bezig ? 'Bezig…' : 'Uploaden'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function AfwijsDialog({ type, onSluiten, onAfwijzen }: { type: DossierDocumentDto; onSluiten: () => void; onAfwijzen: (reden: string) => Promise<void> }) {
  const [reden, setReden] = useState('')
  const [bezig, setBezig] = useState(false)
  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onSluiten()}>
      <DialogContent>
        <DialogTitle>Afwijzen — {type.naam}</DialogTitle>
        <DialogDescription>De reden is verplicht en gaat naar de veldwerker (app). Een afwijzing heractiveert een eventuele blokkade.</DialogDescription>
        <FormField label="Reden" htmlFor="dossier-afwijs-reden">
          <textarea id="dossier-afwijs-reden" rows={3} value={reden} onChange={(e) => setReden(e.target.value)} placeholder="bijv. onleesbare scan, verkeerd document, verlopen polis" />
        </FormField>
        <DialogFooter>
          <Button variant="secundair" onClick={onSluiten} disabled={bezig}>
            Annuleren
          </Button>
          <Button
            variant="gevaar"
            disabled={reden.trim().length < 3 || bezig}
            onClick={() => {
              setBezig(true)
              void onAfwijzen(reden.trim()).finally(() => setBezig(false))
            }}
          >
            {bezig ? 'Bezig…' : 'Afwijzen'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** Weergave via Authorization-fetch + blob (bestanden nooit als navigatie — same-origin-regel).
 * BSN-gevoelig: standaard geblurd; klik-en-houd toont het origineel (inzage is server-side al
 * geauditeerd bij het ophalen). */
function BekijkDialog({ administratieId, document, onSluiten }: { administratieId: string; document: DossierDocumentDto; onSluiten: () => void }) {
  const [url, setUrl] = useState<string | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [onthuld, setOnthuld] = useState(false)
  useEffect(() => {
    let actueel = true
    let objectUrl: string | null = null
    apiFetch(dossierBestandPad(administratieId, document.document_id!))
      .then(async (resp) => {
        if (!resp.ok) throw new Error(`Bestand ophalen mislukt (${resp.status})`)
        objectUrl = URL.createObjectURL(await resp.blob())
        if (actueel) setUrl(objectUrl)
      })
      .catch((err: unknown) => actueel && setFout(err instanceof Error ? err.message : 'Bestand ophalen mislukt'))
    return () => {
      actueel = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [administratieId, document.document_id])
  const isPdf = (document.content_type ?? '').includes('pdf')
  return (
    <Dialog open onOpenChange={(open) => !open && onSluiten()}>
      <DialogContent className="max-w-[900px]">
        <DialogTitle>
          {document.naam} — {document.bestandsnaam ?? 'document'}
        </DialogTitle>
        {document.bsn_gevoelig && (
          <DialogDescription>
            Gemaskeerde weergave (BSN-regel). Houd de muisknop ingedrukt op het document om het te lezen — deze inzage is
            geauditeerd.
          </DialogDescription>
        )}
        {fout && <div className="fout">{fout}</div>}
        {!url && !fout && <SkeletonBlok hoogte={420} />}
        {url && (
          <div
            style={{ position: 'relative', height: '70vh', filter: document.bsn_gevoelig && !onthuld ? 'blur(14px)' : 'none', transition: 'filter .15s', userSelect: 'none' }}
            onMouseDown={() => setOnthuld(true)}
            onMouseUp={() => setOnthuld(false)}
            onMouseLeave={() => setOnthuld(false)}
            onTouchStart={() => setOnthuld(true)}
            onTouchEnd={() => setOnthuld(false)}
          >
            {isPdf ? (
              <iframe title={document.naam} src={url} style={{ width: '100%', height: '100%', border: 0, pointerEvents: document.bsn_gevoelig ? 'none' : 'auto' }} />
            ) : (
              <img alt={document.naam} src={url} style={{ maxWidth: '100%', maxHeight: '100%', display: 'block', margin: '0 auto' }} />
            )}
          </div>
        )}
        <DialogFooter>
          <Button variant="secundair" onClick={onSluiten}>
            Sluiten
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
