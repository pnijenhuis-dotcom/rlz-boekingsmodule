// Inzicht › Verplichtingen — KANTOORBREED (blok B 04-09, mockup offerte-matching.html blok 3 +
// notitie ⑦; het kantoorbrede lijstpatroon van Inzicht › Terugkerende facturen 1-op-1).
//
// Eén rij = één goedgekeurde verplichting mét verbruiksstand en precies één primaire handeling
// ("Open verplichting") + ⋯-menu ("Laten vervallen…"). De server sorteert (overschreden eerst,
// grootste overschrijding bovenaan), pagineert en levert facetten/tellers; de client formatteert
// en rekent niets. Teal = actie, groen = status; een lege stand blijft een actie.
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { AdministratieCombobox } from '../ui/AdministratieCombobox'
import { FoutMelding } from '../ui/FoutMelding'
import {
  AnkerPopup,
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  FormField,
  SkeletonRegels,
  useToastOptioneel,
} from '../ui/basis'
import { formatBedrag, formatDatumKort } from '../werkvoorraad/format'
import { statusLabel } from '../werkvoorraad/status'
import { useAdministraties } from '../werkvoorraad/useAdministraties'
import { VerbruiksBalk } from './VerbruiksBalk'
import {
  haalVerplichtingenKantoorbreed,
  laatVerplichtingVervallen,
  LIJST_STATUS_FACETTEN,
  LIJST_STATUS_LABEL,
  SOORT_LABEL_TEKST,
  type VerplichtingKantoorLijstDto,
  type VerplichtingKantoorRijDto,
  type VerplichtingStatusFacet,
} from './verplichtingApi'

const ALLE = '__alle'

function isStatusFacet(w: string | null): w is VerplichtingStatusFacet {
  return w !== null && (LIJST_STATUS_FACETTEN as string[]).includes(w)
}

function ddmm(iso: string): string {
  return new Date(iso).toLocaleDateString('nl-NL', { day: '2-digit', month: '2-digit' })
}

