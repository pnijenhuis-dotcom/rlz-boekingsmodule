// Instellingen › Autoboeken — kandidaten & actief (mockup autoboek-kandidaten.html = bouwnorm, besluit
// Peter 01-09, ontwerpnotities ①–⑧). De motor (backend, dagelijks in sync-alles) nomineert
// deterministisch per (administratie, leverancier); AANZETTEN blijft een menselijk besluit — hier, in
// bulk, mét LIVE hertoets per rij (niet meer kwalificerend = overgeslagen mét reden, uitkomst-patroon
// bulk-accordering). Aanzetten/uitzetten lopen via de bestaande per-leverancier-opt-in (geen tweede
// schrijver); de per-leverancier-switch op de detailpagina (tab Boeken & AI) blijft bestaan — dit is
// de vind- en bulklaag erboven. "Kandidaat verbergen" = snooze mét verplichte reden, terugvindbaar
// onder het filter "verborgen". Heroverwegen = advies-only. Beheerder-only.
// Restpunten design-ronde 03-09 (mockup inzicht-kantoorbreed.html ⑧): bulk-verbergen is ÉÉN server-call mét
// uitkomst per rij (zelfde lijst als bij aanzetten), en "Selecteer alle N resultaten" naast de pagina-selectie
// stuurt een server-side selectie ({alle, tab, q, verborgen}) mee i.p.v. duizenden id's — de bevestigknop
// benoemt altijd het aantal.
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError } from '../api/client'
import type { AutoboekAanzetUitkomstDto, AutoboekKandidaatRijDto, AutoboekTellersDto } from '../api/types'
import { Badge, Button, Checkbox, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle, FormField, Paginering, SkeletonRegels } from '../ui/basis'
import { FoutMelding } from '../ui/FoutMelding'
import { BevestigDialog } from './BevestigDialog'
import {
  type AutoboekBulkSelectie,
  type AutoboekTab,
  haalAutoboekKandidatenOp,
  herberekenAutoboekKandidaten,
  toonAutoboekKandidaatWeer,
  verbergAutoboekKandidaten,
  zetAutoboekDrempel,
  zetAutoboekKandidaatUit,
  zetAutoboekKandidatenAan,
} from './instellingenApi'
import { detailPad } from './instellingenRegistry'

const PER_PAGINA = 25

function datumKort(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('nl-NL', { day: 'numeric', month: 'short', year: 'numeric' })
}

