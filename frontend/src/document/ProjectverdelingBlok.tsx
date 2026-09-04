import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError } from '../api/client'
import type {
  ProjectverdelingDeelDto,
  ProjectverdelingDto,
  ProjectverdelingInputDto,
  ProjectverdelingVasteRegelDto,
} from '../api/types'
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from '../ui/basis'
import { SearchableCombobox } from './SearchableCombobox'
import {
  haalProjectverdelingOp,
  herverdeelProjectverdeling,
  slaProjectverdelingOp,
  startProjectcijfersSync,
} from './projectverdelingApi'
import { useProjectOpties } from './useSyncOpties'

/** Debounce van het automatisch opslaan — zelfde cadans als de doorbelasting-VerdelingEditor. */
export const AUTO_OPSLAAN_MS = 600

/** Statussen waarin de verdeling bewerkbaar is (spiegel van `_BEVROREN` in app/projectverdeling/service.py:
 * alles behalve geboekt/verwijderd; ter_accordering = alleen-lezen). */
const BEWERKBAAR = new Set(['te_controleren', 'klaar_om_te_boeken', 'handmatig_afmaken', 'boeken_mislukt', 'vraag_open', 'afgewezen'])

interface Props {
  administratieId: string
  documentId: string
  status: string
  soort: string
  /** Telt op bij elke opslag van het boekvoorstel — de verdeling wordt dan live herrekend (restant volgt de regels). */
  boekvoorstelVersie: number
  /** Ná "Herverdelen…" (document terug naar te_controleren) herlaadt de aanroeper het detail. */
  onGewijzigd?: () => void
  /** B3-dekking (bugfix 04-09): ná élke geslaagde opslag van de verdeling — de aanroeper laat de harde checks
   * opnieuw draaien (de check-laag toetst de opgeslagen verdeling; zonder herrun bleven de rode rijen van vóór het
   * verdelen staan — casus Kader Consultancy). */
  onOpgeslagen?: () => void
  /** B3-dekking: meldt of de huidige verdeling de regels zonder kolom-project dekt (actief én compleet) — de
   * boekingsregels-hint zegt dan "gedekt door de projectverdeling" i.p.v. de actie aan te bieden. */
  onStand?: (stand: { dekt: boolean }) => void
  /** B1 (04-09): telt op als de lege project-kolom "Verdelen over projecten…" aanbiedt — het blok opent (pro rato,
   * vorige maand) en scrollt in beeld. */
  openVerzoek?: number
}

interface VasteRij {
  sleutel: string
  projectId: string | null
  bedrag: string
  hint: string
}

const MAANDEN = ['januari', 'februari', 'maart', 'april', 'mei', 'juni', 'juli', 'augustus', 'september', 'oktober', 'november', 'december']

function euro(bedrag: string | number | null | undefined): string {
  if (bedrag === null || bedrag === undefined || bedrag === '') return '—'
  const n = Number(bedrag)
  if (Number.isNaN(n)) return '—'
  return n.toLocaleString('nl-NL', { style: 'currency', currency: 'EUR' })
}

function pct(aandeel: string | null | undefined): string {
  if (!aandeel) return ''
  return `${(Number(aandeel) * 100).toLocaleString('nl-NL', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`
}

function periodeLabel(iso: string | null | undefined): string {
  if (!iso) return ''
  const [jaar, maand] = iso.split('-').map(Number)
  return `${MAANDEN[(maand ?? 1) - 1]} ${jaar}`
}

