// Klant-accordering — accorderingsroute per LEVERANCIER (Peter 17-09, migratie 0156): "1 losse accordeur die alleen de
// aangevinkte leveranciers ziet — dus NIET langs de andere accordeurs". Een leveranciersroute VERVANGT de administratieroute
// voor de aangevinkte leveranciers (zelfde patroon als de afdelingsroute): binnen de route meerdere lagen mét bedragdrempel.
// Peter 18-09 (migratie 0164, casus Bouwadvies Oost Nederland: 3 gewone lagen + een 4e alleen voor 2 leveranciers): keuze
// "Vervangt de gewone route" (default) of "Bovenop de gewone route" mét positie (vóór laag 1 · ná de laatste laag) — de gewone
// lagen hoeven dan niet gekopieerd te worden en een wijziging van de gewone route werkt door in lopende rondes.
// UX (norm: één primaire knop + ⋯, lege stand = actie): lijst mét samenvatting per route, inline editor (naam, leveranciers via
// zoekbare combobox — crediteuren mét open documenten bovenaan — als chips, lagen zoals de administratieroute), Opslaan /
// Route uitzetten. Een leverancier kan in maar één route zitten: de server geeft 409 mét de naam van de andere route — die
// tekst tonen we letterlijk. Geen accordeurs in de administratie = dezelfde melding + acties als op de kaart zelf.
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  deactiveerLeverancierRoute,
  haalLeverancierKandidaten,
  haalLeverancierRoutes,
  maakLeverancierRoute,
  wijzigLeverancierRoute,
  type KandidaatDto,
  type LeverancierKandidaatDto,
  type LeverancierRouteDto,
  type LeverancierRouteModus,
  type LeverancierRoutePositie,
} from '../accordering/accorderingApi'
import type { VendorOptieDto } from '../api/types'
import { SearchableCombobox, type ComboboxOptie } from '../document/SearchableCombobox'
import { Select } from '../ui/basis'
import { rondesTekst } from '../accordering/rondesTekst'
import { AndereAccordeurKoppelen, GeenAccordeursMelding } from './GeenAccordeursMelding'
import { KeuzeKaarten } from './KeuzeKaarten'

interface LaagInvoer {
  accordeurId: string
  drempel: string
}

interface RouteInvoer {
  routeId: string | null
  naam: string
  vendorIds: string[]
  lagen: LaagInvoer[]
  modus: LeverancierRouteModus
  positie: LeverancierRoutePositie
}

const LEEG: RouteInvoer = {
  routeId: null,
  naam: '',
  vendorIds: [],
  lagen: [{ accordeurId: '', drempel: '' }],
  modus: 'vervangt',
  positie: 'na',
}

/** Combobox-opties: open documenten bovenaan (server sorteert), label "Naam · 3 open" zodat het verschil zichtbaar is. */
export function leverancierOpties(
  kandidaten: LeverancierKandidaatDto[] | null,
  crediteuren: VendorOptieDto[],
  uitgesloten: string[],
): ComboboxOptie[] {
  const bron: { id: string; naam: string | null; open: number }[] = kandidaten
    ? kandidaten.map((k) => ({ id: k.vendor_id, naam: k.naam, open: k.open_documenten }))
    : crediteuren.map((c) => ({ id: c.id, naam: c.naam, open: 0 }))
  return bron
    .filter((c) => !uitgesloten.includes(c.id))
    .map((c) => ({
      id: c.id,
      label: `${c.naam ?? c.id}${c.open > 0 ? ` · ${c.open} open` : ''}`,
    }))
}

