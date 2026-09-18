import { useEffect, useRef, useState } from 'react'
import { dagKort, handvatBereik, initialen, vulhandvatVoorbeeld, type DagKaart, type DagKolom, type VulhandvatVoorbeeld } from './dagEerst'
import { UREN_STATUS_KLEUR, UREN_STATUS_LABEL, urenKort, type PlanningKaartDto, type PlanningWeekDto } from './planningApi'
import { maakSleepPayload, useDagDrop } from './useDagDrop'

/* Weekgrid dag-eerst (mockup planning-v3-dag-eerst.html ①/②, akkoord Peter 18-09): vijf dagkolommen (za/zo alleen als er
 * iets op staat, inklapbaar), sticky dagkop mét datum + dagtotaal (hergebruik .tabel-scroll.sticky-koppen.plan-scroll van
 * 18-09), per dag projectkaarten mét ploeg-initialen (uitvoerder = groene rand, conflict = oranje rand), aantal,
 * urenstatus-stip = laagste status van de ploeg (tooltip per persoon), werkopdracht-tekst, chip "achteraf", kaart zonder
 * ploeg = "gereserveerd" (grijs, dashed). Slepen: projecttegel → dag = reservering; pool → kaart = toevoegen; initiaal →
 * andere kaart = verplaatsen (Alt/Option = kopiëren). Vulhandvat (②): kaart selecteren → bolletje rechts → over dagen
 * slepen (pointer-events; ghost-kaarten mét conflicten oranje; bestaande kaart van hetzelfde project = overgeslagen; stopt bij
 * vrijdag). Teal = actie (handvat, drop-zones), groen = status, oranje = conflict. */

export type SleepSoort = 'pool' | 'kaart' | 'project'

export interface KaartDropPayload {
  soort: SleepSoort
  gebruikerId: string | null
  projectId: string | null
  datum: string | null
  /** Alt/Option ingedrukt bij het loslaten = kopiëren i.p.v. verplaatsen. */
  kopieer: boolean
}

export function kaartSleepPayload(gebruikerId: string, projectId: string, datum: string): string {
  return maakSleepPayload('kaart', `${gebruikerId}|${projectId}|${datum}`)
}

export function ontleedDropPayload(payload: { soort: string; id: string } | null, kopieer: boolean): KaartDropPayload | null {
  if (!payload) return null
  if (payload.soort === 'pool') return { soort: 'pool', gebruikerId: payload.id, projectId: null, datum: null, kopieer }
  if (payload.soort === 'project') return { soort: 'project', gebruikerId: null, projectId: payload.id, datum: null, kopieer }
  if (payload.soort === 'kaart') {
    const [gebruikerId, projectId, datum] = payload.id.split('|')
    return { soort: 'kaart', gebruikerId, projectId, datum, kopieer }
  }
  return null
}

export interface DagEerstGridProps {
  data: PlanningWeekDto
  kolommen: DagKolom[]
  /** Werkdagen (ma–vr) — het handvat stopt bij vrijdag; za/zo-kolommen staan alleen in `kolommen` als ze iets dragen. */
  werkdagen: string[]
  vandaagIso: string
  geselecteerd: string | null
  oplichten: string | null
  projectSelectie: string | null
  onSelecteer: (kaart: DagKaart | null) => void
  onDagKlik: (datum: string) => void
  onDropOpDag: (datum: string, payload: KaartDropPayload) => void
  onDropOpKaart: (kaart: DagKaart, payload: KaartDropPayload) => void
  onVerwijderPersoon: (kaart: DagKaart, persoon: PlanningKaartDto) => void
  onDagdeel: (kaart: DagKaart, persoon: PlanningKaartDto) => void
  onVerwijderReservering: (kaart: DagKaart) => void
  onWerkopdracht: (kaart: DagKaart) => void
  onHandvatLoslaten: (kaart: DagKaart, doelDatums: string[], voorbeeld: VulhandvatVoorbeeld) => void
  onOpenWeekstaat: (persoon: PlanningKaartDto) => void
}

