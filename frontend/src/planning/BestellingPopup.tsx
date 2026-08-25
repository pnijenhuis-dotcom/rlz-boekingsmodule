import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError } from '../api/client'
import { Badge, Button, useToastOptioneel } from '../ui/basis'
import {
  annuleerBestelling,
  haalBestelling,
  haalBestellingPdfBlob,
  schatM2,
  verstuurBestelling,
  werkConceptBij,
  type BestelRegelDto,
  type BestellingDto,
} from './transportApi'

/* Bestelling-popup (steigerbouw-run D3, mockup planning-steigerbouw #bestelling-detail = norm —
 * vorm conform het UVA-verhuursysteem-voorbeeld): kop met nummer + status-badge (concept r2),
 * meta (leverdatum + weeknummer, leveradres = projectadres, status levering), volledige catalogus
 * in vaste volgorde met aantallen (0 = niet bestellen, grijs), bundel-m²-som, "was …"-markering
 * voor gewijzigde regels na een eerdere verzending, "Geleverd"-kolom uit de gekoppelde
 * transporten, PDF-bon per revisie, versturen = revisie + mail (mens klikt expliciet). */

function weekVan(iso: string): number {
  const d = new Date(`${iso.slice(0, 10)}T12:00:00Z`)
  const dag = d.getUTCDay() || 7
  d.setUTCDate(d.getUTCDate() + 4 - dag)
  return Math.ceil(((d.getTime() - Date.UTC(d.getUTCFullYear(), 0, 1)) / 86400000 + 1) / 7)
}

function datumLabel(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(`${iso}T12:00:00`)
  return `${d.toLocaleDateString('nl-NL', { weekday: 'short', day: 'numeric', month: 'numeric' })} · wk ${weekVan(iso)}`
}

