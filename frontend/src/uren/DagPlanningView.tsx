/** Planningstab van de UITVOERDER (Peter 02-10, run B punt 26 — herziet "geen planningstab" van 18-09 blok D uitsluitend voor
 * deze rol): "het tabje mijn uren moeten we vervangen door tabje planning. Hierin moet de uitvoerder een lijst zien van alle
 * geplande projecten van die dag (gaat dus mee met de agenda) en die moet met links swipen een dag terug kunnen kijken en met
 * rechts swipen in de toekomst kunnen kijken."
 *
 * - Leest de kantoorplanning LIVE (`GET /uren/uitvoerder/dagplanning?datum=`): project, opdrachtgever, plaats, ploeg,
 *   werkopdracht en een vrachtwagen-icoon als er op dat project die dag een transport gepland staat (Transport-tab,
 *   status ≠ geannuleerd). Alleen-lezen: plannen doet het kantoor (besluit B 22-08).
 * - Swipe links = dag terug, swipe rechts = dag vooruit (pointer-events, ≥ 40 px horizontaal, verticaal scrollen blijft
 *   van de browser); pijlknoppen ≥ 48 px en "vandaag" voor wie niet swipet.
 * - Tik op een project = de bestaande projectkaart (+ Uren / Meerwerk melden) — project-eerst (18-09).
 * - Offline: de laatst geladen stand van die dag uit localStorage mét chip "offline — stand van HH:MM"; geen stand = fout
 *   mét "Opnieuw proberen". Nooit stil leeg.
 * Dit bestand hoort bij de accordeur-chunk: geen kantoor-imports. */
import { useCallback, useEffect, useRef, useState } from 'react'
import { haalDagplanning, isoDatumVan, schuifDag, type DagPlanningProjectDto } from './urenApi'
import { isGeenVerbinding } from './urenOffline'

/** Minimale horizontale afstand (px) vóór een beweging als swipe telt — korter is een tik of een scroll. */
export const SWIPE_DREMPEL_PX = 40

const CACHE_PREFIX = 'uren-dagplanning:'

interface DagCache {
  op: string
  rijen: DagPlanningProjectDto[]
}

function leesCache(datum: string): DagCache | null {
  try {
    const ruw = localStorage.getItem(CACHE_PREFIX + datum)
    if (!ruw) return null
    const data = JSON.parse(ruw) as DagCache
    return Array.isArray(data.rijen) && typeof data.op === 'string' ? data : null
  } catch {
    return null
  }
}

function schrijfCache(datum: string, rijen: DagPlanningProjectDto[]): void {
  try {
    localStorage.setItem(CACHE_PREFIX + datum, JSON.stringify({ op: new Date().toISOString(), rijen } satisfies DagCache))
  } catch {
    // opslag vol/geblokkeerd: de live stand staat in beeld, de cache is een extra
  }
}

/** Richting van een swipe uit de pointer-verplaatsing: 'terug' (naar links), 'vooruit' (naar rechts) of null (tik/scroll). */
export function swipeRichting(dx: number, dy: number): 'terug' | 'vooruit' | null {
  if (Math.abs(dx) < SWIPE_DREMPEL_PX || Math.abs(dx) <= Math.abs(dy)) return null
  return dx < 0 ? 'terug' : 'vooruit'
}

/** "ma 5 okt" — dagkop in NL. */
export function dagKop(iso: string): string {
  const d = new Date(`${iso}T12:00:00`)
  return d.toLocaleDateString('nl-NL', { weekday: 'short', day: 'numeric', month: 'short' })
}

/** "transport gepland: 07:30 · levering" — tooltip/aria van het vrachtwagen-icoon. */
export function transportLabel(t: { soort: string; tijdstip: string | null }): string {
  const tijd = t.tijdstip ? t.tijdstip.slice(0, 5) : null
  return `transport gepland: ${[tijd, t.soort].filter(Boolean).join(' · ')}`
}

function Vrachtwagen({ label }: { label: string }) {
  return (
    <span className="acc-transport-icoon" role="img" aria-label={label} title={label} data-testid="transport-icoon">
      <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false">
        <path
          d="M2 6a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v9H2zM14 9h4.2a1 1 0 0 1 .8.4l2.6 3.4a1 1 0 0 1 .2.6V15h-7.8z"
          fill="currentColor"
        />
        <circle cx="6.5" cy="17.5" r="2" fill="var(--acc-panel, #fff)" stroke="currentColor" strokeWidth="1.6" />
        <circle cx="17.5" cy="17.5" r="2" fill="var(--acc-panel, #fff)" stroke="currentColor" strokeWidth="1.6" />
      </svg>
    </span>
  )
}

export interface DagPlanningProjectDoel {
  administratie_id: string
  project_id: string
  project_naam: string | null
}