export function LeverancierRoutes({
  administratieId,
  naam,
  kandidaten,
  crediteuren,
  isBeheerder,
  onKandidatenHerladen,
}: {
  administratieId: string
  naam?: string
  kandidaten: KandidaatDto[]
  crediteuren: VendorOptieDto[]
  isBeheerder: boolean
  /** Ná "Bestaande accordeur koppelen": de kaart herlaadt de kandidatenlijst. */
  onKandidatenHerladen?: () => void
}) {
  const [routes, setRoutes] = useState<LeverancierRouteDto[] | null>(null)
  const [leverancierKandidaten, setLeverancierKandidaten] = useState<LeverancierKandidaatDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [melding, setMelding] = useState<string | null>(null)
  const [editor, setEditor] = useState<RouteInvoer | null>(null)
  const [bezig, setBezig] = useState(false)

  const laad = useCallback(() => {
    haalLeverancierRoutes(administratieId)
      .then((d) => setRoutes(d.routes))
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Onbekende fout'))
  }, [administratieId])

  useEffect(() => {
    laad()
  }, [laad])

  // Crediteuren mét open documenten (punt 3, 18-09) — pas laden als de editor opent; mislukt = terugval op de kale lijst.
  useEffect(() => {
    if (!editor || leverancierKandidaten !== null) return
    haalLeverancierKandidaten(administratieId)
      .then((d) => setLeverancierKandidaten(d.crediteuren))
      .catch(() => setLeverancierKandidaten([]))
  }, [editor, leverancierKandidaten, administratieId])

  const naamVan = (vendorId: string) =>
    leverancierKandidaten?.find((k) => k.vendor_id === vendorId)?.naam ?? crediteuren.find((c) => c.id === vendorId)?.naam ?? vendorId

  const opties = useMemo(
    () => leverancierOpties(leverancierKandidaten && leverancierKandidaten.length > 0 ? leverancierKandidaten : null, crediteuren, editor?.vendorIds ?? []),
    [leverancierKandidaten, crediteuren, editor?.vendorIds],
  )

  const opslaan = async () => {
    if (!editor) return
    setBezig(true)
    setFout(null)
    setMelding(null)
    const payload = {
      naam: editor.naam.trim(),
      vendor_ids: editor.vendorIds,
      modus: editor.modus,
      positie: editor.modus === 'bovenop' ? editor.positie : null,
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
      modus: route.modus ?? 'vervangt',
      positie: route.positie ?? 'na',
    })

  return (
    <div style={{ display: 'grid', gap: 8 }} data-testid="leverancier-routes">
      <h3 style={{ margin: '6px 0 0' }}>Leveranciersroutes</h3>
      <div className="hint" style={{ margin: 0 }}>
        Een leveranciersroute geldt alleen voor de aangevinkte leveranciers: óf ze <b>vervangt</b> de gewone route (alleen de
        accordeur(s) in deze route zien die facturen), óf ze komt er <b>bovenop</b> (de gewone lagen plus een extra laag vóór
        of ná). Alle andere facturen volgen de gewone route. Een leverancier kan in maar één route zitten.
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
              <b>{route.naam}</b>
              {route.modus === 'bovenop' && (
                <span className="chip" style={{ marginLeft: 6 }} data-testid="route-modus-chip">
                  bovenop de gewone route
                </span>
              )}{' '}
              — {route.samenvatting}
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
        <div className="actions" style={{ margin: 0, justifyContent: 'flex-start' }}>
          <button type="button" className="btn secondary" onClick={() => setEditor({ ...LEEG, lagen: [{ accordeurId: '', drempel: '' }] })}>
            + Leveranciersroute
          </button>
        </div>
      )}
      {editor && (
        <div className="panel" style={{ display: 'grid', gap: 10, padding: 10, minWidth: 0 }} data-testid="leverancier-route-editor">
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
            <div style={{ maxWidth: 420 }}>
              <SearchableCombobox
                label="leverancier"
                toonLabel={false}
                placeholder="Leverancier toevoegen… (open documenten bovenaan)"
                opties={opties}
                waarde={null}
                laden={editor !== null && leverancierKandidaten === null && crediteuren.length === 0}
                onWijzig={(id) => {
                  if (!id || editor.vendorIds.includes(id)) return
                  setEditor({ ...editor, vendorIds: [...editor.vendorIds, id] })
                }}
              />
            </div>
          </div>
          <div style={{ display: 'grid', gap: 6 }}>
            <span>Werking</span>
            <KeuzeKaarten<LeverancierRouteModus>
              naam={`route-modus-${editor.routeId ?? 'nieuw'}`}
              waarde={editor.modus}
              onKies={(modus) => setEditor({ ...editor, modus })}
              opties={[
                {
                  waarde: 'vervangt',
                  ariaLabel: 'Vervangt de gewone route',
                  kop: <b>Vervangt de gewone route</b>,
                  uitleg: 'Alleen de lagen hieronder — de gewone accordeurs zien deze facturen niet.',
                },
                {
                  waarde: 'bovenop',
                  ariaLabel: 'Bovenop de gewone route',
                  kop: <b>Bovenop de gewone route</b>,
                  uitleg: 'De gewone lagen blijven; de lagen hieronder komen erbij. Wijzigt de gewone route, dan volgt deze route mee.',
                },
              ]}
            />
            {editor.modus === 'bovenop' && (
              <KeuzeKaarten<LeverancierRoutePositie>
                naam={`route-positie-${editor.routeId ?? 'nieuw'}`}
                waarde={editor.positie}
                onKies={(positie) => setEditor({ ...editor, positie })}
                opties={[
                  { waarde: 'voor', ariaLabel: 'Extra laag vóór laag 1', kop: <b>Vóór laag 1</b>, uitleg: 'De extra accordeur kijkt als eerste.' },
                  { waarde: 'na', ariaLabel: 'Extra laag ná de laatste laag', kop: <b>Ná de laatste laag</b>, uitleg: 'De extra accordeur kijkt als laatste.' },
                ]}
              />
            )}
          </div>
          {kandidaten.length === 0 && naam && (
            <GeenAccordeursMelding
              administratieId={administratieId}
              naam={naam}
              isBeheerder={isBeheerder}
              onGekoppeld={() => onKandidatenHerladen?.()}
              compact
            />
          )}
          {editor.lagen.map((laag, index) => (
            <div key={index} style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <span style={{ minWidth: 52 }}>{editor.modus === 'bovenop' ? `Extra laag ${index + 1}` : `Laag ${index + 1}`}</span>
              <Select
                aria-label={`Accordeur route-laag ${index + 1}`}
                value={laag.accordeurId}
                onChange={(e) => setEditor({ ...editor, lagen: editor.lagen.map((l, i) => (i === index ? { ...l, accordeurId: e.target.value } : l)) })}
                style={{ width: 'auto', minWidth: 160, maxWidth: 280 }}
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
                style={{ width: 220, maxWidth: '100%' }}
                value={laag.drempel}
                onChange={(e) => setEditor({ ...editor, lagen: editor.lagen.map((l, i) => (i === index ? { ...l, drempel: e.target.value } : l)) })}
              />
              <button type="button" className="btn secondary" onClick={() => setEditor({ ...editor, lagen: editor.lagen.filter((_, i) => i !== index) })}>
                Verwijderen
              </button>
            </div>
          ))}
          <div className="actions" style={{ margin: 0, justifyContent: 'flex-start', flexWrap: 'wrap' }}>
            <button type="button" className="btn secondary" onClick={() => setEditor({ ...editor, lagen: [...editor.lagen, { accordeurId: '', drempel: '' }] })}>
              + Laag toevoegen
            </button>
            {/* BUG 18-09 regel 4: de gewenste accordeur ontbreekt in de lijst (geen toegang) → scope-only koppelen, dan herladen. */}
            {kandidaten.length > 0 && isBeheerder && naam && (
              <AndereAccordeurKoppelen administratieId={administratieId} naam={naam} onGekoppeld={() => onKandidatenHerladen?.()} />
            )}
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
