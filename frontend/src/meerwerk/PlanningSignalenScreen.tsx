// Weekstaten ontbreken — KANTOORBREED (mini-run 06-09 blok A; mockup inzicht-kantoorbreed.html ①②⑨ =
// bouwnorm, stijl meerwerk-kantoor.html). De veld-app toont geplande weken maar zes weken terug
// (venster-besluit 04-09); een geplande week zonder ingediende weekstaat die uit dat venster valt
// verdween stil. Hier staat dat signaal kantoorbreed (scope = de administraties van de gebruiker mét de
// uren-opt-in, RLS blijft de waarheid): server-side paginering 25, administratie-facet (filter, nooit
// poort), filter open/afgemeld/alle, tellers "N signalen over M administraties", oudste week bovenaan.
// Eén rij = één (veldwerker, project, week) mét precies één handeling (②): "Herinnering sturen" via het
// bestaande push-anders-mail-kanaal (max 1/dag → knop uit "herinnerd vandaag") of "Afmelden…" mét
// verplichte reden; afgemeld → "Toch tonen". Deep-link naar de weekplanning per rij. Geen blokkade.
// Teal = actie, groen = status.
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { AdministratieCombobox } from '../ui/AdministratieCombobox'
import { FoutMelding } from '../ui/FoutMelding'
import {
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
import { useAdministraties } from '../werkvoorraad/useAdministraties'
import {
  FILTER_LABEL,
  FILTERS,
  haalPlanningSignalen,
  herinnerPlanningSignaal,
  meldPlanningSignaalAf,
  planningPad,
  sleutelVan,
  trekAfmeldingIn,
  type PlanningSignaalDto,
  type PlanningSignalenLijstDto,
  type SignaalFilter,
} from './planningSignaalApi'

const ALLE = '__alle'
/** Minimale lengte van een reden — spiegelt de server. */
const REDEN_MINIMUM = 5

function ddmm(iso: string): string {
  return new Date(iso).toLocaleDateString('nl-NL', { day: '2-digit', month: '2-digit' })
}

function dagen(decimaal: string): string {
  const n = Number(decimaal)
  const tekst = Number.isFinite(n) ? String(n).replace('.', ',') : decimaal
  return `${tekst} ${n === 1 ? 'dag' : 'dagen'}`
}

function isFilter(w: string | null): w is SignaalFilter {
  return w !== null && (FILTERS as string[]).includes(w)
}

export function PlanningSignalenScreen() {
  const { administraties } = useAdministraties()
  const toast = useToastOptioneel()
  const [zoekParams, setZoekParams] = useSearchParams()
  const administratieId = zoekParams.get('administratie_id') ?? zoekParams.get('administratie') ?? ''
  const filterParam = zoekParams.get('filter')
  const filter: SignaalFilter = isFilter(filterParam) ? filterParam : 'open'
  const [pagina, setPagina] = useState(1)
  const [data, setData] = useState<PlanningSignalenLijstDto | null>(null)
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [geenRecht, setGeenRecht] = useState(false)
  const [actieFout, setActieFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState<string | null>(null)
  const [versie, setVersie] = useState(0)
  const [afmelden, setAfmelden] = useState<PlanningSignaalDto | null>(null)

  const herlaad = useCallback(() => setVersie((v) => v + 1), [])

  useEffect(() => {
    let actueel = true
    setLaadFout(null)
    haalPlanningSignalen({ pagina, filter, administratieId: administratieId || null })
      .then((d) => {
        if (actueel) setData(d)
      })
      .catch((err: unknown) => {
        if (!actueel) return
        if (err instanceof ApiError && err.status === 403) setGeenRecht(true)
        else setLaadFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
    return () => {
      actueel = false
    }
  }, [pagina, filter, administratieId, versie])

  const zetParam = (naam: string, waarde: string | null) => {
    const p = new URLSearchParams(zoekParams)
    if (waarde) p.set(naam, waarde)
    else p.delete(naam)
    p.delete('administratie')
    setZoekParams(p, { replace: true })
    setPagina(1)
  }

  const rijSleutel = (s: PlanningSignaalDto) => `${s.administratie_id}:${s.gebruiker_id}:${s.project_id}:${s.jaar}:${s.weeknummer}`

  const herinner = async (s: PlanningSignaalDto) => {
    setBezig(rijSleutel(s))
    setActieFout(null)
    try {
      const r = await herinnerPlanningSignaal(sleutelVan(s))
      toast.meld(`Herinnering verstuurd aan ${s.gebruiker_naam} (${r.kanaal}).`)
      herlaad()
    } catch (err) {
      setActieFout(err instanceof ApiError ? err.message : 'Herinnering versturen mislukt.')
    } finally {
      setBezig(null)
    }
  }

  const tochTonen = async (s: PlanningSignaalDto) => {
    setBezig(rijSleutel(s))
    setActieFout(null)
    try {
      await trekAfmeldingIn(sleutelVan(s))
      toast.meld('Afmelding ingetrokken — het signaal telt weer mee.')
      herlaad()
    } catch (err) {
      setActieFout(err instanceof ApiError ? err.message : 'Afmelding intrekken mislukt.')
    } finally {
      setBezig(null)
    }
  }

  const comboboxOpties = useMemo(
    () => [{ id: ALLE, naam: 'Alle administraties' }, ...(administraties ?? [])],
    [administraties],
  )
  const rijen = data?.rijen ?? []
  const paginas = Math.max(1, Math.ceil((data?.totaal ?? 0) / (data?.per_pagina ?? 25)))

  if (geenRecht) {
    return (
      <p className="hint">
        Meerwerk &amp; urenstaten vereist een module-recht — een Beheerder kent dit toe onder Gebruikers &amp; toegang.
      </p>
    )
  }

  /** Actie-kolom: precies één handeling per rij + de deep-link naar de weekplanning. */
  const actieVoor = (s: PlanningSignaalDto) => {
    const druk = bezig === rijSleutel(s)
    const deeplink = (
      <Link to={planningPad(s)} className="btn secondary" aria-label={`Naar de planning van week ${s.weeknummer} van ${s.gebruiker_naam}`}>
        Naar de planning →
      </Link>
    )
    if (s.status === 'afgemeld') {
      return (
        <>
          <button
            type="button"
            className="linkbtn"
            aria-label={`Toch tonen: week ${s.weeknummer} van ${s.gebruiker_naam}`}
            disabled={druk}
            onClick={() => void tochTonen(s)}
          >
            Toch tonen
          </button>{' '}
          {deeplink}
        </>
      )
    }
    return (
      <>
        <Button
          variant="secundair"
          maat="klein"
          aria-label={`Herinnering sturen aan ${s.gebruiker_naam} voor week ${s.weeknummer}`}
          disabled={druk || s.herinnerd_vandaag || !s.gebruiker_actief}
          title={
            s.herinnerd_vandaag
              ? 'Vandaag al herinnerd — morgen kan het opnieuw'
              : !s.gebruiker_actief
                ? 'De veldwerker is niet actief — herinneren heeft geen zin'
                : undefined
          }
          onClick={() => void herinner(s)}
        >
          {s.herinnerd_vandaag ? 'Herinnerd vandaag' : 'Herinnering sturen'}
        </Button>{' '}
        <Button
          variant="secundair"
          maat="klein"
          aria-label={`Afmelden: week ${s.weeknummer} van ${s.gebruiker_naam}`}
          disabled={druk}
          onClick={() => setAfmelden(s)}
        >
          Afmelden…
        </Button>{' '}
        {deeplink}
      </>
    )
  }

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 style={{ margin: 0 }}>Weekstaten ontbreken</h1>
          <div className="hint" style={{ marginTop: 2 }}>
            Geplande weken zonder ingediende weekstaat die ouder zijn dan de {data?.venster_weken ?? 6} weken die de veld-app
            toont — over al je administraties met uren &amp; meerwerk. Herinner de veldwerker (de week komt dan terug in zijn
            app) of meld het signaal af met een reden. Niets blokkeert.
          </div>
        </div>
      </div>

      <div className="panel" data-testid="planning-signalen-paneel" style={{ padding: 0, overflow: 'hidden' }}>
        <div
          className="p-kop"
          style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 18px', borderBottom: '1px solid var(--border)', flexWrap: 'wrap' }}
        >
          <h2 style={{ margin: 0, fontSize: 14.5 }}>Geplande weken zonder weekstaat</h2>
          {data && (
            <>
              <Badge variant={data.tellers.open > 0 ? 'warn' : 'stil'} data-testid="chip-open">
                {data.tellers.open} open
              </Badge>
              <Badge variant="stil" data-testid="chip-afgemeld">
                {data.tellers.afgemeld} afgemeld
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
          <div className="segment" role="group" aria-label="Filter">
            {FILTERS.map((f) => (
              <button
                key={f}
                type="button"
                className={filter === f ? 'actief' : undefined}
                onClick={() => zetParam('filter', f === 'open' ? null : f)}
              >
                {FILTER_LABEL[f]}
                {data ? ` (${f === 'open' ? data.tellers.open : f === 'afgemeld' ? data.tellers.afgemeld : data.tellers.open + data.tellers.afgemeld})` : ''}
              </button>
            ))}
          </div>
        </div>

        {actieFout && (
          <div className="fout" style={{ margin: '10px 18px' }}>
            {actieFout}
          </div>
        )}
        {laadFout && <FoutMelding melding="De signalen konden niet geladen worden." detail={laadFout} onOpnieuw={herlaad} />}
        {data === null && !laadFout && <SkeletonRegels />}
        {data !== null && rijen.length === 0 && (
          <div className="hint" style={{ padding: '14px 18px' }} data-testid="planning-signalen-leeg">
            {filter === 'open'
              ? 'Geen geplande weken zonder weekstaat buiten het app-venster — alles is ingediend of afgemeld.'
              : `Geen signalen met status "${FILTER_LABEL[filter]}".`}
          </div>
        )}
        {rijen.length > 0 && (
          <div className="tabel-scroll">
            <table data-testid="planning-signalen-tabel">
              <thead>
                <tr>
                  <th style={{ width: 90 }}>Week</th>
                  <th style={{ width: '16%' }}>Administratie</th>
                  <th>Veldwerker</th>
                  <th>Project</th>
                  <th style={{ width: 90 }}>Gepland</th>
                  <th style={{ width: 150 }}>Stand</th>
                  <th style={{ width: 380 }} />
                </tr>
              </thead>
              <tbody>
                {rijen.map((s) => (
                  <tr key={rijSleutel(s)} data-testid="planning-signaal-rij">
                    <td>
                      <strong>wk {s.weeknummer}</strong>
                      <div className="hint" style={{ margin: 0, fontSize: 11.5 }}>
                        {ddmm(s.maandag)} – {ddmm(s.zondag)}
                      </div>
                    </td>
                    <td>
                      <Link to={`/?administratie=${s.administratie_id}`} className="text-primary no-underline hover:underline">
                        {s.administratie_naam}
                      </Link>
                    </td>
                    <td>
                      {s.gebruiker_naam}
                      {!s.gebruiker_actief && (
                        <>
                          {' '}
                          <Badge variant="stil">niet actief</Badge>
                        </>
                      )}
                    </td>
                    <td>{s.project_naam ?? <span className="hint">onbekend project</span>}</td>
                    <td>{dagen(s.geplande_dagen)}</td>
                    <td>
                      {s.status === 'afgemeld' ? (
                        <Badge variant="stil" data-testid="chip-status">
                          afgemeld
                        </Badge>
                      ) : s.soort === 'concept' ? (
                        <Badge variant="warn" data-testid="chip-status">
                          concept, niet ingediend
                        </Badge>
                      ) : (
                        <Badge variant="danger" data-testid="chip-status">
                          geen weekstaat
                        </Badge>
                      )}
                      {s.laatste_herinnering && (
                        <div className="hint" style={{ margin: 0, fontSize: 11.5 }}>
                          herinnerd {ddmm(s.laatste_herinnering.op)} · {s.herinneringen}×
                          {s.laatste_herinnering.kanaal ? ` · ${s.laatste_herinnering.kanaal}` : ''}
                        </div>
                      )}
                      {s.afmelding && (
                        <div className="hint" style={{ margin: 0, fontSize: 11.5 }}>
                          afgemeld: {s.afmelding.reden}
                          {s.afmelding.door_naam ? ` · ${s.afmelding.door_naam}` : ''} · {ddmm(s.afmelding.op)}
                        </div>
                      )}
                    </td>
                    <td className="acties" style={{ whiteSpace: 'nowrap', textAlign: 'right' }}>
                      {actieVoor(s)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && (
          <div
            className="voet hint"
            data-testid="planning-signalen-voet"
            style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 8, padding: '10px 18px', borderTop: '1px solid var(--border)', flexWrap: 'wrap' }}
          >
            <Button variant="ghost" maat="klein" aria-label="Vorige pagina" disabled={pagina <= 1} onClick={() => setPagina((p) => p - 1)}>
              ‹
            </Button>
            <span>
              {pagina} van {paginas}
            </span>
            <Button variant="ghost" maat="klein" aria-label="Volgende pagina" disabled={pagina >= paginas} onClick={() => setPagina((p) => p + 1)}>
              ›
            </Button>
            <span>
              · {data.totaal} {data.totaal === 1 ? 'signaal' : 'signalen'} over {data.administraties_in_selectie}{' '}
              {data.administraties_in_selectie === 1 ? 'administratie' : 'administraties'}
            </span>
          </div>
        )}
      </div>

      {afmelden && (
        <AfmeldDialoog
          signaal={afmelden}
          onSluiten={() => setAfmelden(null)}
          onGelukt={() => {
            setAfmelden(null)
            toast.meld('Signaal afgemeld — het blijft zichtbaar onder "afgemeld".')
            herlaad()
          }}
        />
      )}
    </div>
  )
}

/** Afmelden mét verplichte, inhoudelijke reden (≥ 5 tekens, spiegel van de server) — gaat het audit log in. */
function AfmeldDialoog({
  signaal,
  onSluiten,
  onGelukt,
}: {
  signaal: PlanningSignaalDto
  onSluiten: () => void
  onGelukt: () => void
}) {
  const [reden, setReden] = useState('')
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const geldig = reden.trim().length >= REDEN_MINIMUM

  const bevestig = async () => {
    if (!geldig) return
    setBezig(true)
    setFout(null)
    try {
      await meldPlanningSignaalAf(sleutelVan(signaal), reden.trim())
      onGelukt()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Afmelden mislukt.')
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onSluiten()}>
      <DialogContent aria-describedby={undefined} data-testid="afmeld-dialoog">
        <DialogTitle>Signaal afmelden</DialogTitle>
        <DialogDescription>
          Het signaal telt daarna niet meer mee en blijft zichtbaar onder "afgemeld". Leg vast waarom er voor deze week geen
          weekstaat hoeft te komen — de reden komt in het audit log.
        </DialogDescription>
        <div className="hint" style={{ marginTop: 0 }}>
          Week {signaal.weeknummer} · {signaal.gebruiker_naam} · {signaal.project_naam ?? 'onbekend project'} ({signaal.administratie_naam})
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void bevestig()
          }}
        >
          <FormField label="Reden" htmlFor="planning-signaal-reden">
            <textarea
              id="planning-signaal-reden"
              required
              rows={4}
              value={reden}
              onChange={(e) => setReden(e.target.value)}
              placeholder="Bijvoorbeeld: die week ziek gemeld, niet gewerkt."
              style={{ width: '100%', fontFamily: 'inherit', fontSize: 12.5 }}
            />
          </FormField>
          {!geldig && reden.trim() !== '' && <div className="hint">Geef een inhoudelijke reden (minimaal {REDEN_MINIMUM} tekens).</div>}
          {fout && <div className="fout">{fout}</div>}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onSluiten} disabled={bezig}>
              Annuleren
            </Button>
            <Button type="submit" disabled={bezig || !geldig}>
              {bezig ? 'Bezig…' : 'Afmelden'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