export function DagPlanningView({
  startDatum,
  vangFout,
  openProject,
  openMijnUren,
}: {
  /** Begindag (deep-link `?planning=JJJJ-Wnn` → maandag van die week), anders vandaag. */
  startDatum?: string | null
  vangFout: (err: unknown) => string
  /** Tik op een project → de bestaande projectkaart (+ Uren / Meerwerk melden). */
  openProject: (doel: DagPlanningProjectDoel, datum: string) => void
  /** Weekoverzicht van de eigen uren (de oude "Mijn uren"-flow, nu één tik verder). */
  openMijnUren: () => void
}) {
  const vandaag = isoDatumVan(new Date())
  const [datum, setDatum] = useState(startDatum ?? vandaag)
  const [rijen, setRijen] = useState<DagPlanningProjectDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [offlineStand, setOfflineStand] = useState<string | null>(null)
  const start = useRef<{ x: number; y: number; id: number } | null>(null)

  const laad = useCallback(() => {
    setFout(null)
    setOfflineStand(null)
    setRijen(null)
    let actief = true
    haalDagplanning(datum)
      .then((data) => {
        if (!actief) return
        setRijen(data)
        schrijfCache(datum, data)
      })
      .catch((err) => {
        if (!actief) return
        const cache = isGeenVerbinding(err) ? leesCache(datum) : null
        if (cache) {
          // Offline: laatst geladen dag mét chip — de stand kan verouderd zijn, dat staat erbij.
          setRijen(cache.rijen)
          setOfflineStand(new Date(cache.op).toLocaleTimeString('nl-NL', { hour: '2-digit', minute: '2-digit' }))
          return
        }
        setFout(vangFout(err) || 'Planning kon niet geladen worden.')
      })
    return () => {
      actief = false
    }
  }, [datum, vangFout])
  useEffect(() => laad(), [laad])

  const schuif = (delta: number) => setDatum((d) => schuifDag(d, delta))

  // Swipe (Peter: links = dag terug, rechts = dag vooruit). Pointer-events zodat muis én touch werken; alleen de
  // horizontale beweging telt, verticaal scrollen blijft van de browser (touch-action: pan-y).
  const onPointerDown = (e: React.PointerEvent) => {
    start.current = { x: e.clientX, y: e.clientY, id: e.pointerId }
  }
  const onPointerUp = (e: React.PointerEvent) => {
    const s = start.current
    start.current = null
    if (!s || s.id !== e.pointerId) return
    const richting = swipeRichting(e.clientX - s.x, e.clientY - s.y)
    if (richting === 'terug') schuif(-1)
    if (richting === 'vooruit') schuif(1)
  }
  const onPointerCancel = () => {
    start.current = null
  }

  const isVandaag = datum === vandaag

  return (
    <div className="acc-dagplan" data-testid="dagplanning">
      <div className="acc-seclabel acc-dagplan-kop">
        <button
          type="button"
          className="acc-iconbtn acc-dagplan-nav"
          aria-label="Dag terug"
          data-testid="dag-terug"
          onClick={() => schuif(-1)}
        >
          ‹
        </button>
        <span className="acc-dagplan-datum" data-testid="dagplanning-datum">
          <b>{dagKop(datum)}</b>
          {isVandaag ? (
            <small> · vandaag</small>
          ) : (
            <button type="button" className="acc-tekstlink" data-testid="dag-vandaag" onClick={() => setDatum(vandaag)}>
              vandaag
            </button>
          )}
        </span>
        <button
          type="button"
          className="acc-iconbtn acc-dagplan-nav"
          aria-label="Dag vooruit"
          data-testid="dag-vooruit"
          onClick={() => schuif(1)}
        >
          ›
        </button>
      </div>
      {offlineStand && (
        <span className="acc-chip wacht acc-offline-chip" data-testid="chip-offline" role="status">
          ● offline — stand van {offlineStand}
        </span>
      )}
      <div
        className="acc-dagplan-lijst"
        data-testid="dagplanning-lijst"
        onPointerDown={onPointerDown}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerCancel}
      >
        {fout && (
          <div className="acc-afwijs">
            {fout}{' '}
            <button type="button" className="acc-tekstlink" onClick={laad}>
              Opnieuw proberen
            </button>
          </div>
        )}
        {rijen === null && !fout && <p className="acc-qcount">Laden…</p>}
        {rijen !== null && rijen.length === 0 && (
          <p className="acc-qcount" data-testid="dagplanning-leeg">
            Geen werk gepland op {dagKop(datum)} — het kantoor plant in de planning-agenda.
          </p>
        )}
        {(rijen ?? []).map((p) => (
          <button
            key={`${p.administratie_id}-${p.project_id}`}
            type="button"
            className="acc-card klik acc-dagplan-kaart"
            data-testid="dagplanning-project"
            onClick={() =>
              openProject({ administratie_id: p.administratie_id, project_id: p.project_id, project_naam: p.project_naam }, datum)
            }
          >
            <span className="acc-dagplan-inhoud">
              <span className="acc-tt">{p.project_naam ?? 'Project'}</span>
              <span className="acc-meta acc-dagplan-meta">
                {[p.opdrachtgever, p.plaats].filter(Boolean).join(' · ') || 'projectgegevens volgen'}
              </span>
              <span className="acc-meta acc-dagplan-ploeg" data-testid="dagplanning-ploeg">
                {p.gereserveerd
                  ? 'gereserveerd — ploeg volgt'
                  : p.ploeg.map((lid) => `${lid.naam ?? 'onbekend'}${lid.dagdeel === 'half' ? ' (½)' : ''}`).join(', ')}
              </span>
              {p.werkopdrachten.map((wo) => (
                <span key={wo.groep_id} className="acc-werkopdracht">
                  📋 {wo.afwijkend && <b>afwijkend: </b>}
                  {wo.tekst}
                </span>
              ))}
            </span>
            <span className="acc-dagplan-rechts">
              {p.transport && <Vrachtwagen label={transportLabel(p.transport)} />}
              <span className="acc-meta">{p.gereserveerd ? '—' : `${p.ploeg.length} man`}</span>
            </span>
          </button>
        ))}
      </div>
      <div className="acc-notitie">
        <span>🔒</span>
        <span>
          Alleen-lezen: plannen doet het kantoor. Tik op een project voor de projectkaart met "+ Uren" en "Meerwerk melden".
        </span>
      </div>
      <button type="button" className="acc-tekstlink acc-dagplan-mijnuren" data-testid="link-mijn-uren" onClick={openMijnUren}>
        ⏱ Mijn uren (weekoverzicht) ›
      </button>
    </div>
  )
}
