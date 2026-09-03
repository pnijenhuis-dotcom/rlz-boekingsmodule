// Inzicht › Crediteuren — dubbelen over álle administraties, mét actie (design-ronde 03-09, mockup
// crediteuren-dubbelen-v2.html = bouwnorm, ontwerpnotities ①–⑧; principe minimale mens 02-09). Geen
// administratie-picker als poort: één kantoorbrede lijst van dubbel-clusters, zwaarste sleutel bovenaan
// (btw > KvK > IBAN > naam), administratie/sleutel als facet, zoekveld, paginering 25. Per cluster één
// primaire actie: "Voorkeur kiezen & rest archiveren…" — STAP-0 03-09: archiveren via de RLZ-API kán niet,
// dus de uitkomst is een RLZ-werklijst-regel ("klaargezet — archiveer in RLZ: <namen>") mét status
// open/gedaan + dagelijkse hertoets; boekingsgeheugen en crediteur-kenmerk verhuizen direct naar de
// voorkeur. Open posten op een te archiveren crediteur = blokkerend ("eerst afletteren"). "Geen dubbel —
// afmelden" is primair alleen bij naam-clusters mét aantoonbaar verschillend KvK; anders in het ⋯-menu.
// Nooit verwijderen; teal = actie, groen = status.
import { useCallback, useEffect, useRef, useState } from 'react'
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
  Paginering,
  SkeletonRegels,
  useToastOptioneel,
} from '../ui/basis'
import { formatDatumKort } from '../werkvoorraad/format'
import {
  archiveerCluster,
  haalClusterDetailOp,
  haalDubbelenOp,
  haalWerklijstOp,
  markeerWerklijstGedaan,
  meldClusterAf,
  SLEUTEL_LABEL,
  type ClusterDetailDto,
  type ClusterDto,
  type KaartDto,
  type LijstDto,
  type SleutelSoort,
  type WerklijstDto,
} from './api'

const PER_PAGINA = 25
const ALLE = '__alle__'
const SLEUTELS: SleutelSoort[] = ['btw_nummer', 'kvk_nummer', 'iban', 'naam']

