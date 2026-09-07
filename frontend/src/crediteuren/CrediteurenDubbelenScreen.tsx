// Inzicht › Crediteuren — dubbelen over álle administraties, mét actie (design-ronde 03-09, mockup
// crediteuren-dubbelen-v2.html; blok B13 07-09 "schaalbaar", richting Peter 06-09: 271 clusters/11 pagina's is niet
// minimale-mens). Eén kantoorbrede lijst, zwaarste sleutel bovenaan, administratie/sleutel/classificatie als facet,
// zoekveld, paginering 25. Het systeem classificeert élk cluster deterministisch: EENDUIDIG (identieke naam/IBAN,
// geen conflicterend KvK/btw, verliezers met hooguit enkele boekingen) handelt de knop "Eenduidige clusters
// automatisch afhandelen (N)" in één run af — mét dry-run-preview per administratie; TWIJFEL blijft mens: "Voorkeur
// kiezen…" (radio) of "Geen dubbel — afmelden" (reden). Afhandelen = de verliezers worden in de MODULE onbruikbaar
// (voorstellen, matching, autoboeken, geheugen → voorkeur); RLZ-archivering is geen doel meer — de RLZ-opruimlijst is
// een optionele CSV-export onder ⋯, geen teller. Alles terugdraaibaar (paneel "Afgehandeld"). Nooit verwijderen;
// teal = actie, groen = status.
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
  autoAfhandelen,
  draaiAfhandelingTerug,
  haalAfhandelingenOp,
  haalClusterDetailOp,
  haalDubbelenOp,
  haalOpruimlijstCsvOp,
  handelClusterAf,
  meldClusterAf,
  SLEUTEL_LABEL,
  type AfhandelingenDto,
  type AfhandelingRegelDto,
  type AutoRunDto,
  type Classificatie,
  type ClusterDetailDto,
  type ClusterDto,
  type KaartDto,
  type LijstDto,
  type SleutelSoort,
} from './api'

const PER_PAGINA = 25
const ALLE = '__alle__'
const SLEUTELS: SleutelSoort[] = ['btw_nummer', 'kvk_nummer', 'iban', 'naam']

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

