// Voorwaarden + privacyverklaring-akkoord (blok 3, docs/avg/05 bijlage A): verplicht vóór het
// eerste gebruik; het akkoord (wie/wanneer/tekstversie) landt server-side in het append-only
// audit log. Zonder akkoord weigert de server de wachtrij (fail-closed) — dit scherm is de
// enige weg erdoorheen.

import { useEffect, useState } from 'react'
import { haalVoorwaarden, legVoorwaardenAkkoordVast, type VoorwaardenDto } from './accordeurApi'

interface Props {
  naAkkoord: () => void
}

export function VoorwaardenScherm({ naAkkoord }: Props) {
  const [voorwaarden, setVoorwaarden] = useState<VoorwaardenDto | null>(null)
  const [aangevinkt, setAangevinkt] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)

  useEffect(() => {
    haalVoorwaarden()
      .then(setVoorwaarden)
      .catch(() => setFout('De voorwaarden konden niet geladen worden. Probeer het opnieuw.'))
  }, [])

  const bevestig = async () => {
    setFout(null)
    setBezig(true)
    try {
      await legVoorwaardenAkkoordVast()
      naAkkoord()
    } catch {
      setFout('Het akkoord kon niet vastgelegd worden. Probeer het opnieuw.')
    } finally {
      setBezig(false)
    }
  }

  const tekst = voorwaarden
    ? voorwaarden.tekst
        .replaceAll('[klantnaam]', voorwaarden.administratie_namen.join(' / ') || 'de klant')
        .replaceAll('[Klantnaam]', voorwaarden.administratie_namen.join(' / ') || 'De klant')
        .replaceAll('[administratie]', voorwaarden.administratie_namen.join(' / ') || 'de administratie')
    : null

  return (
    <div className="acc-vol" style={{ justifyContent: 'flex-start', paddingTop: 40 }}>
      <div className="acc-appnaam">
        RLZ <span>Goedkeuren</span>
      </div>
      <div className="acc-bio" style={{ padding: 0 }}>
        <b>Voordat je begint</b>
        <div className="acc-sub">Lees de gebruiksvoorwaarden en de privacyverklaring en ga akkoord.</div>
      </div>
      {fout && <div className="acc-fout">{fout}</div>}
      {tekst && (
        <>
          <div className="acc-voorwaarden">{tekst}</div>
          <label className="acc-akkoordregel">
            <input
              type="checkbox"
              checked={aangevinkt}
              onChange={(e) => setAangevinkt(e.target.checked)}
            />
            <span>Ik heb de gebruiksvoorwaarden en de privacyverklaring gelezen en ga akkoord.</span>
          </label>
          <button className="acc-btn groen" disabled={!aangevinkt || bezig} onClick={() => void bevestig()}>
            {bezig ? 'Bezig…' : 'Akkoord en beginnen'}
          </button>
          <div className="acc-sub" style={{ fontSize: 11, color: 'var(--acc-muted)', maxWidth: 340 }}>
            Je akkoord wordt vastgelegd met naam, datum, tijdstip en tekstversie ({voorwaarden?.tekst_versie}).
          </div>
        </>
      )}
    </div>
  )
}
