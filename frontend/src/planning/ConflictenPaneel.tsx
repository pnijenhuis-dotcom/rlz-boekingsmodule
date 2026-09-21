import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge, Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from '../ui/basis'
import { CONFLICT_SOORT_LABEL, type Conflict, type ConflictDagGroep } from './dagEerst'

/* Conflictenpaneel boven het grid (opdracht Peter 21-09 — vervángt de inline `linkbtn`-lap van de v3-balk, mockup-notitie
 * "Conflictenbalk" bijgewerkt): kop "N conflicten in week 39" (getoonde week; "deze week" alleen als dat de huidige is),
 * gegroepeerd per dag, per rij persoon · projecten · soort conflict · handeling. Alleen huidige + toekomstige dagen — een
 * verstreken dag is historie (zie "Per project"). Ingeklapt 3 rijen, uitgeklapt = tabel in `.tabel-scroll`, nooit een
 * inline lap tekst. Elk signaal draagt een actie (Kernprincipe 7.2): "Houd ‹A›" / "Houd ‹B›" = de andere kaart(en) weg via
 * de bulkroute (audit, ongedaan maken), "Beide (halve dagen)…" = bewust gehouden mét reden (rij verdwijnt tot de planning
 * wijzigt); afwezig: "Van planning halen" / "Tóch plannen…"; > 5: "Ploeg aanpassen" (paneel); dossier: "Dossier openen".
 * Nooit blokkerend — kantoor beslist. Oranje = conflict (designpass v2), teal = actie. */

export interface ConflictenPaneelProps {
  groepen: ConflictDagGroep[]
  /** "deze week" of "week 39" (conflictWeekLabel). */
  weekLabel: string
  /** Conflicten op verstreken dagen die het paneel bewust niet toont (wél in "Per project"). */
  verstrekenAantal: number
  projectNaam: (projectId: string) => string
  bezig?: boolean
  onSpring: (sleutel: string) => void
  /** Dubbel: houd dit project, de andere kaart(en) van die persoon-dag gaan weg (bulkroute, bron conflict). */
  onHoud: (conflict: Conflict, projectId: string) => void
  /** Afwezig: de kaart van die persoon-dag van de planning halen (bulkroute, bron conflict). */
  onVerwijder: (conflict: Conflict) => void
  /** Bewust houden mét reden (dubbel → halve dagen; afwezig → tóch plannen). */
  onAkkoord: (conflict: Conflict, reden: string) => void
}

const INGEKLAPT = 3

