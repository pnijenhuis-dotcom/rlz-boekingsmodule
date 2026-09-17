// Klant-accordering — accorderingsroute per LEVERANCIER (Peter 17-09, migratie 0156): "1 losse accordeur die alleen de
// aangevinkte leveranciers ziet — dus NIET langs de andere accordeurs". Een leveranciersroute VERVANGT de administratieroute
// voor de aangevinkte leveranciers (zelfde patroon als de afdelingsroute): binnen de route meerdere lagen mét bedragdrempel.
// UX (norm: één primaire knop + ⋯, lege stand = actie): lijst mét samenvatting per route ("laag 1 Sophia → laag 2 D. Directeur
// · > € 5.000,00 · alleen Firma Q"), inline editor (naam, leveranciers als meervoudige keuze mét chips, lagen zoals de
// administratieroute), Opslaan / Route uitzetten. Een leverancier kan in maar één route zitten: de server geeft 409 mét de naam
// van de andere route — die tekst tonen we letterlijk.
import { useCallback, useEffect, useState } from 'react'
import {
  deactiveerLeverancierRoute,
  haalLeverancierRoutes,
  maakLeverancierRoute,
  wijzigLeverancierRoute,
  type KandidaatDto,
  type LeverancierRouteDto,
} from '../accordering/accorderingApi'
import type { VendorOptieDto } from '../api/types'
import { Select } from '../ui/basis'
import { rondesTekst } from '../accordering/rondesTekst'

interface LaagInvoer {
  accordeurId: string
  drempel: string
}

interface RouteInvoer {
  routeId: string | null
  naam: string
  vendorIds: string[]
  lagen: LaagInvoer[]
}

const LEEG: RouteInvoer = { routeId: null, naam: '', vendorIds: [], lagen: [{ accordeurId: '', drempel: '' }] }

