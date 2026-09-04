import { useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from '../ui/basis'
import { haalVolgendNummer, maakProject } from './projectenApi'

/* "Nieuw project" — één dialoog, sinds 04-09 (fix C3) een eigen bestand omdat er drie ingangen
 * op zitten en géén tweede projectmotor mag ontstaan:
 *   1. de projectenlijst ("+ Nieuw project"),
 *   2. /planning ("+ Project aanmaken", B+P — blok C 31-08),
 *   3. de projectkolom van het boekvoorstel én de projectverdeling
 *      ("+ Nieuw project aanmaken…" als vaste onderste rij in de project-combobox, besluit
 *      Peter 04-09 — je hoeft het controlescherm niet meer te verlaten voor een nieuw project).
 * Gedrag ongewijzigd: volgend vrij nummer als voorstel (verrijking, nooit blokkerend),
 * naam-preview conform de naamconventie, aanmaken via de bestaande RLZ-projectmotor
 * (idempotent — RLZ blijft de bron) en `onKlaar(rlz_project_id)` naar de aanroeper.
 * Sinds 04-09 op de Radix-Dialog i.p.v. een handgerolde overlay: focus-trap, Escape en
 * scroll-lock gratis, en een klik in een portalende combobox-lijst sluit de dialoog niet. */

export function NieuwProjectModal({
  administratieId,
  onKlaar,
  onAnnuleren,
}: {
  administratieId: string
  onKlaar: (projectId: string) => void
  onAnnuleren: () => void
}) {
  const [nummer, setNummer] = useState('')
  const [plaats, setPlaats] = useState('')
  const [opdrachtgever, setOpdrachtgever] = useState('')
  const [startdatum, setStartdatum] = useState('')
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  useEffect(() => {
    haalVolgendNummer(administratieId)
      .then((r) => setNummer((huidig) => huidig || r.projectnummer))
      .catch(() => undefined) // voorstel is verrijking — handmatig invullen kan altijd
  }, [administratieId])

  const naam = nummer && plaats && opdrachtgever ? `${nummer.trim()} ${plaats.trim()} (${opdrachtgever.trim()})` : null

  const aanmaken = async () => {
    setBezig(true)
    setFout(null)
    try {
      const resultaat = await maakProject(administratieId, {
        projectnummer: nummer.trim(),
        plaats: plaats.trim(),
        opdrachtgever: opdrachtgever.trim(),
        startdatum: startdatum || null,
      })
      onKlaar(resultaat.rlz_project_id)
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Aanmaken mislukt — probeer het opnieuw.')
    } finally {
      setBezig(false)
    }
  }

  const veldStijl = {
    background: 'var(--panel-2)',
    border: '1px solid var(--border)',
    borderRadius: 9,
    color: 'var(--text)',
    font: 'inherit',
    padding: '8px 11px',
    width: '100%',
  } as const

  return (
    <Dialog
      open
      onOpenChange={(o) => {
        if (!o && !bezig) onAnnuleren()
      }}
    >
      <DialogContent breed aria-label="Nieuw project">
        <DialogTitle>Nieuw project</DialogTitle>
        <DialogDescription>
          Wordt volgens de naamconventie aangemaakt in RLZ (projectmotor, idempotent) en daarna hierheen gesynct — één
          bron van waarheid.
        </DialogDescription>
        <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))' }}>
          <label style={{ fontSize: 12, fontWeight: 600 }}>
            Projectnummer
            <input value={nummer} onChange={(e) => setNummer(e.target.value)} placeholder="26xxx" style={veldStijl} />
            <span style={{ color: 'var(--faint)', fontSize: 11, fontWeight: 400 }}>volgende vrije nummer voorgesteld</span>
          </label>
          <label style={{ fontSize: 12, fontWeight: 600 }}>
            Plaats
            <input value={plaats} onChange={(e) => setPlaats(e.target.value)} placeholder="bijv. Tilburg" style={veldStijl} />
          </label>
          <label style={{ fontSize: 12, fontWeight: 600 }}>
            Opdrachtgever
            <input
              value={opdrachtgever}
              onChange={(e) => setOpdrachtgever(e.target.value)}
              placeholder="bijv. Heijmans"
              style={veldStijl}
            />
          </label>
          <label style={{ fontSize: 12, fontWeight: 600 }}>
            Startdatum
            <input type="date" value={startdatum} onChange={(e) => setStartdatum(e.target.value)} style={veldStijl} />
          </label>
        </div>
        {naam && (
          <p className="hint" style={{ background: 'var(--info-bg)', borderRadius: 8, color: 'var(--info)', marginTop: 12, padding: '10px 13px' }}>
            Naam wordt: <b>{naam}</b> — conform de naamconventie, max 50 tekens (RLZ-grens).
          </p>
        )}
        {fout && <div className="fout" style={{ marginTop: 8 }}>{fout}</div>}
        <DialogFooter>
          <Button variant="secundair" maat="klein" onClick={onAnnuleren} disabled={bezig}>
            Annuleren
          </Button>
          <Button maat="klein" onClick={() => void aanmaken()} disabled={bezig || !naam}>
            {bezig ? 'Bezig…' : 'Aanmaken in RLZ'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