export function DagEerstGrid(p: DagEerstGridProps) {
  const [handvat, setHandvat] = useState<{ kaart: DagKaart; tot: string } | null>(null)
  const [weekend, setWeekend] = useState(false)
  const tabelRef = useRef<HTMLTableElement>(null)
  const [altKey, setAltKey] = useState(false)

  const { dragOverDag, dagDropProps } = useDagDrop<HTMLTableCellElement>(
    (datum, payload, e) => {
      const ontleed = ontleedDropPayload(payload, e.altKey)
      if (ontleed) p.onDropOpDag(datum, ontleed)
    },
    (e) => (e.altKey ? 'copy' : 'move'),
  )

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

  // Deeplink/conflictenbalk: de opgelichte kaart in beeld scrollen.
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
        <table
          ref={tabelRef}
          className={`plan-grid plan-dagen${handvat ? ' plan-handvat-actief' : ''}`}
          style={{ tableLayout: 'fixed', minWidth: 760 }}
          onKeyDown={(e) => setAltKey(e.altKey)}
          onKeyUp={(e) => setAltKey(e.altKey)}
          onDragOver={(e) => setAltKey(e.altKey)}
        >
          <thead>
            <tr>
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
            <tr>
              {getoond.map((k) => {
                const ghost = voorbeeld?.doelen.find((d) => d.datum === k.datum)
                return (
                  <td
                    key={k.datum}
                    data-datum={k.datum}
                    data-testid={`dag-${k.datum}`}
                    className={`plan-dagkolom${k.datum === p.vandaagIso ? ' plan-vandaag' : ''}${dragOverDag === k.datum ? ' plan-dragover' : ''}${p.projectSelectie ? ' plan-kiesbaar' : ''}`}
                    title={p.projectSelectie ? 'Klik om het geselecteerde project hier te reserveren' : undefined}
                    onClick={(e) => {
                      if (e.target === e.currentTarget || (e.target as HTMLElement).classList.contains('plan-drop')) p.onDagKlik(k.datum)
                    }}
                    onPointerEnter={() => {
                      if (handvat && p.werkdagen.includes(k.datum)) setHandvat({ ...handvat, tot: k.datum })
                    }}
                    {...dagDropProps(k.datum)}
                  >
                    {k.kaarten.map((kaart) => (
                      <KaartView
                        key={kaart.sleutel}
                        kaart={kaart}
                        geselecteerd={p.geselecteerd === kaart.sleutel}
                        oplichten={p.oplichten === kaart.sleutel}
                        handvatActief={handvat?.kaart.sleutel === kaart.sleutel}
                        altKey={altKey}
                        onSelecteer={() => p.onSelecteer(p.geselecteerd === kaart.sleutel ? null : kaart)}
                        onDrop={(payload) => p.onDropOpKaart(kaart, payload)}
                        onVerwijderPersoon={(persoon) => p.onVerwijderPersoon(kaart, persoon)}
                        onDagdeel={(persoon) => p.onDagdeel(kaart, persoon)}
                        onVerwijderReservering={() => p.onVerwijderReservering(kaart)}
                        onWerkopdracht={() => p.onWerkopdracht(kaart)}
                        onOpenWeekstaat={p.onOpenWeekstaat}
                        onHandvatStart={() => setHandvat({ kaart, tot: kaart.datum })}
                      />
                    ))}
                    {ghost && !ghost.overgeslagen && ghost.items.length > 0 && (
                      <div className="plan-kaart ghost" data-testid={`ghost-${k.datum}`} aria-hidden>
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
                      <div className="plan-kaart ghost overgeslagen" data-testid={`ghost-overgeslagen-${k.datum}`} aria-hidden>
                        <div className="s">overgeslagen — staat hier al</div>
                      </div>
                    )}
                    <div className="plan-drop" aria-hidden={!p.projectSelectie}>
                      {k.kaarten.length === 0 ? 'sleep project of persoon hierheen' : 'sleep hierheen'}
                    </div>
                  </td>
                )
              })}
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
  altKey,
  onSelecteer,
  onDrop,
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
  altKey: boolean
  onSelecteer: () => void
  onDrop: (payload: KaartDropPayload) => void
  onVerwijderPersoon: (persoon: PlanningKaartDto) => void
  onDagdeel: (persoon: PlanningKaartDto) => void
  onVerwijderReservering: () => void
  onWerkopdracht: () => void
  onOpenWeekstaat: (persoon: PlanningKaartDto) => void
  onHandvatStart: () => void
}) {
  const [over, setOver] = useState(false)
  const conflictPersonen = new Set(kaart.conflicten.map((c) => c.gebruiker_id).filter(Boolean))
  const heeftConflict = kaart.conflicten.length > 0
  const klasse = [
    'plan-kaart',
    kaart.gereserveerd ? 'leeg' : '',
    geselecteerd ? 'sel' : '',
    oplichten ? 'oplichten' : '',
    heeftConflict ? 'conflict' : '',
    kaart.na_einddatum ? 'na-einddatum' : '',
    over ? 'over' : '',
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
      onDragEnter={(e) => {
        e.preventDefault()
        e.stopPropagation()
        setOver(true)
      }}
      onDragOver={(e) => {
        e.preventDefault()
        e.stopPropagation()
        e.dataTransfer.dropEffect = e.altKey ? 'copy' : 'move'
        setOver(true)
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOver(false)
      }}
      onDrop={(e) => {
        e.preventDefault()
        e.stopPropagation()
        setOver(false)
        const raw = e.dataTransfer.getData('text/plain')
        const i = raw.indexOf(':')
        const ontleed = ontleedDropPayload(i > 0 ? { soort: raw.slice(0, i), id: raw.slice(i + 1) } : null, e.altKey)
        if (ontleed) onDrop(ontleed)
      }}
    >
      <div className="n">
        {kaart.project_naam ?? kaart.project_id}
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
            return (
              <span
                key={persoon.gebruiker_id}
                role="listitem"
                draggable
                className={`plan-av${persoon.rol === 'uitvoerder' ? ' u' : ''}${conflict ? ' c' : ''}`}
                data-testid={`initiaal-${persoon.gebruiker_id}`}
                title={`${persoon.naam ?? '?'}${persoon.rol === 'uitvoerder' ? ' (uitvoerder)' : ''} · ${persoon.uren_detail ?? UREN_STATUS_LABEL[persoon.uren_status ?? 'geen']}${persoon.dagdeel === 'half' ? ' · ½ dag' : ''}${conflict ? ' · conflict' : ''} — sleep naar een andere kaart = verplaatsen (Alt = kopiëren)`}
                onDragStart={(e) => {
                  e.stopPropagation()
                  e.dataTransfer.effectAllowed = 'copyMove'
                  e.dataTransfer.setData('text/plain', kaartSleepPayload(persoon.gebruiker_id, kaart.project_id, kaart.datum))
                }}
                onClick={(e) => e.stopPropagation()}
              >
                {initialen(persoon.naam)}
                {persoon.dagdeel === 'half' && <sup>½</sup>}
              </span>
            )
          })}
          {altKey && <span className="plan-chip grijs">Alt = kopiëren</span>}
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
          title="Sleep over de dagen om kaart + ploeg te kopiëren (Excel-vulhandvat; stopt bij vrijdag)"
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