export function ConflictenPaneel({ groepen, weekLabel, verstrekenAantal, projectNaam, bezig, onSpring, onHoud, onVerwijder, onAkkoord }: ConflictenPaneelProps) {
  const [open, setOpen] = useState(false)
  const [akkoordVoor, setAkkoordVoor] = useState<Conflict | null>(null)
  const rijen = groepen.flatMap((g) => g.rijen.map((c) => ({ groep: g, c })))
  if (rijen.length === 0) {
    if (verstrekenAantal === 0) return null
    return (
      <div className="plan-conf" role="status" data-testid="conflictenbalk">
        <span className="hint" style={{ margin: 0 }}>
          Geen conflicten {weekLabel} — {verstrekenAantal} op verstreken {verstrekenAantal === 1 ? 'dag' : 'dagen'} (historie, zie
          &quot;Per project&quot;).
        </span>
      </div>
    )
  }
  const getoond = open ? rijen : rijen.slice(0, INGEKLAPT)
  const kop = `${rijen.length} ${rijen.length === 1 ? 'conflict' : 'conflicten'} ${weekLabel === 'deze week' ? 'deze week' : `in ${weekLabel}`}`

  return (
    <div className="plan-conf plan-conf-paneel" role="region" aria-label="Conflicten" data-testid="conflictenbalk">
      <div className="plan-conf-kop">
        <b>{kop}</b>
        <span className="hint" style={{ margin: 0, fontSize: 11 }}>
          nooit blokkerend — kantoor beslist
          {verstrekenAantal > 0 && ` · ${verstrekenAantal} op verstreken ${verstrekenAantal === 1 ? 'dag' : 'dagen'} niet getoond (zie "Per project")`}
        </span>
        {rijen.length > INGEKLAPT && (
          <button type="button" className="linkbtn" style={{ marginLeft: 'auto', fontSize: 12.5 }} onClick={() => setOpen((o) => !o)} data-testid="conflicten-toggle">
            {open ? 'Minder tonen' : `Alle ${rijen.length} tonen`}
          </button>
        )}
      </div>
      {/* Overflow-les 18-09: élke tabel in een paneel staat in .tabel-scroll — ook ingeklapt (768 px). */}
      <div className="tabel-scroll" style={open ? { maxHeight: 320 } : undefined}>
        <table className="plan-conf-tabel" data-testid="conflicten-tabel">
          <thead>
            <tr>
              <th>Dag</th>
              <th>Persoon</th>
              <th>Projecten</th>
              <th>Conflict</th>
              <th>Handeling</th>
            </tr>
          </thead>
          <tbody>
            {getoond.map(({ groep, c }, i) => {
              const eersteVanDag = i === 0 || getoond[i - 1].groep.datum !== groep.datum
              return (
                <tr key={`${c.soort}-${c.gebruiker_id ?? ''}-${c.datum}-${c.project_id}`} data-testid={`conflict-rij-${c.soort}-${c.datum}-${c.gebruiker_id ?? c.project_id}`}>
                  <td className="plan-conf-dag">{eersteVanDag ? groep.label : ''}</td>
                  <td>{c.naam ?? (c.soort === 'te_groot' ? `${c.tekst.split(': ')[1]?.split(' op ')[0] ?? '?'}` : '?')}</td>
                  <td>{c.project_ids.map((p) => projectNaam(p)).join(' én ')}</td>
                  <td>
                    <Badge variant="warn">{CONFLICT_SOORT_LABEL[c.soort]}</Badge>
                  </td>
                  <td className="plan-conf-acties">
                    {c.soort === 'dubbel' &&
                      c.project_ids.map((p) => (
                        <button key={p} type="button" className="linkbtn" disabled={bezig} onClick={() => onHoud(c, p)} data-testid={`houd-${c.gebruiker_id}-${c.datum}-${p}`}>
                          Houd {projectNaam(p)}
                        </button>
                      ))}
                    {c.soort === 'dubbel' && (
                      <button type="button" className="linkbtn" disabled={bezig} onClick={() => setAkkoordVoor(c)} data-testid={`beide-${c.gebruiker_id}-${c.datum}`}>
                        Beide (halve dagen)…
                      </button>
                    )}
                    {c.soort === 'afwezig' && (
                      <>
                        <button type="button" className="linkbtn" disabled={bezig} onClick={() => onVerwijder(c)} data-testid={`verwijder-${c.gebruiker_id}-${c.datum}`}>
                          Van planning halen
                        </button>
                        <button type="button" className="linkbtn" disabled={bezig} onClick={() => setAkkoordVoor(c)}>
                          Tóch plannen…
                        </button>
                      </>
                    )}
                    {c.soort === 'te_groot' && (
                      <button type="button" className="linkbtn" onClick={() => onSpring(`${c.project_id}|${c.datum}`)}>
                        Ploeg aanpassen
                      </button>
                    )}
                    {c.soort === 'geen_dossier' && (
                      <Link to="/veldwerkers" className="linkbtn">
                        Dossier openen →
                      </Link>
                    )}
                    <button type="button" className="linkbtn" title="Toon in grid" onClick={() => onSpring(`${c.project_id}|${c.datum}`)} data-testid={`spring-${c.soort}-${c.gebruiker_id ?? ''}-${c.datum}-${c.project_id}`}>
                      Toon in grid
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {akkoordVoor && (
        <AkkoordDialoog
          conflict={akkoordVoor}
          projectNaam={projectNaam}
          onAnnuleren={() => setAkkoordVoor(null)}
          onBevestig={(reden) => {
            const c = akkoordVoor
            setAkkoordVoor(null)
            onAkkoord(c, reden)
          }}
        />
      )}
    </div>
  )
}

/** Reden verplicht (≥ 3 tekens) — komt in het logboek; de rij verdwijnt tot de planning van die persoon-dag wijzigt. */
function AkkoordDialoog({ conflict, projectNaam, onBevestig, onAnnuleren }: { conflict: Conflict; projectNaam: (id: string) => string; onBevestig: (reden: string) => void; onAnnuleren: () => void }) {
  const [reden, setReden] = useState('')
  const teKort = reden.trim().length < 3
  const dubbel = conflict.soort === 'dubbel'
  const titel = dubbel ? 'Beide houden (halve dagen)' : 'Tóch plannen'
  return (
    <Dialog open onOpenChange={(o) => !o && onAnnuleren()}>
      <DialogContent aria-label={titel}>
        <DialogTitle>{titel}</DialogTitle>
        <DialogDescription>
          <b>{conflict.naam ?? '?'}</b> blijft op {conflict.project_ids.map(projectNaam).join(' én ')} staan
          {dubbel ? ' — beide kaarten worden een halve dag (½).' : ' ondanks de afwezigheid.'} De reden is verplicht en komt in het
          logboek; het conflict verdwijnt uit de lijst tot de planning van die dag wijzigt.
        </DialogDescription>
        <label style={{ fontSize: 12, fontWeight: 600, display: 'block' }}>
          Reden (verplicht)
          <input
            value={reden}
            onChange={(e) => setReden(e.target.value)}
            placeholder={dubbel ? 'bijv. ochtend Bergeijk, middag Eindhoven — afgesproken met de uitvoerder' : 'bijv. komt tóch een halve dag'}
            aria-label="Reden bewust houden"
            autoFocus
            style={{ display: 'block', width: '100%', marginTop: 4 }}
          />
        </label>
        <DialogFooter>
          <Button variant="secundair" maat="klein" onClick={onAnnuleren}>
            Annuleren
          </Button>
          <Button maat="klein" data-testid="bevestig-akkoord" disabled={teKort} onClick={() => onBevestig(reden.trim())}>
            {titel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