/** Vorige afgesloten kalendermaand (client-side default vóór de eerste server-ronde; de server rekent bindend). */
export function defaultPeriode(vandaag = new Date()): string {
  const d = new Date(vandaag.getFullYear(), vandaag.getMonth() - 1, 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
}

/** De laatste 12 afgesloten maanden als keuzelijst voor "pro rato ▾". */
function periodeOpties(vandaag = new Date()): string[] {
  return Array.from({ length: 12 }, (_, i) => {
    const d = new Date(vandaag.getFullYear(), vandaag.getMonth() - 1 - i, 1)
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
  })
}

function naarBedragString(invoer: string): string | null {
  const zonderRuis = invoer.replace(/\s|€/g, '')
  // NL-notatie: punt = duizendtal zodra er een komma staat; anders is de punt het decimaalteken.
  const genormaliseerd = (zonderRuis.includes(',') ? zonderRuis.replace(/\./g, '') : zonderRuis).replace(',', '.')
  if (genormaliseerd === '' || genormaliseerd === '-') return null
  const n = Number(genormaliseerd)
  if (!Number.isFinite(n)) return null
  return n.toFixed(2)
}

function rijenUitDto(dto: ProjectverdelingDto): VasteRij[] {
  return (dto.vaste_regels ?? []).map((r: ProjectverdelingVasteRegelDto, i) => ({
    sleutel: `${r.project_id}-${i}`,
    projectId: r.project_id,
    bedrag: Number(r.bedrag).toFixed(2).replace('.', ','),
    hint: r.hint ?? '',
  }))
}

function ProRatoPreview({ delen, restant }: { delen: ProjectverdelingDeelDto[]; restant: string | null | undefined }) {
  const proRato = delen.filter((d) => d.wijze === 'pro_rato').sort((a, b) => Number(b.bedrag) - Number(a.bedrag))
  if (proRato.length === 0) return null
  const getoond = proRato.slice(0, 3)
  const rest = proRato.length - getoond.length
  return (
    <div className="pv-preview" data-testid="pv-preview">
      {getoond.map((d, i) => (
        <span key={d.project_id}>
          {i > 0 && <>&nbsp;·&nbsp;</>}
          {d.project_naam ?? d.project_id} {pct(d.aandeel)} · {euro(d.bedrag)}
        </span>
      ))}
      {rest > 0 && <>&nbsp;·&nbsp;+ {rest} kleinere</>}
      {' — grootste-rest-centen, som exact '}
      {euro(restant)}
      <ul style={{ margin: '4px 0 0', paddingLeft: 16 }}>
        {proRato.map((d) => (
          <li key={`${d.project_id}-lijst`}>
            {d.project_naam ?? d.project_id}: {pct(d.aandeel)} · {euro(d.bedrag)}
            {d.omzet ? ` (omzet ${euro(d.omzet)})` : ''}
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Restant-balk (UX-norm "restant-balk", mockup doorbelasten-blok-v2 ②) — drie standen op het basisbedrag. */
function RestantBalk({ dto }: { dto: ProjectverdelingDto }) {
  const basis = Number(dto.basisbedrag ?? 0)
  const vast = (dto.vaste_regels ?? []).reduce((som, r) => som + Number(r.bedrag), 0)
  const proRato = dto.compleet && dto.pro_rato ? Number(dto.pro_rato_bedrag ?? 0) : 0
  const verdeeld = vast + proRato
  const teVeel = basis >= 0 ? vast > basis + 0.004 : vast < basis - 0.004
  const som = basis !== 0 ? Math.round((verdeeld / basis) * 1000) / 10 : dto.compleet ? 100 : 0
  const stand = dto.compleet ? 'compleet' : teVeel ? 'te_veel' : 'deels'
  const breedte = Math.min(100, Math.max(0, stand === 'compleet' ? 100 : som))
  return (
    <div className={`restant-balk ${stand === 'compleet' ? 'compleet' : stand === 'te_veel' ? 'te-veel' : ''}`} data-testid="pv-restant-balk">
      <b>{euro(dto.basisbedrag)} excl.</b>
      <div className="balk" aria-hidden="true">
        <span style={{ width: `${breedte}%` }} />
      </div>
      {stand === 'compleet' ? (
        <b className="compleet-tekst">verdeeld 100% ✓</b>
      ) : stand === 'te_veel' ? (
        <span className="te-veel-tekst">{euro(vast - basis)} te veel vast</span>
      ) : (
        <>
          <b>verdeeld {som.toLocaleString('nl-NL')}%</b>
          <span className="nog">nog {euro(basis - verdeeld)}</span>
        </>
      )}
      {dto.status === 'geboekt' && <span className="chip ok">omzetstanden vastgelegd</span>}
    </div>
  )
}

/** Controlescherm-blok "Projectverdeling" (mockup blok 1, 1-op-1): vaste regels (project + bedrag + hint) vóór,
 * het restant pro rato over de projecten mét omzet in de gekozen maand ("pro rato ▾"), preview "Verdeling
 * tonen ▸", restant-balk, blokkade in één zin, lege omzetstand = actie (⟳ projectcijfers). Auto-opslaan 600 ms
 * — de server berekent de centen bindend. Ná boeken alleen-lezen mét chip "omzetstanden vastgelegd" en, bij een
 * hercontrole-afwijking boven de drempel, de `.signaal`-banner mét "Herverdelen…" (tegenboeken + nieuwe
 * verdeling als voorstel; mens bevestigt, nooit stil herboeken). Beschikbaar op élk inkoopdocument van een
 * administratie mét projectplicht/actieve projecten (B1 04-09): vooringevuld bij de leverancier-opt-in (prefill, B2),
 * anders via de tekstknop "Verdelen over projecten…" of de gelijknamige actie in de lege project-kolom (openVerzoek). */
export function ProjectverdelingBlok({ administratieId, documentId, status, soort, boekvoorstelVersie, onGewijzigd, onOpgeslagen, onStand, openVerzoek = 0 }: Props) {
  const relevant = soort === 'inkoopfactuur' && (BEWERKBAAR.has(status) || status === 'ter_accordering' || status === 'geboekt')
  const [dto, setDto] = useState<ProjectverdelingDto | null | undefined>(undefined)
  const [fout, setFout] = useState<string | null>(null)
  const [rijen, setRijen] = useState<VasteRij[]>([])
  const [proRato, setProRato] = useState(false)
  const [periode, setPeriode] = useState<string>(defaultPeriode())
  const [geopend, setGeopend] = useState(false)
  const [toonVerdeling, setToonVerdeling] = useState(false)
  const [opslaanBezig, setOpslaanBezig] = useState(false)
  const [syncBezig, setSyncBezig] = useState(false)
  const [herverdeelOpen, setHerverdeelOpen] = useState(false)
  const [herverdeelReden, setHerverdeelReden] = useState('')
  const [herverdeelBezig, setHerverdeelBezig] = useState(false)
  const [herverdeelFout, setHerverdeelFout] = useState<string | null>(null)
  const timer = useRef<number | null>(null)
  const laatsteVerzonden = useRef<string>('')
  const blokRef = useRef<HTMLDivElement | null>(null)
  const bewerkbaar = BEWERKBAAR.has(status)
  const projecten = useProjectOpties(administratieId)

  // B1 (04-09): de lege stand van de project-kolom biedt "Verdelen over projecten…" aan — zelfde actie als de
  // tekstknop hieronder (pro rato vorige maand als startpunt), plus in beeld scrollen.
  useEffect(() => {
    if (openVerzoek === 0 || !bewerkbaar) return
    setGeopend(true)
    setProRato(true)
    setPeriode(defaultPeriode())
    blokRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
  }, [openVerzoek, bewerkbaar])

  // Laden (+ herladen bij elke boekvoorstel-opslag: het restant volgt de regels).
  useEffect(() => {
    if (!relevant) return
    let actief = true
    setFout(null)
    haalProjectverdelingOp(administratieId, documentId)
      .then((data) => {
        if (!actief) return
        setDto(data)
        setRijen(rijenUitDto(data))
        setProRato(Boolean(data.pro_rato))
        setPeriode(data.pro_rato_periode ?? defaultPeriode())
        setGeopend(data.status === 'voorstel' || data.status === 'geboekt')
        laatsteVerzonden.current = JSON.stringify(uitgaand(rijenUitDto(data), Boolean(data.pro_rato), data.pro_rato_periode ?? defaultPeriode()))
      })
      .catch((err: unknown) => {
        if (actief) setFout(err instanceof ApiError ? err.message : 'Projectverdeling niet te laden.')
      })
    return () => {
      actief = false
    }
  }, [administratieId, documentId, boekvoorstelVersie, relevant, status])

  const opslaan = useCallback(
    async (invoer: ProjectverdelingInputDto, forceer = false) => {
      const sleutel = JSON.stringify(invoer)
      if (!forceer && sleutel === laatsteVerzonden.current) return
      laatsteVerzonden.current = sleutel
      setOpslaanBezig(true)
      setFout(null)
      try {
        const data = await slaProjectverdelingOp(administratieId, documentId, invoer)
        setDto(data)
        onOpgeslagen?.()
      } catch (err) {
        setFout(err instanceof ApiError ? err.message : 'Opslaan van de verdeling mislukt.')
      } finally {
        setOpslaanBezig(false)
      }
    },
    [administratieId, documentId, onOpgeslagen],
  )

  // B3-dekking: de stand naar buiten — dekt = de verdeling is actief (voorstel/geboekt mét vaste regels en/of pro
  // rato) én compleet; spiegel van `ProjectverdelingData.dekt_regels_zonder_project` (app/projectverdeling/data.py).
  useEffect(() => {
    if (!onStand) return
    const actief = Boolean(dto && (dto.status === 'voorstel' || dto.status === 'geboekt') && ((dto.vaste_regels?.length ?? 0) > 0 || dto.pro_rato))
    onStand({ dekt: actief && Boolean(dto?.compleet) })
  }, [dto, onStand])

  // Auto-opslaan: alleen als élke vaste regel volledig is (project + bedrag) — de server rekent restant/blokkade.
  useEffect(() => {
    if (!bewerkbaar || !geopend || dto === undefined) return
    if (rijen.some((r) => r.projectId === null || naarBedragString(r.bedrag) === null)) return
    const invoer = uitgaand(rijen, proRato, periode)
    if (JSON.stringify(invoer) === laatsteVerzonden.current) return
    if (timer.current) window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => void opslaan(invoer), AUTO_OPSLAAN_MS)
    return () => {
      if (timer.current) window.clearTimeout(timer.current)
    }
  }, [rijen, proRato, periode, bewerkbaar, geopend, dto, opslaan])

  const projectOpties = useMemo(() => projecten.opties, [projecten.opties])

  if (!relevant || dto === undefined) return null
  if (dto === null) return null
  // B1: zonder projectplicht én zonder actieve projecten heeft verdelen geen zin — geen blok.
  if (dto.beschikbaar === false && dto.status === 'geen') return null

  const zichtbaar = geopend || dto.status === 'voorstel' || dto.status === 'geboekt'
  if (!zichtbaar) {
    if (!bewerkbaar) return null
    return (
      <div className="projectverdeling-blok" data-testid="projectverdeling-blok" ref={blokRef}>
        <button
          type="button"
          className="linkbtn"
          onClick={() => {
            setGeopend(true)
            setProRato(true)
            setPeriode(defaultPeriode())
          }}
        >
          Verdelen over projecten…
        </button>
      </div>
    )
  }

  const geboekt = dto.status === 'geboekt'
  const alleenLezen = geboekt || !bewerkbaar
  const delen = dto.delen ?? []
  const hercontrole = dto.hercontrole
  const signaal = geboekt && hercontrole?.signaal

  const wijzigRij = (sleutel: string, patch: Partial<VasteRij>) =>
    setRijen((huidig) => huidig.map((r) => (r.sleutel === sleutel ? { ...r, ...patch } : r)))

  const verwijderRij = (sleutel: string) => setRijen((huidig) => huidig.filter((r) => r.sleutel !== sleutel))

  const voegRijToe = () => setRijen((huidig) => [...huidig, { sleutel: `nieuw-${Date.now()}-${huidig.length}`, projectId: null, bedrag: '', hint: '' }])

  const verdelingWeghalen = async () => {
    setGeopend(false)
    setRijen([])
    setProRato(false)
    laatsteVerzonden.current = ''
    await opslaan({ vaste_regels: [], pro_rato_periode: null, vervallen: true }, true)
  }

  const cijfersVerversen = async () => {
    setSyncBezig(true)
    try {
      await startProjectcijfersSync(administratieId)
      setFout('Projectcijfers-sync gestart — de omzetstanden verschijnen zodra de run klaar is (herlaad daarna het document).')
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Cijfers-sync starten mislukt.')
    } finally {
      setSyncBezig(false)
    }
  }

  const herverdelen = async (reden: string) => {
    setHerverdeelBezig(true)
    setHerverdeelFout(null)
    try {
      await herverdeelProjectverdeling(administratieId, documentId, reden)
      setHerverdeelOpen(false)
      onGewijzigd?.()
    } catch (err) {
      setHerverdeelFout(err instanceof ApiError ? err.message : 'Herverdelen mislukt.')
    } finally {
      setHerverdeelBezig(false)
    }
  }

  return (
    <div className="panel projectverdeling-blok" data-testid="projectverdeling-blok" ref={blokRef}>
      <h2 style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        Projectverdeling
        {dto.prefill && !dto.opgeslagen && <span className="chip geheugen">voorstel — pro rato per leverancier aan</span>}
        {opslaanBezig && <span className="pv-hint">opslaan…</span>}
      </h2>
      <div className="tabel-scroll">
        <table className="pv-tabel">
          <thead>
            <tr>
              <th style={{ width: '38%' }}>Project</th>
              <th style={{ width: 110 }}>Wijze</th>
              <th style={{ width: 110, textAlign: 'right' }}>Bedrag excl.</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {(alleenLezen ? (dto.vaste_regels ?? []).map((r, i) => ({ sleutel: `${r.project_id}-${i}`, projectId: r.project_id, bedrag: r.bedrag, hint: r.hint ?? '', naam: r.project_naam })) : rijen).map(
              (rij) => (
                <tr key={rij.sleutel} data-testid="pv-vaste-regel">
                  <td>
                    {alleenLezen ? (
                      <div className="veld">{('naam' in rij ? (rij.naam as string | null | undefined) : null) ?? rij.projectId}</div>
                    ) : (
                      <SearchableCombobox
                        label="Project (vast)"
                        toonLabel={false}
                        opties={projectOpties}
                        waarde={rij.projectId}
                        onWijzig={(id) => wijzigRij(rij.sleutel, { projectId: id })}
                        placeholder="— kies project —"
                        vereist
                      />
                    )}
                  </td>
                  <td>
                    <span className="chip geboekt">vast</span>
                  </td>
                  <td className="pv-euro">
                    {alleenLezen ? (
                      <b>{euro(rij.bedrag)}</b>
                    ) : (
                      <input
                        className="veld klein pv-bedrag"
                        inputMode="decimal"
                        aria-label="Bedrag excl. (vast)"
                        value={rij.bedrag}
                        onChange={(e) => wijzigRij(rij.sleutel, { bedrag: e.target.value })}
                        placeholder="0,00"
                      />
                    )}
                  </td>
                  <td className="pv-hint">
                    {alleenLezen ? (
                      rij.hint
                    ) : (
                      <span style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                        <input
                          className="veld klein"
                          aria-label="Toelichting (vast)"
                          value={rij.hint}
                          onChange={(e) => wijzigRij(rij.sleutel, { hint: e.target.value })}
                          placeholder="toelichting"
                          style={{ flex: 1 }}
                        />
                        <button type="button" className="linkbtn" onClick={() => verwijderRij(rij.sleutel)} aria-label="Vaste regel verwijderen">
                          ✕
                        </button>
                      </span>
                    )}
                  </td>
                </tr>
              ),
            )}
            <tr data-testid="pv-restant-regel">
              <td>
                <b>Restant — pro rato omzet {periodeLabel(alleenLezen ? dto.pro_rato_periode : proRato ? periode : null) || '(uit)'}</b>
                <div className="pv-hint">
                  {proRato || dto.pro_rato
                    ? `${dto.aantal_projecten_met_omzet ?? 0} projecten mét omzet · omzetloos telt niet mee · OVH uitgesloten`
                    : 'pro rato staat uit — het restant moet via vaste regels verdeeld worden'}
                </div>
              </td>
              <td>
                {alleenLezen ? (
                  <span className="chip klaar">{dto.pro_rato ? 'pro rato' : 'uit'}</span>
                ) : (
                  <select
                    className="pv-periode"
                    aria-label="Pro rato omzetmaand"
                    value={proRato ? periode : ''}
                    onChange={(e) => {
                      if (e.target.value === '') {
                        setProRato(false)
                      } else {
                        setProRato(true)
                        setPeriode(e.target.value)
                      }
                    }}
                  >
                    <option value="">pro rato uit</option>
                    {periodeOpties().map((p) => (
                      <option key={p} value={p}>
                        pro rato {periodeLabel(p)} ▾
                      </option>
                    ))}
                  </select>
                )}
              </td>
              <td className="pv-euro">
                <b>{euro(dto.pro_rato_bedrag)}</b>
              </td>
              <td>
                {delen.some((d) => d.wijze === 'pro_rato') && (
                  <button type="button" className="btn secondary" onClick={() => setToonVerdeling((v) => !v)}>
                    {toonVerdeling ? 'Verdeling verbergen ▾' : 'Verdeling tonen ▸'}
                  </button>
                )}
              </td>
            </tr>
            {toonVerdeling && (
              <tr>
                <td colSpan={4}>
                  <ProRatoPreview delen={delen} restant={dto.pro_rato_bedrag} />
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {!alleenLezen && (
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', margin: '8px 0 10px' }}>
          <button type="button" className="btn secondary" onClick={voegRijToe}>
            + Regel toevoegen (vast)
          </button>
          <button type="button" className="linkbtn" onClick={() => void verdelingWeghalen()}>
            Verdeling weghalen
          </button>
        </div>
      )}
      <RestantBalk dto={dto} />
      {dto.blokkade && !alleenLezen && (
        <p className="pv-blokkade" data-testid="pv-blokkade">
          {dto.blokkade}
          {dto.omzet_cache_leeg && (
            <>
              {' '}
              <button type="button" className="btn secondary" onClick={() => void cijfersVerversen()} disabled={syncBezig}>
                ⟳ Projectcijfers verversen
              </button>
            </>
          )}
        </p>
      )}
      {fout && <div className="fout">{fout}</div>}
      {signaal && hercontrole && (
        <div className="signaal" role="status" data-testid="pv-signaal">
          ⚠{' '}
          <span>
            <b>Hercontrole {periodeLabel(hercontrole.op.slice(0, 7) + '-01')}:</b> omzet {periodeLabel(hercontrole.periode)} is ná het boeken
            gewijzigd — verdeling wijkt nu {Number(hercontrole.afwijking_pct ?? 0).toLocaleString('nl-NL')}% af (drempel{' '}
            {Number(hercontrole.drempel_pct).toLocaleString('nl-NL')}%).
          </span>
          <button type="button" className="btn secondary pv-actie" onClick={() => setHerverdeelOpen(true)}>
            Herverdelen…
          </button>
        </div>
      )}
      {herverdeelOpen && hercontrole && (
        <Dialog open onOpenChange={(open) => !open && !herverdeelBezig && setHerverdeelOpen(false)}>
          <DialogContent breed data-testid="pv-herverdeel-dialoog">
            <DialogTitle>Herverdelen — tegenboeken en opnieuw boeken</DialogTitle>
            <DialogDescription>
              De boeking wordt tegengeboekt en komt terug op &ldquo;te controleren&rdquo; mét de nieuwe verdeling als voorstel; u boekt
              daarna opnieuw. Niets gebeurt stil — de btw-aangifte-poort geldt onverkort.
            </DialogDescription>
            <div className="tabel-scroll">
              <table className="pv-vergelijk">
                <thead>
                  <tr>
                    <th>Project</th>
                    <th style={{ textAlign: 'right' }}>Oud</th>
                    <th style={{ textAlign: 'right' }}>Nieuw</th>
                  </tr>
                </thead>
                <tbody>
                  {vergelijk(delen, hercontrole.nieuwe_verdeling).map((r) => (
                    <tr key={r.project_id}>
                      <td>{r.naam}</td>
                      <td className={`pv-euro ${r.oud !== r.nieuw ? 'oud' : ''}`}>{euro(r.oud)}</td>
                      <td className="pv-euro">
                        <b>{euro(r.nieuw)}</b>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <label style={{ display: 'block', marginTop: 12 }}>
              Reden (verplicht)
              <textarea
                className="veld"
                aria-label="Reden herverdelen"
                value={herverdeelReden}
                onChange={(e) => setHerverdeelReden(e.target.value)}
                placeholder={`omzet ${periodeLabel(hercontrole.periode)} gewijzigd ná het boeken — verdeling wijkt ${hercontrole.afwijking_pct}% af`}
                rows={2}
                style={{ width: '100%', marginTop: 4 }}
              />
            </label>
            {herverdeelFout && <div className="fout">{herverdeelFout}</div>}
            <DialogFooter>
              <Button type="button" variant="secundair" onClick={() => setHerverdeelOpen(false)} disabled={herverdeelBezig}>
                Annuleren
              </Button>
              <Button
                type="button"
                onClick={() => {
                  // Reden vooringevuld (opdracht): leeg gelaten = de standaardtekst gaat mee (verplicht, ≥ 5 tekens).
                  const standaard = `omzet ${periodeLabel(hercontrole.periode)} gewijzigd ná het boeken — verdeling wijkt ${hercontrole.afwijking_pct}% af`
                  const reden = herverdeelReden.trim().length >= 5 ? herverdeelReden.trim() : standaard
                  if (reden !== herverdeelReden) setHerverdeelReden(reden)
                  void herverdelen(reden)
                }}
                disabled={herverdeelBezig}
              >
                {herverdeelBezig ? 'Bezig…' : 'Tegenboeken en herverdelen'}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </div>
  )
}

function uitgaand(rijen: VasteRij[], proRato: boolean, periode: string): ProjectverdelingInputDto {
  return {
    vaste_regels: rijen
      .filter((r) => r.projectId !== null)
      .map((r) => ({ project_id: r.projectId as string, bedrag: naarBedragString(r.bedrag) ?? '0.00', hint: r.hint.trim() || null })),
    pro_rato_periode: proRato ? periode : null,
  }
}

function vergelijk(oud: ProjectverdelingDeelDto[], nieuw: ProjectverdelingDeelDto[]) {
  const per = new Map<string, { project_id: string; naam: string; oud: string; nieuw: string }>()
  const tel = (lijst: ProjectverdelingDeelDto[], kant: 'oud' | 'nieuw') => {
    for (const d of lijst) {
      const rij = per.get(d.project_id) ?? { project_id: d.project_id, naam: d.project_naam ?? d.project_id, oud: '0.00', nieuw: '0.00' }
      rij[kant] = (Number(rij[kant]) + Number(d.bedrag)).toFixed(2)
      if (d.project_naam) rij.naam = d.project_naam
      per.set(d.project_id, rij)
    }
  }
  tel(oud, 'oud')
  tel(nieuw, 'nieuw')
  return [...per.values()].sort((a, b) => Number(b.nieuw) - Number(a.nieuw))
}
