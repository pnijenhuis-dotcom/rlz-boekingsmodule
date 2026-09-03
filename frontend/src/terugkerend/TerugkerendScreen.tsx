// Inzicht › Terugkerende facturen — KANTOORBREED (design-ronde 03-09 blok B1; mockup
// inzicht-kantoorbreed.html paneel 1 + ontwerpnotities ①②③ = bouwnorm; principe "minimale mens,
// maximale autonomie", besluit Peter 02-09). Het autoboek-kandidaten-patroon: één kantoorbreed endpoint
// (scope = de administraties van de gebruiker, RLS blijft de waarheid), paginering 25 server-side,
// zoekveld, facetten administratie/status (filter, nooit poort), tellers "N signalen over M
// administraties", urgentste bovenaan. Eén rij = één signaal mét precies één handeling (②): ontbreekt →
// "Navragen bij leverancier…" (concept-mail, de MENS bewerkt en verstuurt), prijsstijging → "Naar de
// boeking →"; snooze/afmelden in het ⋯-menu. "⟳ Herbereken alles" = één kantoorbrede achtergrondrun
// (③, 202 + status-poll) — nooit meer per administratie klikken. Teal = actie, groen = status.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
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
import { useAdministraties } from '../werkvoorraad/useAdministraties'
import {
  haalConceptMail,
  haalHerberekenStatus,
  haalKantoorSignalen,
  haalLaatsteHerbereken,
  KANTOOR_STATUS_LABEL,
  snoozeTerugkerend,
  startHerberekenAlles,
  verstuurConceptMail,
  zetTerugkerendAfgemeld,
  zetTerugkerendDrempel,
  type ConceptMailDto,
  type HerberekenRunDto,
  type KantoorLijstDto,
  type KantoorRijDto,
  type KantoorStatusFacet,
} from './terugkerendApi'

const ALLE = '__alle'
const STATUS_FACETTEN: KantoorStatusFacet[] = ['aandacht', 'gesnoozed', 'afgemeld', 'alle']

function plusDagen(dagen: number): string {
  const d = new Date()
  d.setDate(d.getDate() + dagen)
  return d.toISOString().slice(0, 10)
}

function ddmm(iso: string): string {
  return new Date(iso).toLocaleDateString('nl-NL', { day: '2-digit', month: '2-digit' })
}