function downloadBlob(blob: Blob, bestandsnaam: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = bestandsnaam
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export function CrediteurenDubbelenScreen() {
  const toast = useToastOptioneel()
  const [pagina, setPagina] = useState(1)
  const [zoek, setZoek] = useState('')
  const [administratieId, setAdministratieId] = useState('')
  const [sleutel, setSleutel] = useState('')
  const [classificatie, setClassificatie] = useState<Classificatie | ''>('')
  const [data, setData] = useState<LijstDto | null>(null)
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [versie, setVersie] = useState(0)
  const [uitkomst, setUitkomst] = useState<string | null>(null)
  const [menuOpen, setMenuOpen] = useState<string | null>(null)
  const menuKnoppen = useRef<Record<string, HTMLButtonElement | null>>({})
  const [paneelMenuOpen, setPaneelMenuOpen] = useState(false)
  const paneelMenuKnop = useRef<HTMLButtonElement | null>(null)
  const [afhandelVoor, setAfhandelVoor] = useState<ClusterDto | null>(null)
  const [afmeldVoor, setAfmeldVoor] = useState<ClusterDto | null>(null)
  const [autoOpen, setAutoOpen] = useState(false)
  const [toonAfgehandeld, setToonAfgehandeld] = useState(false)
  const [afhandelingen, setAfhandelingen] = useState<AfhandelingenDto | null>(null)
  const [afhandelingenFout, setAfhandelingenFout] = useState<string | null>(null)
  const [terugdraaiVoor, setTerugdraaiVoor] = useState<AfhandelingRegelDto | null>(null)
  const [exportFout, setExportFout] = useState<string | null>(null)

  const herlaad = useCallback(() => setVersie((v) => v + 1), [])

  useEffect(() => {
    let actueel = true
    setLaadFout(null)
    haalDubbelenOp({ pagina, q: zoek, administratieId, sleutel, classificatie })
      .then((dto) => actueel && setData(dto))
      .catch((err: unknown) => actueel && setLaadFout(err instanceof Error ? err.message : 'Onbekende fout'))
    return () => {
      actueel = false
    }
  }, [pagina, zoek, administratieId, sleutel, classificatie, versie])

  useEffect(() => {
    if (!toonAfgehandeld) return
    let actueel = true
    setAfhandelingenFout(null)
    haalAfhandelingenOp()
      .then((dto) => actueel && setAfhandelingen(dto))
      .catch((err: unknown) => actueel && setAfhandelingenFout(err instanceof Error ? err.message : 'Onbekende fout'))
    return () => {
      actueel = false
    }
  }, [toonAfgehandeld, versie])

  const exporteer = async () => {
    setPaneelMenuOpen(false)
    setExportFout(null)
    try {
      downloadBlob(await haalOpruimlijstCsvOp(), 'rlz-opruimlijst-crediteuren.csv')
      toast.meld('RLZ-opruimlijst gedownload', 'ok')
    } catch (err) {
      setExportFout(err instanceof Error ? err.message : 'Export mislukt.')
    }
  }

  const tellers = data?.tellers
  const facetAdministraties = [{ id: ALLE, naam: 'Alle administraties' }, ...(data?.facetten.administraties ?? []).map((f) => ({ id: f.administratie_id, naam: `${f.naam} (${f.aantal})` }))]

  return (
    <div data-testid="crediteuren-dubbelen-scherm">
      <div className="topbar">
        <div>
          <div className="mb-1 text-[12.5px] text-muted">Inzicht</div>
          <h1>Crediteuren</h1>
          <div style={{ color: 'var(--muted)', fontSize: 12.5, marginTop: 3 }}>
            Dubbele crediteuren over álle administraties. Eenduidige clusters handelt het systeem af; alleen twijfel vraagt een keuze. Een
            afgehandelde dubbel wordt in de module niet meer voorgesteld — in Reeleezee verandert niets en er wordt niets verwijderd.
          </div>
        </div>
      </div>

      <div className="panel inst-paneel">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '14px 18px', borderBottom: '1px solid var(--border)', flexWrap: 'wrap' }}>
          <h2 style={{ margin: 0, fontSize: 12, letterSpacing: '1.1px', textTransform: 'uppercase', color: 'var(--muted)', fontWeight: 800 }}>Dubbel-signalering</h2>
          {tellers && (
            <Badge variant={tellers.clusters > 0 ? 'warn' : 'ok'} data-testid="clusters-chip">
              {tellers.clusters} {tellers.clusters === 1 ? 'twijfelcluster' : 'twijfelclusters'}
            </Badge>
          )}
          {tellers && tellers.clusters + tellers.eenduidig > 0 && (
            <span className="hint" style={{ margin: 0 }}>
              over {tellers.administraties} {tellers.administraties === 1 ? 'administratie' : 'administraties'}
            </span>
          )}
          {tellers && tellers.eenduidig > 0 && (
            <Button variant="secundair" maat="klein" onClick={() => setAutoOpen(true)} data-testid="auto-knop">
              Eenduidige clusters automatisch afhandelen ({tellers.eenduidig})
            </Button>
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
          <select
            className="sel"
            aria-label="Classificatie"
            value={classificatie}
            onChange={(e) => {
              setClassificatie(e.target.value as Classificatie | '')
              setPagina(1)
            }}
          >
            <option value="">Alle clusters</option>
            <option value="twijfel">Twijfel (mens){tellers ? ` (${tellers.clusters})` : ''}</option>
            <option value="eenduidig">Eenduidig (systeem){tellers ? ` (${tellers.eenduidig})` : ''}</option>
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
            style={{ width: 200, maxWidth: '100%' }}
          />
          <button
            type="button"
            className="linkbtn"
            ref={paneelMenuKnop}
            aria-label="Meer acties voor crediteuren"
            aria-haspopup="menu"
            aria-expanded={paneelMenuOpen}
            onClick={() => setPaneelMenuOpen((o) => !o)}
          >
            ⋯
          </button>
          <AnkerPopup
            open={paneelMenuOpen}
            anker={paneelMenuKnop.current}
            kant="onder"
            uitlijning="eind"
            className="rijmenu"
            role="menu"
            aria-label="Acties voor crediteuren"
            onAnkerUitBeeld={() => setPaneelMenuOpen(false)}
          >
            <button type="button" className="linkbtn" role="menuitem" onClick={() => void exporteer()}>
              Exporteer RLZ-opruimlijst (CSV)
            </button>
            <button
              type="button"
              className="linkbtn"
              role="menuitem"
              onClick={() => {
                setPaneelMenuOpen(false)
                setToonAfgehandeld((t) => !t)
              }}
            >
              {toonAfgehandeld ? 'Afgehandeld verbergen' : 'Afgehandeld tonen (terugdraaien)'}
            </button>
          </AnkerPopup>
        </div>

        {uitkomst && (
          <div className="hint" role="status" style={{ margin: '10px 18px' }} data-testid="afhandel-uitkomst">
            <Badge variant="ok">{uitkomst}</Badge>
          </div>
        )}
        {exportFout && <FoutMelding melding="De RLZ-opruimlijst kon niet geëxporteerd worden." detail={exportFout} onOpnieuw={() => void exporteer()} />}
        {laadFout && <FoutMelding melding="De dubbel-signalering kon niet geladen worden." detail={laadFout} onOpnieuw={herlaad} />}
        {data === null && !laadFout && <SkeletonRegels />}
        {data !== null && data.rijen.length === 0 && (
          <p className="hint" style={{ padding: '14px 18px' }} role="status">
            {data.tellers.clusters + data.tellers.eenduidig === 0
              ? 'Geen dubbele crediteuren gevonden in de administraties binnen je scope.'
              : 'Geen clusters binnen dit filter.'}
          </p>
        )}
        {data !== null && data.rijen.length > 0 && (
          <div className="tabel-scroll">
            <table data-testid="clusters-tabel">
              <thead>
                <tr>
                  <th style={{ width: '30%' }}>Cluster</th>
                  <th>Administratie</th>
                  <th>Waarom dubbel</th>
                  <th>Beoordeling</th>
                  <th style={{ width: 220 }} />
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
                      onAfhandelen={() => setAfhandelVoor(c)}
                      onAfmelden={() => setAfmeldVoor(c)}
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

      {toonAfgehandeld && (
        <div className="panel inst-paneel" style={{ marginTop: 16 }} data-testid="afgehandeld-paneel">
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '14px 18px', borderBottom: '1px solid var(--border)', flexWrap: 'wrap' }}>
            <h2 style={{ margin: 0, fontSize: 12, letterSpacing: '1.1px', textTransform: 'uppercase', color: 'var(--muted)', fontWeight: 800 }}>Afgehandeld</h2>
            {afhandelingen && <Badge variant="stil">{afhandelingen.actief} actief</Badge>}
            <span className="hint" style={{ margin: 0, flex: '1 1 320px' }}>
              Elke afhandeling (systeem of mens) staat hier mét reden en is terug te draaien; boekingsgeheugen dat al naar de voorkeur
              verhuisde blijft staan (zichtbaar in het auditlog).
            </span>
          </div>
          {afhandelingenFout && <FoutMelding melding="De afhandelingen konden niet geladen worden." detail={afhandelingenFout} onOpnieuw={herlaad} />}
          {afhandelingen === null && !afhandelingenFout && <SkeletonRegels />}
          {afhandelingen && afhandelingen.regels.length === 0 && (
            <p className="hint" style={{ padding: '14px 18px' }}>
              Nog niets afgehandeld.
            </p>
          )}
          {afhandelingen && afhandelingen.regels.length > 0 && (
            <div className="tabel-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Administratie</th>
                    <th>Voorkeur (blijft)</th>
                    <th>Onbruikbaar in de module</th>
                    <th>Hoe</th>
                    <th style={{ width: 150 }} />
                  </tr>
                </thead>
                <tbody>
                  {afhandelingen.regels.map((r) => (
                    <tr key={r.id}>
                      <td>{r.administratie_naam}</td>
                      <td style={{ fontWeight: 700 }}>{r.voorkeur_naam ?? r.voorkeur_vendor_id.slice(0, 8)}</td>
                      <td>{r.verliezers.map((v) => v.naam ?? v.vendor_id.slice(0, 8)).join(', ')}</td>
                      <td>
                        {r.teruggedraaid_op ? (
                          <>
                            <Badge variant="stil">teruggedraaid</Badge>
                            <div className="hint" style={{ margin: '3px 0 0', fontSize: 11.5 }}>
                              {formatDatumKort(r.teruggedraaid_op)} · {r.teruggedraaid_reden}
                            </div>
                          </>
                        ) : (
                          <>
                            <Badge variant="ok">{r.bron === 'auto' ? 'systeem' : 'mens'}</Badge>
                            <div className="hint" style={{ margin: '3px 0 0', fontSize: 11.5 }}>
                              {formatDatumKort(r.afgehandeld_op)} · {r.classificatie_reden}
                            </div>
                          </>
                        )}
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        {!r.teruggedraaid_op && (
                          <Button variant="secundair" maat="klein" onClick={() => setTerugdraaiVoor(r)} aria-label={`Terugdraaien: ${r.voorkeur_naam ?? ''}`}>
                            Terugdraaien…
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
      )}

      {autoOpen && (
        <AutoAfhandelDialog
          administratieId={administratieId}
          onKlaar={(melding) => {
            setAutoOpen(false)
            setUitkomst(melding)
            toast.meld(melding, 'ok')
            herlaad()
          }}
          onAnnuleren={() => setAutoOpen(false)}
        />
      )}
      {afhandelVoor && (
        <AfhandelDialog
          cluster={afhandelVoor}
          onKlaar={(melding) => {
            setAfhandelVoor(null)
            setUitkomst(melding)
            toast.meld(melding, 'ok')
            herlaad()
          }}
          onAnnuleren={() => setAfhandelVoor(null)}
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
      {terugdraaiVoor && (
        <TerugdraaiDialog
          regel={terugdraaiVoor}
          onKlaar={() => {
            setTerugdraaiVoor(null)
            toast.meld('Afhandeling teruggedraaid — crediteuren zijn weer bruikbaar', 'ok')
            herlaad()
          }}
          onAnnuleren={() => setTerugdraaiVoor(null)}
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
  onAfhandelen,
  onAfmelden,
}: {
  cluster: ClusterDto
  naam: string
  menuOpen: boolean
  menuKnop: (el: HTMLButtonElement | null) => void
  menuAnker: HTMLButtonElement | null
  onMenu: () => void
  onSluitMenu: () => void
  onAfhandelen: () => void
  onAfmelden: () => void
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
        <td>
          <Badge variant={c.eenduidig ? 'ok' : 'warn'} title={c.classificatie_reden} data-testid="classificatie-chip">
            {c.eenduidig ? 'eenduidig — systeem' : 'twijfel — mens'}
          </Badge>
          <div className="hint" style={{ margin: '3px 0 0', fontSize: 11.5 }}>{c.classificatie_reden.replace(/^(eenduidig|twijfel): /, '')}</div>
        </td>
        <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
          <div style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
            {c.afmelden_primair ? (
              <Button variant="secundair" maat="klein" onClick={onAfmelden} aria-label={`Geen dubbel — afmelden: ${naam}`}>
                Geen dubbel — afmelden
              </Button>
            ) : (
              <Button maat="klein" onClick={onAfhandelen} aria-label={`Voorkeur kiezen: ${naam}`}>
                Voorkeur kiezen…
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
              {c.afmelden_primair ? (
                <button
                  type="button"
                  className="linkbtn"
                  role="menuitem"
                  onClick={() => {
                    onSluitMenu()
                    onAfhandelen()
                  }}
                >
                  Voorkeur kiezen…
                </button>
              ) : (
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
            </AnkerPopup>
          </div>
        </td>
      </tr>
      <tr className="cluster-leden" data-testid="cluster-leden">
        <td colSpan={5} style={{ paddingLeft: 34, background: 'var(--panel-2)', fontSize: 12, color: 'var(--muted)' }}>
          {c.crediteuren.map((k) => (
            <div key={k.vendor_id}>
              <b style={{ color: 'var(--text)' }}>{k.naam ?? k.vendor_id.slice(0, 8)}</b> · {kaartRegel(k)}
              {k.vendor_id === c.voorkeur_suggestie && (
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

function AutoAfhandelDialog({ administratieId, onKlaar, onAnnuleren }: { administratieId: string; onKlaar: (melding: string) => void; onAnnuleren: () => void }) {
  const [preview, setPreview] = useState<AutoRunDto | null>(null)
  const [previewFout, setPreviewFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  useEffect(() => {
    let actueel = true
    autoAfhandelen({ dryRun: true, administratieId: administratieId || undefined })
      .then((p) => actueel && setPreview(p))
      .catch((err: unknown) => actueel && setPreviewFout(err instanceof Error ? err.message : 'Onbekende fout'))
    return () => {
      actueel = false
    }
  }, [administratieId])

  const bevestig = async () => {
    setBezig(true)
    setFout(null)
    try {
      const r = await autoAfhandelen({ dryRun: false, administratieId: administratieId || undefined })
      const melding = `${r.afgehandeld} ${r.afgehandeld === 1 ? 'cluster' : 'clusters'} automatisch afgehandeld over ${r.administraties.filter((a) => a.afgehandeld > 0).length} ${r.administraties.filter((a) => a.afgehandeld > 0).length === 1 ? 'administratie' : 'administraties'}${r.fouten ? ` · ${r.fouten} mislukt (zie log)` : ''}${r.twijfel ? ` · ${r.twijfel} twijfel blijft voor u` : ''}`
      onKlaar(melding)
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Afhandelen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onAnnuleren()}>
      <DialogContent aria-describedby={undefined} data-testid="auto-dialoog">
        <DialogTitle>Eenduidige clusters automatisch afhandelen</DialogTitle>
        <DialogDescription>
          Eenduidig = identieke naam of hetzelfde IBAN, geen tegenstrijdig KvK-/btw-nummer en de crediteur die wegvalt heeft hooguit enkele
          boekingen. Het systeem kiest de meest gebruikte crediteur als voorkeur; de andere wordt in de module niet meer voorgesteld. Geheugen en
          kenmerken verhuizen mee. Alles is terug te draaien; in Reeleezee verandert niets.
        </DialogDescription>
        {preview === null && !previewFout && <SkeletonRegels />}
        {previewFout && <FoutMelding melding="De preview kon niet geladen worden." detail={previewFout} />}
        {preview && (
          <div data-testid="auto-preview">
            <p style={{ margin: '8px 0' }}>
              <b>{preview.eenduidig}</b> {preview.eenduidig === 1 ? 'cluster' : 'clusters'} eenduidig over {preview.administraties.filter((a) => a.eenduidig > 0).length}{' '}
              {preview.administraties.filter((a) => a.eenduidig > 0).length === 1 ? 'administratie' : 'administraties'}
              {preview.twijfel > 0 ? ` · ${preview.twijfel} twijfel ${preview.twijfel === 1 ? 'blijft' : 'blijven'} voor u` : ''}
            </p>
            <div className="tabel-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Administratie</th>
                    <th>Eenduidig</th>
                    <th>Twijfel</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.administraties
                    .filter((a) => a.eenduidig > 0)
                    .map((a) => (
                      <tr key={a.administratie_id}>
                        <td>{a.administratie_naam}</td>
                        <td>{a.eenduidig}</td>
                        <td>{a.twijfel}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
            <details style={{ marginTop: 8 }}>
              <summary className="hint" style={{ cursor: 'pointer' }}>
                Wat er precies gebeurt ({preview.administraties.reduce((n, a) => n + a.voorbeelden.length, 0)} clusters)
              </summary>
              <ul style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 12 }}>
                {preview.administraties.flatMap((a) =>
                  a.voorbeelden.map((v) => (
                    <li key={v.cluster_id}>
                      {a.administratie_naam}: <b>{v.voorkeur_naam}</b> blijft; {v.verliezer_namen.join(', ')} wordt onbruikbaar
                      <span className="hint" style={{ marginLeft: 6 }}>({v.reden.replace(/^eenduidig: /, '')})</span>
                    </li>
                  )),
                )}
              </ul>
            </details>
          </div>
        )}
        {fout && <div className="fout">{fout}</div>}
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={onAnnuleren} disabled={bezig}>
            Annuleren
          </Button>
          <Button type="button" onClick={() => void bevestig()} disabled={bezig || !preview || preview.eenduidig === 0}>
            {bezig ? 'Bezig…' : `Afhandelen (${preview?.eenduidig ?? 0})`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function AfhandelDialog({ cluster, onKlaar, onAnnuleren }: { cluster: ClusterDto; onKlaar: (melding: string) => void; onAnnuleren: () => void }) {
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
  const verliezers = kaarten.filter((k) => k.vendor_id !== voorkeur)
  const kanBevestigen = detail !== null && verliezers.length > 0 && !bezig

  const bevestig = async () => {
    setBezig(true)
    setFout(null)
    try {
      const r = await handelClusterAf(
        cluster.administratie_id,
        voorkeur,
        verliezers.map((k) => k.vendor_id),
      )
      onKlaar(r.melding)
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Afhandelen mislukt.')
      if (err instanceof ApiError && err.status === 422) setPoging((p) => p + 1)
    } finally {
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onAnnuleren()}>
      <DialogContent aria-describedby={undefined} data-testid="afhandel-dialoog">
        <DialogTitle>Voorkeur kiezen</DialogTitle>
        <DialogDescription>
          {cluster.administratie_naam} · kies de crediteur die blijft. De andere wordt in de module niet meer voorgesteld of gekozen;
          boekingsgeheugen, btw-/KvK-kenmerk en vertrouwde IBAN's verhuizen naar de voorkeur en open boekvoorstellen worden omgezet. In
          Reeleezee verandert niets; terugdraaien kan onder ⋯ › Afgehandeld.
        </DialogDescription>
        {detail === null && !detailFout && <SkeletonRegels />}
        {detailFout && <FoutMelding melding="De kaartgegevens konden niet geladen worden." detail={detailFout} onOpnieuw={() => setPoging((p) => p + 1)} />}
        {detail && (
          <div className="hint" style={{ margin: '4px 0 8px' }} data-testid="detail-classificatie">
            <Badge variant={detail.eenduidig ? 'ok' : 'warn'}>{detail.eenduidig ? 'eenduidig' : 'twijfel'}</Badge>{' '}
            {detail.classificatie_reden.replace(/^(eenduidig|twijfel): /, '')}
          </div>
        )}
        <fieldset style={{ border: 0, padding: 0, margin: '10px 0' }}>
          <legend className="hint" style={{ margin: '0 0 6px' }}>
            Voorkeur (blijft bruikbaar)
          </legend>
          {kaarten.map((k) => {
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
                  {!isVoorkeur && <span className="hint" style={{ marginLeft: 6 }}>wordt onbruikbaar in de module</span>}
                  <div className="hint" style={{ margin: '2px 0 0', fontSize: 11.5 }}>{kaartRegel(k)}</div>
                </span>
              </label>
            )
          })}
        </fieldset>
        {fout && <div className="fout">{fout}</div>}
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={onAnnuleren} disabled={bezig}>
            Annuleren
          </Button>
          <Button type="button" onClick={() => void bevestig()} disabled={!kanBevestigen}>
            {bezig ? 'Bezig…' : `Afhandelen: ${verliezers.length === 1 ? 'de andere wordt' : `${verliezers.length} andere worden`} onbruikbaar`}
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

function TerugdraaiDialog({ regel, onKlaar, onAnnuleren }: { regel: AfhandelingRegelDto; onKlaar: () => void; onAnnuleren: () => void }) {
  const [reden, setReden] = useState('')
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  const bevestig = async () => {
    setBezig(true)
    setFout(null)
    try {
      await draaiAfhandelingTerug(regel.id, reden.trim())
      onKlaar()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Terugdraaien mislukt.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onAnnuleren()}>
      <DialogContent aria-describedby={undefined} data-testid="terugdraai-dialoog">
        <DialogTitle>Afhandeling terugdraaien</DialogTitle>
        <DialogDescription>
          {regel.verliezers.map((v) => v.naam ?? v.vendor_id.slice(0, 8)).join(', ')} ({regel.administratie_naam}) wordt weer bruikbaar; het kenmerk van{' '}
          {regel.voorkeur_naam ?? 'de voorkeur'} en omgezette boekvoorstellen gaan terug naar de oude stand. Al verhuisd boekingsgeheugen blijft staan
          (auditlog). Een reden is verplicht.
        </DialogDescription>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void bevestig()
          }}
        >
          <FormField label="Reden" htmlFor="terugdraai-reden">
            <input id="terugdraai-reden" autoFocus value={reden} onChange={(e) => setReden(e.target.value)} placeholder='bv. "toch twee bedrijven"' />
          </FormField>
          {fout && <div className="fout">{fout}</div>}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onAnnuleren} disabled={bezig}>
              Annuleren
            </Button>
            <Button type="submit" variant="secundair" disabled={bezig || reden.trim() === ''}>
              {bezig ? 'Bezig…' : 'Terugdraaien'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