export function VerplichtingenScreen() {
  const { administraties } = useAdministraties()
  const toast = useToastOptioneel()
  const [zoekParams, setZoekParams] = useSearchParams()
  const administratieId = zoekParams.get('administratie_id') ?? zoekParams.get('administratie') ?? ''
  const statusParam = zoekParams.get('status')
  const status: VerplichtingStatusFacet = isStatusFacet(statusParam) ? statusParam : 'lopend'

  const [zoek, setZoek] = useState('')
  const [pagina, setPagina] = useState(1)
  const [data, setData] = useState<VerplichtingKantoorLijstDto | null>(null)
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [actieFout, setActieFout] = useState<string | null>(null)
  const [versie, setVersie] = useState(0)
  const [menuVoor, setMenuVoor] = useState<string | null>(null)
  const menuKnoppen = useRef<Record<string, HTMLButtonElement | null>>({})
  const [uitgeklapt, setUitgeklapt] = useState<Set<string>>(new Set())
  const [vervalVoor, setVervalVoor] = useState<VerplichtingKantoorRijDto | null>(null)

  const herlaad = useCallback(() => setVersie((v) => v + 1), [])

  useEffect(() => {
    let actueel = true
    setLaadFout(null)
    haalVerplichtingenKantoorbreed({ pagina, q: zoek, administratieId: administratieId || null, status })
      .then((d) => {
        if (actueel) setData(d)
      })
      .catch((err: unknown) => {
        if (actueel) setLaadFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
    return () => {
      actueel = false
    }
  }, [pagina, zoek, administratieId, status, versie])

  const zetParam = (naam: string, waarde: string | null) => {
    const p = new URLSearchParams(zoekParams)
    if (waarde) p.set(naam, waarde)
    else p.delete(naam)
    p.delete('administratie')
    setZoekParams(p, { replace: true })
    setPagina(1)
  }

  const comboboxOpties = useMemo(
    () => [{ id: ALLE, naam: 'Alle administraties' }, ...(administraties ?? [])],
    [administraties],
  )

  const rijen = data?.rijen ?? []
  const paginas = Math.max(1, Math.ceil((data?.totaal ?? 0) / (data?.per_pagina ?? 25)))
  const sleutel = (r: VerplichtingKantoorRijDto) => r.document_id
  const titel = (r: VerplichtingKantoorRijDto) =>
    `${r.offertenummer ?? 'zonder nummer'} ${r.leverancier_naam ?? 'onbekende leverancier'}`

  const wisselUitklap = (id: string) =>
    setUitgeklapt((s) => {
      const n = new Set(s)
      if (n.has(id)) n.delete(id)
      else n.add(id)
      return n
    })

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 style={{ margin: 0 }}>Inzicht › Verplichtingen</h1>
          <div className="hint" style={{ marginTop: 2 }}>
            Goedgekeurde offertes, prijsopgaven en opdrachtbevestigingen over al je administraties, mét de
            verbruiksstand: wat is er al aan facturen tegen weggeboekt en hoeveel ruimte is er nog. Cumulatief — de
            grens ís het goedgekeurde bedrag.
          </div>
        </div>
      </div>

      <div className="panel" data-testid="verplichtingen-paneel" style={{ padding: 0, overflow: 'hidden' }}>
        <div
          className="p-kop"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: '14px 18px',
            borderBottom: '1px solid var(--border)',
            flexWrap: 'wrap',
          }}
        >
          <h2 style={{ margin: 0, fontSize: 14.5 }}>Verplichtingen</h2>
          {data && (
            <>
              <Badge variant="ok" data-testid="chip-lopend">
                {data.tellers.lopend} lopend
              </Badge>
              <Badge variant="warn" data-testid="chip-overschreden">
                {data.tellers.overschreden} overschreden
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
              onWijzig={(id) => zetParam('administratie_id', id === ALLE ? null : id)}
              placeholder="Administratie: alle"
            />
          </div>
          <select
            aria-label="Status"
            value={status}
            onChange={(e) => zetParam('status', e.target.value === 'lopend' ? null : e.target.value)}
            style={{ width: 'auto' }}
          >
            {LIJST_STATUS_FACETTEN.map((s) => (
              <option key={s} value={s}>
                Status: {LIJST_STATUS_LABEL[s]}
                {data ? ` (${data.facetten.status[s] ?? 0})` : ''}
              </option>
            ))}
          </select>
          <input
            type="search"
            aria-label="Zoek offerte of leverancier"
            placeholder="🔍 zoek offerte, leverancier…"
            value={zoek}
            onChange={(e) => {
              setZoek(e.target.value)
              setPagina(1)
            }}
            style={{ width: 220, maxWidth: '100%' }}
          />
        </div>

        {actieFout && (
          <div className="fout" style={{ margin: '10px 18px' }}>
            {actieFout}
          </div>
        )}
        {laadFout && (
          <FoutMelding melding="De verplichtingen konden niet geladen worden." detail={laadFout} onOpnieuw={herlaad} />
        )}
        {data === null && !laadFout && <SkeletonRegels />}
        {data !== null && rijen.length === 0 && (
          <p className="hint" style={{ padding: '14px 18px' }} data-testid="verplichtingen-leeg">
            {status === 'lopend'
              ? 'Nog geen goedgekeurde verplichtingen. Zet een offerte, prijsopgave of opdrachtbevestiging in de werkvoorraad (tab \u201cVerplichtingen\u201d) en laat die accorderen — daarna wordt elke factuur er cumulatief tegen gematcht.'
              : `Geen verplichtingen met status "${LIJST_STATUS_LABEL[status]}".`}
          </p>
        )}
        {rijen.length > 0 && (
          <div className="tabel-scroll">
            <table data-testid="verplichtingen-tabel">
              <thead>
                <tr>
                  <th style={{ width: '26%' }}>Offerte</th>
                  <th>Administratie</th>
                  <th>Project · akkoord</th>
                  <th style={{ width: '24%' }}>Verbruik</th>
                  <th>Stand</th>
                  <th style={{ width: 210 }} />
                </tr>
              </thead>
              <tbody>
                {rijen.map((r) => {
                  const key = sleutel(r)
                  const open = uitgeklapt.has(key)
                  return (
                    <Fragment key={key}>
                      <tr data-testid="verplichting-rij">
                        <td>
                          <div style={{ fontWeight: 700 }}>
                            {r.offertenummer ?? '— zonder nummer —'} {r.leverancier_naam ?? 'onbekende leverancier'}
                          </div>
                          <div className="hint" style={{ margin: 0, fontSize: 11.5 }}>
                            {r.soort_label ? SOORT_LABEL_TEKST[r.soort_label] : 'verplichting'}
                            {r.geldig_tot ? ` · geldig t/m ${formatDatumKort(r.geldig_tot)}` : ''}
                          </div>
                        </td>
                        <td>
                          <Link
                            to={`/?administratie=${r.administratie_id}`}
                            className="text-primary no-underline hover:underline"
                          >
                            {r.administratie_naam}
                          </Link>
                        </td>
                        <td>
                          {r.project_naam ?? 'geen project'}
                          <div className="hint" style={{ margin: 0, fontSize: 11.5 }}>
                            {r.goedgekeurd_op ? `akkoord ${ddmm(r.goedgekeurd_op)}` : 'akkoord onbekend'}
                            {r.goedgekeurd_door_naam ? ` · ${r.goedgekeurd_door_naam}` : ''}
                          </div>
                        </td>
                        <td>
                          <VerbruiksBalk
                            verbruikt={r.verbruikt_excl}
                            totaal={r.totaal_excl}
                            percentage={r.percentage}
                            over={r.over_excl}
                            openFacturen={{ aantal: r.open_facturen_aantal, bedrag: r.open_facturen_excl }}
                            testId={`balk-${key}`}
                          />
                        </td>
                        <td>
                          {r.status === 'vervallen' ? (
                            <Badge variant="stil">vervallen</Badge>
                          ) : r.status === 'overschreden' ? (
                            <span className="chip afwijking">
                              − {formatBedrag(r.over_excl)} over
                            </span>
                          ) : (
                            <span className="chip ok">binnen</span>
                          )}
                        </td>
                        <td className="acties" style={{ whiteSpace: 'nowrap', textAlign: 'right' }}>
                          <button
                            type="button"
                            className="linkbtn"
                            aria-expanded={open}
                            onClick={() => wisselUitklap(key)}
                            aria-label={`Gekoppelde facturen van ${titel(r)}`}
                          >
                            {r.facturen.length} {r.facturen.length === 1 ? 'factuur' : 'facturen'} {open ? '▴' : '▾'}
                          </button>{' '}
                          <Link
                            to={`/verplichting/${r.administratie_id}/${r.document_id}`}
                            className="btn secondary"
                            aria-label={`Open verplichting ${titel(r)}`}
                          >
                            Open verplichting →
                          </Link>{' '}
                          <button
                            type="button"
                            className="linkbtn"
                            aria-label={`Meer acties ${titel(r)}`}
                            aria-haspopup="menu"
                            aria-expanded={menuVoor === key}
                            ref={(el) => {
                              menuKnoppen.current[key] = el
                            }}
                            onClick={() => setMenuVoor((h) => (h === key ? null : key))}
                          >
                            ⋯
                          </button>
                          <AnkerPopup
                            open={menuVoor === key}
                            anker={menuKnoppen.current[key] ?? null}
                            kant="onder"
                            uitlijning="eind"
                            className="rijmenu"
                            role="menu"
                            onAnkerUitBeeld={() => setMenuVoor(null)}
                          >
                            {r.status === 'vervallen' ? (
                              <span className="hint" style={{ padding: '2px 8px' }}>
                                Al vervallen — nieuwe facturen worden hier niet meer tegen gematcht.
                              </span>
                            ) : (
                              <button
                                type="button"
                                className="linkbtn"
                                role="menuitem"
                                onClick={() => {
                                  setMenuVoor(null)
                                  setVervalVoor(r)
                                }}
                              >
                                Laten vervallen…
                              </button>
                            )}
                          </AnkerPopup>
                        </td>
                      </tr>
                      {open && (
                        <tr className="cluster-leden" data-testid="verplichting-facturen">
                          <td
                            colSpan={6}
                            style={{
                              paddingLeft: 34,
                              background: 'var(--panel-2)',
                              fontSize: 12,
                              color: 'var(--muted)',
                            }}
                          >
                            {r.facturen.length === 0 ? (
                              <div>Nog geen facturen tegen deze verplichting gematcht.</div>
                            ) : (
                              r.facturen.map((f) => (
                                <div key={f.document_id}>
                                  <Link to={`/documenten/${r.administratie_id}/${f.document_id}`}>
                                    <b style={{ color: 'var(--text)' }}>
                                      {f.referentie ?? f.document_id.slice(0, 8)}
                                    </b>
                                  </Link>{' '}
                                  · {f.factuurdatum ? formatDatumKort(f.factuurdatum) : 'geen datum'} ·{' '}
                                  {formatBedrag(f.bedrag_excl)} ·{' '}
                                  {f.verrekend ? 'verrekend in de stand' : `${statusLabel(f.status)} — telt nog niet mee`}
                                </div>
                              ))
                            )}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        {data && (
          <div
            className="voet hint"
            data-testid="verplichtingen-voet"
            style={{
              margin: 0,
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '10px 18px',
              borderTop: '1px solid var(--border)',
              flexWrap: 'wrap',
            }}
          >
            <Button
              variant="ghost"
              maat="klein"
              aria-label="Vorige pagina"
              disabled={pagina <= 1}
              onClick={() => setPagina((p) => p - 1)}
            >
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
              onClick={() => setPagina((p) => p + 1)}
            >
              ›
            </Button>
            <span>
              · {data.totaal} {data.totaal === 1 ? 'verplichting' : 'verplichtingen'} over{' '}
              {data.administraties_in_selectie}{' '}
              {data.administraties_in_selectie === 1 ? 'administratie' : 'administraties'}
            </span>
            <span>· overschreden eerst, dan het hoogste verbruik · ⋯-menu: laten vervallen (audit)</span>
          </div>
        )}
      </div>

      {vervalVoor && (
        <VervalDialoog
          rij={vervalVoor}
          onKlaar={() => {
            toast.meld(
              `${vervalVoor.offertenummer ?? 'Verplichting'} laten vervallen — nieuwe facturen worden er niet meer tegen gematcht.`,
            )
            setVervalVoor(null)
            herlaad()
          }}
          onFout={(melding) => {
            setActieFout(melding)
            setVervalVoor(null)
          }}
          onAnnuleren={() => setVervalVoor(null)}
        />
      )}
    </div>
  )
}

/** ⑥ Laten vervallen — reden verplicht; gematchte facturen blijven ongemoeid. */
function VervalDialoog({
  rij,
  onKlaar,
  onFout,
  onAnnuleren,
}: {
  rij: VerplichtingKantoorRijDto
  onKlaar: () => void
  onFout: (melding: string) => void
  onAnnuleren: () => void
}) {
  const [reden, setReden] = useState('')
  const [bezig, setBezig] = useState(false)

  const versturen = async () => {
    setBezig(true)
    try {
      await laatVerplichtingVervallen(rij.administratie_id, rij.document_id, reden.trim())
      onKlaar()
    } catch (err) {
      onFout(err instanceof ApiError ? err.message : 'Laten vervallen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onAnnuleren()}>
      <DialogContent data-testid="verval-dialoog">
        <DialogTitle>Verplichting laten vervallen{rij.offertenummer ? ` — ${rij.offertenummer}` : ''}</DialogTitle>
        <DialogDescription>
          {rij.leverancier_naam ?? 'Deze leverancier'} · {rij.administratie_naam}. Vanaf nu worden er geen nieuwe
          facturen meer tegen deze verplichting gematcht; de {rij.facturen.length} al gekoppelde{' '}
          {rij.facturen.length === 1 ? 'factuur blijft' : 'facturen blijven'} ongemoeid. De reden is verplicht.
        </DialogDescription>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void versturen()
          }}
        >
          <FormField label="Reden" htmlFor="lijst-verval-reden">
            <textarea
              id="lijst-verval-reden"
              required
              rows={3}
              value={reden}
              onChange={(e) => setReden(e.target.value)}
              placeholder="bv. opdracht is niet doorgegaan"
              style={{ width: '100%', fontFamily: 'inherit', fontSize: 12.5 }}
            />
          </FormField>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onAnnuleren} disabled={bezig}>
              Annuleren
            </Button>
            <Button type="submit" variant="gevaar" disabled={bezig || reden.trim() === ''}>
              {bezig ? 'Bezig…' : 'Laten vervallen'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
