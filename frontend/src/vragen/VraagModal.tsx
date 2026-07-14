import { useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import type { VraagDto } from '../api/types'
import { useMedewerkers } from './useMedewerkers'
import { haalEigenaarOp, stelVraag } from './vragenApi'

interface Props {
  administratieId: string
  documentId: string
  onGesteld: (vraag: VraagDto) => void
  onAnnuleren: () => void
}

/** Vraagmodal (mockup #vraagmodal): toewijzen-select met de administratie-eigenaar als
 * voorgeselecteerde standaard ("— eigenaar administratie (standaard)"), verplichte vraagtekst,
 * en de expliciete melding dat boeken geblokkeerd wordt tot het antwoord er is. */
export function VraagModal({ administratieId, documentId, onGesteld, onAnnuleren }: Props) {
  const { medewerkers, fout: medewerkersFout } = useMedewerkers(administratieId)
  const [eigenaarId, setEigenaarId] = useState<string | null>(null)
  const [eigenaarGeladen, setEigenaarGeladen] = useState(false)
  const [toegewezenAan, setToegewezenAan] = useState<string>('')
  const [vraagTekst, setVraagTekst] = useState('')
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  useEffect(() => {
    let actief = true
    haalEigenaarOp(administratieId)
      .then((data) => {
        if (!actief) return
        setEigenaarId(data.eigenaar_gebruiker_id)
        setToegewezenAan(data.eigenaar_gebruiker_id ?? '')
        setEigenaarGeladen(true)
      })
      .catch(() => {
        // Geen eigenaar op te halen: de select werkt gewoon, alleen zonder voorselectie —
        // de backend weigert een vraag zonder toewijzing zichtbaar (geen stille default).
        if (actief) setEigenaarGeladen(true)
      })
    return () => {
      actief = false
    }
  }, [administratieId])

  const versturen = async () => {
    setBezig(true)
    setFout(null)
    try {
      const vraag = await stelVraag(administratieId, documentId, {
        vraag_tekst: vraagTekst,
        toegewezen_aan: toegewezenAan || null,
      })
      onGesteld(vraag)
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Vraag versturen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  const tekstLeeg = vraagTekst.trim() === ''

  return (
    <div
      className="modal-bg"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !bezig) onAnnuleren()
      }}
    >
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="vraag-modal-titel">
        <h2 id="vraag-modal-titel">Vraag stellen over deze factuur</h2>
        <div className="row">
          <label htmlFor="vraag-toewijzen">Toewijzen aan</label>
          <select
            id="vraag-toewijzen"
            value={toegewezenAan}
            disabled={!medewerkers || !eigenaarGeladen}
            onChange={(e) => setToegewezenAan(e.target.value)}
          >
            {!eigenaarId && <option value="">— kies een medewerker —</option>}
            {(medewerkers ?? []).map((m) => (
              <option key={m.id} value={m.id}>
                {m.naam}
                {m.id === eigenaarId ? ' — eigenaar administratie (standaard)' : ''}
              </option>
            ))}
          </select>
          {medewerkersFout && <div className="fout">Kon medewerkers niet laden: {medewerkersFout}</div>}
        </div>
        <div className="row">
          <label htmlFor="vraag-tekst">Vraag</label>
          <textarea
            id="vraag-tekst"
            rows={3}
            placeholder="Bijv.: op welke kostenpost moet dit geboekt worden?"
            value={vraagTekst}
            onChange={(e) => setVraagTekst(e.target.value)}
          />
        </div>
        <p className="hint" style={{ marginTop: 0 }}>
          De factuur krijgt status <b>Vraag open</b> en verschijnt in de vragenlijst van de gekozen collega.
          Boeken is geblokkeerd tot de vraag beantwoord (of ingetrokken) is.
        </p>
        {fout && <div className="fout">{fout}</div>}
        <div className="actions">
          <button type="button" className="btn secondary" onClick={onAnnuleren} disabled={bezig}>
            Annuleren
          </button>
          <button type="button" className="btn" onClick={() => void versturen()} disabled={bezig || tekstLeeg}>
            {bezig ? 'Bezig…' : 'Vraag versturen'}
          </button>
        </div>
      </div>
    </div>
  )
}
