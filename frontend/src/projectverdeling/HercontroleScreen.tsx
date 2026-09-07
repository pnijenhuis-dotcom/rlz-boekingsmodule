// Inzicht › Projectverdeling — KANTOORBREED (opdracht 06-09 blok B; mockup inzicht-kantoorbreed.html ①②⑨
// = bouwnorm, zelfde patroon als Inzicht › Reconciliatie). De maandelijkse hercontrole (blok C 04-09, ⑥)
// rekent geboekte pro-rato-verdelingen opnieuw uit tegen de actuele omzetstand; wijkt de verdeling boven de
// administratie-drempel af, dan staat het signaal hier — over álle administraties in scope (RLS blijft de
// waarheid), zwaarste afwijking eerst, server-side gepagineerd (25), facet administratie + zoekterm in de URL
// (filter, nooit poort), tellers "N signalen · over M administraties". Elke rij draagt de BESTAANDE actie
// "Herverdelen…" (dezelfde dialoog + server-route als op het controlescherm: tegenboeken + nieuwe verdeling als
// voorstel, mens boekt opnieuw) én de deep-link naar het document. Geen nieuwe motor — alleen lijst + ingang.
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import type { ProjectverdelingDeelDto, ProjectverdelingSignaalLijstDto, ProjectverdelingSignaalRijDto } from '../api/types'
import { HerverdeelDialoog, euro, periodeLabel, vergelijk } from '../document/HerverdeelDialoog'
import { haalHercontroleSignalenOp } from '../document/projectverdelingApi'
import { AdministratieCombobox } from '../ui/AdministratieCombobox'
import { FoutMelding } from '../ui/FoutMelding'
import { Badge, Button, SkeletonRegels, useToastOptioneel } from '../ui/basis'
import { useAdministraties } from '../werkvoorraad/useAdministraties'

const ALLE = '__alle'
/** Aantal gewijzigde projecten dat de compacte kolom toont vóór "+ n". */
const COMPACT_MAX = 3

function ddmm(iso: string | null | undefined): string {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('nl-NL', { day: '2-digit', month: '2-digit' })
}

function pctLabel(pct: string): string {
  return `${Number(pct).toLocaleString('nl-NL', { maximumFractionDigits: 2 })} %`
}

/** Deep-link naar het controlescherm — zelfde padopbouw als de reconciliatie-bevindingen (`_doel_pad`). */
export function documentPad(r: ProjectverdelingSignaalRijDto): string {
  return `/?administratie=${r.administratie_id}&document=${r.document_id}`
}

/** Compacte weergave "oud → nieuw": alleen de projecten waarvan het deel verschuift, grootste nieuwe deel eerst. */
export function verschuivingen(oud: ProjectverdelingDeelDto[], nieuw: ProjectverdelingDeelDto[]) {
  return vergelijk(oud, nieuw).filter((r) => r.oud !== r.nieuw)
}

