// Materiaalcatalogus › tab "Mini-voorraad" (opdracht Peter 06-09; mockup mini-voorraad.html blok 2 +
// ontwerpnotities ①–⑧ = norm). Speciale producten die bij het BOEKEN van een inkoopfactuur automatisch
// uit de regels ontstaan (omschrijving = letterlijk de factuurtekst = sleutel, ⑦). Volle schermbreedte,
// geen halve panelen, knoppen nooit gestapeld (UI-les 05-09): kolommen Product · Stand · acties.
// ⑧ MENS-MANIPULATIE ONMOGELIJK: er is geen corrigeer-/samenvoeg-knop en geen invoer van standen —
// de enige handelingen zijn "Naam bevestigen" (weergavenaam, nooit een aantal), "Voorraadlog ▸"
// (append-only uitklap), en achter het ⋯-menu "Beschadiging melden…" (gebeurtenis mét verplicht
// project) en — Beheerder — "Archiveren…" (nooit verwijderen). Teal = actie, groen = status, oranje
// chip = "nieuw — controleer naam" (signaal mét actie, ④). Server-side paginering 25.
import { Fragment, useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/client'
import { useAuthOptioneel } from '../auth/AuthContext'
import { AnkerPopup, Badge, Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle, FormField, SkeletonRegels, useToastOptioneel } from '../ui/basis'
import { BeschadigingDialog } from './BeschadigingDialog'
import {
  aantalTekst,
  archiveerProduct,
  bevestigNaam,
  dearchiveerProduct,
  haalProducten,
  PER_PAGINA,
  productNaam,
  type MiniProductDto,
  type ProductFilter,
  type ProductLijstDto,
} from './miniVoorraadApi'
import { VoorraadLog } from './VoorraadLog'

export const MINI_VOORRAAD_UIT_TEKST = 'Mini-voorraad staat uit voor deze administratie — een Beheerder zet de opt-in aan op de administratie-detailpagina (Instellingen › Administraties).'
export const MINI_VOORRAAD_LEEG_TEKST = 'Nog geen speciale producten. Producten verschijnen hier automatisch bij het boeken van een inkoopfactuur van deze administratie — dienst- en transportregels tellen niet mee.'

/** Minimale lengte van een archiveer-reden — spiegelt de server (≥ 5). */
const REDEN_MINIMUM = 5
const NAAM_MAX = 200

const FILTERS: { waarde: ProductFilter; label: string }[] = [
  { waarde: 'alle', label: 'alle' },
  { waarde: 'nieuw', label: 'nieuw — controleer' },
  { waarde: 'gearchiveerd', label: 'gearchiveerd' },
]

export function MiniVoorraadTab({ administratieId }: { administratieId: string }) {
  const auth = useAuthOptioneel()
  const isBeheerder = auth?.rol === 'beheerder'
  const toast = useToastOptioneel()
  const [filter, setFilter] = useState<ProductFilter>('alle')
  const [zoek, setZoek] = useState('')
  const [pagina, setPagina] = useState(1)
  const [data, setData] = useState<ProductLijstDto | null>(null)
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [uit, setUit] = useState(false)
  const [versie, setVersie] = useState(0)
  const [openLogs, setOpenLogs] = useState<Set<string>>(new Set())
  const [menuVoor, setMenuVoor] = useState<string | null>(null)
  const menuKnoppen = useRef(new Map<string, HTMLButtonElement>())
  const [naamVoor, setNaamVoor] = useState<MiniProductDto | null>(null)
  const [archiveerVoor, setArchiveerVoor] = useState<MiniProductDto | null>(null)
  const [beschadigingVoor, setBeschadigingVoor] = useState<MiniProductDto | null>(null)
  const [actieFout, setActieFout] = useState<string | null>(null)

  const herlaad = useCallback(() => setVersie((v) => v + 1), [])

  useEffect(() => {
    if (!administratieId) return
    let actueel = true
    setLaadFout(null)
    haalProducten(administratieId, { pagina, q: zoek, filter })
      .then((d) => {
        if (!actueel) return
        setData(d)
        setUit(!d.ingeschakeld)
      })
      .catch((err: unknown) => {
        if (!actueel) return
        if (err instanceof ApiError && err.status === 409) {
          setUit(true)
          setData(null)
          return
        }
        setLaadFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
    return () => {
      actueel = false
    }
  }, [administratieId, pagina, zoek, filter, versie])

  const toggleLog = (id: string) =>
    setOpenLogs((huidig) => {
      const volgende = new Set(huidig)
      if (volgende.has(id)) volgende.delete(id)
      else volgende.add(id)
      return volgende
    })

  const dearchiveer = async (p: MiniProductDto) => {
    setActieFout(null)
    try {
      await dearchiveerProduct(administratieId, p.id)
      toast.meld(`${productNaam(p)} staat weer actief in de mini-voorraad.`)
      herlaad()
    } catch (err) {
      setActieFout(err instanceof ApiError ? err.message : 'Dearchiveren mislukt.')
    }
  }

  const rijen = data?.items ?? []
  const paginas = Math.max(1, Math.ceil((data?.totaal ?? 0) / (data?.per_pagina ?? PER_PAGINA)))

  if (uit) {
    return (
      <p className="hint" data-testid="mini-voorraad-uit">
        {MINI_VOORRAAD_UIT_TEKST}
      </p>
    )
  }

  return (
    <div data-testid="mini-voorraad-tab">
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', margin: '10px 0 8px' }}>
        <h3 style={{ margin: 0, fontSize: 14 }}>Mini-voorraad — speciale producten</h3>
        {data && data.nieuw_controleren > 0 && (
          <button type="button" className="linkbtn" style={{ padding: 0 }} onClick={() => { setFilter('nieuw'); setPagina(1) }} aria-label={`${data.nieuw_controleren} nieuw — controleer naam`}>
            <Badge variant="warn" data-testid="chip-nieuw-controleer">
              {data.nieuw_controleren} nieuw — controleer
            </Badge>
          </button>
        )}
        <span style={{ marginLeft: 'auto' }} />
        <select aria-label="Filter producten" value={filter} onChange={(e) => { setFilter(e.target.value as ProductFilter); setPagina(1) }} style={{ width: 'auto' }}>
          {FILTERS.map((f) => (
            <option key={f.waarde} value={f.waarde}>
              Toon: {f.label}
            </option>
          ))}
        </select>
        <input
          type="search"
          aria-label="Zoek product"
          placeholder="🔍 zoek product, leverancier of code…"
          value={zoek}
          onChange={(e) => { setZoek(e.target.value); setPagina(1) }}
          style={{ width: 260, maxWidth: '100%' }}
        />
      </div>
      <p className="hint" style={{ marginTop: 0 }}>
        Productomschrijving = letterlijk de tekst van de leveranciersfactuur; de stand is uitsluitend een afgeleide van brondocumenten
        (instroom bij boeken, storno draait terug) en gemelde beschadigingen mét project. Er valt hier niets te corrigeren — telverschillen
        blijven zichtbaar in de voorraad-aansluiting.
      </p>
      {actieFout && <div className="fout">{actieFout}</div>}
      {laadFout && <div className="fout">De mini-voorraad kon niet geladen worden: {laadFout}</div>}
      {data === null && !laadFout && <SkeletonRegels />}
      {data !== null && rijen.length === 0 && (
        <p className="hint" data-testid="mini-voorraad-leeg">
          {filter === 'alle' && !zoek ? MINI_VOORRAAD_LEEG_TEKST : `Geen producten met dit filter${zoek ? ` en zoekterm “${zoek}”` : ''}.`}
        </p>
      )}
      {rijen.length > 0 && (
        <div className="tabel-scroll">
          <table data-testid="mini-voorraad-tabel">
            <thead>
              <tr>
                <th>Product (omschrijving = letterlijk van de leveranciersfactuur)</th>
                <th className="amount" style={{ width: 110 }}>
                  Stand
                </th>
                <th className="acties" style={{ width: 340 }} />
              </tr>
            </thead>
            <tbody>
              {rijen.map((p) => {
                const naam = productNaam(p)
                const logOpen = openLogs.has(p.id)
                return (
                  <Fragment key={p.id}>
                    <tr data-testid="mini-voorraad-rij" style={{ opacity: p.gearchiveerd ? 0.6 : 1 }}>
                      <td>
                        <div>
                          <b>{naam}</b>{' '}
                          {p.nieuw_controleren && !p.gearchiveerd && (
                            <Badge variant="warn" data-testid="chip-nieuw">
                              nieuw — controleer naam
                            </Badge>
                          )}
                          {p.gearchiveerd && <Badge variant="stil">gearchiveerd</Badge>}
                        </div>
                        <div className="hint" style={{ margin: 0, fontSize: 11.5 }}>
                          {p.leverancier_naam ?? 'leverancier onbekend'} · {p.artikelcode ? `code ${p.artikelcode}` : 'geen code'}
                          {p.eenheid ? ` · ${p.eenheid}` : ''}
                          {p.weergavenaam?.trim() && p.weergavenaam !== p.omschrijving ? ` · factuurtekst: ${p.omschrijving}` : ''}
                        </div>
                      </td>
                      <td className="amount" style={{ fontVariantNumeric: 'tabular-nums' }}>
                        <b>{aantalTekst(p.stand)}</b>
                      </td>
                      <td className="acties" style={{ whiteSpace: 'nowrap', textAlign: 'right' }}>
                        {p.nieuw_controleren && !p.gearchiveerd && (
                          <>
                            <Button maat="klein" aria-label={`Naam bevestigen: ${p.omschrijving}`} onClick={() => setNaamVoor(p)}>
                              Naam bevestigen
                            </Button>{' '}
                          </>
                        )}
                        <Button variant="secundair" maat="klein" aria-expanded={logOpen} aria-label={`Voorraadlog van ${naam}`} onClick={() => toggleLog(p.id)}>
                          Voorraadlog {logOpen ? '▾' : '▸'}
                        </Button>{' '}
                        <button
                          ref={(el) => {
                            if (el) menuKnoppen.current.set(p.id, el)
                            else menuKnoppen.current.delete(p.id)
                          }}
                          type="button"
                          className="btn secondary meer"
                          aria-label={`Meer acties voor ${naam}`}
                          aria-haspopup="menu"
                          aria-expanded={menuVoor === p.id}
                          title="Meer acties: beschadiging melden, archiveren"
                          onClick={() => setMenuVoor((h) => (h === p.id ? null : p.id))}
                        >
                          ⋯
                        </button>
                        <AnkerPopup
                          open={menuVoor === p.id}
                          anker={menuKnoppen.current.get(p.id) ?? null}
                          kant="onder"
                          uitlijning="eind"
                          className="rijmenu"
                          role="menu"
                          onAnkerUitBeeld={() => setMenuVoor(null)}
                        >
                          {!p.gearchiveerd && (
                            <button
                              type="button"
                              className="linkbtn"
                              role="menuitem"
                              onClick={() => {
                                setMenuVoor(null)
                                setBeschadigingVoor(p)
                              }}
                            >
                              Beschadiging melden…
                            </button>
                          )}
                          {isBeheerder && !p.gearchiveerd && (
                            <button
                              type="button"
                              className="linkbtn"
                              role="menuitem"
                              onClick={() => {
                                setMenuVoor(null)
                                setArchiveerVoor(p)
                              }}
                            >
                              Archiveren…
                            </button>
                          )}
                          {isBeheerder && p.gearchiveerd && (
                            <button
                              type="button"
                              className="linkbtn"
                              role="menuitem"
                              onClick={() => {
                                setMenuVoor(null)
                                void dearchiveer(p)
                              }}
                            >
                              Dearchiveren
                            </button>
                          )}
                          {!isBeheerder && p.gearchiveerd && (
                            <span className="hint" role="menuitem" style={{ margin: 0, padding: '4px 8px', display: 'block' }}>
                              Beheerder dearchiveert
                            </span>
                          )}
                        </AnkerPopup>
                      </td>
                    </tr>
                    {logOpen && (
                      <tr className="subrij" data-testid="mini-voorraad-logrij">
                        <td colSpan={3}>
                          <VoorraadLog administratieId={administratieId} productId={p.id} productNaam={naam} />
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
        <div className="hint" data-testid="mini-voorraad-voet" style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
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
            · {data.totaal} {data.totaal === 1 ? 'product' : 'producten'}
            {data.nieuw_controleren > 0 ? ` · ${data.nieuw_controleren} nieuw — controleer naam` : ''}
          </span>
        </div>
      )}

      {naamVoor && (
        <NaamDialoog
          administratieId={administratieId}
          product={naamVoor}
          onSluiten={() => setNaamVoor(null)}
          onGelukt={(p) => {
            setNaamVoor(null)
            toast.meld(`Naam bevestigd: ${productNaam(p)}.`)
            herlaad()
          }}
        />
      )}
      {archiveerVoor && (
        <ArchiveerDialoog
          administratieId={administratieId}
          product={archiveerVoor}
          onSluiten={() => setArchiveerVoor(null)}
          onGelukt={(p) => {
            setArchiveerVoor(null)
            toast.meld(`${productNaam(p)} gearchiveerd — stand en voorraadlog blijven bewaard.`)
            herlaad()
          }}
        />
      )}
      {beschadigingVoor && (
        <BeschadigingDialog
          administratieId={administratieId}
          product={beschadigingVoor}
          onSluiten={() => setBeschadigingVoor(null)}
          onGemeld={(m) => {
            const naam = productNaam(beschadigingVoor)
            setBeschadigingVoor(null)
            toast.meld(`Beschadiging vastgelegd voor ${naam} (${aantalTekst(m.aantal)}) — zichtbaar in het voorraadlog.`)
            // De nieuwe regel direct laten zien: log van dít product open.
            setOpenLogs((h) => new Set(h).add(beschadigingVoor.id))
            herlaad()
          }}
        />
      )}
    </div>
  )
}

/** "Naam bevestigen": wijzigt UITSLUITEND de weergavenaam (⑦) — de factuurtekst blijft de sleutel en
 * staat ter referentie in de dialoog; bevestigen mét ongewijzigde tekst mag (dan is de factuurtekst de naam). */
function NaamDialoog({
  administratieId,
  product,
  onSluiten,
  onGelukt,
}: {
  administratieId: string
  product: MiniProductDto
  onSluiten: () => void
  onGelukt: (p: MiniProductDto) => void
}) {
  const [naam, setNaam] = useState(product.weergavenaam?.trim() ? product.weergavenaam : product.omschrijving)
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const geldig = naam.trim().length >= 1 && naam.trim().length <= NAAM_MAX

  const bevestig = async () => {
    if (!geldig) return
    setBezig(true)
    setFout(null)
    try {
      onGelukt(await bevestigNaam(administratieId, product.id, naam.trim()))
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Bevestigen mislukt.')
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onSluiten()}>
      <DialogContent aria-describedby={undefined} data-testid="naam-dialoog">
        <DialogTitle>Naam bevestigen</DialogTitle>
        <DialogDescription>
          Kies de weergavenaam voor dit product. De factuurtekst blijft de sleutel waarmee nieuwe inkoopregels van deze leverancier
          worden herkend — die wijzigt niet. Aantallen veranderen hier nooit.
        </DialogDescription>
        <div className="hint" style={{ marginTop: 0 }}>
          factuurtekst: <b>{product.omschrijving}</b>
          {product.leverancier_naam ? ` · ${product.leverancier_naam}` : ''}
          {product.artikelcode ? ` · code ${product.artikelcode}` : ''}
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void bevestig()
          }}
        >
          <FormField label="Weergavenaam" htmlFor="mini-weergavenaam" hint={`1–${NAAM_MAX} tekens; gelijk laten aan de factuurtekst mag`}>
            <input id="mini-weergavenaam" autoFocus required maxLength={NAAM_MAX} value={naam} onChange={(e) => setNaam(e.target.value)} style={{ width: '100%' }} />
          </FormField>
          {fout && <div className="fout">{fout}</div>}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onSluiten} disabled={bezig}>
              Annuleren
            </Button>
            <Button type="submit" disabled={bezig || !geldig}>
              {bezig ? 'Bezig…' : 'Naam bevestigen'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

/** Beheerder — archiveren mét inhoudelijke reden (≥ 5 tekens, audit). Nooit verwijderen (⑥): de stand
 * en het log blijven; komt het product opnieuw op een factuur voor, dan dearchiveert de instroom 'm. */
function ArchiveerDialoog({
  administratieId,
  product,
  onSluiten,
  onGelukt,
}: {
  administratieId: string
  product: MiniProductDto
  onSluiten: () => void
  onGelukt: (p: MiniProductDto) => void
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
      onGelukt(await archiveerProduct(administratieId, product.id, reden.trim()))
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Archiveren mislukt.')
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onSluiten()}>
      <DialogContent aria-describedby={undefined} data-testid="archiveer-dialoog">
        <DialogTitle>Product archiveren</DialogTitle>
        <DialogDescription>
          <b>{productNaam(product)}</b> verdwijnt uit de actieve lijst en de materiaallijst; stand ({aantalTekst(product.stand)}) en voorraadlog
          blijven bewaard — er wordt niets verwijderd. Komt het product opnieuw op een inkoopfactuur voor, dan wordt het automatisch
          weer actief. Leg vast waarom; de reden komt in het audit log.
        </DialogDescription>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void bevestig()
          }}
        >
          <FormField label="Reden" htmlFor="mini-archiveer-reden">
            <textarea
              id="mini-archiveer-reden"
              required
              rows={3}
              value={reden}
              onChange={(e) => setReden(e.target.value)}
              placeholder="Bijvoorbeeld: eenmalige inkoop, wordt niet meer geleverd."
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
              {bezig ? 'Bezig…' : 'Archiveren'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