function tijd(iso: string | null): string {
  if (!iso) return 'nog niet gedraaid'
  return new Date(iso).toLocaleString('nl-NL', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function bedrag(waarde: string | null): string {
  if (waarde === null) return ''
  const n = Number(waarde)
  return Number.isFinite(n) ? `€ ${n.toLocaleString('nl-NL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : waarde
}

function sleutel(r: { administratie_id: string; vendor_id: string }): string {
  return `${r.administratie_id}:${r.vendor_id}`
}

function chipVariant(chip: string): 'ok' | 'info' | 'warn' {
  if (chip.startsWith('geheugen nog') || chip === 'buitenland-tarief') return 'warn'
  if (chip === 'vast maandbedrag' || chip === 'bedrag wisselt') return 'info'
  return 'ok'
}

export function AutoboekKandidaten({ onStand }: { onStand?: (t: AutoboekTellersDto) => void }) {
  const [tab, setTab] = useState<AutoboekTab>('kandidaten')
  const [verborgen, setVerborgen] = useState(false)
  const [zoek, setZoek] = useState('')
  const [pagina, setPagina] = useState(1)
  const [rijen, setRijen] = useState<AutoboekKandidaatRijDto[] | null>(null)
  const [totaal, setTotaal] = useState(0)
  const [tellers, setTellers] = useState<AutoboekTellersDto | null>(null)
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [versie, setVersie] = useState(0)
  const [selectie, setSelectie] = useState<string[]>([])
  // "Selecteer alle N resultaten": server-side selectie binnen het actieve filter (tab/q/verborgen), over álle pagina's.
  const [alleGeselecteerd, setAlleGeselecteerd] = useState(false)
  const [bezig, setBezig] = useState(false)
  const [actieFout, setActieFout] = useState<string | null>(null)
  const [bevestigAanzetten, setBevestigAanzetten] = useState(false)
  const [uitkomsten, setUitkomsten] = useState<{ soort: 'aanzetten' | 'verbergen'; lijst: AutoboekAanzetUitkomstDto[] } | null>(null)
  const [verbergVoor, setVerbergVoor] = useState<{ rijen: AutoboekKandidaatRijDto[]; aantal: number } | null>(null)
  const [verbergReden, setVerbergReden] = useState('')
  const [uitzetVoor, setUitzetVoor] = useState<AutoboekKandidaatRijDto | null>(null)
  const [drempelInvoer, setDrempelInvoer] = useState('')
  const [drempelBezig, setDrempelBezig] = useState(false)

  const herlaad = useCallback(() => setVersie((v) => v + 1), [])

  useEffect(() => {
    let actueel = true
    setLaadFout(null)
    haalAutoboekKandidatenOp({ tab, q: zoek, pagina, verborgen: tab === 'kandidaten' && verborgen })
      .then((dto) => {
        if (!actueel) return
        setRijen(dto.rijen)
        setTotaal(dto.totaal)
        setTellers(dto.tellers)
        setDrempelInvoer((huidig) => huidig || String(dto.tellers.drempel))
        onStand?.(dto.tellers)
      })
      .catch((err: unknown) => {
        if (actueel) setLaadFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
    return () => {
      actueel = false
    }
    // onStand bewust niet in de deps: een inline callback zou elke render een refetch geven.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, zoek, pagina, verborgen, versie])

  const wisSelectie = () => {
    setSelectie([])
    setAlleGeselecteerd(false)
  }

  const kiesTab = (t: AutoboekTab) => {
    setTab(t)
    setPagina(1)
    wisSelectie()
    setUitkomsten(null)
    setActieFout(null)
  }

  const geselecteerdeRijen = (rijen ?? []).filter((r) => selectie.includes(sleutel(r)))
  const paginaVolledig = rijen !== null && rijen.length > 0 && selectie.length === rijen.length
  const aantalGeselecteerd = alleGeselecteerd ? totaal : selectie.length
  const heeftSelectie = alleGeselecteerd || selectie.length > 0

  /** Wat naar de bulk-endpoints gaat: de aangevinkte rijen, óf de server-side filterset ("alle N"). */
  const bulkSelectie = (): AutoboekBulkSelectie =>
    alleGeselecteerd
      ? { alle: true, tab, q: zoek, verborgen: tab === 'kandidaten' && verborgen }
      : { items: geselecteerdeRijen.map((x) => ({ administratie_id: x.administratie_id, vendor_id: x.vendor_id })) }

  const aanzetten = async () => {
    setBezig(true)
    setActieFout(null)
    try {
      const r = await zetAutoboekKandidatenAan(bulkSelectie())
      setUitkomsten({ soort: 'aanzetten', lijst: r.uitkomsten })
      setBevestigAanzetten(false)
      wisSelectie()
      herlaad()
    } catch (err) {
      setActieFout(err instanceof ApiError ? err.message : 'Aanzetten mislukt.')
    } finally {
      setBezig(false)
    }
  }

  const verberg = async () => {
    if (!verbergVoor) return
    setBezig(true)
    setActieFout(null)
    try {
      // Eén request voor de hele selectie (B5.1): de server verbergt per rij in een eigen transactie en
      // meldt per rij verborgen | overgeslagen mét reden | fout — één fout stopt de rest niet.
      const r = await verbergAutoboekKandidaten(bulkSelectie(), verbergReden)
      setUitkomsten({ soort: 'verbergen', lijst: r.uitkomsten })
      setVerbergVoor(null)
      setVerbergReden('')
      wisSelectie()
      herlaad()
    } catch (err) {
      setActieFout(err instanceof ApiError ? err.message : 'Verbergen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  const uitzet = async () => {
    if (!uitzetVoor) return
    setBezig(true)
    setActieFout(null)
    try {
      await zetAutoboekKandidaatUit(uitzetVoor.administratie_id, uitzetVoor.vendor_id)
      setUitzetVoor(null)
      herlaad()
    } catch (err) {
      setActieFout(err instanceof ApiError ? err.message : 'Uitzetten mislukt.')
    } finally {
      setBezig(false)
    }
  }

  const weerTonen = async (r: AutoboekKandidaatRijDto) => {
    setActieFout(null)
    try {
      await toonAutoboekKandidaatWeer(r.administratie_id, r.vendor_id)
      herlaad()
    } catch (err) {
      setActieFout(err instanceof ApiError ? err.message : 'Weer tonen mislukt.')
    }
  }

  const herbereken = async () => {
    setBezig(true)
    setActieFout(null)
    try {
      await herberekenAutoboekKandidaten()
      herlaad()
    } catch (err) {
      setActieFout(err instanceof ApiError ? err.message : 'Herberekenen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  const drempelOpslaan = async () => {
    const n = Number(drempelInvoer)
    if (!Number.isInteger(n) || n < 1 || n > 50) {
      setActieFout('De drempel is een geheel getal tussen 1 en 50.')
      return
    }
    setDrempelBezig(true)
    setActieFout(null)
    try {
      await zetAutoboekDrempel(n)
      herlaad()
    } catch (err) {
      setActieFout(err instanceof ApiError ? err.message : 'Drempel opslaan mislukt.')
    } finally {
      setDrempelBezig(false)
    }
  }

  const drempel = tellers?.drempel ?? 5
  const naamVan = (r: AutoboekKandidaatRijDto) => r.leverancier_naam ?? r.vendor_id
  const uitkomstNaam = (u: AutoboekAanzetUitkomstDto) => {
    if (u.leverancier_naam || u.administratie_naam) return `${u.leverancier_naam ?? u.vendor_id} · ${u.administratie_naam ?? ''}`.trim()
    const rij = (rijen ?? []).find((r) => r.administratie_id === u.administratie_id && r.vendor_id === u.vendor_id)
    return rij ? `${naamVan(rij)} · ${rij.administratie_naam}` : u.vendor_id
  }
  const uitkomstTekst = (u: AutoboekAanzetUitkomstDto) =>
    u.status === 'aangezet' ? 'autoboeken aan' : u.status === 'verborgen' ? 'verborgen' : `${u.status} — ${u.reden ?? ''}`

  return (
    <div className="panel inst-paneel" data-testid="autoboek-kandidaten">
      <div className="p-kop" style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '14px 18px', borderBottom: '1px solid var(--border)', flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0, fontSize: 14.5 }}>Autoboeken</h2>
        <span className="hint" style={{ margin: 0, flex: '1 1 320px' }}>
          criteria: ≥ {drempel} boekingen op rij waarbij het voorstel ongewijzigd is geboekt · volledig app-bevestigd geheugen · geen open vraag,
          correctie of duplicaatsignaal. Stand van {tijd(tellers?.laatste_run_op ?? null)}.
        </span>
        <Button variant="secundair" maat="klein" onClick={() => void herbereken()} disabled={bezig}>
          Herbereken
        </Button>
      </div>

      <div className="segment inst-tabs" role="tablist" aria-label="Autoboeken" style={{ margin: '10px 18px 0' }}>
        {(['kandidaten', 'actief', 'heroverwegen'] as AutoboekTab[]).map((t) => (
          <button key={t} type="button" role="tab" aria-selected={tab === t} className={tab === t ? 'actief' : undefined} onClick={() => kiesTab(t)}>
            {t === 'kandidaten' ? 'Kandidaten' : t === 'actief' ? 'Actief' : 'Heroverwegen'}
            {tellers ? ` (${t === 'kandidaten' ? tellers.kandidaten : t === 'actief' ? tellers.actief : tellers.heroverwegen})` : ''}
          </button>
        ))}
      </div>

      <div className="filterrij" style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 18px', borderBottom: '1px solid var(--border)', flexWrap: 'wrap' }}>
        <input
          type="search"
          aria-label="Zoek leverancier of administratie"
          placeholder="Zoek leverancier of administratie…"
          value={zoek}
          onChange={(e) => {
            setZoek(e.target.value)
            setPagina(1)
            setAlleGeselecteerd(false)
          }}
          style={{ width: 280, maxWidth: '100%' }}
        />
        {tellers && tab === 'kandidaten' && !verborgen && (
          <span className="hint" style={{ margin: 0 }}>
            {tellers.kandidaten} kandidaten over {tellers.administraties_met_kandidaten} administraties
          </span>
        )}
        {tab === 'kandidaten' && (
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0, fontSize: 12 }}>
            <Checkbox
              aria-label="Verborgen kandidaten tonen"
              checked={verborgen}
              onChange={(e) => {
                setVerborgen(e.target.checked)
                setPagina(1)
                wisSelectie()
              }}
            />
            verborgen{tellers ? ` (${tellers.verborgen})` : ''}
          </label>
        )}
        {tab === 'kandidaten' && !verborgen && rijen && rijen.length > 0 && (
          <label style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, margin: 0 }}>
            Selecteer alles
            <Checkbox
              aria-label="Alle kandidaten op deze pagina selecteren"
              checked={alleGeselecteerd || selectie.length === rijen.length}
              indeterminate={!alleGeselecteerd && selectie.length > 0 && selectie.length < rijen.length}
              onChange={(e) => {
                setAlleGeselecteerd(false)
                setSelectie(e.target.checked ? rijen.map(sleutel) : [])
              }}
            />
          </label>
        )}
      </div>

      {tab === 'heroverwegen' && (
        <div className="waarschuwing" style={{ margin: '12px 18px', padding: '11px 13px', borderRadius: 10, background: 'var(--warn-bg)', color: 'var(--warn)', fontSize: 12.5 }}>
          ⚠ Heroverwegen zet níéts automatisch uit — het is een advies mét onderbouwing. Uitzetten is één klik, geaudit; de leverancier
          verschijnt pas weer als kandidaat zodra hij opnieuw aan de criteria voldoet (teller start opnieuw ná de laatste correctie).
        </div>
      )}

      {actieFout && <div className="fout" style={{ margin: '10px 18px' }}>{actieFout}</div>}
      {uitkomsten && (
        <div className="hint" role="status" style={{ margin: '10px 18px' }} data-testid="aanzet-uitkomsten">
          <b>
            {uitkomsten.soort === 'aanzetten'
              ? `${uitkomsten.lijst.filter((u) => u.status === 'aangezet').length} aangezet`
              : `${uitkomsten.lijst.filter((u) => u.status === 'verborgen').length} verborgen`}
            {uitkomsten.lijst.some((u) => u.status === 'overgeslagen') ? ` · ${uitkomsten.lijst.filter((u) => u.status === 'overgeslagen').length} overgeslagen` : ''}
            {uitkomsten.lijst.some((u) => u.status === 'fout') ? ` · ${uitkomsten.lijst.filter((u) => u.status === 'fout').length} mislukt` : ''}
          </b>
          <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
            {uitkomsten.lijst.map((u) => (
              <li key={sleutel(u)}>
                {uitkomstNaam(u)}: {uitkomstTekst(u)}
              </li>
            ))}
          </ul>
        </div>
      )}

      {laadFout && <FoutMelding melding="De kandidaten konden niet geladen worden." detail={laadFout} onOpnieuw={herlaad} />}
      {rijen === null && !laadFout && <SkeletonRegels />}
      {rijen !== null && rijen.length === 0 && (
        <p className="hint" style={{ padding: '14px 18px' }}>
          {tab === 'kandidaten'
            ? verborgen
              ? 'Geen verborgen kandidaten.'
              : `Geen kandidaten — geen leverancier voldoet nu aan ≥ ${drempel} ongewijzigde boekingen op rij mét bevestigd geheugen.`
            : tab === 'actief'
              ? 'Nog geen leveranciers met autoboeken aan.'
              : 'Geen signalen ná activatie — niets te heroverwegen.'}
        </p>
      )}
      {rijen !== null && rijen.length > 0 && (
        <div className="tabel-scroll">
          <table>
            <thead>
              <tr>
                {tab === 'kandidaten' && !verborgen && <th style={{ width: 36 }} />}
                <th>Leverancier · administratie</th>
                <th>{tab === 'heroverwegen' ? 'Signaal' : verborgen ? 'Verborgen (reden)' : 'Onderbouwing (live getoetst)'}</th>
                <th style={{ width: 130 }}>Laatste factuur</th>
                {(tab === 'heroverwegen' || tab === 'actief' || verborgen) && <th style={{ width: 130 }} />}
              </tr>
            </thead>
            <tbody>
              {rijen.map((r) => {
                const key = sleutel(r)
                return (
                  <tr key={key} className={alleGeselecteerd || selectie.includes(key) ? 'geselecteerd' : undefined}>
                    {tab === 'kandidaten' && !verborgen && (
                      <td>
                        <Checkbox
                          aria-label={`Selecteer ${naamVan(r)} (${r.administratie_naam})`}
                          checked={alleGeselecteerd || selectie.includes(key)}
                          onChange={(e) => {
                            // Eén rij uitvinken ná "alle N" = terug naar een pagina-selectie zonder die rij.
                            const basis = alleGeselecteerd ? rijen.map(sleutel) : selectie
                            setAlleGeselecteerd(false)
                            setSelectie(e.target.checked ? [...basis, key] : basis.filter((k) => k !== key))
                          }}
                        />
                      </td>
                    )}
                    <td>
                      <div style={{ fontWeight: 700 }}>{naamVan(r)}</div>
                      <div className="hint" style={{ margin: 0, fontSize: 11.5 }}>
                        <Link to={detailPad(r.administratie_id, 'boeken-ai')} className="text-primary no-underline hover:underline">
                          {r.administratie_naam}
                        </Link>
                        {r.actief && r.actief_sinds ? ` · actief sinds ${datumKort(r.actief_sinds)}` : ''}
                      </div>
                    </td>
                    <td>
                      <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                        {tab === 'heroverwegen'
                          ? r.heroverweeg_signalen.map((s) => (
                              <Badge key={s} variant="warn">
                                {s}
                              </Badge>
                            ))
                          : verborgen
                            ? <span className="hint" style={{ margin: 0 }}>{r.snooze_reden} · {datumKort(r.snooze_op)}</span>
                            : r.chips.map((c) => (
                                <Badge key={c} variant={chipVariant(c)}>
                                  {c}
                                </Badge>
                              ))}
                        {tab === 'actief' && r.heroverweeg_signalen.length > 0 && <Badge variant="warn">{r.heroverweeg_signalen.length} signaal · zie Heroverwegen</Badge>}
                      </div>
                    </td>
                    <td className="hint" style={{ fontSize: 11.5 }}>
                      {r.laatste_document_id ? (
                        <Link to={`/documenten/${r.administratie_id}/${r.laatste_document_id}`} className="text-primary no-underline hover:underline">
                          {datumKort(r.laatste_factuur_datum)}
                        </Link>
                      ) : (
                        datumKort(r.laatste_factuur_datum)
                      )}
                      <br />
                      {bedrag(r.laatste_factuur_bedrag)}
                    </td>
                    {(tab === 'heroverwegen' || tab === 'actief') && (
                      <td style={{ textAlign: 'right' }}>
                        <Button variant="secundair" maat="klein" aria-label={`Autoboeken uitzetten voor ${naamVan(r)}`} onClick={() => setUitzetVoor(r)}>
                          Uitzetten
                        </Button>
                      </td>
                    )}
                    {verborgen && (
                      <td style={{ textAlign: 'right' }}>
                        <Button variant="secundair" maat="klein" aria-label={`Weer tonen ${naamVan(r)}`} onClick={() => void weerTonen(r)}>
                          Weer tonen
                        </Button>
                      </td>
                    )}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      {totaal > PER_PAGINA && (
        <div style={{ padding: '8px 18px' }}>
          <Paginering pagina={pagina} totaal={totaal} grootte={PER_PAGINA} onPagina={setPagina} label="leveranciers" />
        </div>
      )}

      {tab === 'kandidaten' && !verborgen && heeftSelectie && (
        <div className="bulkvoet" role="toolbar" aria-label="Bulk-bediening kandidaten" style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 18px', borderTop: '1px solid var(--border)', background: 'var(--panel-2)', flexWrap: 'wrap' }}>
          <b style={{ fontSize: 12.5 }}>
            {alleGeselecteerd ? `Alle ${totaal} resultaten geselecteerd` : paginaVolledig && totaal > selectie.length ? `Pagina geselecteerd (${selectie.length})` : `${selectie.length} geselecteerd`}
          </b>
          {!alleGeselecteerd && paginaVolledig && totaal > selectie.length && (
            <button type="button" className="linkbtn" style={{ fontSize: 12.5 }} onClick={() => setAlleGeselecteerd(true)}>
              Selecteer alle {totaal} resultaten
            </button>
          )}
          {alleGeselecteerd && (
            <button type="button" className="linkbtn" style={{ fontSize: 12.5 }} onClick={() => setAlleGeselecteerd(false)}>
              Alleen deze pagina
            </button>
          )}
          <span style={{ marginLeft: 'auto' }} />
          <Button variant="secundair" maat="klein" onClick={() => { setVerbergReden(''); setVerbergVoor({ rijen: geselecteerdeRijen, aantal: aantalGeselecteerd }) }}>
            Kandidaat verbergen…
          </Button>
          <Button maat="klein" onClick={() => setBevestigAanzetten(true)}>
            Autoboeken aanzetten ({aantalGeselecteerd})
          </Button>
        </div>
      )}

      <div id="drempel" style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '12px 18px', borderTop: '1px solid var(--border)', flexWrap: 'wrap' }}>
        <span className="hint" style={{ margin: 0, flex: '1 1 320px' }}>
          Drempel &ldquo;N op rij ongewijzigd&rdquo; (Beheerder-instelling, default 5): geldt bij de volgende herberekening én bij elke live hertoets.
        </span>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0, whiteSpace: 'nowrap' }}>
          N =
          <input type="number" aria-label="Drempel op rij ongewijzigd" min={1} max={50} step={1} style={{ width: 70 }} value={drempelInvoer} onChange={(e) => setDrempelInvoer(e.target.value)} />
          <Button variant="secundair" maat="klein" disabled={drempelBezig || !drempelInvoer || Number(drempelInvoer) === drempel} onClick={() => void drempelOpslaan()}>
            Drempel opslaan
          </Button>
        </label>
      </div>

      {bevestigAanzetten && (
        <BevestigDialog
          titel={`Autoboeken aanzetten voor ${aantalGeselecteerd} leverancier${aantalGeselecteerd === 1 ? '' : 's'}?`}
          bericht={
            (alleGeselecteerd ? `Dit betreft álle ${totaal} resultaten binnen het huidige filter, ook buiten deze pagina. ` : '') +
            `Elke rij wordt op dít moment opnieuw getoetst; een leverancier die intussen niet meer kwalificeert wordt overgeslagen mét reden. ` +
            `Facturen van aangezette leveranciers boeken daarna automatisch zodra álle harde checks groen zijn en het voorstel volledig uit bevestigd ` +
            `boekingsgeheugen komt (volumerem, accorderingspoort en duplicaat-/vraagpoorten blijven onverkort). Elke boeking krijgt de chip "automatisch" en staat in het audit log.`
          }
          bezig={bezig}
          fout={actieFout}
          onBevestigen={() => void aanzetten()}
          onAnnuleren={() => setBevestigAanzetten(false)}
        />
      )}

      {uitzetVoor && (
        <BevestigDialog
          titel={`Autoboeken uitzetten voor ${naamVan(uitzetVoor)}?`}
          bericht={`Facturen van ${naamVan(uitzetVoor)} (${uitzetVoor.administratie_naam}) wachten weer op de boek-klik van een medewerker. De leverancier verschijnt pas opnieuw als kandidaat zodra de teller weer aan de drempel komt.`}
          bezig={bezig}
          fout={actieFout}
          onBevestigen={() => void uitzet()}
          onAnnuleren={() => setUitzetVoor(null)}
        />
      )}

      <Dialog open={verbergVoor !== null} onOpenChange={(open) => !open && !bezig && setVerbergVoor(null)}>
        <DialogContent aria-describedby={undefined} data-testid="verberg-dialoog">
          <DialogTitle>Kandidaat verbergen</DialogTitle>
          <DialogDescription>
            {verbergVoor?.aantal === 1 && verbergVoor.rijen[0] ? naamVan(verbergVoor.rijen[0]) : `${verbergVoor?.aantal ?? 0} kandidaten`} verdwijnt uit de kandidatenlijst tot je
            &ldquo;Weer tonen&rdquo; kiest onder het filter &ldquo;verborgen&rdquo;. Een reden is verplicht en wordt geauditeerd — niets verdwijnt stil.
            {alleGeselecteerd ? ' Dit betreft álle resultaten binnen het huidige filter, ook buiten deze pagina.' : ''}
          </DialogDescription>
          <form
            onSubmit={(e) => {
              e.preventDefault()
              void verberg()
            }}
          >
            <FormField label="Reden" htmlFor="verberg-reden">
              <input id="verberg-reden" autoFocus value={verbergReden} onChange={(e) => setVerbergReden(e.target.value)} placeholder='bv. "wil ik handmatig houden"' />
            </FormField>
            {actieFout && <div className="fout">{actieFout}</div>}
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setVerbergVoor(null)} disabled={bezig}>
                Annuleren
              </Button>
              <Button type="submit" disabled={bezig || verbergReden.trim() === ''}>
                {bezig ? 'Bezig…' : `Verbergen (${verbergVoor?.aantal ?? 0})`}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
