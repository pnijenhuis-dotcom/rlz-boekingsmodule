// Bulk klant-accordering instellen (mockup bulk-accordering.html = norm, besluiten Peter 01-09):
// één dialoog stelt de accorderingslagen in voor álle geselecteerde administraties. De preview
// (scope-melding per accordeur, overschrijf-waarschuwing mét telling vervallen rondes,
// uitkomstenlijst) en het resultaat ná toepassen delen dezelfde weergave (mockup-notitie ⑥).
// Server-side is de bulk een orkestratie over de bestaande per-administratie-configuratieroute;
// dit scherm is Beheerder-werk (endpoints require_beheerder, scope-aanmaak is Beheerder-exclusief).
import { useEffect, useMemo, useState } from 'react'
import {
  bulkAccorderingPreview,
  bulkAccorderingToepassen,
  haalAlleAccordeurKandidaten,
  type BulkInstellenPreviewDto,
  type BulkInstelUitkomstDto,
  type KandidaatDto,
} from '../accordering/accorderingApi'
import { ApiError } from '../api/client'
import { bedragAlsGetal, normaliseerBedrag } from '../document/bedrag'
import { SearchableCombobox } from '../document/SearchableCombobox'
import { Badge, Button, Checkbox, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle, useToastOptioneel } from '../ui/basis'

interface LaagInvoer {
  accordeurId: string | null
  drempel: string
}

function uitkomstTag(u: BulkInstelUitkomstDto): { tekst: string; variant: 'ok' | 'warn' } {
  if (u.uitkomst === 'vervangen') {
    const rondes = u.rondes_vervallen === 1 ? '1 ronde vervalt' : `${u.rondes_vervallen} rondes vervallen`
    return { tekst: `vervangen${u.rondes_vervallen > 0 ? ` · ${rondes}` : ''}`, variant: 'warn' }
  }
  if (u.uitkomst === 'ingesteld') {
    const delen = ['ingesteld']
    if (u.toggle_aangezet) delen.push('toggle aan')
    if (u.scope_toegevoegd_voor.length > 0) delen.push('scope toegevoegd')
    return { tekst: delen.join(' · '), variant: 'ok' }
  }
  if (u.uitkomst === 'fout') return { tekst: 'fout', variant: 'warn' }
  return { tekst: 'overgeslagen', variant: 'warn' }
}

