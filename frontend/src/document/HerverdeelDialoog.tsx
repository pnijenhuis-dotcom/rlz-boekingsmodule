// Herverdelen-dialoog projectverdeling (blok C 04-09, ontwerpnotitie ⑥) — uitgelicht op 06-09 (blok B) zodat
// het controlescherm (ProjectverdelingBlok) én Inzicht › Projectverdeling (HercontroleScreen) precies dezelfde
// dialoog en dezelfde server-route gebruiken: oud vs nieuw per project, reden (vooringevuld, verplicht ≥ 5
// tekens) → POST …/projectverdeling/herverdelen = de BESTAANDE tegenboek-én-opnieuw-boeken-route. Geen
// motor-logica hier: de server rekent en toetst (aangifte-poort), de client formatteert en bevestigt.
import { useState } from 'react'
import { ApiError } from '../api/client'
import type { ProjectverdelingDeelDto, ProjectverdelingHerverdeelResultaatDto } from '../api/types'
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from '../ui/basis'
import { herverdeelProjectverdeling } from './projectverdelingApi'

export const MAANDEN = ['januari', 'februari', 'maart', 'april', 'mei', 'juni', 'juli', 'augustus', 'september', 'oktober', 'november', 'december']

export function euro(bedrag: string | number | null | undefined): string {
  if (bedrag === null || bedrag === undefined || bedrag === '') return '—'
  const n = Number(bedrag)
  if (Number.isNaN(n)) return '—'
  return n.toLocaleString('nl-NL', { style: 'currency', currency: 'EUR' })
}

/** "2026-07-01" → "juli 2026" (leeg = ''). */
export function periodeLabel(iso: string | null | undefined): string {
  if (!iso) return ''
  const [jaar, maand] = iso.split('-').map(Number)
  return `${MAANDEN[(maand ?? 1) - 1]} ${jaar}`
}

/** Vooringevulde reden (opdracht 04-09): leeg gelaten = deze tekst gaat mee (verplicht veld, nooit leeg). */
export function standaardReden(periode: string | null | undefined, afwijkingPct: string | null | undefined): string {
  return `omzet ${periodeLabel(periode)} gewijzigd ná het boeken — verdeling wijkt ${afwijkingPct ?? '?'}% af`
}

export interface VergelijkRij {
  project_id: string
  naam: string
  oud: string
  nieuw: string
}

/** Oud vs nieuw per project (som per project, naam uit welke kant 'm kent), grootste nieuwe deel bovenaan. */
export function vergelijk(oud: ProjectverdelingDeelDto[], nieuw: ProjectverdelingDeelDto[]): VergelijkRij[] {
  const per = new Map<string, VergelijkRij>()
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

interface Props {
  administratieId: string
  documentId: string
  /** De bevroren verdeling van de boeking. */
  delenOud: ProjectverdelingDeelDto[]
  /** De herrekende verdeling uit de hercontrole. */
  delenNieuw: ProjectverdelingDeelDto[]
  /** Omzetmaand (ISO, eerste dag) — alleen voor de tekst. */
  periode: string | null | undefined
  afwijkingPct: string | null | undefined
  onSluiten: () => void
  /** Ná een geslaagde herverdeling (document staat weer op te_controleren mét de nieuwe verdeling als voorstel). */
  onGelukt: (resultaat: ProjectverdelingHerverdeelResultaatDto) => void
}

export function HerverdeelDialoog({ administratieId, documentId, delenOud, delenNieuw, periode, afwijkingPct, onSluiten, onGelukt }: Props) {
  const [reden, setReden] = useState('')
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  const herverdelen = async () => {
    const standaard = standaardReden(periode, afwijkingPct)
    const tekst = reden.trim().length >= 5 ? reden.trim() : standaard
    if (tekst !== reden) setReden(tekst)
    setBezig(true)
    setFout(null)
    try {
      const resultaat = await herverdeelProjectverdeling(administratieId, documentId, tekst)
      onGelukt(resultaat)
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Herverdelen mislukt.')
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onSluiten()}>
      <DialogContent breed data-testid="pv-herverdeel-dialoog">
        <DialogTitle>Herverdelen — tegenboeken en opnieuw boeken</DialogTitle>
        <DialogDescription>
          De boeking wordt tegengeboekt en komt terug op &ldquo;te controleren&rdquo; mét de nieuwe verdeling als voorstel; u boekt daarna
          opnieuw. Niets gebeurt stil — de btw-aangifte-poort geldt onverkort.
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
              {vergelijk(delenOud, delenNieuw).map((r) => (
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
            value={reden}
            onChange={(e) => setReden(e.target.value)}
            placeholder={standaardReden(periode, afwijkingPct)}
            rows={2}
            style={{ width: '100%', marginTop: 4 }}
          />
        </label>
        {fout && <div className="fout">{fout}</div>}
        <DialogFooter>
          <Button type="button" variant="secundair" onClick={onSluiten} disabled={bezig}>
            Annuleren
          </Button>
          <Button type="button" onClick={() => void herverdelen()} disabled={bezig}>
            {bezig ? 'Bezig…' : 'Tegenboeken en herverdelen'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