function bedrag(waarde: string): string {
  const n = Number(waarde)
  return Number.isFinite(n) ? `€ ${n.toLocaleString('nl-NL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : waarde
}

function clusterNaam(c: ClusterDto): string {
  return c.crediteuren.map((k) => k.naam ?? k.vendor_id.slice(0, 8)).join(' / ')
}

function kaartRegel(k: KaartDto): string {
  const delen: string[] = []
  delen.push(k.btw_nummer ? `btw ${k.btw_nummer}` : 'geen btw op kaart')
  if (k.kvk_nummer) delen.push(`KvK ${k.kvk_nummer}`)
  if (k.ibans.length) delen.push(`IBAN ${k.ibans.join(', ')}`)
  delen.push(`${k.aantal_boekingen} ${k.aantal_boekingen === 1 ? 'boeking' : 'boekingen'}`)
  if (k.laatst_geboekt) delen.push(`laatst geboekt ${formatDatumKort(k.laatst_geboekt)}`)
  return delen.join(' · ')
}

function chipVariant(chip: string): 'warn' | 'stil' | 'ok' {
  if (chip === 'naam ≈') return 'stil'
  if (chip.startsWith('verschillend KvK')) return 'ok'
  return 'warn'
}

export function CrediteurenDubbelenScreen() {
  const toast = useToastOptioneel()
  const [pagina, setPagina] = useState(1)
  const [zoek, setZoek] = useState('')
  const [administratieId, setAdministratieId] = useState('')
  const [sleutel, setSleutel] = useState('')
  const [data, setData] = useState<LijstDto | null>(null)
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [versie, setVersie] = useState(0)
  const [uitkomst, setUitkomst] = useState<string | null>(null)
  const [menuOpen, setMenuOpen] = useState<string | null>(null)
  const menuKnoppen = useRef<Record<string, HTMLButtonElement | null>>({})
  const [archiveerVoor, setArchiveerVoor] = useState<ClusterDto | null>(null)
  const [afmeldVoor, setAfmeldVoor] = useState<ClusterDto | null>(null)
  const [werklijst, setWerklijst] = useState<WerklijstDto | null>(null)
  const [werklijstFout, setWerklijstFout] = useState<string | null>(null)
  const [toonGedaan, setToonGedaan] = useState(false)

  const herlaad = useCallback(() => setVersie((v) => v + 1), [])

  useEffect(() => {
    let actueel = true
    setLaadFout(null)
    haalDubbelenOp({ pagina, q: zoek, administratieId, sleutel })
      .then((dto) => actueel && setData(dto))
      .catch((err: unknown) => actueel && setLaadFout(err instanceof Error ? err.message : 'Onbekende fout'))
    return () => {
      actueel = false
    }
  }, [pagina, zoek, administratieId, sleutel, versie])

  useEffect(() => {
    let actueel = true
    setWerklijstFout(null)
    haalWerklijstOp()
      .then((dto) => actueel && setWerklijst(dto))
      .catch((err: unknown) => actueel && setWerklijstFout(err instanceof Error ? err.message : 'Onbekende fout'))
    return () => {
      actueel = false
    }
  }, [versie])

  const gedaanMarkeren = async (id: string) => {
    try {
      await markeerWerklijstGedaan(id)
      toast.meld('Werklijst-regel gemarkeerd als gedaan', 'ok')
      herlaad()
    } catch (err) {
      setWerklijstFout(err instanceof ApiError ? err.message : 'Markeren mislukt.')
    }
  }

  const tellers = data?.tellers
  const facetAdministraties = [{ id: ALLE, naam: 'Alle administraties' }, ...(data?.facetten.administraties ?? []).map((f) => ({ id: f.administratie_id, naam: `${f.naam} (${f.aantal})` }))]
  const openRegels = (werklijst?.regels ?? []).filter((r) => r.status === 'open')
  const gedaanRegels = (werklijst?.regels ?? []).filter((r) => r.status === 'gedaan')

  return (
    <div data-testid="crediteuren-dubbelen-scherm">
      <div className="topbar">
        <div>
          <div className="mb-1 text-[12.5px] text-muted">Inzicht</div>
          <h1>Crediteuren</h1>
          <div style={{ color: 'var(--muted)', fontSize: 12.5, marginTop: 3 }}>
            Dubbele crediteuren over álle administraties, zwaarste signaal bovenaan. Kies per cluster de voorkeur; de rest komt op de
            RLZ-werklijst om te archiveren — niets wordt verwijderd.
          </div>
        </div>
      </div>

      <div className="panel inst-paneel">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '14px 18px', borderBottom: '1px solid var(--border)', flexWrap: 'wrap' }}>
          <h2 style={{ margin: 0, fontSize: 12, letterSpacing: '1.1px', textTransform: 'uppercase', color: 'var(--muted)', fontWeight: 800 }}>Dubbel-signalering</h2>
          {tellers && (
            <Badge variant={tellers.clusters > 0 ? 'warn' : 'ok'} data-testid="clusters-chip">
              {tellers.clusters} {tellers.clusters === 1 ? 'cluster' : 'clusters'}
            </Badge>
          )}
          {tellers && tellers.clusters > 0 && (
            <span className="hint" style={{ margin: 0 }}>
              over {tellers.administraties} {tellers.administraties === 1 ? 'administratie' : 'administraties'}
              {tellers.klaargezet > 0 ? ` · ${tellers.klaargezet} klaargezet voor RLZ` : ''}
            </span>
          )}
          <span style={{ marginLeft: 'auto' }} />
          <div style={{ minWidth: 220 }}>
            <AdministratieCombobox
              label="Administratie"
              toonLabel={false}
              administraties={facetAdministraties}
              waarde={administratieId || ALLE}
              onWijzig={(id) => {
                setAdministratieId(id === ALLE ? '' : id)
                setPagina(1)
              }}
              placeholder="Administratie: alle"
            />
          </div>
          <select
            className="sel"
            aria-label="Sleutel"
            value={sleutel}
            onChange={(e) => {
              setSleutel(e.target.value)
              setPagina(1)
            }}
          >
            <option value="">Sleutel: alle</option>
            {SLEUTELS.map((s) => (
              <option key={s} value={s} disabled={!data?.facetten.sleutels[s]}>
                {SLEUTEL_LABEL[s]}
                {data?.facetten.sleutels[s] ? ` (${data.facetten.sleutels[s]})` : ''}
              </option>
            ))}
          </select>
          <input
            type="search"
            aria-label="Zoek crediteur"
            placeholder="🔍 zoek crediteur…"
            value={zoek}
            onChange={(e) => {
              setZoek(e.target.value)
              setPagina(1)
            }}
            style={{ width: 240, maxWidth: '100%' }}
          />
        </div>

        {uitkomst && (
          <div className="hint" role="status" style={{ margin: '10px 18px' }} data-testid="archiveer-uitkomst">
            <Badge variant="ok">{uitkomst}</Badge>
          </div>
        )}
        {laadFout && <FoutMelding melding="De dubbel-signalering kon niet geladen worden." detail={laadFout} onOpnieuw={herlaad} />}
        {data === null && !laadFout && <SkeletonRegels />}
        {data !== null && data.rijen.length === 0 && (
          <p className="hint" style={{ padding: '14px 18px' }} role="status">
            {data.tellers.clusters + data.tellers.klaargezet === 0
              ? 'Geen dubbele crediteuren gevonden in de administraties binnen je scope.'
              : 'Geen clusters binnen dit filter.'}
          </p>
        )}
        {data !== null && data.rijen.length > 0 && (
          <div className="tabel-scroll">
            <table data-testid="clusters-tabel">
              <thead>
                <tr>
                  <th style={{ width: '32%' }}>Cluster</th>
                  <th>Administratie</th>
                  <th>Waarom dubbel</th>
                  <th style={{ width: 260 }} />
                </tr>
              </thead>
              <tbody>
                {data.rijen.map((c) => {
                  const naam = clusterNaam(c)
                  return (
                    <ClusterRij
                      key={c.cluster_id}
                      cluster={c}
                      naam={naam}
                      menuOpen={menuOpen === c.cluster_id}
                      menuKnop={(el) => {
                        menuKnoppen.current[c.cluster_id] = el
                      }}
                      menuAnker={menuKnoppen.current[c.cluster_id] ?? null}
                      onMenu={() => setMenuOpen((m) => (m === c.cluster_id ? null : c.cluster_id))}
                      onSluitMenu={() => setMenuOpen(null)}
                      onArchiveer={() => setArchiveerVoor(c)}
                      onAfmelden={() => setAfmeldVoor(c)}
                      onGedaan={c.klaargezet ? () => void gedaanMarkeren(c.klaargezet!.werklijst_id) : undefined}
                    />
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        {data !== null && data.totaal > PER_PAGINA && (
          <div style={{ padding: '8px 18px' }}>
            <Paginering pagina={pagina} totaal={data.totaal} grootte={PER_PAGINA} onPagina={setPagina} label="clusters" />
          </div>
        )}
      </div>

      <div className="panel inst-paneel" style={{ marginTop: 16 }} data-testid="rlz-werklijst">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '14px 18px', borderBottom: '1px solid var(--border)', flexWrap: 'wrap' }}>
          <h2 style={{ margin: 0, fontSize: 12, letterSpacing: '1.1px', textTransform: 'uppercase', color: 'var(--muted)', fontWeight: 800 }}>RLZ-werklijst</h2>
          {werklijst && <Badge variant={werklijst.open > 0 ? 'warn' : 'ok'}>{werklijst.open} open</Badge>}
          <span className="hint" style={{ margin: 0, flex: '1 1 320px' }}>
            Archiveren kan niet via de Reeleezee-API: deze regels zijn klikwerk in RLZ (Relaties › Crediteuren › archiveren). De dagelijkse
            hertoets vinkt een regel af zodra de crediteur in RLZ gearchiveerd is; handmatig afvinken kan óók.
          </span>
          {gedaanRegels.length > 0 && (
            <button type="button" className="linkbtn" onClick={() => setToonGedaan((t) => !t)}>
              {toonGedaan ? 'gedaan verbergen' : `${gedaanRegels.length} gedaan tonen`}
            </button>
          )}
        </div>
        {werklijstFout && <FoutMelding melding="De RLZ-werklijst kon niet geladen worden." detail={werklijstFout} onOpnieuw={herlaad} />}
        {werklijst && openRegels.length === 0 && !toonGedaan && (
          <p className="hint" style={{ padding: '14px 18px' }}>
            Niets klaargezet — kies bij een cluster hierboven de voorkeur om de overige crediteuren op deze lijst te zetten.
          </p>
        )}
        {werklijst && (openRegels.length > 0 || (toonGedaan && gedaanRegels.length > 0)) && (
          <div className="tabel-scroll">
            <table>
              <thead>
                <tr>
                  <th>Administratie</th>
                  <th>Voorkeur (blijft)</th>
                  <th>Archiveer in RLZ</th>
                  <th>Status</th>
                  <th style={{ width: 170 }} />
                </tr>
              </thead>
              <tbody>
                {[...openRegels, ...(toonGedaan ? gedaanRegels : [])].map((r) => (
                  <tr key={r.id}>
                    <td>{r.administratie_naam}</td>
                    <td style={{ fontWeight: 700 }}>{r.voorkeur_naam ?? r.voorkeur_vendor_id.slice(0, 8)}</td>
                    <td>
                      {r.te_archiveren.map((t) => (
                        <div key={t.vendor_id}>
                          {t.naam ?? t.vendor_id.slice(0, 8)}
                          {r.hertoets_detail?.[t.vendor_id] ? <span className="hint" style={{ marginLeft: 6 }}>({r.hertoets_detail[t.vendor_id]})</span> : null}
                        </div>
                      ))}
                    </td>
                    <td>
                      {r.status === 'open' ? (
                        <>
                          <Badge variant="warn">klaargezet</Badge>
                          <div className="hint" style={{ margin: '3px 0 0', fontSize: 11.5 }}>
                            sinds {formatDatumKort(r.aangemaakt_op)}
                            {r.laatste_hertoets_op ? ` · laatst getoetst ${formatDatumKort(r.laatste_hertoets_op)}` : ' · nog niet getoetst'}
                          </div>
                        </>
                      ) : (
                        <>
                          <Badge variant="ok">gedaan</Badge>
                          <div className="hint" style={{ margin: '3px 0 0', fontSize: 11.5 }}>
                            {r.gedaan_op ? formatDatumKort(r.gedaan_op) : ''}
                            {r.gedaan_bron === 'hertoets' ? ' · gezien in RLZ' : r.gedaan_bron === 'handmatig' ? ' · handmatig afgevinkt' : ''}
                          </div>
                        </>
                      )}
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      {r.status === 'open' && (
                        <Button variant="secundair" maat="klein" onClick={() => void gedaanMarkeren(r.id)} aria-label={`Markeer als gedaan: ${r.te_archiveren.map((t) => t.naam).join(', ')}`}>
                          Markeer als gedaan
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {archiveerVoor && (
        <ArchiveerDialog
          cluster={archiveerVoor}
          onKlaar={(melding) => {
            setArchiveerVoor(null)
            setUitkomst(melding)
            toast.meld(melding, 'ok')
            herlaad()
          }}
          onAnnuleren={() => setArchiveerVoor(null)}
        />
      )}
      {afmeldVoor && (
        <AfmeldDialog
          cluster={afmeldVoor}
          onKlaar={() => {
            setAfmeldVoor(null)
            toast.meld('Cluster afgemeld — komt voor deze combinatie niet terug', 'ok')
            herlaad()
          }}
          onAnnuleren={() => setAfmeldVoor(null)}
        />
      )}
    </div>
  )
}

function ClusterRij({
  cluster: c,
  naam,
  menuOpen,
  menuKnop,
  menuAnker,
  onMenu,
  onSluitMenu,
  onArchiveer,
  onAfmelden,
  onGedaan,
}: {
  cluster: ClusterDto
  naam: string
  menuOpen: boolean
  menuKnop: (el: HTMLButtonElement | null) => void
  menuAnker: HTMLButtonElement | null
  onMenu: () => void
  onSluitMenu: () => void
  onArchiveer: () => void
  onAfmelden: () => void
  onGedaan?: () => void
}) {
  const sub = `${c.crediteuren.length} crediteuren${c.laatst_geboekt ? ` · laatst geboekt ${formatDatumKort(c.laatst_geboekt)}` : ' · nog niet geboekt'}`
  return (
    <>
      <tr data-testid="cluster-rij">
        <td>
          <div style={{ fontWeight: 700 }}>{naam}</div>
          <div className="hint" style={{ margin: '2px 0 0', fontSize: 11.5 }}>{sub}</div>
        </td>
        <td>{c.administratie_naam}</td>
        <td>
          <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
            {c.chips.map((chip) => (
              <Badge key={chip} variant={chipVariant(chip)}>
                {chip}
              </Badge>
            ))}
          </div>
        </td>
        <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
          <div style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
            {c.klaargezet ? (
              <Badge variant="ok" title={`klaargezet ${formatDatumKort(c.klaargezet.aangemaakt_op)}`}>
                klaargezet — archiveer in RLZ: {c.klaargezet.namen.join(', ')}
              </Badge>
            ) : c.afmelden_primair ? (
              <Button variant="secundair" maat="klein" onClick={onAfmelden} aria-label={`Geen dubbel — afmelden: ${naam}`}>
                Geen dubbel — afmelden
              </Button>
            ) : (
              <Button maat="klein" onClick={onArchiveer} aria-label={`Voorkeur kiezen & rest archiveren: ${naam}`}>
                Voorkeur kiezen &amp; rest archiveren…
              </Button>
            )}
            <button
              type="button"
              className="linkbtn"
              ref={menuKnop}
              aria-label={`Meer acties voor ${naam}`}
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              onClick={onMenu}
            >
              ⋯
            </button>
            <AnkerPopup
              open={menuOpen}
              anker={menuAnker}
              kant="onder"
              uitlijning="eind"
              className="rijmenu"
              role="menu"
              aria-label={`Acties voor ${naam}`}
              onAnkerUitBeeld={onSluitMenu}
            >
              {!c.klaargezet && c.afmelden_primair && (
                <button
                  type="button"
                  className="linkbtn"
                  role="menuitem"
                  onClick={() => {
                    onSluitMenu()
                    onArchiveer()
                  }}
                >
                  Voorkeur kiezen &amp; rest archiveren…
                </button>
              )}
              {!c.klaargezet && !c.afmelden_primair && (
                <button
                  type="button"
                  className="linkbtn"
                  role="menuitem"
                  onClick={() => {
                    onSluitMenu()
                    onAfmelden()
                  }}
                >
                  Geen dubbel — afmelden…
                </button>
              )}
              {c.klaargezet && onGedaan && (
                <button
                  type="button"
                  className="linkbtn"
                  role="menuitem"
                  onClick={() => {
                    onSluitMenu()
                    onGedaan()
                  }}
                >
                  Markeer als gedaan in RLZ
                </button>
              )}
            </AnkerPopup>
          </div>
        </td>
      </tr>
      <tr className="cluster-leden" data-testid="cluster-leden">
        <td colSpan={4} style={{ paddingLeft: 34, background: 'var(--panel-2)', fontSize: 12, color: 'var(--muted)' }}>
          {c.crediteuren.map((k) => (
            <div key={k.vendor_id}>
              <b style={{ color: 'var(--text)' }}>{k.naam ?? k.vendor_id.slice(0, 8)}</b> · {kaartRegel(k)}
              {k.vendor_id === c.voorkeur_suggestie && !c.klaargezet && (
                <Badge variant="ok" style={{ marginLeft: 6 }}>
                  voorkeur (meest gebruikt)
                </Badge>
              )}
            </div>
          ))}
        </td>
      </tr>
    </>
  )
}

function ArchiveerDialog({ cluster, onKlaar, onAnnuleren }: { cluster: ClusterDto; onKlaar: (melding: string) => void; onAnnuleren: () => void }) {
  const vendorIds = cluster.crediteuren.map((k) => k.vendor_id)
  const [detail, setDetail] = useState<ClusterDetailDto | null>(null)
  const [detailFout, setDetailFout] = useState<string | null>(null)
  const [voorkeur, setVoorkeur] = useState(cluster.voorkeur_suggestie)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [poging, setPoging] = useState(0)

  useEffect(() => {
    let actueel = true
    setDetail(null)
    setDetailFout(null)
    haalClusterDetailOp(cluster.administratie_id, vendorIds)
      .then((d) => {
        if (!actueel) return
        setDetail(d)
        setVoorkeur(d.voorkeur_suggestie)
      })
      .catch((err: unknown) => actueel && setDetailFout(err instanceof Error ? err.message : 'Onbekende fout'))
    return () => {
      actueel = false
    }
    // vendorIds is afgeleid van cluster; cluster is stabiel zolang de dialoog open is.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cluster.cluster_id, poging])

  const kaarten = detail?.crediteuren ?? cluster.crediteuren
  const teArchiveren = kaarten.filter((k) => k.vendor_id !== voorkeur)
  const geblokkeerd = teArchiveren.filter((k) => (detail?.open_posten[k.vendor_id] ?? []).length > 0)
  const toetsMislukt = detail !== null && !detail.toets_ok
  const kanBevestigen = detail !== null && !toetsMislukt && geblokkeerd.length === 0 && teArchiveren.length > 0 && !bezig

  const bevestig = async () => {
    setBezig(true)
    setFout(null)
    try {
      const r = await archiveerCluster(
        cluster.administratie_id,
        voorkeur,
        teArchiveren.map((k) => k.vendor_id),
      )
      onKlaar(r.melding)
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        // Server hertoetst de open posten opnieuw: intussen open post óf toets mislukt → tonen + detail verversen.
        setFout(err.message)
        setPoging((p) => p + 1)
      } else {
        setFout(err instanceof ApiError ? err.message : 'Klaarzetten mislukt.')
      }
    } finally {
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onAnnuleren()}>
      <DialogContent aria-describedby={undefined} data-testid="archiveer-dialoog">
        <DialogTitle>Voorkeur kiezen &amp; rest archiveren</DialogTitle>
        <DialogDescription>
          {cluster.administratie_naam} · kies de crediteur die blijft. De overige komen op de RLZ-werklijst om in Reeleezee te archiveren
          (de API kan dat niet zelf); boekingsgeheugen en btw-/KvK-kenmerk verhuizen direct naar de voorkeur, zodat voorstellen blijven
          werken. Niets wordt verwijderd.
        </DialogDescription>
        {detail === null && !detailFout && <SkeletonRegels />}
        {detailFout && <FoutMelding melding="De kaartgegevens konden niet geladen worden." detail={detailFout} onOpnieuw={() => setPoging((p) => p + 1)} />}
        <fieldset style={{ border: 0, padding: 0, margin: '10px 0' }}>
          <legend className="hint" style={{ margin: '0 0 6px' }}>
            Voorkeur (blijft actief)
          </legend>
          {kaarten.map((k) => {
            const posten = detail?.open_posten[k.vendor_id] ?? []
            const isVoorkeur = k.vendor_id === voorkeur
            return (
              <label key={k.vendor_id} style={{ display: 'flex', gap: 8, alignItems: 'flex-start', padding: '6px 0', cursor: 'pointer' }}>
                <input
                  type="radio"
                  name="voorkeur"
                  value={k.vendor_id}
                  aria-label={`Voorkeur: ${k.naam ?? k.vendor_id.slice(0, 8)}`}
                  checked={isVoorkeur}
                  onChange={() => setVoorkeur(k.vendor_id)}
                  style={{ marginTop: 3 }}
                />
                <span style={{ flex: 1 }}>
                  <b>{k.naam ?? k.vendor_id.slice(0, 8)}</b>
                  {isVoorkeur && k.vendor_id === (detail?.voorkeur_suggestie ?? cluster.voorkeur_suggestie) && (
                    <Badge variant="ok" style={{ marginLeft: 6 }}>
                      voorkeur (meest gebruikt)
                    </Badge>
                  )}
                  {!isVoorkeur && <span className="hint" style={{ marginLeft: 6 }}>wordt gearchiveerd</span>}
                  <div className="hint" style={{ margin: '2px 0 0', fontSize: 11.5 }}>{kaartRegel(k)}</div>
                  {!isVoorkeur && posten.length > 0 && (
                    <div className="fout" style={{ marginTop: 6 }} data-testid="open-posten-blokkade">
                      <b>
                        {posten.length} open {posten.length === 1 ? 'post' : 'posten'} — eerst afletteren
                      </b>
                      <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
                        {posten.map((p) => (
                          <li key={p.rlz_document_id}>
                            {p.referentie ?? p.rlz_document_id}
                            {p.datum ? ` · ${formatDatumKort(p.datum)}` : ''} · {bedrag(p.open_bedrag)} open
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </span>
              </label>
            )
          })}
        </fieldset>
        {toetsMislukt && (
          <div className="fout" data-testid="toets-mislukt">
            Open-posten-toets in Reeleezee mislukt — eerst opnieuw proberen; zonder groene toets wordt er niets klaargezet.
            <div className="hint" style={{ margin: '4px 0 0' }}>{detail?.toets_fout}</div>
            <div style={{ marginTop: 6 }}>
              <Button type="button" variant="secundair" maat="klein" onClick={() => setPoging((p) => p + 1)}>
                Opnieuw toetsen
              </Button>
            </div>
          </div>
        )}
        {fout && <div className="fout">{fout}</div>}
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={onAnnuleren} disabled={bezig}>
            Annuleren
          </Button>
          <Button type="button" onClick={() => void bevestig()} disabled={!kanBevestigen}>
            {bezig ? 'Bezig…' : `Klaarzetten: archiveer ${teArchiveren.length === 1 ? 'de andere' : `${teArchiveren.length} andere`} in RLZ`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function AfmeldDialog({ cluster, onKlaar, onAnnuleren }: { cluster: ClusterDto; onKlaar: () => void; onAnnuleren: () => void }) {
  const [reden, setReden] = useState(cluster.kvk_verschilt ? 'Verschillende KvK-nummers — twee bedrijven' : '')
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  const bevestig = async () => {
    setBezig(true)
    setFout(null)
    try {
      await meldClusterAf(
        cluster.administratie_id,
        cluster.crediteuren.map((k) => k.vendor_id),
        reden.trim(),
      )
      onKlaar()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Afmelden mislukt.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onAnnuleren()}>
      <DialogContent aria-describedby={undefined} data-testid="afmeld-dialoog">
        <DialogTitle>Geen dubbel — afmelden</DialogTitle>
        <DialogDescription>
          {clusterNaam(cluster)} ({cluster.administratie_naam}) verdwijnt uit de dubbel-signalering en komt voor exact deze combinatie niet
          terug. Een reden is verplicht en wordt geauditeerd — niets verdwijnt stil.
        </DialogDescription>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void bevestig()
          }}
        >
          <FormField label="Reden" htmlFor="afmeld-reden">
            <input id="afmeld-reden" autoFocus value={reden} onChange={(e) => setReden(e.target.value)} placeholder='bv. "andere KvK — twee vestigingen"' />
          </FormField>
          {fout && <div className="fout">{fout}</div>}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onAnnuleren} disabled={bezig}>
              Annuleren
            </Button>
            <Button type="submit" variant="secundair" disabled={bezig || reden.trim() === ''}>
              {bezig ? 'Bezig…' : 'Afmelden'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