export function HercontroleScreen() {
  const { administraties } = useAdministraties()
  const toast = useToastOptioneel()
  const [zoekParams, setZoekParams] = useSearchParams()
  const administratieId = zoekParams.get('administratie') ?? zoekParams.get('administratie_id') ?? ''
  const zoek = zoekParams.get('q') ?? ''
  const paginaParam = Number(zoekParams.get('pagina') ?? '1')
  const pagina = Number.isInteger(paginaParam) && paginaParam >= 1 ? paginaParam : 1
  const [data, setData] = useState<ProjectverdelingSignaalLijstDto | null>(null)
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [versie, setVersie] = useState(0)
  const [herverdeelRij, setHerverdeelRij] = useState<ProjectverdelingSignaalRijDto | null>(null)

  const herlaad = useCallback(() => setVersie((v) => v + 1), [])

  useEffect(() => {
    let actueel = true
    setLaadFout(null)
    haalHercontroleSignalenOp({ pagina, administratieId: administratieId || null, q: zoek })
      .then((d) => {
        if (actueel) setData(d)
      })
      .catch((err: unknown) => {
        if (actueel) setLaadFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
    return () => {
      actueel = false
    }
  }, [pagina, zoek, administratieId, versie])

  /** Facet/zoekterm/pagina leven in de URL (deep-linkbaar, ‹ › en terugweg behouden het filter). */
  const zetParams = (patch: Record<string, string | null>) => {
    const p = new URLSearchParams(zoekParams)
    for (const [naam, waarde] of Object.entries(patch)) {
      if (waarde) p.set(naam, waarde)
      else p.delete(naam)
    }
    p.delete('administratie_id') // legacy-param opruimen zodra er gekozen wordt
    setZoekParams(p, { replace: true })
  }
  const zetFilter = (patch: Record<string, string | null>) => zetParams({ ...patch, pagina: null })

  const comboboxOpties = useMemo(
    () => [{ id: ALLE, naam: 'Alle administraties' }, ...(administraties ?? [])],
    [administraties],
  )
  const rijen = data?.rijen ?? []
  const paginas = Math.max(1, Math.ceil((data?.totaal ?? 0) / (data?.per_pagina ?? 25)))
  const tellers = data?.tellers ?? { signalen: data?.totaal ?? 0, administraties: data?.administraties ?? 0 }
  const gefilterd = administratieId !== '' || zoek.trim() !== ''

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 style={{ margin: 0 }}>Inzicht › Projectverdeling</h1>
          <div className="hint" style={{ marginTop: 2 }}>
            Geboekte facturen waarvan de verdeling over projecten (pro rato omzet) ná het boeken is gaan afwijken omdat de omzet
            van die maand nog veranderde — over al je administraties, zwaarste afwijking eerst. Herverdelen = tegenboeken en de
            nieuwe verdeling als voorstel klaarzetten; u boekt daarna opnieuw.
          </div>
        </div>
      </div>

      <div className="panel" data-testid="hercontrole-paneel" style={{ padding: 0, overflow: 'hidden' }}>
        <div
          className="p-kop"
          style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 18px', borderBottom: '1px solid var(--border)', flexWrap: 'wrap' }}
        >
          <h2 style={{ margin: 0, fontSize: 14.5 }}>Hercontrole projectverdeling</h2>
          {data && (
            <>
              <Badge variant={tellers.signalen > 0 ? 'warn' : 'stil'} data-testid="chip-signalen">
                {tellers.signalen} {tellers.signalen === 1 ? 'signaal' : 'signalen'}
              </Badge>
              <Badge variant="stil" data-testid="chip-administraties">
                over {tellers.administraties} {tellers.administraties === 1 ? 'administratie' : 'administraties'}
              </Badge>
            </>
          )}
          <span style={{ marginLeft: 'auto' }} />
          <div style={{ minWidth: 220 }}>
            <AdministratieCombobox
              label="Administratie"
              toonLabel={false}
              administraties={comboboxOpties}
              waarde={administratieId || ALLE}
              onWijzig={(id) => zetFilter({ administratie: id === ALLE ? null : id })}
              placeholder="Administratie: alle"
            />
          </div>
          <input
            type="search"
            aria-label="Zoek leverancier of referentie"
            placeholder="🔍 leverancier of referentie…"
            value={zoek}
            onChange={(e) => zetFilter({ q: e.target.value || null })}
            style={{ width: 220, maxWidth: '100%' }}
          />
        </div>

        {laadFout && <FoutMelding melding="De hercontrole-signalen konden niet geladen worden." detail={laadFout} onOpnieuw={herlaad} />}
        {data === null && !laadFout && <SkeletonRegels />}
        {data !== null && rijen.length === 0 && (
          <div className="hint" style={{ padding: '14px 18px' }} data-testid="hercontrole-leeg">
            {gefilterd
              ? 'Geen afwijkingen binnen dit filter.'
              : 'Geen afwijkingen — de maandelijkse hercontrole draait mee in de dagelijkse sync.'}
          </div>
        )}
        {rijen.length > 0 && (
          <div className="tabel-scroll">
            <table data-testid="hercontrole-tabel">
              <thead>
                <tr>
                  <th>Leverancier</th>
                  <th style={{ width: '18%' }}>Administratie</th>
                  <th style={{ width: 130 }}>Afwijking</th>
                  <th>Verdeling oud → nieuw</th>
                  <th style={{ width: 300 }} />
                </tr>
              </thead>
              <tbody>
                {rijen.map((r) => {
                  const verschoven = verschuivingen(r.delen_oud ?? [], r.delen_nieuw ?? [])
                  return (
                    <tr key={r.document_id} data-testid="hercontrole-rij">
                      <td>
                        <div>
                          <b>{r.leverancier ?? r.bestandsnaam}</b>
                        </div>
                        <div className="hint" style={{ margin: 0, fontSize: 11.5 }}>
                          {[r.referentie, r.totaalbedrag ? euro(r.totaalbedrag) : null, r.geboekt_op ? `geboekt ${ddmm(r.geboekt_op)}` : null]
                            .filter(Boolean)
                            .join(' · ')}
                        </div>
                      </td>
                      <td>
                        <Link to={`/?administratie=${r.administratie_id}`} className="text-primary no-underline hover:underline">
                          {r.administratie_naam}
                        </Link>
                      </td>
                      <td>
                        <Badge variant="warn" data-testid="chip-afwijking">
                          {pctLabel(r.afwijking_pct)} afwijking
                        </Badge>
                        <div className="hint" style={{ margin: 0, fontSize: 11.5 }}>
                          drempel {pctLabel(r.drempel_pct)} · omzet {r.pro_rato_periode_label ?? periodeLabel(r.pro_rato_periode)}
                        </div>
                      </td>
                      <td>
                        {verschoven.length === 0 ? (
                          <span className="hint">—</span>
                        ) : (
                          <div style={{ fontSize: 12.5 }}>
                            {verschoven.slice(0, COMPACT_MAX).map((v) => (
                              <div key={v.project_id} style={{ whiteSpace: 'nowrap' }}>
                                {v.naam}: {euro(v.oud)} → <b>{euro(v.nieuw)}</b>
                              </div>
                            ))}
                            {verschoven.length > COMPACT_MAX && (
                              <div className="hint" style={{ margin: 0, fontSize: 11.5 }}>
                                + {verschoven.length - COMPACT_MAX} {verschoven.length - COMPACT_MAX === 1 ? 'project' : 'projecten'}
                              </div>
                            )}
                          </div>
                        )}
                      </td>
                      <td className="acties" style={{ whiteSpace: 'nowrap', textAlign: 'right' }}>
                        <Button
                          variant="secundair"
                          maat="klein"
                          aria-label={`Herverdelen: ${r.leverancier ?? r.bestandsnaam} ${r.referentie ?? ''}`.trim()}
                          onClick={() => setHerverdeelRij(r)}
                        >
                          Herverdelen…
                        </Button>{' '}
                        <Link to={documentPad(r)} className="btn secondary" aria-label={`Naar het document van ${r.leverancier ?? r.bestandsnaam}`}>
                          Naar het document →
                        </Link>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        {data && (
          <div
            className="voet hint"
            data-testid="hercontrole-voet"
            style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 8, padding: '10px 18px', borderTop: '1px solid var(--border)', flexWrap: 'wrap' }}
          >
            <Button variant="ghost" maat="klein" aria-label="Vorige pagina" disabled={pagina <= 1} onClick={() => zetParams({ pagina: String(pagina - 1) })}>
              ‹
            </Button>
            <span>
              {pagina} van {paginas}
            </span>
            <Button
              variant="ghost"
              maat="klein"
              aria-label="Volgende pagina"
              disabled={pagina >= paginas}
              onClick={() => zetParams({ pagina: String(pagina + 1) })}
            >
              ›
            </Button>
            <span>
              · {data.totaal} {data.totaal === 1 ? 'signaal' : 'signalen'} over {data.administraties}{' '}
              {data.administraties === 1 ? 'administratie' : 'administraties'}
            </span>
          </div>
        )}
      </div>

      {herverdeelRij && (
        <HerverdeelDialoog
          administratieId={herverdeelRij.administratie_id}
          documentId={herverdeelRij.document_id}
          delenOud={herverdeelRij.delen_oud ?? []}
          delenNieuw={herverdeelRij.delen_nieuw ?? []}
          periode={herverdeelRij.pro_rato_periode}
          afwijkingPct={herverdeelRij.afwijking_pct}
          onSluiten={() => setHerverdeelRij(null)}
          onGelukt={() => {
            const naam = herverdeelRij.leverancier ?? herverdeelRij.bestandsnaam
            setHerverdeelRij(null)
            toast.meld(`Tegengeboekt — ${naam} staat weer op "te controleren" mét de nieuwe verdeling als voorstel.`)
            herlaad()
          }}
        />
      )}
    </div>
  )
}
