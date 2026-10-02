import { useEffect, useRef, useState, type CSSProperties, type MouseEvent } from 'react'
import { dagKort, handvatBereik, initialen, matrixRijen, transportTooltip, transportenPerCel, vulhandvatVoorbeeld, type DagKaart, type DagKolom, type VulhandvatVoorbeeld } from './dagEerst'
import { UREN_STATUS_KLEUR, UREN_STATUS_LABEL, urenKort, type PlanningKaartDto, type PlanningTransportKortDto, type PlanningWeekDto, type UrenFilter } from './planningApi'
import { projectKleurIndex, projectKleurVar, splitsProjectnummer } from './projectKleur'
import { useDagDrop } from './useDagDrop'

/* Weekgrid dag-eerst v4 — PROJECT × DAG-MATRIX (feedback Peter 28-09, herziet v3 18-09 "vrije kaartvolgorde per dag"): rijen =
 * projecten mét planning of reservering deze week (dezelfde rij over de week: "project 1 staat bovenaan, ook al is het op
 * donderdag als 3e ingepland"), kolommen = dagen mét sticky dagkop + dagtotaal (18-09). Rijvolgorde: eerste geplande dag,
 * aantal geplande dagen (aflopend), projectnummer (dagEerst.matrixRijen). Een cel zónder kaart = lege plancel "+ plannen" voor
 * dát project op dié dag (klik = paneel mét de ploeg van de dichtstbijzijnde eerdere dag als voorstel, niets opgeslagen) én
 * drop-doel voor een projecttegel. Onderaan een drop-rij "sleep een project hierheen" voor een NIEUWE rij (of klik project,
 * dan dag). Kaartinhoud ongewijzigd (initialen, urenstatus-stip, werkopdracht, chips, handvat); het handvat vult cellen op
 * dezelfde rij. VERVALLEN in v4: slepen van personen (pool → kaart, initiaal → kaart) — klik op élke kaart (ook een
 * gereserveerde) opent het ploeg-paneel; dat is dé werkwijze. Teal = actie, groen = status, oranje = conflict. */

export type SleepSoort = 'project'

export interface KaartDropPayload {
  soort: SleepSoort
  projectId: string
}

/** v4: alleen projecttegels zijn nog sleepbaar; een persoon-payload (oude pool/kaart-vorm) wordt genegeerd. */
export function ontleedDropPayload(payload: { soort: string; id: string } | null): KaartDropPayload | null {
  if (!payload) return null
  if (payload.soort === 'project') return { soort: 'project', projectId: payload.id }
  return null
}

export interface DagEerstGridProps {
  data: PlanningWeekDto
  /** Dagkolommen ZONDER urenfilter (de matrix filtert rijen, niet cellen). */
  kolommen: DagKolom[]
  urenFilter: UrenFilter
  /** Werkdagen (ma–vr) — het handvat stopt bij vrijdag; za/zo-kolommen staan alleen in `kolommen` als ze iets dragen. */
  werkdagen: string[]
  vandaagIso: string
  geselecteerd: string | null
  oplichten: string | null
  projectSelectie: string | null
  onSelecteer: (kaart: DagKaart | null) => void
  /** Lege cel geklikt: paneel openen voor project × dag (voorstel-ploeg, niets opgeslagen). */
  onLegeCel: (projectId: string, datum: string) => void
  onDagKlik: (datum: string) => void
  onDropOpDag: (datum: string, payload: KaartDropPayload) => void
  onVerwijderPersoon: (kaart: DagKaart, persoon: PlanningKaartDto) => void
  onDagdeel: (kaart: DagKaart, persoon: PlanningKaartDto) => void
  onVerwijderReservering: (kaart: DagKaart) => void
  onWerkopdracht: (kaart: DagKaart) => void
  onHandvatLoslaten: (kaart: DagKaart, doelDatums: string[], voorbeeld: VulhandvatVoorbeeld) => void
  onOpenWeekstaat: (persoon: PlanningKaartDto) => void
  /** Run B punt 24 (02-10): vrachtwagen-icoon geklikt → Transport-tab op die dag. */
  onTransportKlik: (datum: string) => void
}