export function BestellingPopup({ administratieId, bestellingId, onSluiten, onGewijzigd }: { administratieId: string; bestellingId: string; onSluiten: () => void; onGewijzigd: () => void }) {
  const { meld } = useToastOptioneel()
  const [b, setB] = useState<BestellingDto | null>(null)
  const [regels, setRegels] = useState<Record<string, number>>({})
  const [leverdatum, setLeverdatum] = useState('')
  const [levertijd, setLevertijd] = useState('')
  const [leveradres, setLeveradres] = useState('')
  const [contact, setContact] = useState('')
  const [opmerking, setOpmerking] = useState('')
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState<string | null>(null)
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [annuleerReden, setAnnuleerReden] = useState<string | null>(null)

  const laad = useCallback(() => {
    setFout(null)
    haalBestelling(administratieId, bestellingId)
      .then((data) => {
        setB(data)
        setRegels(Object.fromEntries(data.regels.filter((r) => r.aantal > 0).map((r) => [r.product.id, r.aantal])))
        setLeverdatum(data.gewenste_leverdatum ?? '')
        setLevertijd(data.gewenste_levertijd ? data.gewenste_levertijd.slice(0, 5) : '')
        setLeveradres(data.leveradres ?? '')
        setContact(data.contactpersoon ?? '')
        setOpmerking(data.opmerking ?? '')
      })
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Bestelling laden mislukt'))
  }, [administratieId, bestellingId])
  useEffect(() => {
    laad()
  }, [laad])
  useEffect(() => () => {
    if (pdfUrl) URL.revokeObjectURL(pdfUrl)
  }, [pdfUrl])

  const producten = useMemo(() => new Map((b?.regels ?? []).map((r) => [r.product.id, r.product])), [b])
  const m2 = useMemo(() => schatM2(regels, producten), [regels, producten])
  const muteerbaar = b !== null && b.status !== 'geannuleerd'
  const wasVan = (r: BestelRegelDto) => (r.was === null ? null : r.was)
  const gewijzigd = (r: BestelRegelDto) => wasVan(r) !== null && (regels[r.product.id] ?? 0) !== wasVan(r)
  const onopgeslagen = b !== null && JSON.stringify(Object.fromEntries(b.regels.filter((r) => r.aantal > 0).map((r) => [r.product.id, r.aantal]))) !== JSON.stringify(regels)

  async function opslaan(): Promise<BestellingDto | null> {
    if (!b) return null
    setBezig('opslaan')
    setFout(null)
    try {
      const nieuw = await werkConceptBij(administratieId, bestellingId, {
        regels,
        gewenste_leverdatum: leverdatum || null,
        gewenste_levertijd: levertijd ? `${levertijd}:00` : null,
        leveradres: leveradres || null,
        contactpersoon: contact || null,
        opmerking: opmerking || null,
      })
      setB(nieuw)
      onGewijzigd()
      return nieuw
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Opslaan mislukt.')
      return null
    } finally {
      setBezig(null)
    }
  }

  async function versturen() {
    const opgeslagen = await opslaan()
    if (!opgeslagen) return
    setBezig('versturen')
    setFout(null)
    try {
      const nieuw = await verstuurBestelling(administratieId, bestellingId)
      setB(nieuw)
      meld(`Bestelling ${nieuw.nummer} r${nieuw.revisie} verstuurd aan ${nieuw.leverancier_email} — PDF-bon in de bijlage, levering gekoppeld.`)
      onGewijzigd()
      laad()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Versturen mislukt.')
    } finally {
      setBezig(null)
    }
  }

  async function toonPdf(revisie: number) {
    try {
      const url = await haalBestellingPdfBlob(administratieId, bestellingId, revisie)
      setPdfUrl(url)
      window.open(url, '_blank', 'noopener')
    } catch (err) {
      setFout(err instanceof Error ? err.message : 'PDF ophalen mislukt')
    }
  }

  const volgendeRevisie = (b?.revisie ?? 0) + 1
  const groepen = useMemo(() => {
    const per = new Map<string, { bundel: string; regels: BestelRegelDto[] }>()
    for (const r of b?.regels ?? []) {
      const key = r.product.categorie_naam
      if (!per.has(key)) per.set(key, { bundel: r.product.bundel, regels: [] })
      per.get(key)!.regels.push(r)
    }
    return [...per.entries()]
  }, [b])
  const bundels = useMemo(() => [...new Set(groepen.map(([, g]) => g.bundel))], [groepen])

  return (
    <div className="modal-bg" role="presentation" onClick={() => bezig === null && onSluiten()}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="bestelling-titel" style={{ maxWidth: 780, padding: 0, display: 'flex', flexDirection: 'column', maxHeight: '92vh' }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '16px 20px', borderBottom: '1px solid var(--border)' }}>
          <div style={{ width: 38, height: 38, borderRadius: 10, background: 'var(--info-bg)', display: 'grid', placeItems: 'center', fontSize: 18 }}>🚚</div>
          <div style={{ flex: 1 }}>
            <h2 id="bestelling-titel" style={{ margin: 0, fontSize: 15 }}>
              Bestelling {b?.nummer ?? '…'}{' '}
              {b && (b.status === 'concept' || b.heeft_concept_wijzigingen || onopgeslagen) && <Badge variant="warn">concept r{volgendeRevisie}</Badge>}
              {b && b.status === 'verstuurd' && !b.heeft_concept_wijzigingen && !onopgeslagen && <Badge variant="ok">verstuurd r{b.revisie}</Badge>}
              {b && b.status === 'geannuleerd' && <Badge variant="danger">geannuleerd</Badge>}
            </h2>
            {b && (
              <div className="hint" style={{ margin: 0 }}>
                {b.project_naam ?? 'project'} → {b.leverancier_naam}
                {b.revisies.length > 0 && ` · r${b.revisies[b.revisies.length - 1].revisie} verstuurd ${new Date(b.revisies[b.revisies.length - 1].verstuurd_op).toLocaleDateString('nl-NL')} aan ${b.revisies[b.revisies.length - 1].verzonden_naar}`}
              </div>
            )}
          </div>
          <button className="linkbtn" onClick={onSluiten} aria-label="Sluiten" disabled={bezig !== null}>
            ✕
          </button>
        </div>

        {fout && <div className="fout" style={{ margin: '10px 20px 0' }}>{fout}</div>}
        {b === null && !fout && <p className="hint" style={{ padding: 20 }}>Laden…</p>}

        {b !== null && (
          <>
            <div style={{ display: 'flex', gap: 10, padding: '12px 20px', borderBottom: '1px solid var(--border)', background: 'var(--panel-2)', flexWrap: 'wrap' }}>
              <label className="hint" style={{ flex: 1, minWidth: 150, margin: 0 }}>
                <span style={{ display: 'block', fontSize: 10.5, textTransform: 'uppercase', letterSpacing: '.06em', fontWeight: 700 }}>Leverdatum</span>
                <input type="date" value={leverdatum} onChange={(e) => setLeverdatum(e.target.value)} disabled={!muteerbaar} style={{ width: '100%' }} />
                <span style={{ fontSize: 11 }}>{leverdatum ? datumLabel(leverdatum) : 'nog geen datum'}</span>
              </label>
              <label className="hint" style={{ flex: '0 0 110px', margin: 0 }}>
                <span style={{ display: 'block', fontSize: 10.5, textTransform: 'uppercase', letterSpacing: '.06em', fontWeight: 700 }}>Tijd</span>
                <input type="time" value={levertijd} onChange={(e) => setLevertijd(e.target.value)} disabled={!muteerbaar} style={{ width: '100%' }} />
              </label>
              <label className="hint" style={{ flex: 2, minWidth: 200, margin: 0 }}>
                <span style={{ display: 'block', fontSize: 10.5, textTransform: 'uppercase', letterSpacing: '.06em', fontWeight: 700 }}>Leveradres (projectadres)</span>
                <input type="text" value={leveradres} onChange={(e) => setLeveradres(e.target.value)} disabled={!muteerbaar} style={{ width: '100%' }} />
              </label>
              <div className="hint" style={{ flex: '0 0 auto', margin: 0 }}>
                <span style={{ display: 'block', fontSize: 10.5, textTransform: 'uppercase', letterSpacing: '.06em', fontWeight: 700 }}>Status levering</span>
                <span style={{ fontSize: 13, fontWeight: 600 }}>{b.transport_ids.length > 0 ? `${b.transport_ids.length} transport gekoppeld` : 'volgt na versturen'}</span>
                <span style={{ display: 'block', fontSize: 10.5 }}>koppeling verhuursysteem = later</span>
              </div>
              {b.revisies.length > 0 && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  {b.revisies.map((r) => (
                    <Button key={r.revisie} variant="secundair" maat="klein" onClick={() => void toonPdf(r.revisie)} title={`Verstuurd ${new Date(r.verstuurd_op).toLocaleString('nl-NL')} · ${Number(r.m2_totaal).toLocaleString('nl-NL')} m²`}>
                      📄 r{r.revisie}
                    </Button>
                  ))}
                </div>
              )}
            </div>

            <div style={{ display: 'flex', gap: 12, padding: '8px 20px', borderBottom: '1px solid var(--border)', fontSize: 10.5, textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--faint)', fontWeight: 700 }}>
              <span style={{ width: 34 }} />
              <span style={{ flex: 1 }}>Product</span>
              <span style={{ width: 84, textAlign: 'right' }}>Besteld</span>
              <span style={{ width: 70 }} />
              <span style={{ width: 70, textAlign: 'right' }}>Geleverd</span>
            </div>

            <div style={{ overflow: 'auto', flex: 1 }}>
              {bundels.map((bundel, bi) => (
                <div key={bundel}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '11px 20px', background: 'var(--info-bg)', borderBottom: '1px solid var(--border)' }}>
                    <b style={{ fontSize: 13 }}>
                      {bi + 1} · {bundel === 'steiger' ? 'Vierkante meter (bundel)' : bundel === 'trappentoren' ? 'Trappentoren (bundel)' : bundel}
                    </b>
                    <span className="hint" style={{ margin: 0, fontSize: 11.5 }}>{bundel === 'steiger' ? 'onderliggende regels tellen op — Σ(aantal × lengte) / 4,6' : 'RS-onderdelen'}</span>
                    <span style={{ marginLeft: 'auto', fontSize: 15, fontWeight: 800, color: 'var(--primary)' }}>
                      {bundel === 'steiger' ? `${m2.toLocaleString('nl-NL')} m²` : Object.entries(regels).filter(([pid]) => producten.get(pid)?.bundel === bundel).reduce((s, [, n]) => s + n, 0) || '—'}
                    </span>
                  </div>
                  {groepen
                    .filter(([, g]) => g.bundel === bundel)
                    .map(([cat, g]) => (
                      <div key={cat}>
                        <div style={{ padding: '9px 20px 6px', fontSize: 10.5, textTransform: 'uppercase', letterSpacing: '.07em', color: 'var(--faint)', fontWeight: 800 }}>{cat}</div>
                        {g.regels.map((r) => {
                          const aantal = regels[r.product.id] ?? 0
                          const was = wasVan(r)
                          const delta = gewijzigd(r) ? (aantal > (was ?? 0) ? 'plus' : 'min') : null
                          return (
                            <div key={r.product.id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '7px 20px', borderBottom: '1px solid var(--border)', opacity: aantal === 0 && !delta ? 0.7 : 1 }}>
                              <span style={{ width: 34, fontSize: 11, color: 'var(--faint)', fontVariantNumeric: 'tabular-nums' }}>{r.product.nummer}</span>
                              <span style={{ flex: 1, fontSize: 13, color: aantal === 0 ? 'var(--faint)' : undefined }}>
                                {r.product.naam}
                                {r.product.verpakking && <span className="hint" style={{ fontSize: 11 }}> · {r.product.verpakking}</span>}
                              </span>
                              <input
                                type="number"
                                min={0}
                                inputMode="numeric"
                                aria-label={`Aantal ${r.product.naam}`}
                                value={aantal}
                                disabled={!muteerbaar}
                                onChange={(e) => {
                                  const n = Math.max(0, Math.floor(Number(e.target.value) || 0))
                                  setRegels((huidig) => {
                                    const kopie = { ...huidig }
                                    if (n === 0) delete kopie[r.product.id]
                                    else kopie[r.product.id] = n
                                    return kopie
                                  })
                                }}
                                style={{
                                  width: 84,
                                  textAlign: 'right',
                                  fontWeight: 600,
                                  borderColor: delta === 'min' ? 'var(--warn)' : delta === 'plus' ? 'var(--ok)' : undefined,
                                  background: delta === 'min' ? 'var(--warn-bg)' : delta === 'plus' ? 'var(--ok-bg)' : undefined,
                                }}
                              />
                              <span style={{ width: 70, fontSize: 10.5, fontWeight: 700, textAlign: 'right', color: delta === 'min' ? 'var(--warn)' : 'var(--ok)' }}>{delta ? `was ${was}` : ''}</span>
                              <span style={{ width: 70, textAlign: 'right', fontSize: 12.5, color: 'var(--faint)', fontVariantNumeric: 'tabular-nums' }}>{r.geleverd > 0 ? r.geleverd : '—'}</span>
                            </div>
                          )
                        })}
                      </div>
                    ))}
                </div>
              ))}
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '14px 20px', borderTop: '1px solid var(--border)', background: 'var(--panel-2)', flexWrap: 'wrap' }}>
              <div className="hint" style={{ flex: 1, margin: 0, fontSize: 11.5, minWidth: 260 }}>
                0 = niet bestellen (grijs) · gewijzigde regels kleuren mét &quot;was …&quot; · <b>Geleverd</b> volgt uit de gekoppelde transporten (later: het
                verhuursysteem) · elke revisie + verzending in de audit.
                {b.leverancier_email ? '' : ' ⚠ Deze leverancier heeft nog geen bestel-mailadres (Instellingen → Materiaalcatalogus).'}
              </div>
              {muteerbaar && b.status !== 'concept' && annuleerReden === null && (
                <Button variant="ghost" maat="klein" onClick={() => setAnnuleerReden('')}>
                  Annuleren…
                </Button>
              )}
              {muteerbaar && b.status === 'concept' && annuleerReden === null && (
                <Button variant="ghost" maat="klein" onClick={() => setAnnuleerReden('')}>
                  Bestelling annuleren…
                </Button>
              )}
              <Button variant="secundair" onClick={onSluiten} disabled={bezig !== null}>
                Sluiten
              </Button>
              {muteerbaar && (
                <Button variant="secundair" onClick={() => void opslaan()} disabled={bezig !== null || !onopgeslagen}>
                  {bezig === 'opslaan' ? 'Bezig…' : 'Concept opslaan'}
                </Button>
              )}
              {muteerbaar && (
                <Button onClick={() => void versturen()} disabled={bezig !== null || !b.leverancier_email || Object.keys(regels).length === 0 || !leverdatum}>
                  {bezig === 'versturen' ? 'Bezig…' : b.revisie === 0 ? 'Bestelling versturen (r1)…' : `Update-mail versturen (r${volgendeRevisie})…`}
                </Button>
              )}
            </div>
            {annuleerReden !== null && (
              <div style={{ display: 'flex', gap: 8, padding: '0 20px 14px', alignItems: 'center', background: 'var(--panel-2)' }}>
                <input placeholder="Reden van annuleren (verplicht)" value={annuleerReden} onChange={(e) => setAnnuleerReden(e.target.value)} style={{ flex: 1 }} />
                <Button
                  variant="gevaar"
                  maat="klein"
                  disabled={annuleerReden.trim().length < 3 || bezig !== null}
                  onClick={() => {
                    setBezig('annuleren')
                    annuleerBestelling(administratieId, bestellingId, annuleerReden.trim())
                      .then((nieuw) => {
                        setB(nieuw)
                        setAnnuleerReden(null)
                        onGewijzigd()
                      })
                      .catch((err: unknown) => setFout(err instanceof ApiError ? err.message : 'Annuleren mislukt.'))
                      .finally(() => setBezig(null))
                  }}
                >
                  Annuleren bevestigen
                </Button>
                <Button variant="ghost" maat="klein" onClick={() => setAnnuleerReden(null)}>
                  Terug
                </Button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
