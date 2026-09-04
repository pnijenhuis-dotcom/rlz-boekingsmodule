// "Koppel offerte…" (blok B 04-09, mockup offerte-matching blok 2 + notitie ②): voor het geval de
// match de verkeerde of géén offerte pakte. De mens kiest éénmalig; de server onthoudt die keuze
// voor volgende facturen met dezelfde crediteur + project. Ontkoppelen zet 'm terug op de
// automatische match. Nooit een blokkade — dit is een correctie op een signaal.
import { useState } from 'react'
import { ApiError } from '../api/client'
import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from '../ui/basis'
import { formatBedrag, formatDatumKort } from '../werkvoorraad/format'
import { koppelOfferte, SOORT_LABEL_TEKST, type VerplichtingMatchDto } from '../verplichting/verplichtingApi'

export function KoppelOfferteDialog({
  administratieId,
  documentId,
  match,
  onGekoppeld,
  onSluiten,
}: {
  administratieId: string
  documentId: string
  match: VerplichtingMatchDto
  onGekoppeld: (nieuw: VerplichtingMatchDto) => void
  onSluiten: () => void
}) {
  const [gekozen, setGekozen] = useState<string | null>(match.verplichting?.document_id ?? null)
  const [bezig, setBezig] = useState<'koppel' | 'ontkoppel' | null>(null)
  const [fout, setFout] = useState<string | null>(null)

  const voerUit = async (verplichtingId: string | null, soort: 'koppel' | 'ontkoppel') => {
    setBezig(soort)
    setFout(null)
    try {
      onGekoppeld(await koppelOfferte(administratieId, documentId, verplichtingId))
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Koppelen mislukt.')
    } finally {
      setBezig(null)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && bezig === null && onSluiten()}>
      <DialogContent breed data-testid="koppel-offerte-dialoog">
        <DialogTitle>Offerte koppelen aan deze factuur</DialogTitle>
        <DialogDescription>
          Lopende, goedgekeurde verplichtingen van deze leverancier. Kies de juiste — de keuze wordt onthouden voor
          volgende facturen van dezelfde leverancier op hetzelfde project.
        </DialogDescription>

        {match.kandidaten.length === 0 ? (
          <p className="hint" data-testid="geen-kandidaten">
            Er zijn geen lopende goedgekeurde verplichtingen van deze leverancier. Is er wél een offerte? Voeg die dan
            eerst als verplichting toe en laat die accorderen.
          </p>
        ) : (
          <div className="tabel-scroll">
            <table className="lines" data-testid="offerte-kandidaten">
              <tbody>
                <tr>
                  <th />
                  <th>Offerte</th>
                  <th>Project</th>
                  <th className="amount">Goedgekeurd</th>
                  <th className="amount">Al verbruikt</th>
                  <th>Geldig t/m</th>
                </tr>
                {match.kandidaten.map((k) => (
                  <tr key={k.document_id}>
                    <td>
                      <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0 }}>
                        <input
                          type="radio"
                          name="offerte-kandidaat"
                          aria-label={`Kies ${k.offertenummer ?? k.document_id}`}
                          checked={gekozen === k.document_id}
                          onChange={() => setGekozen(k.document_id)}
                        />
                      </label>
                    </td>
                    <td>
                      <b>{k.offertenummer ?? '— zonder nummer —'}</b>
                      <div className="hint" style={{ margin: 0 }}>
                        {k.soort_label ? SOORT_LABEL_TEKST[k.soort_label] : 'verplichting'}
                      </div>
                    </td>
                    <td>{k.project_naam ?? '—'}</td>
                    <td className="amount">{formatBedrag(k.totaal_excl)}</td>
                    <td className="amount">{formatBedrag(k.verbruikt_excl)}</td>
                    <td>{k.geldig_tot ? formatDatumKort(k.geldig_tot) : 'geen einddatum'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {match.handmatig_gekoppeld && match.verplichting && (
          <p className="hint" data-testid="handmatig-regel">
            <Badge variant="paars">handmatig gekoppeld</Badge> aan{' '}
            {match.verplichting.offertenummer ?? 'een verplichting'} — ontkoppelen zet de automatische match terug.
          </p>
        )}
        {fout && <div className="fout">{fout}</div>}

        <DialogFooter>
          <Button type="button" variant="ghost" onClick={onSluiten} disabled={bezig !== null}>
            Annuleren
          </Button>
          {match.handmatig_gekoppeld && (
            <Button
              type="button"
              variant="secundair"
              disabled={bezig !== null}
              onClick={() => void voerUit(null, 'ontkoppel')}
            >
              {bezig === 'ontkoppel' ? 'Bezig…' : 'Ontkoppelen'}
            </Button>
          )}
          <Button
            type="button"
            disabled={bezig !== null || gekozen === null || gekozen === match.verplichting?.document_id}
            onClick={() => void voerUit(gekozen, 'koppel')}
          >
            {bezig === 'koppel' ? 'Bezig…' : 'Koppelen'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
