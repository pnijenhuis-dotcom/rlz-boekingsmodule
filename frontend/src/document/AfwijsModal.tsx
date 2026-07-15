import { useEffect, useState } from 'react'
import { ApiError, apiPostJson } from '../api/client'
import type { AfwijzingDto } from '../api/types'
import { useMedewerkers } from '../vragen/useMedewerkers'
import { haalEigenaarOp } from '../vragen/vragenApi'

interface Props {
  administratieId: string
  documentId: string
  onAfgewezen: (afwijzing: AfwijzingDto) => void
  onAnnuleren: () => void
}

/** Afwijsmodal (mockup #afwijsmodal): verplicht redenveld, "Ter controle naar"-select met de
 * administratie-eigenaar als voorgeselecteerde standaard, en de expliciete melding dat de
 * factuur zichtbaar blijft in de werkvoorraad — zelfde opbouw en eigenaar-default als de
 * vraagmodal (vragen/VraagModal.tsx). */
export function AfwijsModal({ administratieId, documentId, onAfgewezen, onAnnuleren }: Props) {
  const { medewerkers, fout: medewerkersFout } = useMedewerkers(administratieId)
  const [eigenaarId, setEigenaarId] = useState<string | null>(null)
  const [eigenaarGeladen, setEigenaarGeladen] = useState(false)
  const [toegewezenAan, setToegewezenAan] = useState<string>('')
  const [reden, setReden] = useState('')
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
        // Geen eigenaar op te halen: de select werkt gewoon, alleen zonder voorselectie — de
        // backend weigert een afwijzing zonder toewijzing zichtbaar (geen stille default).
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
      const afwijzing = await apiPostJson<AfwijzingDto>(
        `/administraties/${administratieId}/documenten/${documentId}/afwijzen`,
        { reden, toegewezen_aan: toegewezenAan || null },
      )
      onAfgewezen(afwijzing)
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Afwijzen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  const redenLeeg = reden.trim() === ''

  return (
    <div
      className="modal-bg"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !bezig) onAnnuleren()
      }}
    >
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="afwijs-modal-titel">
        <h2 id="afwijs-modal-titel">Factuur afwijzen</h2>
        <div className="row">
          <label htmlFor="afwijs-reden">Reden van afwijzing (verplicht)</label>
          <textarea
            id="afwijs-reden"
            rows={3}
            placeholder="Bijv.: niet onze bestelling / dubbele aanlevering / onjuiste tenaamstelling"
            value={reden}
            onChange={(e) => setReden(e.target.value)}
          />
        </div>
        <div className="row">
          <label htmlFor="afwijs-toewijzen">Ter controle naar</label>
          <select
            id="afwijs-toewijzen"
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
        <p className="hint" style={{ marginTop: 0 }}>
          De factuur krijgt status <b>Afgewezen — ter controle</b> en blijft zichtbaar in de werkvoorraad.
          Niets verdwijnt zonder spoor; heropenen zet het document terug op de status van vóór de afwijzing.
        </p>
        {fout && <div className="fout">{fout}</div>}
        <div className="actions">
          <button type="button" className="btn secondary" onClick={onAnnuleren} disabled={bezig}>
            Annuleren
          </button>
          <button type="button" className="btn" onClick={() => void versturen()} disabled={bezig || redenLeeg}>
            {bezig ? 'Bezig…' : 'Afwijzen'}
          </button>
        </div>
      </div>
    </div>
  )
}