export function DagEerstGrid(p: DagEerstGridProps) {
  const [handvat, setHandvat] = useState<{ kaart: DagKaart; tot: string } | null>(null)
  const [weekend, setWeekend] = useState(false)
  const tabelRef = useRef<HTMLTableElement>(null)

  const { dragOverDag, dagDropProps } = useDagDrop<HTMLTableCellElement>((datum, payload) => {
    const ontleed = ontleedDropPayload(payload)
    if (ontleed) p.onDropOpDag(datum, ontleed)
  }, 'copy')

  // Vulhandvat: pointerup ergens = loslaten; Escape = afbreken.
  useEffect(() => {
    if (!handvat) return
    const los = () => {
      const bereik = handvatBereik(p.werkdagen, handvat.kaart.datum, handvat.tot).filter((d) => d !== handvat.kaart.datum)
      setHandvat(null)
      if (bereik.length > 0) p.onHandvatLoslaten(handvat.kaart, bereik, vulhandvatVoorbeeld(p.data, handvat.kaart, bereik))
    }
    const toets = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setHandvat(null)
    }
    window.addEventListener('pointerup', los)
    window.addEventListener('keydown', toets)
    return () => {
      window.removeEventListener('pointerup', los)
      window.removeEventListener('keydown', toets)
    }
  }, [handvat, p])

  // Deeplink/conflictenpaneel: de opgelichte kaart in beeld scrollen.
  useEffect(() => {
    if (!p.oplichten || !tabelRef.current) return
    const el = tabelRef.current.querySelector<HTMLElement>(`[data-kaart="${p.oplichten}"]`)
    el?.scrollIntoView?.({ block: 'center', behavior: 'smooth' })
  }, [p.oplichten])

  const voorbeeld: VulhandvatVoorbeeld | null = handvat
    ? vulhandvatVoorbeeld(p.data, handvat.kaart, handvatBereik(p.werkdagen, handvat.kaart.datum, handvat.tot))
    : null

  const weekendKolommen = p.kolommen.filter((k) => !p.werkdagen.includes(k.datum))
  const weekendMetInhoud = weekendKolommen.filter((k) => k.kaarten.length > 0)
  const getoond = p.kolommen.filter((k) => p.werkdagen.includes(k.datum) || (weekend && k.kaarten.length > 0))
  const rijen = matrixRijen(getoond, { urenFilter: p.urenFilter })
  const dossierOnvolledig = new Set(p.data.pool.filter((x) => x.dossier_onvolledig).map((x) => x.gebruiker_id))
  // Run B punt 24: transporten (Transport-tab, status ≠ geannuleerd) per project × dag → icoon op de kaart.
  const transporten = transportenPerCel(p.data)

  function celKlik(e: MouseEvent<HTMLTableCellElement>, datum: string) {
    // Klik op de lege ruimte van een cel (niet op een kaart): mét een geselecteerd project = reserveren (klik-alternatief).
    if (e.target === e.currentTarget || (e.target as HTMLElement).classList.contains('plan-drop')) p.onDagKlik(datum)
  }

  function celProps(datum: string, extraKlasse = '') {
    return {
      'data-datum': datum,
      className: `plan-dagkolom plan-cel-mx${extraKlasse}${datum === p.vandaagIso ? ' plan-vandaag' : ''}${dragOverDag === datum ? ' plan-dragover' : ''}${p.projectSelectie ? ' plan-kiesbaar' : ''}`,
      title: p.projectSelectie ? 'Klik om het geselecteerde project hier te reserveren' : undefined,
      onClick: (e: MouseEvent<HTMLTableCellElement>) => celKlik(e, datum),
      onPointerEnter: () => {
        if (handvat && p.werkdagen.includes(datum)) setHandvat({ ...handvat, tot: datum })
      },
      ...dagDropProps(datum),
    }
  }

  return (
    <>
      {weekendMetInhoud.length > 0 && (
        <div style={{ padding: '6px 12px', fontSize: 11.5 }}>
          <button type="button" className="linkbtn" onClick={() => setWeekend((w) => !w)} data-testid="weekend-toggle">
            {weekend ? 'Weekend verbergen' : `Weekend tonen (${weekendMetInhoud.reduce((s, k) => s + k.kaarten.length, 0)} kaarten op za/zo)`}
          </button>
        </div>
      )}
      <div className="tabel-scroll sticky-koppen plan-scroll" data-testid="plan-grid-scroll">
        <table ref={tabelRef} className={`plan-grid plan-dagen plan-matrix${handvat ? ' plan-handvat-actief' : ''}`} style={{ tableLayout: 'fixed', minWidth: 800 }}>
          <colgroup>
            <col style={{ width: 124 }} />
            {getoond.map((k) => (
              <col key={k.datum} />
            ))}
          </colgroup>
          <thead>
            <tr>
              <th style={{ textAlign: 'left' }} className="plan-rijkop-kop">
                <span style={{ textTransform: 'uppercase', letterSpacing: '.04em', fontSize: 11, color: 'var(--muted)' }}>Project</span>
                <span style={{ display: 'block', fontSize: 12, fontWeight: 700, textTransform: 'none', letterSpacing: 0 }} data-testid="matrix-rijen-telling">
                  {rijen.length} {rijen.length === 1 ? 'rij' : 'rijen'}
                </span>
              </th>
              {getoond.map((k) => (
                <th key={k.datum} className={k.datum === p.vandaagIso ? 'plan-vandaag' : undefined} style={{ textAlign: 'left' }} data-testid={`dagkop-${k.datum}`}>
                  <span style={{ textTransform: 'uppercase', letterSpacing: '.04em', fontSize: 11, color: 'var(--muted)' }}>
                    {dagKort(k.datum)}
                    {k.datum === p.vandaagIso ? ' · vandaag' : ''}
                  </span>
                  <span style={{ display: 'block', fontSize: 12, fontWeight: 700, textTransform: 'none', letterSpacing: 0 }} data-testid={`dagtotaal-${k.datum}`}>
                    {k.aantal_projecten === 0 ? '—' : `${k.aantal_man} man · ${k.aantal_projecten} ${k.aantal_projecten === 1 ? 'project' : 'projecten'}`}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rijen.map((rij) => (
              <tr
                key={rij.project_id}
                data-testid={`matrix-rij-${rij.project_id}`}
                // Run B punt 25 (02-10): stabiele accentkleur per projectrij (hash projectnummer → --projectkleur-N) als CSS-variabele
                // voor rijkop én kaarten in deze rij.
                data-projectkleur={projectKleurIndex(rij.project_naam)}
                style={{ '--pk': projectKleurVar(rij.project_naam) } as CSSProperties}
              >
                <th className="plan-rijkop" scope="row">
                  <span className="plan-rijkop-naam" title={rij.project_naam ?? rij.project_id}>
                    <ProjectNaam naam={rij.project_naam ?? rij.project_id} />
                  </span>
                  <span className="plan-rijkop-sub">
                    {rij.opdrachtgever ? `${rij.opdrachtgever} · ` : ''}
                    {rij.aantal_dagen} {rij.aantal_dagen === 1 ? 'dag' : 'dagen'}
                  </span>
                </th>
                {rij.cellen.map((cel) => {
                  const ghost = handvat?.kaart.project_id === rij.project_id ? voorbeeld?.doelen.find((d) => d.datum === cel.datum) : undefined
                  return (
                    <td key={cel.datum} data-testid={`cel-${rij.project_id}|${cel.datum}`} {...celProps(cel.datum)}>
                      {cel.kaart && (
                        <KaartView
                          kaart={cel.kaart}
                          geselecteerd={p.geselecteerd === cel.kaart.sleutel}
                          oplichten={p.oplichten === cel.kaart.sleutel}
                          handvatActief={handvat?.kaart.sleutel === cel.kaart.sleutel}
                          dossierOnvolledig={dossierOnvolledig}
                          transporten={transporten.get(cel.kaart.sleutel) ?? []}
                          onTransportKlik={() => p.onTransportKlik(cel.datum)}
                          onSelecteer={() => p.onSelecteer(p.geselecteerd === cel.kaart!.sleutel ? null : cel.kaart)}
                          onVerwijderPersoon={(persoon) => p.onVerwijderPersoon(cel.kaart!, persoon)}
                          onDagdeel={(persoon) => p.onDagdeel(cel.kaart!, persoon)}
                          onVerwijderReservering={() => p.onVerwijderReservering(cel.kaart!)}
                          onWerkopdracht={() => p.onWerkopdracht(cel.kaart!)}
                          onOpenWeekstaat={p.onOpenWeekstaat}
                          onHandvatStart={() => setHandvat({ kaart: cel.kaart!, tot: cel.kaart!.datum })}
                        />
                      )}
                      {ghost && !ghost.overgeslagen && ghost.items.length > 0 && (
                        <div className="plan-kaart ghost" data-testid={`ghost-${cel.datum}`} aria-hidden>
                          <div className="n">{handvat?.kaart.project_naam}</div>
                          <div className="s">kopie · {ghost.conflicten > 0 ? `${ghost.conflicten} conflict` : 'zelfde ploeg'}</div>
                          <div className="ploeg">
                            {ghost.items.map((i) => (
                              <span key={i.gebruiker_id} className={`plan-av${i.conflict ? ' c' : ''}`} title={i.conflict ? `${i.naam ?? '?'}: ${i.conflict === 'afwezig' ? 'afwezig' : `al gepland (${i.conflict_projectnaam ?? '?'})`}` : i.naam ?? undefined}>
                                {initialen(i.naam)}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                      {ghost?.overgeslagen && (
                        <div className="plan-kaart ghost overgeslagen" data-testid={`ghost-overgeslagen-${cel.datum}`} aria-hidden>
                          <div className="s">overgeslagen — staat hier al</div>
                        </div>
                      )}
                      {!cel.kaart && !ghost && (
                        <button
                          type="button"
                          // Run B punt 25: een lege plancel is visueel rustiger dan een geplande kaart — alleen een "+", de tekst pas bij hover/focus.
                          className={`plan-leegcel${p.geselecteerd === `${rij.project_id}|${cel.datum}` ? ' sel' : ''}`}
                          data-testid={`leegcel-${rij.project_id}|${cel.datum}`}
                          aria-label={`${rij.project_naam ?? rij.project_id} op ${dagKort(cel.datum)} plannen`}
                          title={p.projectSelectie ? 'Klik om het geselecteerde project hier te reserveren' : `${rij.project_naam ?? ''} op ${dagKort(cel.datum)} plannen — opent het ploeg-paneel mét de ploeg van de vorige dag als voorstel`}
                          onClick={(e) => {
                            e.stopPropagation()
                            if (p.projectSelectie) p.onDagKlik(cel.datum)
                            else p.onLegeCel(rij.project_id, cel.datum)
                          }}
                        >
                          <span className="plan-leegcel-plus" aria-hidden>
                            +
                          </span>
                          <span className="plan-leegcel-tekst">sleep hierheen / + plannen</span>
                        </button>
                      )}
                    </td>
                  )
                })}
              </tr>
            ))}
            {/* Drop-rij voor een NIEUW project (projecttegel → dag, of klik project, dan dag). */}
            <tr className="plan-droprij" data-testid="matrix-droprij">
              <th className="plan-rijkop" scope="row">
                <span className="plan-rijkop-sub" style={{ display: 'block' }}>
                  {rijen.length === 0 ? 'Nog niets gepland deze week' : 'Nieuw project'}
                </span>
              </th>
              {getoond.map((k) => (
                <td key={k.datum} data-testid={`dag-${k.datum}`} {...celProps(k.datum, ' plan-cel-drop')}>
                  <div className="plan-drop" aria-hidden={!p.projectSelectie}>
                    {p.projectSelectie ? 'klik = hier reserveren' : rijen.length === 0 ? 'sleep een project hierheen (of klik project, dan dag)' : 'sleep project hierheen'}
                  </div>
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
    </>
  )
}

function KaartView({
  kaart,
  geselecteerd,
  oplichten,
  handvatActief,
  dossierOnvolledig,
  transporten,
  onTransportKlik,
  onSelecteer,
  onVerwijderPersoon,
  onDagdeel,
  onVerwijderReservering,
  onWerkopdracht,
  onOpenWeekstaat,
  onHandvatStart,
}: {
  kaart: DagKaart
  geselecteerd: boolean
  oplichten: boolean
  handvatActief: boolean
  dossierOnvolledig: Set<string>
  transporten: PlanningTransportKortDto[]
  onTransportKlik: () => void
  onSelecteer: () => void
  onVerwijderPersoon: (persoon: PlanningKaartDto) => void
  onDagdeel: (persoon: PlanningKaartDto) => void
  onVerwijderReservering: () => void
  onWerkopdracht: () => void
  onOpenWeekstaat: (persoon: PlanningKaartDto) => void
  onHandvatStart: () => void
}) {
  const conflictPersonen = new Set(kaart.conflicten.map((c) => c.gebruiker_id).filter(Boolean))
  const heeftConflict = kaart.conflicten.length > 0
  const klasse = [
    'plan-kaart',
    kaart.gereserveerd ? 'leeg' : '',
    geselecteerd ? 'sel' : '',
    oplichten ? 'oplichten' : '',
    heeftConflict ? 'conflict' : '',
    kaart.na_einddatum ? 'na-einddatum' : '',
  ]
    .filter(Boolean)
    .join(' ')
  return (
    <div
      className={klasse}
      data-kaart={kaart.sleutel}
      data-testid={`kaart-${kaart.sleutel}`}
      role="button"
      tabIndex={0}
      aria-pressed={geselecteerd}
      aria-label={`${kaart.project_naam ?? kaart.project_id} ${dagKort(kaart.datum)}${kaart.gereserveerd ? ' gereserveerd' : ` · ${kaart.ploeg.length} man`}`}
      title={kaart.na_einddatum ? 'Gepland ná de einddatum van het project (zacht signaal, geen blokkade)' : 'Klik = ploeg kiezen (paneel rechts)'}
      onClick={(e) => {
        e.stopPropagation()
        onSelecteer()
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onSelecteer()
        }
      }}
    >
      <div className="n">
        <ProjectNaam naam={kaart.project_naam ?? kaart.project_id} />
        {transporten.length > 0 && (
          <button
            type="button"
            className="plan-transport-icoon"
            data-testid="kaart-transport"
            title={transportTooltip(transporten)}
            aria-label={`${transportTooltip(transporten)} — open de Transport-tab op ${dagKort(kaart.datum)}`}
            onClick={(e) => {
              e.stopPropagation()
              onTransportKlik()
            }}
          >
            <TransportIcoon />
          </button>
        )}
        {!kaart.gereserveerd && (
          <span className="plan-aantal" data-testid="kaart-aantal">
            {kaart.ploeg.length}
          </span>
        )}
      </div>
      <div className="s">
        {kaart.gereserveerd ? (
          <>
            <em className="plan-chip grijs">gereserveerd · nog geen ploeg</em>
            <button
              type="button"
              className="linkbtn"
              style={{ fontSize: 10.5, marginLeft: 6 }}
              aria-label={`Reservering ${kaart.project_naam ?? ''} ${dagKort(kaart.datum)} verwijderen`}
              onClick={(e) => {
                e.stopPropagation()
                onVerwijderReservering()
              }}
            >
              ✕
            </button>
          </>
        ) : (
          [kaart.opdrachtgever, kaart.werkopdracht_tekst ? `${kaart.werkopdracht_afwijkend ? '📋 afwijkend: ' : ''}${kaart.werkopdracht_tekst}` : null].filter(Boolean).join(' · ') || kaart.soort_werk || ''
        )}
      </div>
      {!kaart.gereserveerd && (
        <div className="ploeg" role="list" aria-label="Ploeg">
          {kaart.ploeg.map((persoon) => {
            const conflict = conflictPersonen.has(persoon.gebruiker_id)
            const dossier = dossierOnvolledig.has(persoon.gebruiker_id)
            return (
              <span
                key={persoon.gebruiker_id}
                role="listitem"
                className={`plan-av${persoon.rol === 'uitvoerder' ? ' u' : ''}${conflict ? ' c' : ''}${dossier ? ' d' : ''}`}
                data-testid={`initiaal-${persoon.gebruiker_id}`}
                title={`${persoon.naam ?? '?'}${persoon.rol === 'uitvoerder' ? ' (uitvoerder)' : ''} · ${persoon.uren_detail ?? UREN_STATUS_LABEL[persoon.uren_status ?? 'geen']}${persoon.dagdeel === 'half' ? ' · ½ dag' : ''}${conflict ? ' · conflict' : ''}${dossier ? ' · dossier onvolledig' : ''} — klik de kaart voor de ploeg`}
              >
                {initialen(persoon.naam)}
                {persoon.dagdeel === 'half' && <sup>½</sup>}
              </span>
            )
          })}
        </div>
      )}
      {!kaart.gereserveerd && (
        <div className="meta">
          <button
            type="button"
            className="linkbtn"
            data-testid="uren-status"
            data-status={kaart.status}
            title={kaart.ploeg.map((k) => `${k.naam ?? '?'}: ${k.uren_detail ?? urenKort(k)}`).join('\n')}
            aria-label={`Urenstatus ${kaart.project_naam ?? ''} ${dagKort(kaart.datum)}: ${UREN_STATUS_LABEL[kaart.status]}`}
            onClick={(e) => {
              e.stopPropagation()
              const met = kaart.ploeg.find((k) => k.weekstaat_id)
              if (met) onOpenWeekstaat(met)
            }}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 10.5, color: 'var(--muted)' }}
          >
            <span aria-hidden style={{ width: 7, height: 7, borderRadius: 99, background: UREN_STATUS_KLEUR[kaart.status], flexShrink: 0 }} />
            {kaart.status === 'geen'
              ? 'geen uren'
              : `uren ${kaart.ploeg.filter((k) => (k.uren_status ?? 'geen') !== 'geen').length}/${kaart.ploeg.length}${kaart.status === 'gekeurd' ? ' · gekeurd' : kaart.status === 'vraag' ? ' · afgekeurd/vraag' : ''}`}
          </button>
          {heeftConflict && (
            <span className="plan-chip warn" title={kaart.conflicten.map((c) => c.tekst).join('\n')} data-testid="kaart-conflict">
              conflict{kaart.conflicten.length > 1 ? ` ×${kaart.conflicten.length}` : ''}
            </span>
          )}
          {kaart.achteraf && (
            <span data-testid="achteraf-chip" title="Achteraf gepland: ná de dag zelf in de planning gezet (audit + melding aan de veldwerker)" className="plan-chip purple">
              achteraf
            </span>
          )}
          {kaart.na_einddatum && (
            <span aria-label="ná projecteinddatum" style={{ color: 'var(--warn)', fontWeight: 700 }}>
              ⚠
            </span>
          )}
          <button
            type="button"
            className="linkbtn"
            title="Werkopdracht (periode/dag-override)"
            aria-label={`Werkopdracht ${kaart.project_naam ?? ''} ${dagKort(kaart.datum)}`}
            style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--purple)' }}
            onClick={(e) => {
              e.stopPropagation()
              onWerkopdracht()
            }}
          >
            📋
          </button>
        </div>
      )}
      {geselecteerd && !kaart.gereserveerd && (
        <div className="plan-kaart-acties">
          {kaart.ploeg.map((persoon) => (
            <span key={persoon.gebruiker_id} className="plan-kaart-actie">
              <span>{persoon.naam ?? '?'}</span>
              <button
                type="button"
                className="linkbtn"
                title={persoon.dagdeel === 'half' ? 'Nu ½ dag — maak hele dag' : 'Hele dag — maak ½ dag'}
                onClick={(e) => {
                  e.stopPropagation()
                  onDagdeel(persoon)
                }}
              >
                {persoon.dagdeel === 'half' ? '½' : '1'}
              </button>
              <button
                type="button"
                className="linkbtn"
                title="Uit de planning halen"
                aria-label={`${persoon.naam ?? 'persoon'} uit de planning halen`}
                onClick={(e) => {
                  e.stopPropagation()
                  onVerwijderPersoon(persoon)
                }}
              >
                ✕
              </button>
            </span>
          ))}
        </div>
      )}
      {geselecteerd && !kaart.gereserveerd && kaart.ploeg.length > 0 && (
        <span
          className={`plan-handvat${handvatActief ? ' actief' : ''}`}
          role="button"
          tabIndex={0}
          aria-label="Vulhandvat: sleep over de dagen om kaart en ploeg te kopiëren"
          title="Sleep over de dagen om kaart + ploeg te kopiëren op dezelfde rij (Excel-vulhandvat; stopt bij vrijdag)"
          data-testid="handvat"
          onPointerDown={(e) => {
            e.preventDefault()
            e.stopPropagation()
            onHandvatStart()
          }}
          onClick={(e) => e.stopPropagation()}
        />
      )}
    </div>
  )
}

/** Run B punt 25: projectnummer vetter (en in de projectkleur) dan de rest van de naam — "25147" springt eruit, "Hoofddorp (Grunsven)"
 * blijft gewoon leesbaar. Zonder cijferprefix gewoon de naam. */
function ProjectNaam({ naam }: { naam: string }) {
  const { voorvoegsel, nummer, rest } = splitsProjectnummer(naam)
  if (!nummer) return <>{naam}</>
  return (
    <>
      {voorvoegsel}
      <b className="plan-nr">{nummer}</b>
      {rest}
    </>
  )
}

/** Vrachtwagen (inline SVG, zoals de overige shell-iconen — geen nieuwe dependency); kleur volgt `currentColor`. */
function TransportIcoon() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden focusable="false" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M1.5 6.5h11v9h-11z" />
      <path d="M12.5 9.5h4.2l3.3 3.3v2.7h-7.5" />
      <circle cx="5.5" cy="17.5" r="1.8" />
      <circle cx="17.5" cy="17.5" r="1.8" />
    </svg>
  )
}