function tijd(iso: string): string {
  return new Date(iso).toLocaleString('nl-NL', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function isStatusFacet(w: string | null): w is KantoorStatusFacet {
  return w !== null && (STATUS_FACETTEN as string[]).includes(w)
}

/** Signaal-chip per rij (mockup: "verwacht ± 28-08 — 6 dagen te laat" / "prijs +14% t.o.v. vorige"). */
function signaalTekst(r: KantoorRijDto): string {
  if (r.soort === 'ontbreekt') {
    const d = r.dagen_te_laat ?? 0
    return `verwacht ± ${ddmm(r.verwacht_op)} — ${d} ${d === 1 ? 'dag' : 'dagen'} te laat`
  }
  const pct = Number(r.prijsstijging_pct ?? 0).toLocaleString('nl-NL', { maximumFractionDigits: 1 })
  return `prijs +${pct}% t.o.v. vorige factuur`
}

export function TerugkerendScreen({ pollMs = 1500 }: { pollMs?: number } = {}) {
  const { rol } = useAuth()
  const { administraties } = useAdministraties()
  const toast = useToastOptioneel()
  const [zoekParams, setZoekParams] = useSearchParams()
  // Deep-links: `administratie_id` (werkvoorraad-teller, facet voorgevuld) — `administratie` blijft als legacy werken.
  const administratieId = zoekParams.get('administratie_id') ?? zoekParams.get('administratie') ?? ''
  const statusParam = zoekParams.get('status')
  const status: KantoorStatusFacet = isStatusFacet(statusParam) ? statusParam : 'aandacht'
  const [zoek, setZoek] = useState('')
  const [pagina, setPagina] = useState(1)
  const [data, setData] = useState<KantoorLijstDto | null>(null)
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [actieFout, setActieFout] = useState<string | null>(null)
  const [versie, setVersie] = useState(0)
  const [run, setRun] = useState<HerberekenRunDto | null>(null)
  const [runStartBezig, setRunStartBezig] = useState(false)
  const [menuVoor, setMenuVoor] = useState<string | null>(null)
  const menuKnoppen = useRef<Record<string, HTMLButtonElement | null>>({})
  const [navraag, setNavraag] = useState<KantoorRijDto | null>(null)
  const [drempel, setDrempel] = useState('')
  const [drempelBezig, setDrempelBezig] = useState(false)

  const herlaad = useCallback(() => setVersie((v) => v + 1), [])

  useEffect(() => {
    let actueel = true
    setLaadFout(null)
    haalKantoorSignalen({ pagina, q: zoek, administratieId: administratieId || null, status })
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

  // Stand van de laatste kantoorbrede run bij binnenkomst (en een nog lopende run oppikken).
  useEffect(() => {
    let actueel = true
    haalLaatsteHerbereken()
      .then((r) => {
        if (actueel && r) setRun(r)
      })
      .catch(() => undefined)
    return () => {
      actueel = false
    }
  }, [])

  // Pollen tot klaar/fout; klaar = toast + lijst verversen, fout = zichtbaar (FoutMelding hieronder).
  useEffect(() => {
    if (!run || (run.status !== 'wachtend' && run.status !== 'bezig')) return
    let actueel = true
    const t = window.setTimeout(() => {
      haalHerberekenStatus(run.run_id)
        .then((r) => {
          if (!actueel) return
          setRun(r)
          if (r.status === 'klaar') {
            toast.meld(`Herberekend: ${r.aantal_verwerkt} administraties${r.aantal_fouten ? `, ${r.aantal_fouten} met een fout` : ''}.`)
            herlaad()
          }
        })
        .catch((err: unknown) => {
          if (actueel) setActieFout(err instanceof Error ? err.message : 'Status van de herberekening ophalen mislukt.')
        })
    }, pollMs)
    return () => {
      actueel = false
      window.clearTimeout(t)
    }
  }, [run, pollMs, herlaad, toast])

  const zetParam = (naam: string, waarde: string | null) => {
    const p = new URLSearchParams(zoekParams)
    if (waarde) p.set(naam, waarde)
    else p.delete(naam)
    p.delete('administratie') // legacy-param opruimen zodra er gekozen wordt
    setZoekParams(p, { replace: true })
    setPagina(1)
  }

  const herberekenAlles = async () => {
    setRunStartBezig(true)
    setActieFout(null)
    try {
      setRun(await startHerberekenAlles())
    } catch (err) {
      setActieFout(err instanceof ApiError ? err.message : 'Herberekening starten mislukt.')
    } finally {
      setRunStartBezig(false)
    }
  }

  const rijActie = async (werk: () => Promise<unknown>, tekst: string) => {
    setMenuVoor(null)
    setActieFout(null)
    try {
      await werk()
      toast.meld(tekst)
      herlaad()
    } catch (err) {
      setActieFout(err instanceof ApiError ? err.message : 'Actie mislukt.')
    }
  }

  const drempelOpslaan = async () => {
    const w = drempel.trim().replace(',', '.')
    const n = Number(w)
    if (w === '' || Number.isNaN(n) || n <= 0 || n > 1000) {
      setActieFout('Drempel moet een percentage boven 0 zijn.')
      return
    }
    setDrempelBezig(true)
    setActieFout(null)
    try {
      await zetTerugkerendDrempel(administratieId, w)
      toast.meld(`Drempel prijsstijging gezet op ${w}%.`)
      herlaad()
    } catch (err) {
      setActieFout(err instanceof ApiError ? err.message : 'Drempel opslaan mislukt.')
    } finally {
      setDrempelBezig(false)
    }
  }

  const comboboxOpties = useMemo(
    () => [{ id: ALLE, naam: 'Alle administraties' }, ...(administraties ?? [])],
    [administraties],
  )
  const rijen = data?.rijen ?? []
  const paginas = Math.max(1, Math.ceil((data?.totaal ?? 0) / (data?.per_pagina ?? 25)))
  const runLoopt = run !== null && (run.status === 'wachtend' || run.status === 'bezig')
  const sleutel = (r: KantoorRijDto) => `${r.administratie_id}:${r.vendor_id}:${r.soort}`
  const naam = (r: KantoorRijDto) => r.leverancier ?? 'onbekende leverancier'

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 style={{ margin: 0 }}>Inzicht › Terugkerende facturen</h1>
          <div className="hint" style={{ marginTop: 2 }}>
            Leveranciers met een regelmatig factuurritme (≥ 3 facturen, maand of kwartaal, ±35 %) over al je administraties. Signaal als
            de verwachte factuur uitblijft of de prijs stijgt — puur code, nooit een blokkade.
          </div>
        </div>
      </div>

      <div className="panel" data-testid="terugkerend-paneel" style={{ padding: 0, overflow: 'hidden' }}>
        <div className="p-kop" style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 18px', borderBottom: '1px solid var(--border)', flexWrap: 'wrap' }}>
          <h2 style={{ margin: 0, fontSize: 14.5 }}>Terugkerende facturen</h2>
          {data && (
            <>
              <Badge variant="warn" data-testid="chip-ontbrekend">{data.tellers.ontbrekend} ontbrekend</Badge>
              <Badge variant="stil" data-testid="chip-prijsstijging">{data.tellers.prijsstijging} prijsstijging</Badge>
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
            onChange={(e) => zetParam('status', e.target.value === 'aandacht' ? null : e.target.value)}
            style={{ width: 'auto' }}
          >
            {STATUS_FACETTEN.map((s) => (
              <option key={s} value={s}>
                Status: {KANTOOR_STATUS_LABEL[s]}
                {data ? ` (${data.facetten.status[s] ?? 0})` : ''}
              </option>
            ))}
          </select>
          <input
            type="search"
            aria-label="Zoek leverancier"
            placeholder="🔍 zoek leverancier…"
            value={zoek}
            onChange={(e) => {
              setZoek(e.target.value)
              setPagina(1)
            }}
            style={{ width: 200, maxWidth: '100%' }}
          />
          <Button variant="secundair" maat="klein" disabled={runStartBezig || runLoopt} onClick={() => void herberekenAlles()}>
            ⟳ Herbereken alles
          </Button>
        </div>

        {run && (
          <div className="hint" role="status" data-testid="herbereken-stand" style={{ margin: 0, padding: '8px 18px', borderBottom: '1px solid var(--border)' }}>
            {run.status === 'wachtend' && 'Herberekening staat klaar…'}
            {run.status === 'bezig' && `Herberekening bezig: ${run.aantal_verwerkt} van ${run.aantal_administraties} administraties…`}
            {run.status === 'klaar' &&
              `Stand van ${tijd(run.klaar_op ?? run.aangevraagd_op)} — ${run.aantal_verwerkt} administraties herberekend${run.aantal_fouten ? `, ${run.aantal_fouten} met een fout` : ''}.`}
            {run.status === 'fout' && `Laatste herberekening (${tijd(run.aangevraagd_op)}) mislukt.`}
          </div>
        )}
        {run?.status === 'fout' && (
          <div style={{ padding: '0 18px' }}>
            <FoutMelding melding="De kantoorbrede herberekening is mislukt." detail={run.foutreden} onOpnieuw={() => void herberekenAlles()} />
          </div>
        )}
        {actieFout && <div className="fout" style={{ margin: '10px 18px' }}>{actieFout}</div>}
        {laadFout && <FoutMelding melding="De signalen konden niet geladen worden." detail={laadFout} onOpnieuw={herlaad} />}
        {data === null && !laadFout && <SkeletonRegels />}
        {data !== null && rijen.length === 0 && (
          <p className="hint" style={{ padding: '14px 18px' }}>
            {status === 'aandacht'
              ? 'Geen signalen die aandacht nodig hebben — alle terugkerende leveranciers zijn op schema.'
              : `Geen signalen met status "${KANTOOR_STATUS_LABEL[status]}".`}
          </p>
        )}
        {rijen.length > 0 && (
          <div className="tabel-scroll">
            <table data-testid="terugkerend-tabel">
              <thead>
                <tr>
                  <th style={{ width: '30%' }}>Leverancier</th>
                  <th>Administratie</th>
                  <th>Signaal</th>
                  <th style={{ width: 250 }} />
                </tr>
              </thead>
              <tbody>
                {rijen.map((r) => {
                  const key = sleutel(r)
                  return (
                    <tr key={key} data-testid="terugkerend-rij">
                      <td>
                        <div style={{ fontWeight: 700 }}>{naam(r)}</div>
                        <div className="hint" style={{ margin: 0, fontSize: 11.5 }}>
                          {r.patroon === 'maand' ? 'maandelijks' : 'kwartaal'} · {r.soort === 'prijsstijging' ? 'geboekt' : 'laatst'} {ddmm(r.laatste_datum)}
                          {r.laatste_bedrag ? ` · ${formatBedrag(r.laatste_bedrag)}` : ''}
                        </div>
                      </td>
                      <td>
                        <Link to={`/?administratie=${r.administratie_id}`} className="text-primary no-underline hover:underline">
                          {r.administratie_naam}
                        </Link>
                      </td>
                      <td>
                        <Badge variant={r.status === 'aandacht' ? 'warn' : 'stil'} title={r.soort === 'prijsstijging' && r.vorige_bedrag ? `vorige factuur ${formatBedrag(r.vorige_bedrag)}${r.vorige_datum ? ` (${formatDatumKort(r.vorige_datum)})` : ''}` : undefined}>
                          {signaalTekst(r)}
                        </Badge>
                        {r.status === 'gesnoozed' && r.snooze_tot && <span className="hint" style={{ marginLeft: 6 }}>gesnoozed tot {ddmm(r.snooze_tot)}</span>}
                        {r.status === 'afgemeld' && <span className="hint" style={{ marginLeft: 6 }}>afgemeld</span>}
                      </td>
                      <td className="acties" style={{ whiteSpace: 'nowrap', textAlign: 'right' }}>
                        {r.soort === 'ontbreekt' ? (
                          <Button variant="secundair" maat="klein" onClick={() => setNavraag(r)} aria-label={`Navragen bij ${naam(r)}`}>
                            Navragen bij leverancier…
                          </Button>
                        ) : r.laatste_document_id ? (
                          <Link
                            to={`/?administratie=${r.administratie_id}&document=${r.laatste_document_id}`}
                            className="btn secondary"
                            aria-label={`Naar de boeking van ${naam(r)}`}
                          >
                            Naar de boeking →
                          </Link>
                        ) : (
                          <span className="hint">boeking niet in de app</span>
                        )}{' '}
                        <button
                          type="button"
                          className="linkbtn"
                          aria-label={`Meer acties ${naam(r)}`}
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
                          {r.status === 'gesnoozed' ? (
                            <button type="button" className="linkbtn" role="menuitem" onClick={() => void rijActie(() => snoozeTerugkerend(r.administratie_id, r.vendor_id, null), `Snooze voor ${naam(r)} opgeheven.`)}>
                              Snooze opheffen
                            </button>
                          ) : (
                            r.status !== 'afgemeld' && (
                              <button type="button" className="linkbtn" role="menuitem" onClick={() => void rijActie(() => snoozeTerugkerend(r.administratie_id, r.vendor_id, plusDagen(30)), `${naam(r)} 30 dagen gesnoozed.`)}>
                                Snooze 30 d
                              </button>
                            )
                          )}
                          {r.status === 'afgemeld' ? (
                            <button type="button" className="linkbtn" role="menuitem" onClick={() => void rijActie(() => zetTerugkerendAfgemeld(r.administratie_id, r.vendor_id, false), `${naam(r)} weer aangemeld.`)}>
                              Heractiveren
                            </button>
                          ) : (
                            <button type="button" className="linkbtn" role="menuitem" onClick={() => void rijActie(() => zetTerugkerendAfgemeld(r.administratie_id, r.vendor_id, true), `${naam(r)} afgemeld — geen signaal meer voor deze leverancier.`)}>
                              Afmelden per leverancier
                            </button>
                          )}
                        </AnkerPopup>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        {data && (
          <div className="voet hint" data-testid="terugkerend-voet" style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 8, padding: '10px 18px', borderTop: '1px solid var(--border)', flexWrap: 'wrap' }}>
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
            <span>· ⋯-menu: snooze 30 d · afmelden per leverancier (audit)</span>
            {rol === 'beheerder' && administratieId && (
              <label style={{ marginLeft: 'auto', display: 'flex', gap: 6, alignItems: 'center', margin: 0 }}>
                Drempel prijsstijging (%)
                <input
                  aria-label="Drempel prijsstijging"
                  inputMode="decimal"
                  value={drempel}
                  onChange={(e) => setDrempel(e.target.value)}
                  placeholder="10"
                  style={{ width: 64 }}
                />
                <Button variant="secundair" maat="klein" disabled={drempelBezig || drempel.trim() === ''} onClick={() => void drempelOpslaan()}>
                  Opslaan
                </Button>
              </label>
            )}
          </div>
        )}
      </div>

      {navraag && (
        <ConceptMailDialoog
          rij={navraag}
          onSluiten={() => setNavraag(null)}
          onVerzonden={(aan) => {
            toast.meld(`Navraag verstuurd aan ${aan}.`)
          }}
        />
      )}
    </div>
  )
}

/** "Navragen bij leverancier…" (②): deterministisch concept van de server, de MENS bewerkt ontvanger/
 * onderwerp/tekst en verstuurt expliciet — nooit automatisch; uitkomst blijft zichtbaar in de dialoog. */
function ConceptMailDialoog({
  rij,
  onSluiten,
  onVerzonden,
}: {
  rij: KantoorRijDto
  onSluiten: () => void
  onVerzonden: (aan: string) => void
}) {
  const [concept, setConcept] = useState<ConceptMailDto | null>(null)
  const [naar, setNaar] = useState('')
  const [onderwerp, setOnderwerp] = useState('')
  const [tekst, setTekst] = useState('')
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const [verzondenAan, setVerzondenAan] = useState<string | null>(null)

  useEffect(() => {
    let actueel = true
    haalConceptMail(rij.administratie_id, rij.vendor_id)
      .then((c) => {
        if (!actueel) return
        setConcept(c)
        setNaar(c.ontvanger_e_mail ?? '')
        setOnderwerp(c.onderwerp)
        setTekst(c.tekst)
      })
      .catch((err: unknown) => {
        if (actueel) setFout(err instanceof Error ? err.message : 'Concept ophalen mislukt.')
      })
    return () => {
      actueel = false
    }
  }, [rij.administratie_id, rij.vendor_id])

  const verstuur = async () => {
    setBezig(true)
    setFout(null)
    try {
      const r = await verstuurConceptMail(rij.administratie_id, rij.vendor_id, { naar, onderwerp, tekst })
      setVerzondenAan(r.verzonden_aan)
      onVerzonden(r.verzonden_aan)
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Versturen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onSluiten()}>
      <DialogContent breed aria-describedby={undefined} data-testid="conceptmail-dialoog">
        <DialogTitle>Navragen bij {rij.leverancier ?? 'leverancier'}</DialogTitle>
        <DialogDescription>
          Concept op basis van het factuurritme voor {rij.administratie_naam}. Lees, pas aan en verstuur — er gaat niets automatisch weg.
          {concept && !concept.ontvanger_e_mail && ' De crediteur in Reeleezee heeft geen e-mailadres; vul het zelf in.'}
        </DialogDescription>
        {concept === null && !fout && <SkeletonRegels />}
        {concept !== null && (
          <form
            onSubmit={(e) => {
              e.preventDefault()
              void verstuur()
            }}
          >
            <FormField label="Aan" htmlFor="navraag-naar">
              <input id="navraag-naar" type="email" required value={naar} onChange={(e) => setNaar(e.target.value)} placeholder="facturatie@leverancier.nl" disabled={verzondenAan !== null} />
            </FormField>
            <FormField label="Onderwerp" htmlFor="navraag-onderwerp">
              <input id="navraag-onderwerp" required value={onderwerp} onChange={(e) => setOnderwerp(e.target.value)} disabled={verzondenAan !== null} />
            </FormField>
            <FormField label="Tekst" htmlFor="navraag-tekst">
              <textarea id="navraag-tekst" required rows={12} value={tekst} onChange={(e) => setTekst(e.target.value)} disabled={verzondenAan !== null} style={{ width: '100%', fontFamily: 'inherit', fontSize: 12.5 }} />
            </FormField>
            {fout && <div className="fout">{fout}</div>}
            {verzondenAan && (
              <div role="status" className="hint" data-testid="navraag-verzonden" style={{ color: 'var(--ok)' }}>
                ✓ Verstuurd aan {verzondenAan} — vastgelegd in het audit log.
              </div>
            )}
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={onSluiten} disabled={bezig}>
                {verzondenAan ? 'Sluiten' : 'Annuleren'}
              </Button>
              {!verzondenAan && (
                <Button type="submit" disabled={bezig || naar.trim() === '' || onderwerp.trim() === '' || tekst.trim() === ''}>
                  {bezig ? 'Bezig…' : 'Versturen'}
                </Button>
              )}
            </DialogFooter>
          </form>
        )}
        {concept === null && fout && (
          <>
            <div className="fout">{fout}</div>
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={onSluiten}>
                Sluiten
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
