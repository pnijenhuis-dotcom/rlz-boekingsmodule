import { useState } from 'react'
import { Button } from '../ui/basis'
import type { ProjectTegel } from './dagEerst'
import { maakSleepPayload } from './useDagDrop'

/* Projectbalk boven het grid (mockup v3 ①): álle actieve projecten, zoekbaar (diakriet-loos), gepland-deze-week eerst;
 * een tegel naar een dagkolom slepen = lege kaart ("gereserveerd"); klik-alternatief = tegel selecteren en dan de dag
 * aanklikken (DnD is nooit de enige weg). Horizontaal scrollbaar BINNEN de pagina, "+ N" opent de volledige lijst. */

export const PROJECTBALK_ZICHTBAAR = 12

export function ProjectBalk({
  tegels,
  zoek,
  onZoek,
  selectie,
  onSelecteer,
}: {
  tegels: ProjectTegel[]
  zoek: string
  onZoek: (z: string) => void
  selectie: string | null
  onSelecteer: (projectId: string | null) => void
}) {
  const [alles, setAlles] = useState(false)
  const zichtbaar = alles || zoek.trim() ? tegels : tegels.slice(0, PROJECTBALK_ZICHTBAAR)
  const rest = tegels.length - zichtbaar.length
  const gepland = tegels.filter((t) => t.gepland).length
  return (
    <div className="panel plan-pbalk" data-testid="projectbalk">
      <div className="plan-pbalk-rij">
        <b style={{ fontSize: 12.5 }}>Projecten</b>
        <span className="hint" style={{ margin: 0, fontSize: 11.5 }}>
          sleep een project naar een dag (of klik project, dan dag) · gepland deze week eerst
        </span>
        <input
          type="search"
          aria-label="Zoek project"
          placeholder="Zoek project… (nummer, plaats, opdrachtgever)"
          value={zoek}
          onChange={(e) => onZoek(e.target.value)}
          style={{ marginLeft: 'auto', minWidth: 240, fontSize: 12.5, padding: '6px 10px' }}
        />
        <span style={{ color: 'var(--faint)', fontSize: 11.5, whiteSpace: 'nowrap' }} data-testid="projectbalk-telling">
          {tegels.length} actieve projecten · {gepland} mét planning deze week
        </span>
      </div>
      <div className={`plan-pbalk-lijst${alles ? ' alles' : ''}`} role="list" aria-label="Projecttegels">
        {zichtbaar.length === 0 && (
          <p className="hint" style={{ margin: 0 }}>
            Geen project past bij &quot;{zoek.trim()}&quot; — pas de zoekterm aan.
          </p>
        )}
        {zichtbaar.map((t) => (
          <div
            key={t.project_id}
            role="listitem"
            draggable
            tabIndex={0}
            aria-pressed={selectie === t.project_id}
            data-testid={`projecttegel-${t.project_id}`}
            className={`plan-ptegel${t.gepland ? ' act' : ''}${selectie === t.project_id ? ' sel' : ''}`}
            title={selectie === t.project_id ? 'Geselecteerd — klik op een dag om te reserveren' : 'Sleep naar een dag, of klik en kies dan een dag'}
            onDragStart={(e) => {
              e.dataTransfer.effectAllowed = 'copy'
              e.dataTransfer.setData('text/plain', maakSleepPayload('project', t.project_id))
            }}
            onClick={() => onSelecteer(selectie === t.project_id ? null : t.project_id)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                onSelecteer(selectie === t.project_id ? null : t.project_id)
              }
            }}
          >
            <b>{t.project_naam ?? t.project_id}</b>
            <span>
              {t.opdrachtgever ? `${t.opdrachtgever} · ` : ''}
              {t.gepland ? t.samenvatting : <em className="plan-chip grijs">niet gepland</em>}
            </span>
          </div>
        ))}
        {rest > 0 && (
          <Button variant="secundair" maat="klein" className="plan-ptegel-meer" onClick={() => setAlles(true)} title="Alle projecten tonen">
            + {rest}
          </Button>
        )}
        {alles && tegels.length > PROJECTBALK_ZICHTBAAR && (
          <Button variant="secundair" maat="klein" className="plan-ptegel-meer" onClick={() => setAlles(false)}>
            minder
          </Button>
        )}
      </div>
    </div>
  )
}