/** Uitkomstenlijst — dezelfde weergave vóór (preview) en ná (resultaat), mockup-notitie ⑥. */
function UitkomstLijst({ uitkomsten }: { uitkomsten: BulkInstelUitkomstDto[] }) {
  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden', fontSize: 12.5 }}>
      {uitkomsten.map((u) => {
        const tag = uitkomstTag(u)
        return (
          <div
            key={u.administratie_id}
            style={{ display: 'flex', justifyContent: 'space-between', gap: 10, padding: '8px 12px', borderBottom: '1px solid var(--border)', alignItems: 'baseline', flexWrap: 'wrap' }}
          >
            <span>{u.administratie_naam}</span>
            <span style={{ display: 'flex', gap: 6, alignItems: 'baseline', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
              <Badge variant={tag.variant}>{tag.tekst}</Badge>
              {u.reden && <span className="hint" style={{ margin: 0 }}>{u.reden}</span>}
            </span>
          </div>
        )
      })}
    </div>
  )
}

export function BulkAccorderingDialog({
  administraties,
  onSluiten,
  onGereed,
}: {
  /** De op moment van openen geselecteerde administraties (id + naam). */
  administraties: { id: string; naam: string }[]
  onSluiten: () => void
  onGereed: () => void
}) {
  const { meld } = useToastOptioneel()
  const [kandidaten, setKandidaten] = useState<KandidaatDto[] | null>(null)
  const [lagen, setLagen] = useState<LaagInvoer[]>([{ accordeurId: null, drempel: '' }])
  const [scopeVink, setScopeVink] = useState(true)
  const [preview, setPreview] = useState<BulkInstellenPreviewDto | null>(null)
  const [previewFout, setPreviewFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [resultaat, setResultaat] = useState<BulkInstelUitkomstDto[] | null>(null)

  useEffect(() => {
    haalAlleAccordeurKandidaten()
      .then((r) => setKandidaten(r.kandidaten))
      .catch((err: unknown) => setPreviewFout(err instanceof Error ? err.message : 'Accordeurs laden mislukt'))
  }, [])

  const opties = useMemo(() => (kandidaten ?? []).map((k) => ({ id: k.id, label: k.naam })), [kandidaten])

  const drempelOngeldig = lagen.some((l) => {
    if (!l.drempel.trim()) return false
    const bedrag = bedragAlsGetal(l.drempel)
    return bedrag === null || bedrag <= 0
  })
  const volledigeLagen = lagen.filter((l) => l.accordeurId)
  const invoer = useMemo(
    () => ({
      administratie_ids: administraties.map((a) => a.id),
      lagen: volledigeLagen.map((l, index) => ({
        volgnummer: index + 1,
        accordeur_gebruiker_id: l.accordeurId as string,
        bedrag_drempel: l.drempel.trim() ? normaliseerBedrag(l.drempel) : null,
      })),
      scope_toevoegen: scopeVink,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- sleutel hieronder dekt de inhoud
    [JSON.stringify(volledigeLagen), scopeVink, administraties],
  )

  // Preview zodra er minstens één volledige laag staat (licht gedebounced): scope-meldingen,
  // overschrijf-telling en de uitkomstenlijst komen allemaal van de server — de client rekent niets.
  useEffect(() => {
    if (resultaat || volledigeLagen.length === 0 || drempelOngeldig) {
      setPreview(null)
      return
    }
    let actief = true
    setPreviewFout(null)
    const timer = setTimeout(() => {
      bulkAccorderingPreview(invoer)
        .then((p) => actief && setPreview(p))
        .catch((err: unknown) => actief && setPreviewFout(err instanceof ApiError ? err.message : 'Preview mislukt'))
    }, 250)
    return () => {
      actief = false
      clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(invoer), resultaat])

  const vervangen = (preview?.uitkomsten ?? []).filter((u) => u.uitkomst === 'vervangen')
  const totaalVervallen = vervangen.reduce((som, u) => som + u.rondes_vervallen, 0)

  const toepassen = async () => {
    setBezig(true)
    setFout(null)
    try {
      const r = await bulkAccorderingToepassen(invoer)
      setResultaat(r.uitkomsten)
      const gelukt = r.uitkomsten.filter((u) => u.uitkomst === 'ingesteld' || u.uitkomst === 'vervangen').length
      meld(`Klant-accordering ingesteld op ${gelukt} van ${r.uitkomsten.length} administraties — geauditeerd.`,
        r.uitkomsten.some((u) => u.uitkomst === 'fout' || u.uitkomst === 'overgeslagen') ? 'warn' : 'ok')
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Toepassen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  const klaar = () => {
    if (resultaat) onGereed()
    onSluiten()
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && klaar()}>
      <DialogContent aria-describedby={undefined} data-testid="bulk-accordering-dialoog" style={{ maxWidth: 640 }}>
        <DialogTitle>Klant-accordering instellen — {administraties.length === 1 ? '1 administratie' : `${administraties.length} administraties`}</DialogTitle>
        <DialogDescription>
          De lagen hieronder vervangen de bestaande configuratie en zetten klant-accordering aan waar die uit staat.
        </DialogDescription>

        {!resultaat && (
          <>
            <div>
              <span className="hint" style={{ margin: '0 0 6px', display: 'block', textTransform: 'uppercase', fontSize: 11, letterSpacing: '.05em', fontWeight: 700 }}>
                Accorderingslagen (op volgorde)
              </span>
              {kandidaten !== null && kandidaten.length === 0 && (
                <p className="hint" style={{ margin: 0 }}>
                  Er zijn nog geen actieve klant-accordeurs — nodig eerst een gebruiker uit met de rol Klant-accordeur.
                </p>
              )}
              {lagen.map((laag, index) => (
                <div key={index} style={{ display: 'grid', gridTemplateColumns: '56px 1fr 170px 28px', gap: 8, alignItems: 'center', marginBottom: 6 }}>
                  <b style={{ color: 'var(--primary)', fontSize: 13 }}>Laag {index + 1}</b>
                  <SearchableCombobox
                    label={`Accordeur laag ${index + 1}`}
                    toonLabel={false}
                    opties={opties}
                    waarde={laag.accordeurId}
                    onWijzig={(id) => setLagen((huidig) => huidig.map((l, i) => (i === index ? { ...l, accordeurId: id } : l)))}
                    placeholder="accordeur zoeken…"
                  />
                  <input
                    aria-label={`Voorwaarde laag ${index + 1}`}
                    placeholder="alle facturen (of € boven…)"
                    value={laag.drempel}
                    onChange={(e) => setLagen((huidig) => huidig.map((l, i) => (i === index ? { ...l, drempel: e.target.value } : l)))}
                  />
                  <button
                    type="button"
                    className="linkbtn"
                    aria-label={`Laag ${index + 1} verwijderen`}
                    onClick={() => setLagen((huidig) => (huidig.length > 1 ? huidig.filter((_, i) => i !== index) : huidig))}
                  >
                    ✕
                  </button>
                </div>
              ))}
              <button type="button" className="linkbtn" onClick={() => setLagen((huidig) => [...huidig, { accordeurId: null, drempel: '' }])}>
                + Laag toevoegen
              </button>
              {drempelOngeldig && (
                <div className="hint" style={{ color: 'var(--orange, #b45309)', margin: '4px 0 0' }}>
                  Vul per laag een geldig drempelbedrag in, of laat het veld leeg voor &ldquo;alle facturen&rdquo;.
                </div>
              )}
            </div>

            <label style={{ display: 'flex', gap: 9, alignItems: 'flex-start', fontSize: 12.5, margin: 0 }}>
              <Checkbox checked={scopeVink} onChange={(e) => setScopeVink(e.target.checked)} aria-label="Scope toevoegen waar die ontbreekt" />
              <span className="hint" style={{ margin: 0 }}>
                <b style={{ color: 'var(--text)' }}>Scope toevoegen waar die ontbreekt</b>
                {' — '}
                {preview && preview.scope_ontbreekt.length > 0 ? (
                  <>
                    {preview.scope_ontbreekt
                      .map((s) => `${s.accordeur_naam} heeft nog geen toegang tot ${s.administratie_namen.join(' en ')}`)
                      .join('; ')}
                    ; met deze vink komt die toegang er (geauditeerd). Zonder vink worden die administraties overgeslagen.
                  </>
                ) : (
                  'ontbreekt de toegang van een gekozen accordeur bij een geselecteerde administratie, dan maakt de bulk die aan (geauditeerd). Zonder vink wordt die administratie overgeslagen.'
                )}
              </span>
            </label>

            {preview && vervangen.length > 0 && (
              <div
                role="alert"
                style={{ background: 'var(--orange-bg, #fdf3e3)', border: '1px solid var(--orange, #b45309)', borderRadius: 10, padding: '10px 13px', fontSize: 12.5, color: 'var(--orange, #b45309)' }}
              >
                ⚠ <b>Overschrijven:</b> {vervangen.map((u) => u.administratie_naam).join(' en ')}{' '}
                {vervangen.length === 1 ? 'heeft' : 'hebben'} al een accorderingsconfiguratie — die wordt vervangen.
                {totaalVervallen > 0 && (
                  <>
                    {' '}Daarbij {totaalVervallen === 1 ? 'vervalt' : 'vervallen'}{' '}
                    <b>{totaalVervallen} lopende {totaalVervallen === 1 ? 'accorderingsronde' : 'accorderingsrondes'}</b>{' '}
                    ({vervangen.filter((u) => u.rondes_vervallen > 0).map((u) => `${u.administratie_naam} ${u.rondes_vervallen}`).join(', ')});
                    de documenten gaan terug naar &ldquo;Klaar om te boeken&rdquo; en kunnen daarna in bulk opnieuw
                    aangeboden worden (bestaande banner + bulk-knop).
                  </>
                )}
              </div>
            )}
          </>
        )}

        {previewFout && !resultaat && <div className="fout">{previewFout}</div>}

        {(resultaat || preview) && (
          <div>
            <span className="hint" style={{ margin: '0 0 6px', display: 'block', textTransform: 'uppercase', fontSize: 11, letterSpacing: '.05em', fontWeight: 700 }}>
              {resultaat ? 'Resultaat (per administratie)' : 'Uitkomst na toepassen (per administratie)'}
            </span>
            <UitkomstLijst uitkomsten={resultaat ?? preview?.uitkomsten ?? []} />
          </div>
        )}

        {fout && <div className="fout">{fout}</div>}

        <DialogFooter>
          {resultaat ? (
            <Button onClick={klaar}>Sluiten</Button>
          ) : (
            <>
              <Button variant="ghost" onClick={onSluiten} disabled={bezig}>
                Annuleren
              </Button>
              <Button onClick={() => void toepassen()} disabled={bezig || !preview || volledigeLagen.length === 0 || drempelOngeldig}>
                {bezig ? 'Bezig…' : `Toepassen op ${administraties.length === 1 ? '1 administratie' : `${administraties.length} administraties`}`}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