export function LeverancierRoutes({
  administratieId,
  kandidaten,
  crediteuren,
  isBeheerder,
}: {
  administratieId: string
  kandidaten: KandidaatDto[]
  crediteuren: VendorOptieDto[]
  isBeheerder: boolean
}) {
  const [routes, setRoutes] = useState<LeverancierRouteDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [melding, setMelding] = useState<string | null>(null)
  const [editor, setEditor] = useState<RouteInvoer | null>(null)
  const [bezig, setBezig] = useState(false)
  const [kiesVendor, setKiesVendor] = useState('')

  const laad = useCallback(() => {
    haalLeverancierRoutes(administratieId)
      .then((d) => setRoutes(d.routes))
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Onbekende fout'))
  }, [administratieId])

  useEffect(() => {
    laad()
  }, [laad])

  const naamVan = (vendorId: string) => crediteuren.find((c) => c.id === vendorId)?.naam ?? vendorId

  const opslaan = async () => {
    if (!editor) return
    setBezig(true)
    setFout(null)
    setMelding(null)
    const payload = {
      naam: editor.naam.trim(),
      vendor_ids: editor.vendorIds,
      lagen: editor.lagen
        .filter((l) => l.accordeurId)
        .map((l, i) => ({
          volgnummer: i + 1,
          accordeur_gebruiker_id: l.accordeurId,
          bedrag_drempel: l.drempel ? l.drempel.replace(',', '.') : null,
        })),
    }
    try {
      const resultaat = editor.routeId
        ? await wijzigLeverancierRoute(administratieId, editor.routeId, payload)
        : await maakLeverancierRoute(administratieId, payload)
      setRoutes(resultaat.routes)
      setMelding(`Opgeslagen.${rondesTekst(resultaat.rondes_herberekend ?? 0, resultaat.rondes_vervallen ?? 0)}`)
      setEditor(null)
    } catch (err) {
      setFout(err instanceof Error ? err.message : 'Opslaan mislukt')
    } finally {
      setBezig(false)
    }
  }

  const uitzetten = async (route: LeverancierRouteDto) => {
    if (!window.confirm(`Leveranciersroute "${route.naam}" uitzetten? Lopende rondes van deze leveranciers gaan terug naar de administratieroute.`)) return
    setFout(null)
    try {
      const resultaat = await deactiveerLeverancierRoute(administratieId, route.id)
      setRoutes(resultaat.routes)
      setMelding(`Route uitgezet.${rondesTekst(resultaat.rondes_herberekend ?? 0, resultaat.rondes_vervallen ?? 0)}`)
    } catch (err) {
      setFout(err instanceof Error ? err.message : 'Uitzetten mislukt')
    }
  }

  const bewerk = (route: LeverancierRouteDto) =>
    setEditor({
      routeId: route.id,
      naam: route.naam,
      vendorIds: route.leveranciers.map((l) => l.vendor_id),
      lagen: route.lagen.map((l) => ({ accordeurId: l.accordeur_gebruiker_id, drempel: l.bedrag_drempel ?? '' })),
    })

  return (
    <div style={{ display: 'grid', gap: 8 }} data-testid="leverancier-routes">
      <h3 style={{ margin: '6px 0 0' }}>Leveranciersroutes</h3>
      <div className="hint" style={{ margin: 0 }}>
        Een leveranciersroute vervangt de gewone route voor de aangevinkte leveranciers: alleen de accordeur(s) in deze
        route zien die facturen; alle andere facturen volgen de gewone route zonder deze accordeur. Een leverancier kan in
        maar één route zitten.
      </div>
      {fout && <div className="fout">{fout}</div>}
      {melding && <span className="hint">{melding}</span>}
      {routes === null ? null : routes.length === 0 && !editor ? (
        <p className="hint" style={{ margin: 0 }}>
          Nog geen leveranciersroute — alle facturen volgen de gewone route.
        </p>
      ) : (
        <ul style={{ margin: 0, paddingLeft: 18 }}>
          {routes.map((route) => (
            <li key={route.id} data-testid="leverancier-route">
              <b>{route.naam}</b> — {route.samenvatting}
              {isBeheerder && (
                <>
                  {' '}
                  <button type="button" className="linkbtn" onClick={() => bewerk(route)}>
                    Wijzigen
                  </button>{' '}
                  <button type="button" className="linkbtn" onClick={() => void uitzetten(route)}>
                    Route uitzetten
                  </button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      {isBeheerder && !editor && (
        <div className="actions" style={{ margin: 0 }}>
          <button type="button" className="btn secondary" onClick={() => setEditor({ ...LEEG, lagen: [{ accordeurId: '', drempel: '' }] })}>
            + Leveranciersroute
          </button>
        </div>
      )}
      {editor && (
        <div className="panel" style={{ display: 'grid', gap: 10, padding: 10 }} data-testid="leverancier-route-editor">
          <label style={{ display: 'grid', gap: 4 }}>
            Naam van de route
            <input aria-label="Naam leveranciersroute" value={editor.naam} onChange={(e) => setEditor({ ...editor, naam: e.target.value })} placeholder="bv. Route Firma Q" />
          </label>
          <div style={{ display: 'grid', gap: 6 }}>
            <span>Alleen voor leveranciers</span>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {editor.vendorIds.map((vid) => (
                <span key={vid} className="chip" data-testid="leverancier-chip">
                  {naamVan(vid)}{' '}
                  <button type="button" className="linkbtn" aria-label={`Verwijder ${naamVan(vid)}`} onClick={() => setEditor({ ...editor, vendorIds: editor.vendorIds.filter((v) => v !== vid) })}>
                    ×
                  </button>
                </span>
              ))}
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <Select aria-label="Leverancier toevoegen" value={kiesVendor} onChange={(e) => setKiesVendor(e.target.value)}>
                <option value="">— kies leverancier —</option>
                {crediteuren
                  .filter((c) => !editor.vendorIds.includes(c.id))
                  .map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.naam}
                    </option>
                  ))}
              </Select>
              <button
                type="button"
                className="btn secondary"
                disabled={!kiesVendor}
                onClick={() => {
                  if (!kiesVendor) return
                  setEditor({ ...editor, vendorIds: [...editor.vendorIds, kiesVendor] })
                  setKiesVendor('')
                }}
              >
                Toevoegen
              </button>
            </div>
          </div>
          {editor.lagen.map((laag, index) => (
            <div key={index} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <span style={{ minWidth: 52 }}>Laag {index + 1}</span>
              <Select
                aria-label={`Accordeur route-laag ${index + 1}`}
                value={laag.accordeurId}
                onChange={(e) => setEditor({ ...editor, lagen: editor.lagen.map((l, i) => (i === index ? { ...l, accordeurId: e.target.value } : l)) })}
              >
                <option value="">— kies accordeur —</option>
                {kandidaten.map((k) => (
                  <option key={k.id} value={k.id}>
                    {k.naam}
                  </option>
                ))}
              </Select>
              <input
                aria-label={`Bedragdrempel route-laag ${index + 1}`}
                placeholder="drempel (leeg = alle facturen)"
                style={{ width: 220 }}
                value={laag.drempel}
                onChange={(e) => setEditor({ ...editor, lagen: editor.lagen.map((l, i) => (i === index ? { ...l, drempel: e.target.value } : l)) })}
              />
              <button type="button" className="btn secondary" onClick={() => setEditor({ ...editor, lagen: editor.lagen.filter((_, i) => i !== index) })}>
                Verwijderen
              </button>
            </div>
          ))}
          <div className="actions" style={{ margin: 0 }}>
            <button type="button" className="btn secondary" onClick={() => setEditor({ ...editor, lagen: [...editor.lagen, { accordeurId: '', drempel: '' }] })}>
              + Laag toevoegen
            </button>
            <button type="button" className="btn" disabled={bezig || !editor.naam.trim() || editor.vendorIds.length === 0} onClick={() => void opslaan()}>
              {bezig ? 'Opslaan…' : 'Opslaan'}
            </button>
            <button type="button" className="linkbtn" onClick={() => setEditor(null)}>
              Annuleren
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
